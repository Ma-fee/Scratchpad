from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


@dataclass
class BackendPublishResult:
    backend_uri: str
    shared_path: str
    overwrote_existing: bool


class SharedMemoryBackend(Protocol):
    def publish_text(
        self,
        *,
        namespace: str,
        target_key: str,
        content: str,
        overwrite: bool,
        metadata: dict[str, Any] | None,
        content_type: str | None,
    ) -> BackendPublishResult:
        ...


class FileSharedMemoryBackend:
    """Publish shared memory content into a local filesystem root."""

    def __init__(
        self,
        *,
        root_dir: Path,
        namespace_roots: dict[str, str],
    ) -> None:
        self.root_dir = Path(root_dir)
        self.namespace_roots = dict(namespace_roots)

    def publish_text(
        self,
        *,
        namespace: str,
        target_key: str,
        content: str,
        overwrite: bool,
        metadata: dict[str, Any] | None,
        content_type: str | None,
    ) -> BackendPublishResult:
        namespace_root = self.namespace_roots[namespace]
        namespace_dir = self.root_dir / namespace_root
        namespace_dir.mkdir(parents=True, exist_ok=True)

        content_path = namespace_dir / target_key
        sidecar_path = content_path.with_name(content_path.name + ".meta.json")
        content_path.parent.mkdir(parents=True, exist_ok=True)

        existed = content_path.exists()
        if existed and not overwrite:
            raise FileExistsError(f"Shared memory target exists: {target_key}")

        content_path.write_text(content, encoding="utf-8")
        sidecar = {
            "namespace": namespace,
            "target_key": target_key,
            "content_type": content_type,
            "metadata": metadata or {},
        }
        sidecar_path.write_text(
            json.dumps(sidecar, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        return BackendPublishResult(
            backend_uri=content_path.resolve().as_uri(),
            shared_path=f"/memory/{namespace}/{target_key}",
            overwrote_existing=existed,
        )
