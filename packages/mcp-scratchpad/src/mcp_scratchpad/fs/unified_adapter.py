"""Unified session filesystem adapter.

This adapter provides a single IO facade for session-scoped filesystem access.
When unified mode is enabled, it prefers session overlay FS. Otherwise it falls
back to the legacy FileSystemStore.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..exceptions import ScratchpadFileNotFoundError
from ..storage import FileSystemStore
from ..utils import normalize_path
from .session_manager import SessionFileSystemManager


@dataclass
class UnifiedReadResult:
    """Represents normalized read result from unified adapter."""

    session_id: str
    path: str
    uri: str
    content: str
    layer: str
    version: int | None


class UnifiedSessionFSAdapter:
    """Handles unified read/write operations for session-scoped files."""

    def __init__(
        self,
        session_manager: SessionFileSystemManager | None,
        store: FileSystemStore,
        unified_enabled: bool,
    ) -> None:
        self._session_manager = session_manager
        self._store = store
        self._unified_enabled = unified_enabled

    def build_uri(self, session_id: str, path: str) -> str:
        """Build canonical scratchpad URI."""
        normalized_path = normalize_path(path).lstrip("/")
        return f"scratchpad://{session_id}/{normalized_path}"

    def write_text(self, session_id: str, path: str, content: str) -> None:
        """Write text to overlay FS when enabled; otherwise legacy store."""
        normalized_path = normalize_path(path)

        if self._unified_enabled and self._session_manager is not None:
            self._session_manager.ensure_session(session_id)
            session_fs = self._session_manager.get_session_fs(session_id)
            if session_fs is not None:
                absolute_path = self._as_absolute_path(normalized_path)
                parent = str(Path(absolute_path).parent)
                if parent != "/":
                    session_fs.makedirs(parent, exist_ok=True)
                with session_fs.open(absolute_path, mode="w", encoding="utf-8") as f:
                    f.write(content)
                return

        self._store.session_id = session_id
        self._store.write_file(
            file_path=normalized_path,
            content=content,
            overwrite=True,
            persistent=False,
            expected_version=None,
            permission="read_write",
        )

    def read_text(self, session_id: str, path: str) -> UnifiedReadResult:
        """Read text and return unified metadata shape."""
        normalized_path = normalize_path(path)
        uri = self.build_uri(session_id, normalized_path)

        if self._unified_enabled and self._session_manager is not None:
            self._session_manager.ensure_session(session_id)
            session_fs = self._session_manager.get_session_fs(session_id)
            if session_fs is not None:
                absolute_path = self._as_absolute_path(normalized_path)
                if session_fs.exists(absolute_path):
                    with session_fs.open(
                        absolute_path, mode="r", encoding="utf-8"
                    ) as f:
                        content = f.read()
                    return UnifiedReadResult(
                        session_id=session_id,
                        path=normalized_path,
                        uri=uri,
                        content=content,
                        layer="upper",
                        version=None,
                    )

                mount_result = self._session_manager.resolve_mount_path(absolute_path)
                if mount_result is not None:
                    mount_fs, mount_path = mount_result
                    if mount_fs.exists(mount_path):
                        with mount_fs.open(mount_path, mode="r", encoding="utf-8") as f:
                            content = f.read()
                        return UnifiedReadResult(
                            session_id=session_id,
                            path=normalized_path,
                            uri=uri,
                            content=content,
                            layer="lower",
                            version=None,
                        )

        self._store.session_id = session_id
        records, failed = self._store.read_files([normalized_path])
        if failed:
            raise ScratchpadFileNotFoundError(
                f"File not found: {normalized_path}",
                details={"file_path": normalized_path, "session_id": session_id},
            )

        record = records[0]
        return UnifiedReadResult(
            session_id=session_id,
            path=record.file_path,
            uri=uri,
            content=record.content,
            layer="legacy",
            version=record.version,
        )

    @staticmethod
    def _as_absolute_path(path: str) -> str:
        """Normalize path into absolute form for fsspec memory FS."""
        return f"/{path.lstrip('/')}"
