from __future__ import annotations

from pathlib import Path

from mcp_scratchpad.config.models import OverlayConfig
from mcp_scratchpad.fs.session_manager import SessionFileSystemManager
from mcp_scratchpad.fs.unified_adapter import UnifiedSessionFSAdapter
from mcp_scratchpad.memory.backends import FileSharedMemoryBackend
from mcp_scratchpad.memory.models import PublishMemoryRequest
from mcp_scratchpad.memory.publisher import PublishMemoryService
from mcp_scratchpad.storage import FileSystemStore, set_store


def test_publish_service_reads_from_session_overlay_and_writes_backend(
    tmp_path: Path,
) -> None:
    manager = SessionFileSystemManager(OverlayConfig())
    session_id = manager.create_session()
    store = FileSystemStore(base_dir=tmp_path / "store")
    set_store(store)
    adapter = UnifiedSessionFSAdapter(
        session_manager=manager,
        store=store,
        unified_enabled=True,
    )
    adapter.write_text(session_id, "/workspace/summary.md", "# Summary\n")

    backend = FileSharedMemoryBackend(
        root_dir=tmp_path / "shared",
        namespace_roots={"users": "users"},
    )
    service = PublishMemoryService(adapter=adapter, backend_by_namespace={"users": backend})

    result = service.publish(
        PublishMemoryRequest(
            session_id=session_id,
            source_path="/workspace/summary.md",
            target_namespace="users",
            target_key="user-42/summary.md",
        )
    )

    assert result.shared_path == "/memory/users/user-42/summary.md"
    assert result.published is True
