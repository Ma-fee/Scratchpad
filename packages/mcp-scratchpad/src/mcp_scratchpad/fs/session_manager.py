"""
Session FileSystem Manager - Session Lifecycle Implementation.

This module provides the SessionFileSystemManager class for managing
per-session overlay filesystem instances with full session lifecycle
and metadata tracking.

Architecture:
- Each session gets an isolated overlay filesystem view
- Upper layer: MemoryFileSystem per session (read-write)
- Lower layers: Configured mounts from OverlayConfig (typically read-only)
- Session metadata tracked: creation time, last access, custom metadata
"""

from __future__ import annotations

import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from fsspec import AbstractFileSystem
from fsspec.implementations.dirfs import DirFileSystem
from fsspec.implementations.local import LocalFileSystem
from fsspec.implementations.memory import MemoryFileSystem
from urllib.parse import urlparse

from ..config.models import OverlayConfig
from .backends import create_filesystem
from .overlay import OverlayFileSystem
from .session_validator import validate_session_id


@dataclass
class SessionMetadata:
    """Metadata for a filesystem session.

    Tracks session lifecycle information including creation time,
    last access time, and custom metadata.

    Attributes:
        session_id: Unique identifier for the session (UUID4).
        created_at: Timestamp when the session was created.
        last_accessed: Timestamp of the most recent access.
        metadata: Optional dictionary for custom session data.

    Example:
        >>> from datetime import datetime
        >>> meta = SessionMetadata(
        ...     session_id="abc-123",
        ...     created_at=datetime.now(),
        ...     last_accessed=datetime.now()
        ... )
        >>> meta.session_id
        'abc-123'
    """

    session_id: str
    created_at: datetime
    last_accessed: datetime
    metadata: dict[str, Any] = field(default_factory=dict)


class OverlayFileSystemProtocol(Protocol):
    """Protocol for session-specific overlay filesystem.

    This protocol defines the interface for overlay filesystems that
    will be implemented in Phase 2. It provides a type-safe contract
    for filesystem operations across the session manager.

    Methods:
        ls: List directory contents
        open: Open a file for reading/writing
        exists: Check if a path exists
        isfile: Check if path is a file
        isdir: Check if path is a directory
        info: Get file/directory metadata
    """

    def ls(self, path: str, **kwargs: Any) -> list[dict[str, Any]]:
        """List directory contents."""
        ...

    def open(self, path: str, mode: str = "r", **kwargs: Any) -> Any:  # noqa: A003
        """Open a file."""
        ...

    def exists(self, path: str) -> bool:
        """Check if path exists."""
        ...

    def isfile(self, path: str) -> bool:
        """Check if path is a file."""
        ...

    def isdir(self, path: str) -> bool:
        """Check if path is a directory."""
        ...

    def info(self, path: str) -> dict[str, Any]:
        """Get file/directory info."""
        ...


class SessionUpperDirFileSystem(DirFileSystem):
    """DirFileSystem variant that accepts overlay-style absolute paths."""

    @staticmethod
    def _normalize_overlay_path(path: str) -> str:
        if path.startswith("/") and path != "/":
            return path.lstrip("/")
        return path

    def exists(self, path: str, **kwargs: Any) -> bool:
        return super().exists(self._normalize_overlay_path(path), **kwargs)

    def isdir(self, path: str) -> bool:
        return super().isdir(self._normalize_overlay_path(path))

    def isfile(self, path: str) -> bool:
        return super().isfile(self._normalize_overlay_path(path))

    def info(self, path: str, **kwargs: Any) -> dict[str, Any]:
        return super().info(self._normalize_overlay_path(path), **kwargs)

    def ls(self, path: str, *args: Any, **kwargs: Any) -> list[Any]:
        return super().ls(self._normalize_overlay_path(path), *args, **kwargs)

    def mkdir(self, path: str, *args: Any, **kwargs: Any) -> None:
        super().mkdir(self._normalize_overlay_path(path), *args, **kwargs)

    def makedirs(self, path: str, *args: Any, **kwargs: Any) -> None:
        super().makedirs(self._normalize_overlay_path(path), *args, **kwargs)

    def open(self, path: str, *args: Any, **kwargs: Any) -> Any:
        return super().open(self._normalize_overlay_path(path), *args, **kwargs)

    def rm(self, path: str, *args: Any, **kwargs: Any) -> None:
        super().rm(self._normalize_overlay_path(path), *args, **kwargs)


class SessionFileSystemManager:
    """Manages per-session overlay filesystem instances with lifecycle tracking.

    This class provides session-scoped filesystem management using a
    multi-layer overlay architecture. Each session gets:
    1. A memory-based upper layer for writes
    2. Access to configured readonly lower layers
    3. Full session metadata tracking (creation time, access, expiration)

    Attributes:
        config: Overlay configuration with mount definitions.
        _default_session_ttl: Default TTL for new sessions.
        _sessions: Dictionary mapping session IDs to filesystem instances.
        _session_metadata: Dictionary mapping session IDs to SessionMetadata.
        _mounts: Dictionary mapping mount names to filesystem instances.

    Example:
        >>> from mcp_scratchpad.config.models import OverlayConfig
        >>> config = OverlayConfig(mounts=[])
        >>> manager = SessionFileSystemManager(config)
        >>> session_id = manager.create_session()
        >>> meta = manager.get_session(session_id)
        >>> meta.session_id == session_id
        True
        >>> sessions = manager.list_sessions()
        >>> len(sessions)
        1
        >>> manager.cleanup_session(session_id)
    """

    def __init__(
        self,
        config: OverlayConfig,
        default_session_ttl: timedelta | None = None,
    ) -> None:
        """Initialize the session filesystem manager.

        Args:
            config: Overlay configuration with mount definitions.
            default_session_ttl: Optional default TTL for new sessions.
        """
        self.config: OverlayConfig = config
        self._default_session_ttl: timedelta | None = default_session_ttl
        self._sessions: dict[str, OverlayFileSystem] = {}
        self._session_metadata: dict[str, SessionMetadata] = {}
        self._mounts: dict[str, AbstractFileSystem] = {}
        self._mount_paths: dict[
            str, str
        ] = {}  # Store paths separately (LocalFileSystem is singleton)
        self._last_accessed: dict[str, datetime] = {}
        self._session_upper_backend = self.config.session_upper.backend
        self._session_upper_local_root = Path(self.config.session_upper.local_root)
        self._session_upper_preserve_on_cleanup = (
            self.config.session_upper.preserve_on_cleanup
        )
        self._initialize_mounts()

    def _initialize_mounts(self) -> None:
        """Initialize underlying filesystems from configuration.

        Creates fsspec filesystems for each configured mount.
        Supports file:// URLs and local paths.
        """
        for mount in self.config.mounts:
            try:
                fs = create_filesystem(mount)
                self._mounts[mount.name] = fs

                # 向后兼容：保留 file:// mount 的源路径，供旧逻辑读取 _mount_paths。
                if mount.source.startswith("file://"):
                    parsed = urlparse(mount.source)
                    self._mount_paths[mount.name] = parsed.path
            except Exception as e:
                print(f"Warning: Failed to mount {mount.name}: {e}")

    def _get_mount_for_path(self, path: str) -> tuple[str, AbstractFileSystem] | None:
        """Find the best matching mount for a given path.

        Args:
            path: The path to resolve (e.g., "/memory/shared/foo.txt")

        Returns:
            Tuple of (mount_name, filesystem) or None if no mount matches.
        """
        best_match: tuple[str, AbstractFileSystem] | None = None
        best_len = -1

        for mount in self.config.mounts:
            if mount.name not in self._mounts:
                continue

            mount_point = mount.mount_point.rstrip("/") or "/"
            if mount_point == "/":
                matched = True
            else:
                matched = path == mount_point or path.startswith(f"{mount_point}/")

            if matched and len(mount_point) > best_len:
                best_match = (mount.name, self._mounts[mount.name])
                best_len = len(mount_point)

        return best_match


    def resolve_mount_path(self, path: str) -> tuple[AbstractFileSystem, str] | None:
        """Resolve an overlay-visible path to a mounted filesystem path."""
        mount_match = self._get_mount_for_path(path)
        if mount_match is None:
            return None

        mount_name, fs = mount_match
        mount = self.config.get_mount_by_name(mount_name)
        if mount is None:
            return None

        mount_point = mount.mount_point.rstrip("/") or "/"
        if mount_point == "/":
            relative_path = path
        else:
            relative_path = path[len(mount_point) :]
            relative_path = relative_path or "/"

        if not relative_path.startswith("/"):
            relative_path = f"/{relative_path}"

        return fs, relative_path

    def _init_session_workspace(self, fs: AbstractFileSystem) -> None:
        """Initialize session workspace directory structure."""
        if not fs.exists("/workspace"):
            workspace_path = (
                "workspace" if isinstance(fs, DirFileSystem) else "/workspace"
            )
            fs.mkdir(workspace_path)

    def _build_session_upper_fs(self, session_id: str) -> AbstractFileSystem:
        """Build writable upper filesystem for a session."""
        if self._session_upper_backend == "local":
            session_root = self._session_upper_local_root / session_id
            session_root.mkdir(parents=True, exist_ok=True)
            return SessionUpperDirFileSystem(
                path=str(session_root),
                fs=LocalFileSystem(auto_mkdir=True),
            )

        return SessionUpperDirFileSystem(
            path=f"/__sessions__/{session_id}",
            fs=MemoryFileSystem(),
        )

    def _clear_local_dirfs_prefix(self, fs: DirFileSystem) -> None:
        """Delete local filesystem directory behind a DirFileSystem prefix."""
        root = Path(fs.path)
        if self._session_upper_preserve_on_cleanup:
            return
        if root.exists():
            shutil.rmtree(root, ignore_errors=True)

    def _build_lower_layers_for_session(self) -> list[AbstractFileSystem]:
        """Build lower layers for per-session overlay instances."""
        ro_mounts = [mount for mount in self.config.mounts if mount.mode == "ro"]
        ro_mounts.sort(key=lambda mount: mount.priority, reverse=True)
        lowers: list[AbstractFileSystem] = []

        for mount in ro_mounts:
            fs = self._mounts.get(mount.name)
            if fs is not None:
                lowers.append(fs)

        return lowers

    def create_session(
        self,
        metadata: dict[str, Any] | None = None,
        ttl: timedelta | None = None,
    ) -> str:
        """Create a new session with a unique session ID.

        Args:
            metadata: Optional dictionary of custom session metadata.
            ttl: Optional TTL for this session (overrides default).

        Returns:
            Unique session ID (UUID4 string).
        """
        session_id: str = str(uuid.uuid4())
        now = datetime.now()

        # Create session metadata dict
        meta: dict[str, Any] = metadata.copy() if metadata else {}

        # Store TTL in metadata for expiration tracking
        effective_ttl = ttl if ttl is not None else self._default_session_ttl
        if effective_ttl is not None:
            meta["expires_at"] = now + effective_ttl
            meta["ttl_seconds"] = effective_ttl.total_seconds()

        # Create isolated overlay filesystem for this session
        upper_fs = self._build_session_upper_fs(session_id)
        self._init_session_workspace(upper_fs)
        overlay_fs = OverlayFileSystem(
            upper=upper_fs,
            lowers=self._build_lower_layers_for_session(),
        )
        self._sessions[session_id] = overlay_fs

        # Track session metadata
        self._session_metadata[session_id] = SessionMetadata(
            session_id=session_id,
            created_at=now,
            last_accessed=now,
            metadata=meta,
        )
        self._last_accessed[session_id] = now

        return session_id

    def ensure_session(
        self,
        session_id: str,
        metadata: dict[str, Any] | None = None,
        ttl: timedelta | None = None,
    ) -> str:
        """Ensure a specific session ID exists and return it.

        If the session already exists, refresh access metadata and return the same ID.
        Otherwise create a new session bound to the provided identifier.

        Args:
            session_id: Session ID that should exist.
            metadata: Optional dictionary of custom session metadata.
            ttl: Optional TTL for this session (overrides default).

        Returns:
            The ensured session ID.
        """
        normalized_session_id = validate_session_id(session_id.strip())
        existing = self.get_session(normalized_session_id)
        if existing is not None:
            if metadata:
                existing.metadata.update(metadata)
            return normalized_session_id

        now = datetime.now()
        meta: dict[str, Any] = metadata.copy() if metadata else {}

        effective_ttl = ttl if ttl is not None else self._default_session_ttl
        if effective_ttl is not None:
            meta["expires_at"] = now + effective_ttl
            meta["ttl_seconds"] = effective_ttl.total_seconds()

        upper_fs = self._build_session_upper_fs(normalized_session_id)
        self._init_session_workspace(upper_fs)
        overlay_fs = OverlayFileSystem(
            upper=upper_fs,
            lowers=self._build_lower_layers_for_session(),
        )
        self._sessions[normalized_session_id] = overlay_fs
        self._session_metadata[normalized_session_id] = SessionMetadata(
            session_id=normalized_session_id,
            created_at=now,
            last_accessed=now,
            metadata=meta,
        )
        self._last_accessed[normalized_session_id] = now

        return normalized_session_id

    def get_session(self, session_id: str) -> SessionMetadata | None:
        """Get session metadata with expiration check.

        Retrieves session metadata and updates the last_accessed timestamp.
        Returns None if the session has expired based on TTL.

        Args:
            session_id: The session ID to look up.

        Returns:
            SessionMetadata if session exists and not expired, None otherwise.
        """
        if session_id not in self._session_metadata:
            return None

        meta = self._session_metadata[session_id]

        # Check if session has expired based on TTL in metadata
        expires_at = meta.metadata.get("expires_at")
        if expires_at is not None and datetime.now() > expires_at:
            return None

        # Update last accessed time
        now = datetime.now()
        meta.last_accessed = now
        self._last_accessed[session_id] = now

        return meta

    def get_session_fs(self, session_id: str) -> OverlayFileSystem | None:
        """Get the filesystem instance for a session.

        Updates the last_accessed timestamp when session is accessed.
        Returns None if session has expired.

        Args:
            session_id: The session ID to look up.

        Returns:
            OverlayFileSystem instance if session exists and not expired, None otherwise.
        """
        # Check session exists and isn't expired via get_session
        meta = self.get_session(session_id)
        if meta is None:
            return None

        return self._sessions.get(session_id)

    def get_session_metadata(self, session_id: str) -> SessionMetadata | None:
        """Get metadata for a session.

        Args:
            session_id: The session ID to look up.

        Returns:
            SessionMetadata if session exists, None otherwise.
        """
        return self._session_metadata.get(session_id)

    def cleanup_session(self, session_id: str) -> bool:
        """Clean up resources for a session.

        Args:
            session_id: The session ID to clean up.

        Returns:
            True if session was found and cleaned up, False otherwise.
        """
        if session_id not in self._sessions:
            return False

        fs = self._sessions[session_id]
        upper_fs = fs.upper

        if isinstance(upper_fs, DirFileSystem) and isinstance(
            upper_fs.fs, MemoryFileSystem
        ):
            self._clear_memory_dirfs_prefix(upper_fs)
        elif isinstance(upper_fs, DirFileSystem):
            self._clear_local_dirfs_prefix(upper_fs)
        elif isinstance(upper_fs, MemoryFileSystem):
            self._clear_memory_filesystem(upper_fs)

        # Remove session from all tracking dictionaries
        del self._sessions[session_id]
        self._last_accessed.pop(session_id, None)
        self._session_metadata.pop(session_id, None)

        return True

    @staticmethod
    def _clear_memory_filesystem(fs: MemoryFileSystem) -> None:
        """Best-effort cleanup for an in-memory filesystem."""
        if hasattr(fs, "store") and isinstance(fs.store, dict):
            try:
                fs.store.clear()
            except (AttributeError, TypeError):
                pass

        if hasattr(fs, "_cache") and isinstance(fs._cache, dict):
            try:
                for file_handle in fs._cache.values():
                    try:
                        if hasattr(file_handle, "close"):
                            file_handle.close()
                    except (OSError, ValueError):
                        pass
                fs._cache.clear()
            except (AttributeError, TypeError):
                pass

    @staticmethod
    def _clear_memory_dirfs_prefix(fs: DirFileSystem) -> None:
        """Delete only the files and directories under a DirFileSystem prefix."""
        inner_fs = fs.fs
        root = fs.path.rstrip("/")
        prefix = f"{root}/" if root else ""

        if hasattr(inner_fs, "store") and isinstance(inner_fs.store, dict):
            for path in list(inner_fs.store):
                if path == root or path.startswith(prefix):
                    inner_fs.store.pop(path, None)

        pseudo_dirs = getattr(inner_fs, "pseudo_dirs", None)
        if isinstance(pseudo_dirs, list):
            inner_fs.pseudo_dirs = [
                path
                for path in pseudo_dirs
                if path != root and not path.startswith(prefix)
            ]

        cache = getattr(inner_fs, "_cache", None)
        if isinstance(cache, dict):
            try:
                for file_handle in cache.values():
                    try:
                        if hasattr(file_handle, "close"):
                            file_handle.close()
                    except (OSError, ValueError):
                        pass
                inner_fs._cache.clear()
            except (AttributeError, TypeError):
                pass

    def list_sessions(
        self,
        include_expired: bool = False,
    ) -> list[SessionMetadata]:
        """List all active session metadata.

        Args:
            include_expired: If True, include expired sessions in results.

        Returns:
            List of SessionMetadata for active (non-expired) sessions.

        Example:
            >>> manager = SessionFileSystemManager(OverlayConfig())
            >>> manager.list_sessions()
            []
            >>> session_id = manager.create_session()
            >>> sessions = manager.list_sessions()
            >>> len(sessions)
            1
            >>> sessions[0].session_id == session_id
            True
        """
        result: list[SessionMetadata] = []
        now = datetime.now()

        for meta in self._session_metadata.values():
            # Check expiration
            expires_at = meta.metadata.get("expires_at")
            is_expired = expires_at is not None and now > expires_at

            if not is_expired or include_expired:
                result.append(meta)

        return result

    def is_session_expired(self, session_id: str, timeout_seconds: float) -> bool:
        """Check if a session has expired based on inactivity timeout.

        Args:
            session_id: The session ID to check.
            timeout_seconds: Timeout threshold in seconds.

        Returns:
            True if session has expired, False otherwise.
        """
        if session_id not in self._last_accessed:
            return True

        last_accessed = self._last_accessed[session_id]
        elapsed = (datetime.now() - last_accessed).total_seconds()
        return elapsed > timeout_seconds

    def get_expired_sessions(self, timeout_seconds: float) -> list[str]:
        """Get list of all expired session IDs.

        Args:
            timeout_seconds: Timeout threshold in seconds.

        Returns:
            List of session IDs that have exceeded the timeout.
        """
        expired = []
        now = datetime.now()
        for session_id, last_accessed in self._last_accessed.items():
            elapsed = (now - last_accessed).total_seconds()
            if elapsed > timeout_seconds:
                expired.append(session_id)
        return expired

    def cleanup_expired_sessions(self, timeout_seconds: float | None = None) -> int:
        """Remove all expired sessions.

        Args:
            timeout_seconds: If provided, use this timeout instead of TTL metadata.

        Returns:
            Number of sessions cleaned up.
        """
        if timeout_seconds is not None:
            expired_ids = self.get_expired_sessions(timeout_seconds)
        else:
            # Use TTL metadata to find expired sessions
            now = datetime.now()
            expired_ids = []
            for session_id, meta in self._session_metadata.items():
                expires_at = meta.metadata.get("expires_at")
                if expires_at is not None and now > expires_at:
                    expired_ids.append(session_id)

        for session_id in expired_ids:
            self.cleanup_session(session_id)

        return len(expired_ids)

    def update_session_access(self, session_id: str) -> bool:
        """Manually update the last_accessed timestamp for a session.

        Args:
            session_id: The session ID to update.

        Returns:
            True if session was found and updated, False otherwise.
        """
        if session_id not in self._last_accessed:
            return False

        now = datetime.now()
        self._last_accessed[session_id] = now
        if session_id in self._session_metadata:
            self._session_metadata[session_id].last_accessed = now
        return True
