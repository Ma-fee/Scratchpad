"""Resource limit enforcement for OverlayFileSystem.

This module provides resource limit enforcement to prevent DoS attacks
via resource exhaustion. It implements configurable limits for:
- Maximum file size
- Maximum files per directory
- Maximum directory depth
- Maximum total files
- Maximum total size
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from ..exceptions import FileSizeLimitError, ResourceLimitError

if TYPE_CHECKING:
    from fsspec import AbstractFileSystem


def _normalize_path_internal(path: str) -> str:
    """Internal path normalization for resource limits."""
    if not path.startswith("/"):
        path = "/" + path
    # Remove trailing slash except for root
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    return path


# 默认限制值 (保守的安全默认值)
DEFAULT_MAX_FILE_SIZE_BYTES = 100 * 1024 * 1024  # 100 MB
DEFAULT_MAX_FILES_PER_DIR = 1000
DEFAULT_MAX_DIRECTORY_DEPTH = 10
DEFAULT_MAX_TOTAL_FILES = 10000
DEFAULT_MAX_TOTAL_SIZE_BYTES = 1 * 1024 * 1024 * 1024  # 1 GB


@dataclass
class ResourceLimits:
    """Resource limits configuration for OverlayFileSystem.

    All limits are optional. Setting a limit to 0 or None disables that limit.

    Attributes:
        max_file_size_bytes: Maximum size of a single file
        max_files_per_directory: Maximum number of files in a directory
        max_directory_depth: Maximum nesting depth of directories
        max_total_files: Maximum total number of files in the filesystem
        max_total_size_bytes: Maximum total size of all files
    """

    max_file_size_bytes: int | None = DEFAULT_MAX_FILE_SIZE_BYTES
    max_files_per_directory: int | None = DEFAULT_MAX_FILES_PER_DIR
    max_directory_depth: int | None = DEFAULT_MAX_DIRECTORY_DEPTH
    max_total_files: int | None = DEFAULT_MAX_TOTAL_FILES
    max_total_size_bytes: int | None = DEFAULT_MAX_TOTAL_SIZE_BYTES

    def __post_init__(self) -> None:
        """验证限制值的有效性"""
        # 确保所有限制值都是非负数或 None
        limits = [
            ("max_file_size_bytes", self.max_file_size_bytes),
            ("max_files_per_directory", self.max_files_per_directory),
            ("max_directory_depth", self.max_directory_depth),
            ("max_total_files", self.max_total_files),
            ("max_total_size_bytes", self.max_total_size_bytes),
        ]

        for name, value in limits:
            if value is not None and value < 0:
                raise ValueError(f"{name} cannot be negative: {value}")

    def is_limit_enabled(self, limit_name: str) -> bool:
        """检查特定限制是否启用。

        Args:
            limit_name: 限制属性名

        Returns:
            True 如果限制已启用（值不为 None 且不为 0）
        """
        value = getattr(self, limit_name, None)
        return value is not None and value > 0


class ResourceLimitEnforcer:
    """Resource limit enforcer for filesystem operations.

    This class provides methods to validate resource limits before
    performing filesystem operations.
    """

    def __init__(
        self,
        limits: ResourceLimits | None = None,
        upper_fs: AbstractFileSystem | None = None,
        lowers: list[AbstractFileSystem] | None = None,
    ) -> None:
        """Initialize the resource limit enforcer.

        Args:
            limits: Resource limits configuration (uses defaults if None)
            upper_fs: Upper filesystem layer for size calculations
            lowers: Lower filesystem layers for size calculations
        """
        self.limits = limits or ResourceLimits()
        self.upper = upper_fs
        self.lowers = lowers or []

    def check_file_size(
        self,
        file_path: str,
        file_size: int,
    ) -> None:
        """Check if file size exceeds the limit.

        Args:
            file_path: Path to the file (for error reporting)
            file_size: Size of the file in bytes

        Raises:
            FileSizeLimitError: If file size exceeds the limit
        """
        limit = self.limits.max_file_size_bytes
        if limit is None or limit == 0:
            return

        if file_size > limit:
            raise FileSizeLimitError(
                f"File size {file_size} bytes exceeds limit of {limit} bytes",
                file_path=file_path,
                file_size=file_size,
                size_limit=limit,
            )

    def check_directory_file_count(
        self,
        dir_path: str,
        fs: AbstractFileSystem,
    ) -> None:
        """Check if directory file count exceeds the limit.

        Args:
            dir_path: Path to the directory
            fs: Filesystem to check

        Raises:
            ResourceLimitError: If directory file count exceeds the limit
        """
        limit = self.limits.max_files_per_directory
        if limit is None or limit == 0:
            return

        try:
            # 获取目录中的文件数量
            entries = fs.ls(dir_path, detail=False)
            file_count = len([e for e in entries if not fs.isdir(e)])

            if file_count >= limit:
                raise ResourceLimitError(
                    f"Directory {dir_path} contains {file_count} files, "
                    f"exceeds limit of {limit}",
                    resource_type="files_per_directory",
                    current_value=file_count,
                    limit_value=limit,
                    path=dir_path,
                )
        except ResourceLimitError:
            raise
        except Exception:
            # 如果无法获取目录信息，允许操作继续
            pass

    def check_directory_depth(self, path: str) -> None:
        """Check if directory depth exceeds the limit.

        Args:
            path: Path to check

        Raises:
            ResourceLimitError: If directory depth exceeds the limit
        """
        limit = self.limits.max_directory_depth
        if limit is None or limit == 0:
            return

        # 规范化路径并计算深度
        normalized = _normalize_path_internal(path)
        parts = [p for p in normalized.split("/") if p and p != "."]
        depth = len(parts)

        if depth > limit:
            raise ResourceLimitError(
                f"Directory depth {depth} exceeds limit of {limit}",
                resource_type="directory_depth",
                current_value=depth,
                limit_value=limit,
                path=path,
            )

    def check_total_resources(self) -> None:
        """Check if total resource usage exceeds limits.

        Raises:
            ResourceLimitError: If total files or size exceeds limits
        """
        self._check_total_files()
        self._check_total_size()

    def _check_total_files(self) -> None:
        """检查总文件数是否超过限制"""
        limit = self.limits.max_total_files
        if limit is None or limit == 0:
            return

        if self.upper is None:
            return

        try:
            total_files = self._count_files_recursive(self.upper, "/")

            if total_files >= limit:
                raise ResourceLimitError(
                    f"Total file count {total_files} exceeds limit of {limit}",
                    resource_type="total_files",
                    current_value=total_files,
                    limit_value=limit,
                )
        except ResourceLimitError:
            raise
        except Exception:
            pass

    def _check_total_size(self) -> None:
        """检查总文件大小是否超过限制"""
        limit = self.limits.max_total_size_bytes
        if limit is None or limit == 0:
            return

        if self.upper is None:
            return

        try:
            total_size = self._calculate_total_size(self.upper, "/")

            if total_size > limit:
                raise ResourceLimitError(
                    f"Total size {total_size} bytes exceeds limit of {limit} bytes",
                    resource_type="total_size",
                    current_value=total_size,
                    limit_value=limit,
                )
        except ResourceLimitError:
            raise
        except Exception:
            pass

    def _count_files_recursive(
        self,
        fs: AbstractFileSystem,
        path: str,
    ) -> int:
        """递归计算文件数量"""
        count = 0
        try:
            entries = fs.ls(path, detail=False)
            for entry in entries:
                if fs.isfile(entry):
                    count += 1
                elif fs.isdir(entry):
                    count += self._count_files_recursive(fs, entry)
        except Exception:
            pass
        return count

    def _calculate_total_size(
        self,
        fs: AbstractFileSystem,
        path: str,
    ) -> int:
        """递归计算总文件大小"""
        total = 0
        try:
            entries = fs.ls(path, detail=False)
            for entry in entries:
                if fs.isfile(entry):
                    try:
                        info = fs.info(entry)
                        total += info.get("size", 0)
                    except Exception:
                        pass
                elif fs.isdir(entry):
                    total += self._calculate_total_size(fs, entry)
        except Exception:
            pass
        return total

    def validate_write_operation(
        self,
        path: str,
        data_size: int = 0,
        fs: AbstractFileSystem | None = None,
    ) -> None:
        """Validate all resource limits before a write operation.

        这是写操作的入口点，执行所有适用的限制检查。

        Args:
            path: 目标路径
            data_size: 要写入的数据大小
            fs: 文件系统（用于目录计数检查）

        Raises:
            FileSizeLimitError: 如果文件大小超过限制
            ResourceLimitError: 如果其他资源限制被超过
        """
        # 检查文件大小
        if data_size > 0:
            self.check_file_size(path, data_size)

        # 检查目录深度
        self.check_directory_depth(path)

        # 检查总资源
        self.check_total_resources()

        # 检查父目录的文件数量
        if fs is not None:
            parent = str(Path(path).parent)
            if parent and parent != ".":
                self.check_directory_file_count(parent, fs)

    def validate_mkdir_operation(
        self,
        path: str,
        fs: AbstractFileSystem | None = None,
    ) -> None:
        """Validate resource limits before creating a directory.

        Args:
            path: Directory path to create
            fs: Filesystem to check

        Raises:
            ResourceLimitError: If limits would be exceeded
        """
        # 检查目录深度
        self.check_directory_depth(path)

        # 检查父目录的文件数量
        if fs is not None:
            parent = str(Path(path).parent)
            if parent and parent != "." and parent != "/":
                self.check_directory_file_count(parent, fs)

    def get_resource_stats(self) -> dict[str, int | None]:
        """获取当前资源使用统计。

        Returns:
            Dictionary with current resource usage and limits
        """
        stats: dict[str, int | None] = {
            "max_file_size_bytes": self.limits.max_file_size_bytes,
            "max_files_per_directory": self.limits.max_files_per_directory,
            "max_directory_depth": self.limits.max_directory_depth,
            "max_total_files": self.limits.max_total_files,
            "max_total_size_bytes": self.limits.max_total_size_bytes,
        }

        # 计算当前使用量
        if self.upper is not None:
            try:
                stats["current_total_files"] = self._count_files_recursive(
                    self.upper, "/"
                )
                stats["current_total_size"] = self._calculate_total_size(
                    self.upper, "/"
                )
            except Exception:
                stats["current_total_files"] = None
                stats["current_total_size"] = None

        return stats


def create_default_enforcer(
    upper_fs: AbstractFileSystem | None = None,
    lowers: list[AbstractFileSystem] | None = None,
) -> ResourceLimitEnforcer:
    """创建使用默认限制的资源限制强制执行器。

    Args:
        upper_fs: Upper filesystem layer
        lowers: Lower filesystem layers

    Returns:
        ResourceLimitEnforcer with default limits
    """
    return ResourceLimitEnforcer(
        limits=ResourceLimits(),
        upper_fs=upper_fs,
        lowers=lowers,
    )


def create_unlimited_enforcer(
    upper_fs: AbstractFileSystem | None = None,
    lowers: list[AbstractFileSystem] | None = None,
) -> ResourceLimitEnforcer:
    """创建无限制的资源限制强制执行器。

    用于测试或需要无限资源的场景。

    Args:
        upper_fs: Upper filesystem layer
        lowers: Lower filesystem layers

    Returns:
        ResourceLimitEnforcer with all limits disabled
    """
    return ResourceLimitEnforcer(
        limits=ResourceLimits(
            max_file_size_bytes=None,
            max_files_per_directory=None,
            max_directory_depth=None,
            max_total_files=None,
            max_total_size_bytes=None,
        ),
        upper_fs=upper_fs,
        lowers=lowers,
    )
