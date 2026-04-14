"""Integration tests for tool/resource consistency with unified adapter."""

from __future__ import annotations

from pathlib import Path

import pytest

from mcp_scratchpad.config.models import OverlayConfig
from mcp_scratchpad.fs.session_manager import SessionFileSystemManager
from mcp_scratchpad.fs.unified_adapter import UnifiedSessionFSAdapter
from mcp_scratchpad.resources.read_handler import ResourceReadError, read_resource_text
from mcp_scratchpad.storage import FileSystemStore, set_store
from mcp_scratchpad.tools.apply_diff import apply_patch_with_session
from mcp_scratchpad.tools.edit import (
    apply_edit_with_session,
    apply_multiedit_with_session,
)
from mcp_scratchpad.tools.list import _list_files_tool
from mcp_scratchpad.tools.remove import apply_remove_with_session
from mcp_scratchpad.tools.write import apply_write_with_session


class _FakeContext:
    """Minimal async context for direct tool helper tests."""

    async def info(self, _message: str) -> None:
        return None

    async def report_progress(
        self,
        _current: int,
        _total: int,
        _message: str,
    ) -> None:
        return None


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


@pytest.mark.integration
def test_multiedit_requires_session_context(tmp_path: Path) -> None:
    """Multiedit helper should require explicit session_id."""
    manager = SessionFileSystemManager(OverlayConfig())
    store = FileSystemStore(base_dir=tmp_path)
    set_store(store)
    adapter = UnifiedSessionFSAdapter(
        session_manager=manager, store=store, unified_enabled=True
    )

    with pytest.raises(ValueError, match="session_id is required"):
        apply_multiedit_with_session(
            session_id=None,
            file_path="/workspace/a.txt",
            edits=[{"old_string": "a", "new_string": "b"}],
            adapter=adapter,
        )


@pytest.mark.integration
def test_multiedit_writes_visible_to_resource_read(tmp_path: Path) -> None:
    """Multiedit helper should apply sequential edits through unified adapter."""
    manager = SessionFileSystemManager(OverlayConfig())
    session_id = manager.create_session()

    store = FileSystemStore(base_dir=tmp_path)
    set_store(store)
    adapter = UnifiedSessionFSAdapter(
        session_manager=manager, store=store, unified_enabled=True
    )

    adapter.write_text(session_id, "/workspace/a.txt", "alpha\nbeta\n")

    apply_multiedit_with_session(
        session_id=session_id,
        file_path="/workspace/a.txt",
        edits=[
            {"old_string": "alpha", "new_string": "ALPHA"},
            {"old_string": "beta", "new_string": "BETA"},
        ],
        adapter=adapter,
    )

    content = read_resource_text(
        f"scratchpad://{session_id}/workspace/a.txt",
        session_manager=manager,
    )
    assert "ALPHA" in content
    assert "BETA" in content


@pytest.mark.integration
def test_write_writes_visible_to_resource_read(tmp_path: Path) -> None:
    """Write helper should persist through the unified adapter when session-scoped."""
    manager = SessionFileSystemManager(OverlayConfig())
    session_id = manager.create_session()

    store = FileSystemStore(base_dir=tmp_path)
    set_store(store)
    adapter = UnifiedSessionFSAdapter(
        session_manager=manager, store=store, unified_enabled=True
    )

    apply_write_with_session(
        session_id=session_id,
        file_path="/workspace/new.txt",
        content="hello from write\n",
        adapter=adapter,
    )

    content = read_resource_text(
        f"scratchpad://{session_id}/workspace/new.txt",
        session_manager=manager,
    )
    assert "hello from write" in content


@pytest.mark.integration
def test_remove_deletes_content_visible_to_resource_read(tmp_path: Path) -> None:
    """Remove helper should delete through the unified adapter when session-scoped."""
    manager = SessionFileSystemManager(OverlayConfig())
    session_id = manager.create_session()

    store = FileSystemStore(base_dir=tmp_path)
    set_store(store)
    adapter = UnifiedSessionFSAdapter(
        session_manager=manager, store=store, unified_enabled=True
    )

    adapter.write_text(session_id, "/workspace/remove.txt", "bye\n")

    apply_remove_with_session(
        session_id=session_id,
        file_path="/workspace/remove.txt",
        adapter=adapter,
    )

    with pytest.raises(ResourceReadError):
        read_resource_text(
            f"scratchpad://{session_id}/workspace/remove.txt",
            session_manager=manager,
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_reads_only_current_session_overlay(tmp_path: Path) -> None:
    """List helper should expose only overlay-visible files for the current session."""
    manager = SessionFileSystemManager(OverlayConfig())
    session_id = manager.create_session()

    store = FileSystemStore(base_dir=tmp_path)
    set_store(store)
    adapter = UnifiedSessionFSAdapter(
        session_manager=manager, store=store, unified_enabled=True
    )

    store.write_file(
        file_path="persistent-only.txt",
        content="store-only\n",
        expected_version=None,
        permission="read_write",
        overwrite=True,
        persistent=True,
    )
    adapter.write_text(session_id, "/workspace/overlay.txt", "overlay-only\n")

    result = await _list_files_tool(
        ctx=_FakeContext(),
        session_manager=manager,
        session_id=session_id,
    )

    payloads = [item.text for item in result.content]
    joined = "\n".join(payloads)
    assert "workspace/overlay.txt" in joined
    assert "persistent-only.txt" not in joined
