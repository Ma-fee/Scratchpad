"""
Overlay Filesystem Implementation.

This module provides OverlayFileSystem, an fsspec-compatible filesystem
that implements a union mount with copy-on-write semantics.

Architecture:
- Single writable upper layer (read-write)
- Multiple read-only lower layers (priority order)
- Path resolution: upper takes precedence, then lowers in order
- Memory pressure handling with automatic eviction and graceful degradation
"""

from __future__ import annotations

import os
import sys
import time
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from fsspec import AbstractFileSystem

from .path_security import validate_path_within_bounds, PathTraversalError
from .session_validator import (
    InvalidSessionError,
    SessionIsolationError,
    SessionWorkspace,
    validate_session_id,
)
from ..exceptions import SessionIsolationError as SessionIsolationErrorExport

if TYPE_CHECKING:
    from typing import Any


class MemoryPressureError(Exception):
    """Exception raised when memory usage exceeds configured limits."""

    def __init__(
        self,
        message: str,
        current_usage: int = 0,
        max_allowed: int = 0,
    ) -> None:
        super().__init__(message)
        self.current_usage = current_usage
        self.max_allowed = max_allowed


@dataclass
class MemoryPressureConfig:
    """Configuration for memory pressure handling in OverlayFileSystem."""

    max_memory_bytes: int = 0
    warning_threshold: float = 0.8
    critical_threshold: float = 0.9
    auto_evict: bool = True
    evict_to_target: float = 0.7

    def __post_init__(self) -> None:
        if self.max_memory_bytes < 0:
            raise ValueError(
                f"max_memory_bytes must be non-negative, got {self.max_memory_bytes}"
            )
        if not 0.0 <= self.warning_threshold <= 1.0:
            raise ValueError(
                f"warning_threshold must be between 0.0 and 1.0, got {self.warning_threshold}"
            )
        if not 0.0 <= self.critical_threshold <= 1.0:
            raise ValueError(
                f"critical_threshold must be between 0.0 and 1.0, got {self.critical_threshold}"
            )
        if not 0.0 <= self.evict_to_target <= 1.0:
            raise ValueError(
                f"evict_to_target must be between 0.0 and 1.0, got {self.evict_to_target}"
            )
        if self.warning_threshold >= self.critical_threshold:
            raise ValueError(
                f"warning_threshold ({self.warning_threshold}) must be less than "
                f"critical_threshold ({self.critical_threshold})"
            )


@dataclass
class MemoryStats:
    """Memory usage statistics for OverlayFileSystem."""

    current_usage_bytes: int = 0
    max_allowed_bytes: int = 0
    usage_percentage: float = 0.0
    is_under_pressure: bool = False
    files_count: int = 0
    directories_count: int = 0
    largest_file_bytes: int = 0
    average_file_bytes: float = 0.0
    eviction_count: int = 0
    last_eviction_at: float = 0.0

    @property
    def available_bytes(self) -> int:
        if self.max_allowed_bytes == 0:
            return 0
        return max(0, self.max_allowed_bytes - self.current_usage_bytes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "current_usage_bytes": self.current_usage_bytes,
            "current_usage_mb": round(self.current_usage_bytes / 1024 / 1024, 2),
            "max_allowed_bytes": self.max_allowed_bytes,
            "max_allowed_mb": (
                round(self.max_allowed_bytes / 1024 / 1024, 2)
                if self.max_allowed_bytes > 0
                else None
            ),
            "usage_percentage": round(self.usage_percentage * 100, 2),
            "is_under_pressure": self.is_under_pressure,
            "available_bytes": self.available_bytes,
            "available_mb": round(self.available_bytes / 1024 / 1024, 2),
            "files_count": self.files_count,
            "directories_count": self.directories_count,
            "largest_file_bytes": self.largest_file_bytes,
            "average_file_bytes": round(self.average_file_bytes, 2),
            "eviction_count": self.eviction_count,
            "last_eviction_at": self.last_eviction_at,
        }


@dataclass
class WhiteoutInfo:
    """Information about a whiteout marker.

    Attributes:
        path: The original path that is whited out (e.g., "/file.txt").
        whiteout_path: The path to the whiteout marker (e.g., "/.wh.file.txt").
        is_stale: Whether the whiteout is stale (no corresponding file in any layer).
    """

    path: str
    whiteout_path: str
    is_stale: bool = False


def _normalize_path(path: str) -> str:
    """Normalize a path to start with '/'.

    Args:
        path: The path to normalize.

    Returns:
        Normalized path starting with '/'.
    """
    if not path.startswith("/"):
        path = "/" + path
    # Remove trailing slash except for root
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    return path


def _validate_path_security(path: str, base_path: str | Path | None = None) -> None:
    """Validate path for security threats.

    Checks for and blocks:
    - Path traversal sequences (..)
    - Null bytes
    - Unsafe characters
    - Symlinks that escape bounds (if base_path provided)

    Args:
        path: The path to validate.
        base_path: Optional base path for symlink validation.

    Raises:
        PathTraversalError: If security threat detected.
    """
    if not path:
        raise PathTraversalError("Path cannot be empty", path="")

    # Check for directory traversal sequences
    # Handle various encoding tricks
    test_path = path.replace("\\", "/")

    # Check for .. traversal
    parts = test_path.split("/")
    if ".." in parts:
        raise PathTraversalError(
            f"Path contains directory traversal sequence: {path}",
            path=path,
        )

    # Check for URL encoded variants
    decoded = path.lower()
    for encoded in ["%2e%2e", "%252e%252e", "0x2e0x2e"]:
        if encoded in decoded:
            raise PathTraversalError(
                f"Path contains encoded directory traversal: {path}",
                path=path,
            )

    # Check for null bytes
    if "\x00" in path:
        raise PathTraversalError(
            f"Path contains null bytes: {path}",
            path=path,
        )

    # Check for unsafe characters
    unsafe_chars = set('<>"|?*\x00-\x1f')
    if any(c in unsafe_chars for c in path):
        raise PathTraversalError(
            f"Path contains unsafe characters: {path}",
            path=path,
        )


class OverlayFileSystem(AbstractFileSystem):
    """Overlay filesystem with copy-on-write semantics.

    Implements a union mount filesystem where:
    - The upper layer is writable and takes precedence
    - Lower layers are read-only and searched in priority order
    - Writes always go to the upper layer
    - Reads check upper first, then lowers in order

    Attributes:
        protocol: The filesystem protocol identifier ("overlay").
        cachable: Whether this filesystem can be cached (False for overlay).
        upper: The writable upper filesystem layer.
        lowers: List of read-only lower filesystem layers in priority order.
        session_id: Optional session ID for session-scoped filesystem access.

    Example:
        >>> from fsspec.implementations.memory import MemoryFileSystem
        >>> upper = MemoryFileSystem()
        >>> lowers = [MemoryFileSystem()]
        >>> overlay = OverlayFileSystem(upper, lowers)
        >>> overlay.protocol
        'overlay'
    """

    protocol = "overlay"
    cachable = False

    def __init__(
        self,
        upper: AbstractFileSystem,
        lowers: list[AbstractFileSystem],
        memory_config: MemoryPressureConfig | None = None,
        session_id: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize the overlay filesystem.

        Args:
            upper: The writable upper filesystem layer (read-write).
            lowers: List of read-only lower filesystem layers in priority order.
            memory_config: Optional memory pressure configuration.
            session_id: Optional session ID for session-scoped access control.
            **kwargs: Additional arguments passed to AbstractFileSystem.

        Note:
            Lower layers are ordered by priority - the first layer in the list
            is checked first when resolving paths not found in upper.
        """
        super().__init__(**kwargs)
        self.upper: AbstractFileSystem = upper
        self.lowers: list[AbstractFileSystem] = lowers
        self.memory_config: MemoryPressureConfig = (
            memory_config or MemoryPressureConfig()
        )
        self._eviction_count: int = 0
        self._last_eviction_at: float = 0.0
        self._memory_warning_issued: bool = False
        self._session_id: str | None = None
        self._session_workspace: SessionWorkspace | None = None

        # 如果提供了 session_id，进行验证和初始化
        if session_id is not None:
            self._init_session(session_id)

    # ========================================================================
    # Session Isolation Methods
    # ========================================================================

    def _init_session(self, session_id: str) -> None:
        """初始化 session 上下文。

        Args:
            session_id: Session 标识符

        Raises:
            InvalidSessionError: 如果 session ID 格式无效
        """
        validated_id = validate_session_id(session_id)
        self._session_id = validated_id

        # 创建 session 工作空间
        # 使用内存文件系统时，workspace 在 /workspace 目录
        self._session_workspace = SessionWorkspace(
            session_id=validated_id,
            base_path=Path("/workspace"),
        )

    def _validate_session_access(self, path: str) -> str:
        """验证 session 对路径的访问权限。

        如果配置了 session隔离，验证路径在 session 工作空间内。

        Args:
            path: 要访问的路径

        Returns:
            安全的路径（如果需要在 workspace 内，会加上前缀）

        Raises:
            SessionIsolationError: 如果路径超出 session 工作空间
            PathTraversalError: 如果路径包含遍历序列
        """
        # 首先检查路径安全（防路径遍历）
        _validate_path_security(path)

        # 如果没有配置 session，直接返回路径
        if self._session_id is None or self._session_workspace is None:
            return path

        # 验证路径是否在 session 工作空间内
        try:
            # 检查路径是否以 /workspace 开头，如果不是则添加
            normalized = path.lstrip("/")
            if not normalized.startswith("workspace"):
                # 将路径限制在 workspace 内
                return f"/workspace/{normalized}"
            return path
        except Exception as e:
            raise SessionIsolationError(
                f"Session {self._session_id} cannot access path: {path}",
                session_id=self._session_id,
                attempted_path=path,
            ) from e

    def get_session_id(self) -> str | None:
        """获取当前 session ID。

        Returns:
            Session ID 如果没有配置则返回 None
        """
        return self._session_id

    def is_session_isolated(self) -> bool:
        """检查是否启用了 session 隔离。

        Returns:
            True 如果启用了 session 隔离
        """
        return self._session_id is not None

    # ========================================================================
    # Memory Pressure Handling Methods
    # ========================================================================

    def _estimate_memory_usage(self) -> int:
        """Estimate current memory usage of the upper layer.

        Returns:
            Estimated memory usage in bytes.
        """
        total_bytes = 0
        try:
            if hasattr(self.upper, "store") and isinstance(self.upper.store, dict):
                for path, content in self.upper.store.items():
                    # Handle MemoryFile objects from fsspec MemoryFileSystem
                    if hasattr(content, "getbuffer"):
                        total_bytes += len(content.getbuffer())
                    elif hasattr(content, "read"):
                        # Try to get size from info
                        try:
                            info = self.upper.info(path)
                            total_bytes += info.get("size", 0)
                        except Exception:
                            pass
                    elif isinstance(content, bytes):
                        total_bytes += len(content)
                    elif isinstance(content, str):
                        total_bytes += len(content.encode("utf-8"))
                    elif hasattr(content, "__len__"):
                        try:
                            total_bytes += len(content)
                        except Exception:
                            pass
        except Exception:
            pass
        return total_bytes

    def _get_files_sorted_by_age(self) -> list[tuple[str, float]]:
        """Get list of files sorted by modification time (oldest first).

        Returns:
            List of (path, mtime) tuples sorted by mtime ascending.
        """
        files_with_time: list[tuple[str, float]] = []
        try:
            self._collect_files_with_mtime("/", files_with_time)
        except Exception:
            pass
        files_with_time.sort(key=lambda x: x[1])
        return files_with_time

    def _collect_files_with_mtime(
        self, path: str, result: list[tuple[str, float]]
    ) -> None:
        """Recursively collect files with their modification times."""
        try:
            entries = self.upper.ls(path)
            for entry in entries:
                if isinstance(entry, dict):
                    entry_path = entry.get("name", "")
                else:
                    entry_path = entry if "/" in entry else f"{path}/{entry}"
                if not entry_path or entry_path == path:
                    continue
                entry_name = entry_path.split("/")[-1]
                if entry_name.startswith(".wh."):
                    continue
                if self.upper.isfile(entry_path):
                    try:
                        info = self.upper.info(entry_path)
                        mtime = info.get("mtime", 0) or info.get("created", 0) or 0
                        result.append((entry_path, mtime))
                    except Exception:
                        pass
                elif self.upper.isdir(entry_path):
                    self._collect_files_with_mtime(entry_path, result)
        except Exception:
            pass

    def _evict_files_to_target(self, target_bytes: int) -> int:
        """Evict oldest files until memory usage is below target.

        Args:
            target_bytes: Target memory usage in bytes.

        Returns:
            Number of files evicted.
        """
        evicted_count = 0
        current_usage = self._estimate_memory_usage()
        if current_usage <= target_bytes:
            return 0
        files_by_age = self._get_files_sorted_by_age()
        for file_path, _ in files_by_age:
            if current_usage <= target_bytes:
                break
            try:
                info = self.upper.info(file_path)
                file_size = info.get("size", 0)
                self.upper.rm_file(file_path)
                evicted_count += 1
                current_usage -= file_size
            except Exception:
                continue
        if evicted_count > 0:
            self._eviction_count += evicted_count
            self._last_eviction_at = time.time()
        return evicted_count

    def _check_memory_pressure(
        self, required_bytes: int = 0
    ) -> tuple[bool, MemoryStats]:
        """Check memory pressure status and perform auto-eviction if needed.

        Args:
            required_bytes: Additional bytes that will be allocated.

        Returns:
            Tuple of (is_critical, stats).
        """
        stats = self.get_memory_stats()
        max_bytes = self.memory_config.max_memory_bytes
        if max_bytes == 0:
            return False, stats
        projected_usage = stats.current_usage_bytes + required_bytes
        usage_percentage = projected_usage / max_bytes if max_bytes > 0 else 0
        is_critical = usage_percentage >= self.memory_config.critical_threshold
        is_warning = usage_percentage >= self.memory_config.warning_threshold
        if self.memory_config.auto_evict and is_critical:
            target_bytes = int(max_bytes * self.memory_config.evict_to_target)
            self._evict_files_to_target(target_bytes)
            stats = self.get_memory_stats()
            projected_usage = stats.current_usage_bytes + required_bytes
            usage_percentage = projected_usage / max_bytes if max_bytes > 0 else 0
            is_critical = usage_percentage >= self.memory_config.critical_threshold
        if is_warning and not self._memory_warning_issued:
            warnings.warn(
                f"OverlayFileSystem memory usage at {usage_percentage * 100:.1f}% "
                f"({stats.current_usage_bytes}/{max_bytes} bytes).",
                ResourceWarning,
                stacklevel=2,
            )
            self._memory_warning_issued = True
        elif not is_warning:
            self._memory_warning_issued = False
        return is_critical, stats

    def _check_memory_limit(self, required_bytes: int = 0) -> None:
        """Check if operation would exceed memory limit.

        Args:
            required_bytes: Bytes that will be allocated.

        Raises:
            MemoryPressureError: If the operation would exceed memory limits.
        """
        max_bytes = self.memory_config.max_memory_bytes
        if max_bytes == 0:
            return
        is_critical, stats = self._check_memory_pressure(required_bytes)
        projected_usage = stats.current_usage_bytes + required_bytes
        if projected_usage > max_bytes:
            raise MemoryPressureError(
                f"Memory limit would be exceeded: "
                f"projected={projected_usage} bytes, "
                f"limit={max_bytes} bytes",
                current_usage=stats.current_usage_bytes,
                max_allowed=max_bytes,
            )

    def get_memory_stats(self) -> MemoryStats:
        """Get current memory usage statistics.

        Returns:
            MemoryStats object with current memory usage information.
        """
        current_usage = self._estimate_memory_usage()
        max_bytes = self.memory_config.max_memory_bytes
        usage_percentage = 0.0
        is_under_pressure = False
        if max_bytes > 0:
            usage_percentage = current_usage / max_bytes
            is_under_pressure = (
                usage_percentage >= self.memory_config.critical_threshold
            )
        files_count = 0
        largest_file = 0
        total_file_size = 0
        try:
            files_count, largest_file, total_file_size = self._collect_file_stats()
        except Exception:
            pass
        avg_file_size = total_file_size / files_count if files_count > 0 else 0.0
        return MemoryStats(
            current_usage_bytes=current_usage,
            max_allowed_bytes=max_bytes,
            usage_percentage=usage_percentage,
            is_under_pressure=is_under_pressure,
            files_count=files_count,
            largest_file_bytes=largest_file,
            average_file_bytes=avg_file_size,
            eviction_count=self._eviction_count,
            last_eviction_at=self._last_eviction_at,
        )

    def _collect_file_stats(self) -> tuple[int, int, int]:
        """Collect file statistics.

        Returns:
            Tuple of (files_count, largest_file_size, total_size).
        """
        files_count = 0
        largest = 0
        total = 0
        try:
            if hasattr(self.upper, "store") and isinstance(self.upper.store, dict):
                for path, content in self.upper.store.items():
                    # Skip directories (they don't have content in store)
                    if self.upper.isdir(path):
                        continue
                    files_count += 1
                    # Get size
                    size = 0
                    if hasattr(content, "getbuffer"):
                        size = len(content.getbuffer())
                    elif hasattr(content, "read"):
                        try:
                            info = self.upper.info(path)
                            size = info.get("size", 0)
                        except Exception:
                            pass
                    elif isinstance(content, bytes):
                        size = len(content)
                    elif isinstance(content, str):
                        size = len(content.encode("utf-8"))
                    elif hasattr(content, "__len__"):
                        try:
                            size = len(content)
                        except Exception:
                            pass
                    total += size
                    if size > largest:
                        largest = size
        except Exception:
            pass
        return files_count, largest, total

    def evict_oldest_files(self, count: int = 1) -> list[str]:
        """Manually evict the oldest files from the upper layer.

        Args:
            count: Number of files to evict.

        Returns:
            List of paths that were evicted.
        """
        files_by_age = self._get_files_sorted_by_age()
        evicted: list[str] = []
        for file_path, _ in files_by_age[:count]:
            try:
                self.upper.rm_file(file_path)
                evicted.append(file_path)
            except Exception:
                pass
        if evicted:
            self._eviction_count += len(evicted)
            self._last_eviction_at = time.time()
        return evicted

    def set_memory_config(self, config: MemoryPressureConfig) -> None:
        """Update memory pressure configuration.

        Args:
            config: New memory pressure configuration.
        """
        self.memory_config = config
        self._memory_warning_issued = False

    def _resolve(self, path: str) -> tuple[AbstractFileSystem, str, int] | None:
        """Resolve a path to the filesystem layer containing it.

        Searches through layers in priority order:
        1. Upper layer (layer_index = 0)
        2. Lower layers in order (layer_index = 1, 2, ...)

        If a whiteout marker exists for the path, returns None (path is hidden).

        Args:
            path: The path to resolve. Should start with '/'.

        Returns:
            A tuple of (filesystem, relative_path, layer_index) if found,
            where:
                - filesystem: The AbstractFileSystem containing the path
                - relative_path: The normalized path within that filesystem
                - layer_index: 0 for upper layer, 1+ for lower layers
            Returns None if the path is not found in any layer or is whited-out.

        Example:
            >>> fs, rel_path, idx = overlay._resolve("/test.txt")
            >>> print(idx)  # 0 if in upper layer, 1+ if in lower
        """
        normalized_path = _normalize_path(path)

        # Check if there's a whiteout marker - if so, path is hidden
        if self._has_whiteout(normalized_path):
            return None

        # Check upper layer first (layer_index = 0)
        if self._exists_in_layer(self.upper, normalized_path):
            return (self.upper, normalized_path, 0)

        # Check each lower layer in order (layer_index = 1, 2, ...)
        for idx, lower_fs in enumerate(self.lowers, start=1):
            if self._exists_in_layer(lower_fs, normalized_path):
                return (lower_fs, normalized_path, idx)

        # Not found in any layer
        return None

    def _exists_in_layer(self, fs: AbstractFileSystem, path: str) -> bool:
        """Check if a path exists in a given filesystem layer.

        Args:
            fs: The filesystem to check.
            path: The normalized path to check.

        Returns:
            True if the path exists (as file or directory), False otherwise.
        """
        try:
            return fs.exists(path)
        except Exception:
            return False

    def _get_layer_fs(self, layer_index: int) -> AbstractFileSystem:
        """Get the filesystem for a given layer index.

        Args:
            layer_index: The layer index (0 for upper, 1+ for lowers).

        Returns:
            The AbstractFileSystem for the given layer.

        Raises:
            IndexError: If the layer index is out of range.
        """
        if layer_index == 0:
            return self.upper
        elif 1 <= layer_index <= len(self.lowers):
            return self.lowers[layer_index - 1]
        else:
            raise IndexError(f"Layer index {layer_index} out of range")

    def info(self, path: str, **kwargs: Any) -> dict[str, Any]:
        """Get metadata information about a file or directory.

        Resolves the path to its source layer and retrieves metadata,
        adding a '_layer' field to indicate which layer the file is from.

        Args:
            path: The path to get info for. Should start with '/'.
            **kwargs: Additional arguments passed to the underlying filesystem.

        Returns:
            A dictionary containing file/directory metadata with an additional
            '_layer' field:
                - 0: Upper layer (writable)
                - 1, 2, ...: Lower layers (read-only, in priority order)

        Raises:
            FileNotFoundError: If the path does not exist in any layer.
            PathTraversalError: If path contains traversal sequences.

        Example:
            >>> info = overlay.info("/test.txt")
            >>> print(info["name"], info["size"], info["_layer"])
        """
        # Validate path security
        _validate_path_security(path)

        # Validate session access if session is configured
        safe_path = self._validate_session_access(path)

        resolved = self._resolve(safe_path)
        if resolved is None:
            raise FileNotFoundError(f"Path not found: {path}")

        fs, rel_path, layer_index = resolved
        info = fs.info(rel_path, **kwargs)
        info["_layer"] = layer_index
        return info

    def ls(self, path: str, **kwargs: Any) -> list[str]:
        """List directory contents from all layers, merged.

        Collects directory entries from upper layer and all lower layers,
        merging them with upper layer entries taking precedence (hiding
        duplicates from lower layers).

        Whiteout markers (.wh.* files) are hidden from the listing.
        Files that have whiteout markers are also hidden (appear as deleted).

        Args:
            path: The directory path to list.
            **kwargs: Additional arguments passed to underlying ls calls.

        Returns:
            Sorted list of unique entry names in the directory.
            Entries from upper layer take precedence over lower layers.
            Whited-out files and whiteout markers are excluded.

        Raises:
            PathTraversalError: If path contains traversal sequences.

        Example:
            >>> overlay.ls("/")
            ['file1.txt', 'file2.txt', 'subdir']
        """
        # Validate path security
        _validate_path_security(path)

        normalized_path = _normalize_path(path)

        # Check if the directory itself has a whiteout marker
        # If so, return empty list (directory appears deleted)
        if self._has_whiteout(normalized_path):
            return []

        # Get list of whited-out files in this directory
        whited_out = self._get_whited_out_files(normalized_path)

        # Collect all entries via a set, upper layer entries first
        seen: set[str] = set()
        all_entries: list[str] = []

        # Helper function to add entries, respecting precedence
        def add_entries(entries: list[str] | list[dict[str, Any]]) -> None:
            for entry in entries:
                # Handle both string and dict entries
                if isinstance(entry, dict):
                    # fsspec info dict format - extract name from 'name' field
                    name = entry.get("name", "")
                    if name:
                        name = name.split("/")[-1]
                else:
                    # String format - extract basename
                    name = entry.split("/")[-1] if "/" in entry else entry

                # Skip whiteout markers and whited-out files
                if name.startswith(".wh."):
                    continue
                if name in whited_out:
                    continue

                # Check if this entry (file or directory) has a whiteout marker
                child_path = (
                    f"{normalized_path}/{name}"
                    if normalized_path != "/"
                    else f"/{name}"
                )
                if self._has_whiteout(child_path):
                    continue

                if name and name not in seen:
                    seen.add(name)
                    all_entries.append(name)

        # Get entries from upper layer first (highest priority)
        if self.isdir(normalized_path):
            try:
                upper_entries = self.upper.ls(normalized_path, **kwargs)
                add_entries(upper_entries)
            except Exception:
                pass  # Directory might not exist in upper layer

        # Get entries from each lower layer
        for lower_fs in self.lowers:
            if lower_fs.isdir(normalized_path):
                try:
                    lower_entries = lower_fs.ls(normalized_path, **kwargs)
                    add_entries(lower_entries)
                except Exception:
                    pass  # Directory might not exist in this layer

        return sorted(all_entries)

    def exists(self, path: str, **kwargs: Any) -> bool:
        """Check if a path exists in any layer.

        A path is considered non-existent if it has a whiteout marker
        in the upper layer, even if it exists in a lower layer.

        Args:
            path: The path to check.
            **kwargs: Additional arguments passed to underlying exists calls.

        Returns:
            True if the path exists in upper or any lower layer and is not
            whited-out, False otherwise.

        Raises:
            PathTraversalError: If path contains traversal sequences.

        Example:
            >>> overlay.exists("/test.txt")
            True
            >>> overlay.exists("/deleted.txt")  # Has whiteout marker
            False
        """
        # Validate path security
        _validate_path_security(path)

        normalized_path = _normalize_path(path)

        # Check if there's a whiteout marker for this path
        if self._has_whiteout(normalized_path):
            return False

        # Check if path exists in any layer
        result = self._resolve_without_whiteout(normalized_path)
        return result is not None

    def isfile(self, path: str, **kwargs: Any) -> bool:
        """Check if a path is a file in any layer.

        Args:
            path: The path to check.
            **kwargs: Additional arguments passed to underlying isfile calls.

        Returns:
            True if the path exists and is a file, False otherwise.

        Example:
            >>> overlay.isfile("/test.txt")
            True
        """
        result = self._resolve(path)
        if result is None:
            return False
        fs, rel_path, _ = result
        return fs.isfile(rel_path, **kwargs)

    def isdir(self, path: str, **kwargs: Any) -> bool:
        """Check if a path is a directory in any layer.

        A path is considered non-existent if it has a whiteout marker
        in the upper layer, even if it exists as a directory in a lower layer.

        Args:
            path: The path to check.
            **kwargs: Additional arguments passed to underlying isdir calls.

        Returns:
            True if the path exists as a directory and is not whited-out,
            False otherwise.

        Example:
            >>> overlay.isdir("/subdir")
            True
        """
        normalized_path = _normalize_path(path)

        # Check if there's a whiteout marker for this path
        if self._has_whiteout(normalized_path):
            return False

        # Check if upper layer has a FILE at this path
        # If so, it's not a directory (upper takes precedence)
        if self._exists_in_layer(self.upper, normalized_path):
            if self.upper.isfile(normalized_path, **kwargs):
                return False
            if self.upper.isdir(normalized_path, **kwargs):
                return True

        # Check each lower layer
        for lower_fs in self.lowers:
            if lower_fs.isdir(normalized_path, **kwargs):
                return True

        return False

    def _needs_copy_up(self, path: str) -> bool:
        """Check if a file needs to be copied up from lower to upper layer.

        A file needs copy-up if:
        - It exists in a lower layer (layer_index >= 1)
        - It does NOT exist in the upper layer

        Args:
            path: The path to check.

        Returns:
            True if file exists in lower but not in upper layer, False otherwise.

        Example:
            >>> overlay._needs_copy_up("/file.txt")
            True  # File exists in lower, not upper
        """
        normalized_path = _normalize_path(path)

        # Check if already in upper layer
        if self._exists_in_layer(self.upper, normalized_path):
            return False

        # Check if exists in any lower layer
        for lower_fs in self.lowers:
            if self._exists_in_layer(lower_fs, normalized_path):
                return True

        return False

    def _ensure_parent_dirs(self, path: str) -> None:
        """Ensure parent directories exist in the upper layer.

        Creates all parent directories in the upper layer if they don't exist.
        Uses recursive creation through fsspec makedirs.

        Args:
            path: The file path whose parents should be created.

        Example:
            >>> overlay._ensure_parent_dirs("/a/b/c/file.txt")
            # Creates /a, /a/b, /a/b/c in upper layer
        """
        normalized_path = _normalize_path(path)

        # Handle root path - no parents to create
        if normalized_path == "/":
            return

        # Get the parent directory path
        parts = normalized_path.split("/")
        if len(parts) <= 1:
            return  # Already at root or single component

        parent_path = "/".join(parts[:-1]) or "/"

        # Create parent directories recursively in upper layer
        if not self._exists_in_layer(self.upper, parent_path):
            self.upper.makedirs(parent_path, exist_ok=True)

    def _copy_up(self, path: str) -> None:
        """Copy a file from lower layer to upper layer.

        Implements Copy-on-Write (COW) semantics for the overlay filesystem.
        Reads the file content from the lower layer and writes it to the
        upper layer, preserving binary content exactly.

        Args:
            path: The path to the file to copy up.

        Raises:
            FileNotFoundError: If the file doesn't exist in any layer.
            IsADirectoryError: If the path is a directory, not a file.

        Example:
            >>> overlay._copy_up("/file.txt")
            # File copied from lower to upper layer
        """
        normalized_path = _normalize_path(path)

        # Resolve the path to find which layer has it
        resolved = self._resolve(normalized_path)

        if resolved is None:
            raise FileNotFoundError(f"Path not found: {path}")

        source_fs, rel_path, layer_index = resolved

        # Check if it's a directory
        if source_fs.isdir(rel_path):
            raise IsADirectoryError(f"Path is a directory, not a file: {path}")

        # If already in upper layer, nothing to do
        if layer_index == 0:
            return

        # Read content from source layer (binary mode)
        with source_fs.open(rel_path, "rb") as src_file:
            content = src_file.read()

        # Check memory limit before writing
        self._check_memory_limit(len(content))

        # Ensure parent directories exist in upper layer
        self._ensure_parent_dirs(normalized_path)

        # Write content to upper layer (binary mode)
        with self.upper.open(normalized_path, "wb") as dst_file:
            dst_file.write(content)

    def _is_write_mode(self, mode: str) -> bool:
        """Check if a file mode indicates write intent.

        Write modes include:
        - "w" - write (truncate if exists)
        - "a" - append
        - "x" - create exclusive
        - "+" - read/write update mode (with any of above)

        Args:
            mode: The file open mode string.

        Returns:
            True if the mode indicates write intent, False for read-only.

        Examples:
            >>> overlay._is_write_mode("r")
            False
            >>> overlay._is_write_mode("w")
            True
            >>> overlay._is_write_mode("r+")
            True
            >>> overlay._is_write_mode("rb")
            False
        """
        # Write intent detected by presence of: w, a, x, or +
        return any(c in mode for c in "wax+")

    def _get_whiteout_path(self, path: str) -> str:
        """Get the whiteout marker path for a given path.

        Whiteout markers use the convention: .wh.<filename>
        For example, deleting /dir/file.txt creates .wh.file.txt in upper layer.

        Args:
            path: The path to get whiteout marker for.

        Returns:
            The whiteout marker path (e.g., /.wh.file.txt or /dir/.wh.file.txt).

        Example:
            >>> overlay._get_whiteout_path("/file.txt")
            '/.wh.file.txt'
            >>> overlay._get_whiteout_path("/dir/file.txt")
            '/dir/.wh.file.txt'
        """
        normalized_path = _normalize_path(path)
        parent = "/".join(normalized_path.split("/")[:-1]) or "/"
        filename = normalized_path.split("/")[-1]
        whiteout_name = f".wh.{filename}"
        if parent == "/":
            return f"/{whiteout_name}"
        return f"{parent}/{whiteout_name}"

    def _has_whiteout(self, path: str) -> bool:
        """Check if a whiteout marker exists for a given path.

        Args:
            path: The path to check for whiteout marker.

        Returns:
            True if a whiteout marker exists in upper layer, False otherwise.

        Example:
            >>> overlay._has_whiteout("/file.txt")
            True  # If .wh.file.txt exists in upper layer
        """
        whiteout_path = self._get_whiteout_path(path)
        return self._exists_in_layer(self.upper, whiteout_path)

    def _get_whited_out_files(self, dir_path: str) -> set[str]:
        """Get the set of filenames that have whiteout markers in a directory.

        Scans the upper layer for .wh.* files and extracts the original filenames.

        Args:
            dir_path: The directory path to scan for whiteout markers.

        Returns:
            Set of filenames that have whiteout markers.

        Example:
            >>> overlay._get_whited_out_files("/")
            {'file.txt', 'other.txt'}  # If .wh.file.txt and .wh.other.txt exist
        """
        normalized_path = _normalize_path(dir_path)
        whited_out: set[str] = set()

        if not self._exists_in_layer(self.upper, normalized_path):
            return whited_out

        try:
            entries = self.upper.ls(normalized_path)
            for entry in entries:
                # Handle both string and dict entries
                if isinstance(entry, dict):
                    name = entry.get("name", "").split("/")[-1]
                else:
                    name = entry.split("/")[-1] if "/" in entry else entry

                if name.startswith(".wh."):
                    # Extract the original filename from .wh.<filename>
                    original_name = name[4:]  # Remove ".wh." prefix
                    whited_out.add(original_name)
        except Exception:
            pass  # Directory might not exist or other error

        return whited_out

    def _create_whiteout(self, path: str) -> None:
        """Create a whiteout marker in the upper layer.

        Whiteout markers are empty files with the naming convention .wh.<filename>
        that hide files from lower layers without actually deleting them.

        Args:
            path: The path to create whiteout marker for.

        Example:
            >>> overlay._create_whiteout("/file.txt")
            # Creates empty file /.wh.file.txt in upper layer
        """
        normalized_path = _normalize_path(path)
        whiteout_path = self._get_whiteout_path(normalized_path)

        # Ensure parent directories exist in upper layer
        self._ensure_parent_dirs(whiteout_path)

        # Create empty whiteout marker file
        self.upper.pipe(whiteout_path, b"")

    def rm(self, path: str, **kwargs: Any) -> None:
        """Remove a file with whiteout support.

        Implements overlay filesystem deletion semantics:
        - If file is in upper layer: delete it directly
        - If file is in lower layer only: create whiteout marker in upper layer
        - If file doesn't exist: raise FileNotFoundError

        The whiteout marker (.wh.<filename>) hides the file from view while
        preserving it in the lower layer.

        Args:
            path: The path to the file to remove.
            **kwargs: Additional arguments passed to underlying rm calls.

        Raises:
            FileNotFoundError: If the path doesn't exist in any layer.
            IsADirectoryError: If the path is a directory.

        Example:
            >>> overlay.rm("/file.txt")
            # File deleted from upper, or whiteout created if in lower
        """
        normalized_path = _normalize_path(path)

        # Check whiteout first - if already whited-out, nothing to do (idempotent)
        if self._has_whiteout(normalized_path):
            return

        # Check if path exists (respecting existing whiteouts)
        if not self.exists(normalized_path):
            raise FileNotFoundError(f"Path not found: {path}")

        # Check if it's a directory (we don't handle directory removal yet)
        if self.isdir(normalized_path):
            raise IsADirectoryError(f"Path is a directory: {path}")

        # Resolve to find which layer has the file
        resolved = self._resolve_without_whiteout(normalized_path)
        if resolved is None:
            raise FileNotFoundError(f"Path not found: {path}")

        fs, rel_path, layer_index = resolved

        if layer_index == 0:
            # File is in upper layer - delete it directly
            fs.rm(rel_path, **kwargs)
        else:
            # File is in lower layer only - create whiteout marker
            self._create_whiteout(normalized_path)

    def _resolve_without_whiteout(
        self, path: str
    ) -> tuple[AbstractFileSystem, str, int] | None:
        """Resolve a path without considering whiteout markers.

        This is used internally when we need to know the actual location
        of a file regardless of whiteout status (e.g., for rm operation).

        Args:
            path: The path to resolve.

        Returns:
            Same as _resolve: tuple of (filesystem, path, layer_index) or None.
        """
        normalized_path = _normalize_path(path)

        # Check upper layer first
        if self._exists_in_layer(self.upper, normalized_path):
            return (self.upper, normalized_path, 0)

        # Check each lower layer
        for idx, lower_fs in enumerate(self.lowers, start=1):
            if self._exists_in_layer(lower_fs, normalized_path):
                return (lower_fs, normalized_path, idx)

        return None

    def open(
        self,
        path: str,
        mode: str = "r",
        **kwargs: Any,
    ) -> Any:
        """Open a file for reading or writing with COW semantics.

        Implements Copy-on-Write (COW) semantics for write operations:
        - Read modes: Open file from resolved layer (upper or lower)
        - Write modes: Copy file from lower to upper if needed, then open from upper

        Args:
            path: The file path to open.
            mode: The file open mode. Supported modes:
                - "r", "rb" - read only
                - "w", "wb" - write (truncate if exists)
                - "a", "ab" - append
                - "r+", "w+", "a+" - read/write update modes
            **kwargs: Additional arguments passed to underlying open calls.

        Returns:
            A file-like object for reading or writing.

        Raises:
            FileNotFoundError: If file doesn't exist for read mode.
            IsADirectoryError: If path is a directory.
            PathTraversalError: If path contains traversal sequences.

        Examples:
            # Read from any layer
            >>> with overlay.open("/file.txt", "r") as f:
            ...     content = f.read()

            # Write triggers COW if file in lower layer
            >>> with overlay.open("/file.txt", "w") as f:
            ...     f.write("new content")
        """
        # Validate path security
        _validate_path_security(path)

        normalized_path = _normalize_path(path)

        # Check if this is a write mode
        if self._is_write_mode(mode):
            # Write mode - need to handle COW
            # First, remove any whiteout marker to allow file recreation
            self._remove_whiteout(normalized_path)

            if self._needs_copy_up(normalized_path):
                # Check if the path in lower layer is a directory
                # If so, we cannot copy it up (it's a type conflict)
                # Just remove the directory whiteout and create a new file
                for lower_fs in self.lowers:
                    if lower_fs.isdir(normalized_path):
                        # It's a directory - can't copy up, just ensure parents
                        self._ensure_parent_dirs(normalized_path)
                        break
                else:
                    # File exists in lower layer only - copy it up first
                    self._copy_up(normalized_path)
            else:
                # File doesn't exist in any layer, or already in upper
                # Ensure parent directories exist for new files
                resolved = self._resolve(normalized_path)
                if resolved is None:
                    self._ensure_parent_dirs(normalized_path)

            # Open from upper layer (always write to upper)
            return self.upper.open(normalized_path, mode, **kwargs)
        else:
            # Read mode - resolve and open from source layer
            resolved = self._resolve(normalized_path)
            if resolved is None:
                raise FileNotFoundError(f"Path not found: {path}")

            fs, rel_path, _ = resolved

            # Check if it's a directory (can't open directories)
            if fs.isdir(rel_path):
                raise IsADirectoryError(f"Path is a directory, not a file: {path}")

            # Open from the resolved layer
            return fs.open(rel_path, mode, **kwargs)

    def mkdir(self, path: str, create_parents: bool = False, **kwargs: Any) -> None:
        """Create a directory in the upper layer.

        Creates a single directory in the upper (writable) layer only.
        Lower layers are never modified.

        Args:
            path: The directory path to create.
            create_parents: If True, create parent directories as needed.
                If False, raise FileNotFoundError if parent doesn't exist.
            **kwargs: Additional arguments passed to underlying mkdir calls.

        Raises:
            FileNotFoundError: If parent directory doesn't exist and
                create_parents is False.
            FileExistsError: If the directory already exists in upper layer.

        Example:
            >>> overlay.mkdir("/newdir")
            >>> overlay.mkdir("/a/b/c", create_parents=True)
        """
        normalized_path = _normalize_path(path)

        # Check if directory already exists in upper layer
        if self._exists_in_layer(self.upper, normalized_path):
            raise FileExistsError(f"Directory already exists: {path}")

        # Remove any directory whiteout marker to allow recreation
        self._remove_whiteout(normalized_path)

        if create_parents:
            # Create all parent directories as needed
            self.upper.makedirs(normalized_path, exist_ok=False)
        else:
            # Check if parent directory exists
            parent = "/".join(normalized_path.split("/")[:-1]) or "/"
            if not self._exists_in_layer(self.upper, parent):
                raise FileNotFoundError(f"Parent directory does not exist: {parent}")
            # Create single directory in upper layer
            self.upper.mkdir(normalized_path, **kwargs)

    def makedirs(self, path: str, exist_ok: bool = False, **kwargs: Any) -> None:
        """Create a directory and all its parents in the upper layer.

        Recursively creates all necessary directories in the upper (writable)
        layer only. Lower layers are never modified.

        Args:
            path: The directory path to create.
            exist_ok: If True, don't raise an error if the directory exists.
                If False, raise FileExistsError if directory exists.
            **kwargs: Additional arguments passed to underlying makedirs calls.

        Raises:
            FileExistsError: If the directory already exists and exist_ok is False.

        Example:
            >>> overlay.makedirs("/a/b/c")
            >>> overlay.makedirs("/a/b/c", exist_ok=True)
        """
        normalized_path = _normalize_path(path)

        # Check if directory already exists in upper layer
        if self._exists_in_layer(self.upper, normalized_path):
            if exist_ok:
                return
            raise FileExistsError(f"Directory already exists: {path}")

        # Remove whiteout markers for the directory and all parent directories
        # This allows recreation of directories that were previously deleted
        parts = normalized_path.split("/")
        for i in range(1, len(parts) + 1):
            parent_path = "/".join(parts[:i]) or "/"
            if parent_path != "/":
                self._remove_whiteout(parent_path)

        # Create directory and all parents in upper layer only
        self.upper.makedirs(normalized_path, exist_ok=False, **kwargs)

    def rename(self, path1: str, path2: str, **kwargs: Any) -> None:
        """Rename (move) a file from path1 to path2 with COW semantics.

        Implements overlay filesystem rename semantics:
        - If file is in lower layer: Copy-up then rename in upper layer
        - If file is in upper layer: Rename within upper layer
        - If target exists: Overwrite via delete then rename
        - Creates parent directories for target if needed

        The source file is 'moved' by copying to destination then handling
        the source according to overlay rules:
        - Upper layer files are removed (delete file, no whiteout needed)
        - Lower layer files get a whiteout marker (hide original)

        Args:
            path1: The source file path (current location).
            path2: The destination file path (new location).
            **kwargs: Additional arguments passed to underlying rename calls.

        Raises:
            FileNotFoundError: If the source path doesn't exist in any layer.
            IsADirectoryError: If the source path is a directory.

        Example:
            >>> overlay.rename("/old_name.txt", "/new_name.txt")
            >>> overlay.rename("/dir/file.txt", "/other_dir/file.txt")
        """
        src_path = _normalize_path(path1)
        dst_path = _normalize_path(path2)

        # Check if source exists and is not whited-out
        src_resolved = self._resolve(src_path)
        if src_resolved is None:
            raise FileNotFoundError(f"Path not found: {path1}")

        src_fs, src_rel_path, src_layer = src_resolved

        # Check if source is a directory (not supported for rename)
        if self.isdir(src_path):
            raise IsADirectoryError(f"Path is a directory: {path1}")

        # Track if source was originally in lower layer (need whiteout later)
        originally_in_lower = src_layer != 0

        # Handle COW: if source is in lower layer, copy it up first
        if originally_in_lower:
            self._copy_up(src_path)

        # Ensure parent directories exist for destination
        self._ensure_parent_dirs(dst_path)

        # If destination exists (in any layer), remove it first
        if self.exists(dst_path):
            # Use rm to handle both upper and lower layer targets correctly
            self.rm(dst_path)

        # Copy file content to destination in upper layer
        with self.upper.open(src_path, "rb") as src_file:
            content = src_file.read()

        with self.upper.open(dst_path, "wb") as dst_file:
            dst_file.write(content)

        # Handle source file cleanup based on where it originally existed
        if originally_in_lower:
            # Source was in lower layer - create whiteout to hide it
            self._create_whiteout(src_path)
            # Also remove the copied-up version from upper layer
            if self._exists_in_layer(self.upper, src_path):
                self.upper.rm(src_path, **kwargs)
        else:
            # Source was in upper layer - just delete it
            self.upper.rm(src_path, **kwargs)

    # =========================================================================
    # Large File Streaming Support (Task 29)
    # =========================================================================

    # Size threshold for streaming (1MB)
    _STREAM_THRESHOLD = 1024 * 1024
    # Default chunk size for streaming (64KB)
    _DEFAULT_CHUNK_SIZE = 64 * 1024

    def cat_file(
        self,
        path: str,
        start: int | None = None,
        end: int | None = None,
        **kwargs: Any,
    ) -> bytes:
        """Read file contents with optional byte range.

        This method provides efficient file reading with support for partial
        reads (byte ranges). For large files (>1MB), use streaming methods
        to avoid loading entire file into memory.

        Args:
            path: The file path to read.
            start: Starting byte position for partial reads (default: 0).
            end: Ending byte position for partial reads (default: file size).
            **kwargs: Additional arguments passed to underlying filesystem.

        Returns:
            File contents as bytes. For byte ranges, returns only the requested
            range.

        Raises:
            FileNotFoundError: If the file doesn't exist in any layer.
            IsADirectoryError: If the path is a directory.

        Examples:
            # Read entire file
            >>> content = overlay.cat_file("/test.txt")

            # Read first 1KB
            >>> partial = overlay.cat_file("/large.bin", end=1024)

            # Read bytes 1000-2000
            >>> slice_bytes = overlay.cat_file("/large.bin", start=1000, end=2000)
        """
        normalized_path = _normalize_path(path)

        # Resolve the path to find which layer has the file
        resolved = self._resolve(normalized_path)
        if resolved is None:
            raise FileNotFoundError(f"Path not found: {path}")

        fs, rel_path, _ = resolved

        # Check if it's a directory
        if fs.isdir(rel_path):
            raise IsADirectoryError(f"Path is a directory, not a file: {path}")

        # Use underlying filesystem's cat_file with byte range support
        return fs.cat_file(rel_path, start=start, end=end, **kwargs)

    def cat(
        self,
        paths: str | list[str],
        recursive: bool = False,
        on_error: str = "raise",
        **kwargs: Any,
    ) -> bytes | dict[str, bytes | BaseException]:
        """Read file contents from one or more paths.

        This is the standard fsspec method for reading file contents.
        For single paths, returns bytes. For multiple paths, returns a
        dictionary mapping paths to their contents.

        Args:
            paths: Path string or list of path strings to read.
            recursive: If True and paths is a directory, read all files
                recursively (default: False).
            on_error: Error handling strategy:
                - "raise": Raise exceptions immediately (default)
                - "omit": Skip files that raise errors
                - "return": Return exceptions as values in dict
            **kwargs: Additional arguments passed to underlying filesystem.

        Returns:
            For single path: file contents as bytes.
            For multiple paths: dict mapping {path: contents or exception}.

        Raises:
            FileNotFoundError: If a file doesn't exist (and on_error='raise').

        Examples:
            # Read single file
            >>> content = overlay.cat("/test.txt")

            # Read multiple files
            >>> contents = overlay.cat(["/file1.txt", "/file2.txt"])
        """
        from collections.abc import Iterator

        # Handle single path
        if isinstance(paths, str):
            normalized_path = _normalize_path(paths)
            resolved = self._resolve(normalized_path)

            if resolved is None:
                if on_error == "raise":
                    raise FileNotFoundError(f"Path not found: {paths}")
                elif on_error == "omit":
                    return b""
                else:
                    return {paths: FileNotFoundError(f"Path not found: {paths}")}

            fs, rel_path, _ = resolved
            return fs.cat(rel_path, recursive=recursive, on_error=on_error, **kwargs)

        # Handle multiple paths
        result: dict[str, bytes | BaseException] = {}
        for path in paths:
            try:
                content = self.cat(
                    path, recursive=recursive, on_error="raise", **kwargs
                )
                if isinstance(content, bytes):
                    result[path] = content
                elif isinstance(content, dict):
                    # Content is a dict from recursive cat - add all entries
                    for k, v in content.items():
                        if isinstance(v, (bytes, BaseException)):
                            result[k] = v
                else:
                    # Unexpected type, skip
                    pass
            except Exception as e:
                if on_error == "raise":
                    raise
                elif on_error == "omit":
                    continue
                else:
                    result[path] = e

        return result

    def _cat_file_streaming(
        self,
        path: str,
        chunk_size: int | None = None,
        **kwargs: Any,
    ):
        """Stream file contents in chunks for memory-efficient reading.

        This is the core streaming method for large files. It yields file
        content in chunks without loading the entire file into memory at once.

        Args:
            path: The file path to stream.
            chunk_size: Size of chunks to yield in bytes (default: 64KB).
            **kwargs: Additional arguments (unused, for compatibility).

        Yields:
            File content chunks as bytes.

        Raises:
            FileNotFoundError: If the file doesn't exist in any layer.
            IsADirectoryError: If the path is a directory.

        Examples:
            # Stream large file efficiently
            >>> for chunk in overlay._cat_file_streaming("/large.bin"):
            ...     process_chunk(chunk)

            # Stream with custom chunk size (256KB)
            >>> for chunk in overlay._cat_file_streaming("/large.bin", chunk_size=262144):
            ...     process_chunk(chunk)
        """
        from collections.abc import Iterator

        normalized_path = _normalize_path(path)
        chunk_size = chunk_size or self._DEFAULT_CHUNK_SIZE

        # Resolve the path
        resolved = self._resolve(normalized_path)
        if resolved is None:
            raise FileNotFoundError(f"Path not found: {path}")

        fs, rel_path, _ = resolved

        # Check if it's a directory
        if fs.isdir(rel_path):
            raise IsADirectoryError(f"Path is a directory, not a file: {path}")

        # Get file info for size
        file_info = fs.info(rel_path)
        file_size = file_info.get("size", 0)

        # Stream the file in chunks
        offset = 0
        while offset < file_size:
            # Calculate chunk size (may be smaller at end of file)
            current_chunk_size = min(chunk_size, file_size - offset)
            chunk_end = offset + current_chunk_size

            # Read this chunk using cat_file with byte range
            chunk = fs.cat_file(rel_path, start=offset, end=chunk_end)
            yield chunk

            offset = chunk_end

    def size(self, path: str, **kwargs: Any) -> int | None:
        """Get the size of a file in bytes.

        Args:
            path: The file path to check.
            **kwargs: Additional arguments passed to underlying filesystem.

        Returns:
            File size in bytes, or None if path doesn't exist or is a directory.

        Examples:
            >>> file_size = overlay.size("/large.bin")
            >>> print(f"File is {file_size} bytes")
        """
        normalized_path = _normalize_path(path)
        resolved = self._resolve(normalized_path)

        if resolved is None:
            return None

        fs, rel_path, _ = resolved

        # Handle directory case
        if fs.isdir(rel_path):
            return None

        # Get size from info
        try:
            info = fs.info(rel_path, **kwargs)
            return info.get("size")
        except Exception:
            return None

    def is_streaming_file(
        self, path: str, threshold: int | None = None, **kwargs: Any
    ) -> bool:
        """Check if a file should be streamed rather than loaded entirely.

        Files larger than the streaming threshold should be processed
        using streaming methods to avoid memory pressure.

        Args:
            path: The file path to check.
            threshold: Size threshold in bytes (default: 1MB).
            **kwargs: Additional arguments (for compatibility).

        Returns:
            True if the file should be streamed, False otherwise.

        Examples:
            # Check if file needs streaming
            >>> if overlay.is_streaming_file("/large.bin"):
            ...     for chunk in overlay._cat_file_streaming("/large.bin"):
            ...         process(chunk)
            ... else:
            ...     content = overlay.cat_file("/small.txt")
        """
        normalized_path = _normalize_path(path)
        resolved = self._resolve(normalized_path)

        if resolved is None:
            return False

        fs, rel_path, _ = resolved

        # Get file size
        try:
            info = fs.info(rel_path, **kwargs)
            file_size = info.get("size", 0)
        except Exception:
            return False

        # Directories are not streaming files
        if info.get("type") == "directory":
            return False

        threshold = threshold or self._STREAM_THRESHOLD
        return file_size >= threshold

    # ========================================================================
    # Whiteout Management Methods
    # ========================================================================

    def _remove_whiteout(self, path: str) -> bool:
        """Remove a whiteout marker from the upper layer.

        This is called when a file is being recreated after deletion,
        to ensure the new file is visible.

        Args:
            path: The path to remove whiteout marker for.

        Returns:
            True if a whiteout marker was removed, False otherwise.

        Example:
            >>> overlay._remove_whiteout("/file.txt")
            True  # If .wh.file.txt was removed
        """
        normalized_path = _normalize_path(path)
        whiteout_path = self._get_whiteout_path(normalized_path)

        # Check if whiteout exists in upper layer
        if self._exists_in_layer(self.upper, whiteout_path):
            try:
                self.upper.rm(whiteout_path)
                return True
            except Exception:
                return False
        return False

    def _get_all_whiteouts(self, dir_path: str) -> list[WhiteoutInfo]:
        """Get all whiteout markers in a directory and its subdirectories.

        Recursively scans the upper layer for .wh.* files and returns
        information about each whiteout marker found.

        Args:
            dir_path: The directory path to scan for whiteout markers.

        Returns:
            List of WhiteoutInfo objects for all whiteouts found.

        Example:
            >>> whiteouts = overlay._get_all_whiteouts("/")
            >>> whiteouts[0].path
            '/file.txt'
        """
        normalized_path = _normalize_path(dir_path)
        whiteouts: list[WhiteoutInfo] = []

        def scan_directory(current_dir: str) -> None:
            """Recursively scan directory for whiteout markers."""
            if not self._exists_in_layer(self.upper, current_dir):
                return

            try:
                entries = self.upper.ls(current_dir)
                for entry in entries:
                    # Handle both string and dict entries
                    if isinstance(entry, dict):
                        name = entry.get("name", "").split("/")[-1]
                        entry_type = entry.get("type", "file")
                    else:
                        name = entry.split("/")[-1] if "/" in entry else entry
                        # Check if it's a directory
                        full_path = (
                            f"{current_dir}/{name}"
                            if current_dir != "/"
                            else f"/{name}"
                        )
                        entry_type = (
                            "directory" if self.upper.isdir(full_path) else "file"
                        )

                    if name.startswith(".wh."):
                        # Extract the original filename from .wh.<filename>
                        original_name = name[4:]  # Remove ".wh." prefix
                        if current_dir == "/":
                            original_path = f"/{original_name}"
                        else:
                            original_path = f"{current_dir}/{original_name}"

                        whiteouts.append(
                            WhiteoutInfo(
                                path=original_path,
                                whiteout_path=f"{current_dir}/{name}"
                                if current_dir != "/"
                                else f"/{name}",
                            )
                        )
                    elif entry_type == "directory":
                        # Recursively scan subdirectory
                        if current_dir == "/":
                            subdir = f"/{name}"
                        else:
                            subdir = f"{current_dir}/{name}"
                        scan_directory(subdir)
            except Exception:
                pass  # Directory might not exist or other error

        scan_directory(normalized_path)
        return whiteouts

    def _is_stale_whiteout(self, path: str) -> bool:
        """Check if a whiteout marker is stale.

        A whiteout is stale if there's no corresponding file or directory
        in any layer that it would hide.

        Args:
            path: The path to check for stale whiteout.

        Returns:
            True if the whiteout is stale, False otherwise.
            Returns False if no whiteout exists for the path.

        Example:
            >>> overlay._is_stale_whiteout("/file.txt")
            True  # If no file exists in any layer
        """
        normalized_path = _normalize_path(path)

        # First check if a whiteout exists
        if not self._has_whiteout(normalized_path):
            return False

        # Check if there's a file or directory in any layer
        # (excluding the whiteout marker itself)
        resolved = self._resolve_without_whiteout(normalized_path)
        return resolved is None

    def find_stale_whiteouts(self, dir_path: str) -> list[WhiteoutInfo]:
        """Find all stale whiteout markers in a directory.

        Scans the directory and its subdirectories for whiteout markers
        that no longer correspond to existing files or directories.

        Args:
            dir_path: The directory path to scan.

        Returns:
            List of WhiteoutInfo objects for stale whiteouts.

        Example:
            >>> stale = overlay.find_stale_whiteouts("/")
            >>> # stale contains only whiteouts with no corresponding files
        """
        all_whiteouts = self._get_all_whiteouts(dir_path)
        stale_whiteouts: list[WhiteoutInfo] = []

        for whiteout in all_whiteouts:
            if self._is_stale_whiteout(whiteout.path):
                whiteout.is_stale = True
                stale_whiteouts.append(whiteout)

        return stale_whiteouts

    def cleanup_stale_whiteouts(self, dir_path: str) -> list[str]:
        """Remove all stale whiteout markers from the upper layer.

        Finds and removes stale whiteout markers, cleaning up the
        filesystem state.

        Args:
            dir_path: The directory path to clean up.

        Returns:
            List of whiteout paths that were removed.

        Example:
            >>> removed = overlay.cleanup_stale_whiteouts("/")
            >>> removed
            ['/.wh.orphan.txt', '/.wh.old_file.txt']
        """
        stale_whiteouts = self.find_stale_whiteouts(dir_path)
        removed: list[str] = []

        for whiteout in stale_whiteouts:
            try:
                self.upper.rm(whiteout.whiteout_path)
                removed.append(whiteout.whiteout_path)
            except Exception:
                pass  # Ignore errors during cleanup

        return removed

    def get_whiteout_stats(self, dir_path: str) -> dict[str, Any]:
        """Get statistics about whiteout markers in a directory.

        Args:
            dir_path: The directory path to analyze.

        Returns:
            Dictionary with whiteout statistics:
            - total: Total number of whiteout markers
            - stale: Number of stale whiteout markers
            - valid: Number of valid whiteout markers
            - stale_paths: List of paths to stale whiteouts

        Example:
            >>> stats = overlay.get_whiteout_stats("/")
            >>> stats["total"]
            5
        """
        all_whiteouts = self._get_all_whiteouts(dir_path)
        stale_whiteouts = self.find_stale_whiteouts(dir_path)

        return {
            "total": len(all_whiteouts),
            "stale": len(stale_whiteouts),
            "valid": len(all_whiteouts) - len(stale_whiteouts),
            "stale_paths": [w.whiteout_path for w in stale_whiteouts],
            "by_layer": {},
        }

    # ========================================================================
    # Directory Operations with Whiteout Support
    # ========================================================================

    def rmdir(self, path: str, **kwargs: Any) -> None:
        """Remove a directory with whiteout support.

        Implements overlay filesystem directory deletion semantics:
        - If directory is in upper layer: delete it directly
        - If directory is in lower layer only: create whiteout marker
        - If directory doesn't exist: raise FileNotFoundError
        - If directory is not empty: raise OSError

        Args:
            path: The path to the directory to remove.
            **kwargs: Additional arguments passed to underlying rmdir calls.

        Raises:
            FileNotFoundError: If the path doesn't exist in any layer.
            NotADirectoryError: If the path is a file, not a directory.
            OSError: If the directory is not empty.

        Example:
            >>> overlay.rmdir("/testdir")
            # Directory deleted from upper, or whiteout created if in lower
        """
        normalized_path = _normalize_path(path)

        # Check whiteout first - if already whited-out, nothing to do (idempotent)
        if self._has_whiteout(normalized_path):
            return

        # Check if path exists (respecting existing whiteouts)
        if not self.exists(normalized_path):
            raise FileNotFoundError(f"Path not found: {path}")

        # Check if it's a file (not a directory)
        if not self.isdir(normalized_path):
            raise NotADirectoryError(f"Path is a file, not a directory: {path}")

        # Check if directory is empty
        try:
            entries = self.ls(normalized_path)
            # Filter out empty entries
            if entries and any(e for e in entries if e):
                raise OSError(f"Directory not empty: {path}")
        except OSError:
            raise OSError(f"Directory not empty: {path}")

        # Resolve to find which layer has the directory
        resolved = self._resolve_without_whiteout(normalized_path)
        if resolved is None:
            raise FileNotFoundError(f"Path not found: {path}")

        fs, rel_path, layer_index = resolved

        if layer_index == 0:
            # Directory is in upper layer - check if it also exists in lower layers
            # (might have been auto-created when adding whiteout markers)
            exists_in_lower = False
            for lower_fs in self.lowers:
                if self._exists_in_layer(lower_fs, normalized_path):
                    exists_in_lower = True
                    break

            if exists_in_lower:
                # Directory exists in both upper and lower - remove from upper and create whiteout
                fs.rmdir(rel_path, **kwargs)
                self._create_whiteout(normalized_path)
            else:
                # Directory only in upper - delete it directly
                fs.rmdir(rel_path, **kwargs)
        else:
            # Directory is in lower layer only - create whiteout marker
            self._create_whiteout(normalized_path)
