"""Integration tests for tool/resource consistency with unified adapter."""

from __future__ import annotations

from pathlib import Path

import pytest

from mcp_scratchpad.config.models import OverlayConfig
from mcp_scratchpad.fs.session_manager import SessionFileSystemManager
from mcp_scratchpad.fs.unified_adapter import UnifiedSessionFSAdapter
from mcp_scratchpad.resources.read_handler import read_resource_text
from mcp_scratchpad.storage import FileSystemStore, set_store
from mcp_scratchpad.tools.apply_diff import apply_patch_with_session
from mcp_scratchpad.tools.edit import apply_edit_with_session


@pytest.mark.integration
def test_edit_requires_session_context(tmp_path: Path) -> None:
    """Edit helper should require explicit session_id."""
    manager = SessionFileSystemManager(OverlayConfig())
    store = FileSystemStore(base_dir=tmp_path)
    set_store(store)
    adapter = UnifiedSessionFSAdapter(
        session_manager=manager, store=store, unified_enabled=True
    )

    with pytest.raises(ValueError, match="session_id is required"):
        apply_edit_with_session(
            session_id=None,
            file_path="/workspace/a.txt",
            old_string="a",
            new_string="b",
            replace_all=False,
            adapter=adapter,
        )


@pytest.mark.integration
def test_patch_writes_visible_to_resource_read(tmp_path: Path) -> None:
    """Patch write through tool helper should be readable from resource API."""
    manager = SessionFileSystemManager(OverlayConfig())
    session_id = manager.create_session()

    store = FileSystemStore(base_dir=tmp_path)
    set_store(store)
    adapter = UnifiedSessionFSAdapter(
        session_manager=manager, store=store, unified_enabled=True
    )

    adapter.write_text(session_id, "/workspace/a.txt", "hello\n")

    apply_patch_with_session(
        session_id=session_id,
        file_path="/workspace/a.txt",
        diff=(
            "--- workspace/a.txt\n"
            "+++ workspace/a.txt\n"
            "@@ -1 +1 @@\n"
            "-hello\n"
            "+world\n"
        ),
        adapter=adapter,
    )

    content = read_resource_text(
        f"scratchpad://{session_id}/workspace/a.txt",
        session_manager=manager,
    )
    assert "world" in content
