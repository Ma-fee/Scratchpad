from __future__ import annotations

from pathlib import Path

from mcp_scratchpad.config.models import MountConfig, OverlayConfig
from mcp_scratchpad.fs.session_manager import SessionFileSystemManager
from mcp_scratchpad.fs.unified_adapter import UnifiedSessionFSAdapter
from mcp_scratchpad.memory.backends import FileSharedMemoryBackend
from mcp_scratchpad.memory.models import PublishMemoryRequest
from mcp_scratchpad.memory.publisher import PublishMemoryService
from mcp_scratchpad.storage import FileSystemStore, set_store


def test_publish_memory_makes_content_available_to_other_sessions(
    tmp_path: Path,
) -> None:
    shared_root = tmp_path / "shared-memory"
    overlay_config = OverlayConfig(
        mounts=[
            MountConfig(
                name="shared_memory_users",
                source=f"file://{shared_root / 'users'}",
                mount_point="/memory/users",
                mode="ro",
                priority=50,
                options={"auto_mkdir": True},
            )
        ]
    )
    manager = SessionFileSystemManager(overlay_config)
    session_a = manager.create_session()
    session_b = manager.create_session()

    store = FileSystemStore(base_dir=tmp_path / "store")
    set_store(store)
    adapter = UnifiedSessionFSAdapter(
        session_manager=manager,
        store=store,
        unified_enabled=True,
    )
    adapter.write_text(session_a, "/workspace/summary.md", "published\n")

    backend = FileSharedMemoryBackend(
        root_dir=shared_root,
        namespace_roots={"users": "users"},
    )
    service = PublishMemoryService(adapter=adapter, backend_by_namespace={"users": backend})
    service.publish(
        PublishMemoryRequest(
            session_id=session_a,
            source_path="/workspace/summary.md",
            target_namespace="users",
            target_key="user-42/summary.md",
        )
    )

    result = adapter.read_text(session_b, "/memory/users/user-42/summary.md")
    assert result.content == "published\n"


def test_publish_memory_rejects_existing_target_without_overwrite(
    tmp_path: Path,
) -> None:
    shared_root = tmp_path / "shared-memory"
    overlay_config = OverlayConfig(
        mounts=[
            MountConfig(
                name="shared_memory_users",
                source=f"file://{shared_root / 'users'}",
                mount_point="/memory/users",
                mode="ro",
                priority=50,
                options={"auto_mkdir": True},
            )
        ]
    )
    manager = SessionFileSystemManager(overlay_config)
    session_id = manager.create_session()
    store = FileSystemStore(base_dir=tmp_path / "store")
    set_store(store)
    adapter = UnifiedSessionFSAdapter(
        session_manager=manager,
        store=store,
        unified_enabled=True,
    )
    adapter.write_text(session_id, "/workspace/summary.md", "published\n")

    backend = FileSharedMemoryBackend(
        root_dir=shared_root,
        namespace_roots={"users": "users"},
    )
    service = PublishMemoryService(adapter=adapter, backend_by_namespace={"users": backend})
    request = PublishMemoryRequest(
        session_id=session_id,
        source_path="/workspace/summary.md",
        target_namespace="users",
        target_key="user-42/summary.md",
    )

    service.publish(request)

    try:
        service.publish(request)
    except FileExistsError:
        pass
    else:
        raise AssertionError("expected FileExistsError")


def test_editing_published_memory_in_new_session_stays_session_local(
    tmp_path: Path,
) -> None:
    shared_root = tmp_path / "shared-memory"
    overlay_config = OverlayConfig(
        mounts=[
            MountConfig(
                name="shared_memory_users",
                source=f"file://{shared_root / 'users'}",
                mount_point="/memory/users",
                mode="ro",
                priority=50,
                options={"auto_mkdir": True},
            )
        ]
    )
    manager = SessionFileSystemManager(overlay_config)
    session_a = manager.create_session()
    session_b = manager.create_session()
    session_c = manager.create_session()

    store = FileSystemStore(base_dir=tmp_path / "store")
    set_store(store)
    adapter = UnifiedSessionFSAdapter(
        session_manager=manager,
        store=store,
        unified_enabled=True,
    )
    adapter.write_text(session_a, "/workspace/summary.md", "published\n")

    backend = FileSharedMemoryBackend(
        root_dir=shared_root,
        namespace_roots={"users": "users"},
    )
    service = PublishMemoryService(adapter=adapter, backend_by_namespace={"users": backend})
    service.publish(
        PublishMemoryRequest(
            session_id=session_a,
            source_path="/workspace/summary.md",
            target_namespace="users",
            target_key="user-42/summary.md",
        )
    )

    session_b_result = adapter.read_text(session_b, "/memory/users/user-42/summary.md")
    adapter.write_text(session_b, "/memory/users/user-42/summary.md", "session-b\n")
    session_b_updated = adapter.read_text(session_b, "/memory/users/user-42/summary.md")
    session_c_result = adapter.read_text(session_c, "/memory/users/user-42/summary.md")

    assert session_b_result.content == "published\n"
    assert session_b_updated.content == "session-b\n"
    assert session_c_result.content == "published\n"
