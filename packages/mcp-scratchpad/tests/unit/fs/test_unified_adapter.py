"""Unit tests for the UnifiedSessionFSAdapter."""

from __future__ import annotations

import pytest

from mcp_scratchpad.config.models import OverlayConfig
from mcp_scratchpad.fs.session_manager import SessionFileSystemManager
from mcp_scratchpad.fs.unified_adapter import UnifiedSessionFSAdapter
from mcp_scratchpad.storage import FileSystemStore


@pytest.mark.unit
def test_builds_canonical_uri(file_store: FileSystemStore) -> None:
    adapter = UnifiedSessionFSAdapter(
        session_manager=None, store=file_store, unified_enabled=False
    )

    uri = adapter.build_uri("sess-1", "/workspace/a.txt")

    assert uri == "scratchpad://sess-1/workspace/a.txt"


@pytest.mark.unit
def test_read_prefers_session_overlay_when_unified_enabled(
    file_store: FileSystemStore,
) -> None:
    manager = SessionFileSystemManager(OverlayConfig())
    session_id = manager.create_session()
    adapter = UnifiedSessionFSAdapter(
        session_manager=manager, store=file_store, unified_enabled=True
    )

    adapter.write_text(session_id, "/workspace/a.txt", "hello")
    result = adapter.read_text(session_id, "/workspace/a.txt")

    assert result.content == "hello"
    assert result.layer == "upper"


@pytest.mark.unit
def test_writes_to_same_path_are_isolated_per_session(
    file_store: FileSystemStore,
) -> None:
    manager = SessionFileSystemManager(OverlayConfig())
    session_a = manager.create_session()
    session_b = manager.create_session()
    adapter = UnifiedSessionFSAdapter(
        session_manager=manager,
        store=file_store,
        unified_enabled=True,
    )

    adapter.write_text(session_a, "/workspace/shared.txt", "session-a")
    adapter.write_text(session_b, "/workspace/shared.txt", "session-b")

    result_a = adapter.read_text(session_a, "/workspace/shared.txt")
    result_b = adapter.read_text(session_b, "/workspace/shared.txt")

    assert result_a.content == "session-a"
    assert result_b.content == "session-b"
