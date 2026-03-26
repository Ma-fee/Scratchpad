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

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Protocol

from fsspec import AbstractFileSystem
from fsspec.implementations.memory import MemoryFileSystem

from ..config.models import OverlayConfig


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
        self._sessions: dict[str, MemoryFileSystem] = {}
        self._session_metadata: dict[str, SessionMetadata] = {}
        self._mounts: dict[str, AbstractFileSystem] = {}
        self._mount_paths: dict[
            str, str
        ] = {}  # Store paths separately (LocalFileSystem is singleton)
        self._last_accessed: dict[str, datetime] = {}
        self._initialize_mounts()

    def _initialize_mounts(self) -> None:
        """Initialize underlying filesystems from configuration.

        Creates fsspec filesystems for each configured mount.
        Supports file:// URLs and local paths.
        """
        from pathlib import Path

        from fsspec.implementations.local import LocalFileSystem

        for mount in self.config.mounts:
            source = mount.source

            if source.startswith("file://"):
                # Local filesystem
                path = source[7:]
                fs_path = Path(path)
                if not fs_path.is_absolute():
                    fs_path = fs_path.resolve()

                try:
                    # Create filesystem instance
                    # Note: LocalFileSystem can be a singleton, so we store path separately
                    fs = LocalFileSystem()
                    # Store the base path in a separate dict
                    self._mount_paths[mount.name] = str(fs_path)
                    self._mounts[mount.name] = fs
                except Exception as e:
                    print(f"Warning: Failed to mount {mount.name} at {fs_path}: {e}")

    def _get_mount_for_path(self, path: str) -> tuple[str, AbstractFileSystem] | None:
        """Find the mount that handles a given path.

        Args:
            path: The path to resolve (e.g., "/.claude/skills/python/skill.py")

        Returns:
            Tuple of (mount_name, filesystem) or None if no mount matches.
        """
        # Find matching mount based on mount_point
        for mount in self.config.mounts:
            if path.startswith(mount.mount_point) or mount.mount_point == "/":
                if mount.name in self._mounts:
                    return mount.name, self._mounts[mount.name]
        return None

    def _init_session_workspace(self, fs: MemoryFileSystem) -> None:
        """Initialize session workspace directory structure."""
        if not fs.exists("/workspace"):
            fs.mkdir("/workspace")

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

        # Create isolated MemoryFileSystem for this session
        fs = MemoryFileSystem()
        self._init_session_workspace(fs)
        self._sessions[session_id] = fs

        # Track session metadata
        self._session_metadata[session_id] = SessionMetadata(
            session_id=session_id,
            created_at=now,
            last_accessed=now,
            metadata=meta,
        )
        self._last_accessed[session_id] = now

        return session_id

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

    def get_session_fs(self, session_id: str) -> MemoryFileSystem | None:
        """Get the filesystem instance for a session.

        Updates the last_accessed timestamp when session is accessed.
        Returns None if session has expired.

        Args:
            session_id: The session ID to look up.

        Returns:
            MemoryFileSystem instance if session exists and not expired, None otherwise.
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

        # Clear MemoryFileSystem contents to free memory
        if hasattr(fs, "store") and isinstance(fs.store, dict):
            try:
                fs.store.clear()
            except (AttributeError, TypeError):
                pass

        # Close any open file handles
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

        # Remove session from all tracking dictionaries
        del self._sessions[session_id]
        self._last_accessed.pop(session_id, None)
        self._session_metadata.pop(session_id, None)

        return True

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
