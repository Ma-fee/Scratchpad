from __future__ import annotations

import json
from pathlib import Path

from mcp_scratchpad.memory.backends import FileSharedMemoryBackend


def test_file_backend_writes_content_and_sidecar(tmp_path: Path) -> None:
    backend = FileSharedMemoryBackend(
        root_dir=tmp_path,
        namespace_roots={"users": "users"},
    )

    result = backend.publish_text(
        namespace="users",
        target_key="user-42/summary.md",
        content="hello\n",
        overwrite=False,
        metadata={"source_agent": "agent-1"},
        content_type="text/markdown",
    )

    content_path = tmp_path / "users" / "user-42" / "summary.md"
    sidecar_path = tmp_path / "users" / "user-42" / "summary.md.meta.json"

    assert content_path.read_text(encoding="utf-8") == "hello\n"
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    assert sidecar["content_type"] == "text/markdown"
    assert result.overwrote_existing is False


def test_file_backend_rejects_existing_target_without_overwrite(
    tmp_path: Path,
) -> None:
    backend = FileSharedMemoryBackend(
        root_dir=tmp_path,
        namespace_roots={"users": "users"},
    )
    existing = tmp_path / "users" / "user-42" / "summary.md"
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_text("old\n", encoding="utf-8")

    try:
        backend.publish_text(
            namespace="users",
            target_key="user-42/summary.md",
            content="new\n",
            overwrite=False,
            metadata=None,
            content_type=None,
        )
    except FileExistsError:
        pass
    else:
        raise AssertionError("expected FileExistsError")
