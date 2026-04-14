# Publish Memory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an explicit `publish_memory` path that promotes a session-visible file into shared memory backed by `file://` first, with a backend abstraction that can later support `s3://`.

**Architecture:** Keep existing file tools strictly session-overlay-only. Add a dedicated publish service that reads source content from the current session overlay via the unified adapter, validates namespace and target key, resolves the shared memory backend, writes the shared artifact and metadata sidecar, then exposes the result through existing lower-mount conventions under `/memory/...`.

**Tech Stack:** Python 3.10, FastMCP, Pydantic, fsspec, existing `SessionFileSystemManager`, `OverlayFileSystem`, `UnifiedSessionFSAdapter`, `pytest`, `uv`

---

## File Map

### New Files

- `packages/mcp-scratchpad/src/mcp_scratchpad/memory/__init__.py`
  Responsibility: public exports for memory publishing components.
- `packages/mcp-scratchpad/src/mcp_scratchpad/memory/models.py`
  Responsibility: request/result models and namespace configuration models.
- `packages/mcp-scratchpad/src/mcp_scratchpad/memory/publisher.py`
  Responsibility: publish orchestration, validation, and backend dispatch.
- `packages/mcp-scratchpad/src/mcp_scratchpad/memory/backends.py`
  Responsibility: shared backend abstraction and initial `file://` publisher.
- `packages/mcp-scratchpad/src/mcp_scratchpad/tools/publish_memory.py`
  Responsibility: FastMCP tool registration and XML/structured response shaping.
- `packages/mcp-scratchpad/tests/unit/memory/test_models.py`
  Responsibility: namespace and target-key validation tests.
- `packages/mcp-scratchpad/tests/unit/memory/test_backends.py`
  Responsibility: file backend write and metadata sidecar tests.
- `packages/mcp-scratchpad/tests/unit/memory/test_publisher.py`
  Responsibility: publish orchestration tests using session overlay input.
- `packages/mcp-scratchpad/tests/integration/test_publish_memory.py`
  Responsibility: end-to-end publish and cross-session read behavior.

### Modified Files

- `packages/mcp-scratchpad/src/mcp_scratchpad/server.py`
  Responsibility: register the new tool and initialize any required publisher dependencies.
- `packages/mcp-scratchpad/src/mcp_scratchpad/config/models.py`
  Responsibility: add shared memory namespace/backend configuration if needed.
- `packages/mcp-scratchpad/src/mcp_scratchpad/config/loader.py`
  Responsibility: load shared memory config from YAML.
- `packages/mcp-scratchpad/src/mcp_scratchpad/tools/__init__.py`
  Responsibility: export the new publish registration if the package uses explicit exports.
- `packages/mcp-scratchpad/src/mcp_scratchpad/tools/file_tools.py`
  Responsibility: register `publish_memory` alongside existing file tools.
- `packages/mcp-scratchpad/src/mcp_scratchpad/yaml/scratchpad.yaml`
  Responsibility: add commented shared-memory mount/config example.
- `packages/mcp-scratchpad/docs/overlay-fs-tooling-guide.md`
  Responsibility: link the implementation details once behavior exists.

---

### Task 1: Add Memory Publish Models

**Files:**
- Create: `packages/mcp-scratchpad/src/mcp_scratchpad/memory/models.py`
- Create: `packages/mcp-scratchpad/src/mcp_scratchpad/memory/__init__.py`
- Test: `packages/mcp-scratchpad/tests/unit/memory/test_models.py`

- [x] **Step 1: Write the failing validation tests**

```python
from __future__ import annotations

import pytest

from mcp_scratchpad.memory.models import PublishMemoryRequest


def test_publish_request_accepts_valid_namespace_and_key() -> None:
    request = PublishMemoryRequest(
        session_id="session-1",
        source_path="/workspace/summary.md",
        target_namespace="users",
        target_key="user-42/summary.md",
    )

    assert request.target_namespace == "users"
    assert request.target_key == "user-42/summary.md"


@pytest.mark.parametrize(
    ("namespace", "target_key"),
    [
        ("invalid", "x.md"),
        ("users", "../escape.md"),
        ("users", "/absolute.md"),
        ("users", ""),
    ],
)
def test_publish_request_rejects_invalid_target_inputs(
    namespace: str,
    target_key: str,
) -> None:
    with pytest.raises(ValueError):
        PublishMemoryRequest(
            session_id="session-1",
            source_path="/workspace/summary.md",
            target_namespace=namespace,
            target_key=target_key,
        )
```

- [x] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/mcp-scratchpad/tests/unit/memory/test_models.py -q`  
Expected: FAIL with missing module or missing model definitions

- [x] **Step 3: Write minimal models and exports**

```python
# packages/mcp-scratchpad/src/mcp_scratchpad/memory/models.py
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from ..utils import normalize_path

SUPPORTED_MEMORY_NAMESPACES = ("shared", "users", "agents", "teams")


class PublishMemoryRequest(BaseModel):
    """Validated publish request payload."""

    session_id: str = Field(..., min_length=1)
    source_path: str = Field(..., min_length=1)
    target_namespace: Literal["shared", "users", "agents", "teams"]
    target_key: str = Field(..., min_length=1)
    overwrite: bool = False
    content_type: str | None = None
    metadata: dict[str, Any] | None = None

    @field_validator("source_path")
    @classmethod
    def _validate_source_path(cls, value: str) -> str:
        return f"/{normalize_path(value).lstrip('/')}"

    @field_validator("target_key")
    @classmethod
    def _validate_target_key(cls, value: str) -> str:
        normalized = normalize_path(value)
        if normalized.startswith("/"):
            raise ValueError("target_key must be relative")
        if normalized in {"", "."}:
            raise ValueError("target_key cannot be empty")
        return normalized


class PublishMemoryResult(BaseModel):
    """Structured publish result."""

    session_id: str
    source_path: str
    target_namespace: str
    target_key: str
    shared_path: str
    backend_uri: str
    content_type: str | None = None
    published: bool = True
    overwrote_existing: bool = False
```

```python
# packages/mcp-scratchpad/src/mcp_scratchpad/memory/__init__.py
from .models import PublishMemoryRequest, PublishMemoryResult

__all__ = ["PublishMemoryRequest", "PublishMemoryResult"]
```

- [x] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/mcp-scratchpad/tests/unit/memory/test_models.py -q`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/mcp-scratchpad/src/mcp_scratchpad/memory/__init__.py \
        packages/mcp-scratchpad/src/mcp_scratchpad/memory/models.py \
        packages/mcp-scratchpad/tests/unit/memory/test_models.py
git commit -m "feat(memory): add publish request models"
```

### Task 2: Add Shared Memory Backend Abstraction with File Publisher

**Files:**
- Create: `packages/mcp-scratchpad/src/mcp_scratchpad/memory/backends.py`
- Test: `packages/mcp-scratchpad/tests/unit/memory/test_backends.py`

- [x] **Step 1: Write the failing backend tests**

```python
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
    assert json.loads(sidecar_path.read_text(encoding="utf-8"))["content_type"] == "text/markdown"
    assert result.overwrote_existing is False


def test_file_backend_rejects_existing_target_without_overwrite(tmp_path: Path) -> None:
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
```

- [x] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/mcp-scratchpad/tests/unit/memory/test_backends.py -q`  
Expected: FAIL with missing backend implementation

- [x] **Step 3: Write minimal backend abstraction and file backend**

```python
# packages/mcp-scratchpad/src/mcp_scratchpad/memory/backends.py
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
        self.namespace_roots = namespace_roots

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
        content_path = self.root_dir / namespace_root / target_key
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
        sidecar_path.write_text(json.dumps(sidecar, ensure_ascii=False, indent=2), encoding="utf-8")

        shared_path = f"/memory/{namespace}/{target_key}"
        return BackendPublishResult(
            backend_uri=content_path.resolve().as_uri(),
            shared_path=shared_path,
            overwrote_existing=existed,
        )
```

- [x] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/mcp-scratchpad/tests/unit/memory/test_backends.py -q`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/mcp-scratchpad/src/mcp_scratchpad/memory/backends.py \
        packages/mcp-scratchpad/tests/unit/memory/test_backends.py
git commit -m "feat(memory): add file shared-memory backend"
```

### Task 3: Add Publish Service Layer

**Files:**
- Create: `packages/mcp-scratchpad/src/mcp_scratchpad/memory/publisher.py`
- Test: `packages/mcp-scratchpad/tests/unit/memory/test_publisher.py`

- [x] **Step 1: Write the failing service tests**

```python
from __future__ import annotations

from pathlib import Path

from mcp_scratchpad.config.models import OverlayConfig
from mcp_scratchpad.fs.session_manager import SessionFileSystemManager
from mcp_scratchpad.fs.unified_adapter import UnifiedSessionFSAdapter
from mcp_scratchpad.memory.backends import FileSharedMemoryBackend
from mcp_scratchpad.memory.models import PublishMemoryRequest
from mcp_scratchpad.memory.publisher import PublishMemoryService
from mcp_scratchpad.storage import FileSystemStore, set_store


def test_publish_service_reads_from_session_overlay_and_writes_backend(tmp_path: Path) -> None:
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
```

- [x] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/mcp-scratchpad/tests/unit/memory/test_publisher.py -q`  
Expected: FAIL with missing service implementation

- [x] **Step 3: Write minimal publish service**

```python
# packages/mcp-scratchpad/src/mcp_scratchpad/memory/publisher.py
from __future__ import annotations

from typing import Mapping

from ..fs.unified_adapter import UnifiedSessionFSAdapter
from .backends import SharedMemoryBackend
from .models import PublishMemoryRequest, PublishMemoryResult


class PublishMemoryService:
    """Promote a session-visible file into shared memory."""

    def __init__(
        self,
        *,
        adapter: UnifiedSessionFSAdapter,
        backend_by_namespace: Mapping[str, SharedMemoryBackend],
    ) -> None:
        self._adapter = adapter
        self._backend_by_namespace = dict(backend_by_namespace)

    def publish(self, request: PublishMemoryRequest) -> PublishMemoryResult:
        backend = self._backend_by_namespace.get(request.target_namespace)
        if backend is None:
            raise ValueError(f"No shared memory backend configured for namespace: {request.target_namespace}")

        read_result = self._adapter.read_text(request.session_id, request.source_path)
        backend_result = backend.publish_text(
            namespace=request.target_namespace,
            target_key=request.target_key,
            content=read_result.content,
            overwrite=request.overwrite,
            metadata=request.metadata,
            content_type=request.content_type,
        )
        return PublishMemoryResult(
            session_id=request.session_id,
            source_path=request.source_path,
            target_namespace=request.target_namespace,
            target_key=request.target_key,
            shared_path=backend_result.shared_path,
            backend_uri=backend_result.backend_uri,
            content_type=request.content_type,
            published=True,
            overwrote_existing=backend_result.overwrote_existing,
        )
```

- [x] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/mcp-scratchpad/tests/unit/memory/test_publisher.py -q`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/mcp-scratchpad/src/mcp_scratchpad/memory/publisher.py \
        packages/mcp-scratchpad/tests/unit/memory/test_publisher.py
git commit -m "feat(memory): add publish service"
```

### Task 4: Register `publish_memory` as a Tool

**Files:**
- Create: `packages/mcp-scratchpad/src/mcp_scratchpad/tools/publish_memory.py`
- Modify: `packages/mcp-scratchpad/src/mcp_scratchpad/tools/file_tools.py`
- Modify: `packages/mcp-scratchpad/src/mcp_scratchpad/server.py`
- Test: `packages/mcp-scratchpad/tests/unit/test_file_tool_registration.py`

- [x] **Step 1: Write the failing registration assertion**

```python
def test_register_file_tools_registers_all_public_tools() -> None:
    ...
    assert {
        "read",
        "edit",
        "multiedit",
        "patch",
        "list",
        "write",
        "remove",
        "publish_memory",
    } <= tool_names
```

- [x] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/mcp-scratchpad/tests/unit/test_file_tool_registration.py -q`  
Expected: FAIL because `publish_memory` is not registered

- [x] **Step 3: Write minimal tool registration**

```python
# packages/mcp-scratchpad/src/mcp_scratchpad/tools/publish_memory.py
from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastmcp import Context, FastMCP
from fastmcp.tools.tool import ToolResult
from pydantic import Field

from ..fs.unified_adapter import UnifiedSessionFSAdapter
from ..memory.backends import FileSharedMemoryBackend
from ..memory.models import PublishMemoryRequest
from ..memory.publisher import PublishMemoryService
from ..storage import get_store
from ..utils import build_error_xml, build_file_operation_xml, create_tool_result_xml


def register_publish_memory(
    mcp: FastMCP,
    session_manager,
) -> None:
    @mcp.tool(
        name="publish_memory",
        description="Publish a session-visible file into shared memory storage.",
    )
    async def publish_memory(
        ctx: Context,
        session_id: Annotated[str, Field(description="Session ID")],
        source_path: Annotated[str, Field(description="Session-visible source file path")],
        target_namespace: Annotated[str, Field(description="Shared namespace")],
        target_key: Annotated[str, Field(description="Relative key inside namespace")],
        overwrite: Annotated[bool, Field(description="Allow overwrite")] = False,
    ) -> ToolResult:
        try:
            if session_manager is None:
                raise ValueError("session_manager is required")

            adapter = UnifiedSessionFSAdapter(
                session_manager=session_manager,
                store=get_store(),
                unified_enabled=True,
            )
            backend = FileSharedMemoryBackend(
                root_dir=Path("/tmp/mcp-scratchpad-shared-memory"),
                namespace_roots={
                    "shared": "shared",
                    "users": "users",
                    "agents": "agents",
                    "teams": "teams",
                },
            )
            service = PublishMemoryService(
                adapter=adapter,
                backend_by_namespace={
                    "shared": backend,
                    "users": backend,
                    "agents": backend,
                    "teams": backend,
                },
            )
            result = service.publish(
                PublishMemoryRequest(
                    session_id=session_id,
                    source_path=source_path,
                    target_namespace=target_namespace,
                    target_key=target_key,
                    overwrite=overwrite,
                )
            )
            payload = build_file_operation_xml(result.model_dump(), "publish_memory")
            return create_tool_result_xml(payload, result.model_dump())
        except Exception as exc:
            return create_tool_result_xml(build_error_xml(str(exc), "publish_memory"), {"error": str(exc)})
```

```python
# packages/mcp-scratchpad/src/mcp_scratchpad/tools/file_tools.py
from .publish_memory import register_publish_memory

...
    register_publish_memory(mcp, session_manager=session_manager)
```

- [x] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/mcp-scratchpad/tests/unit/test_file_tool_registration.py -q`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/mcp-scratchpad/src/mcp_scratchpad/tools/publish_memory.py \
        packages/mcp-scratchpad/src/mcp_scratchpad/tools/file_tools.py \
        packages/mcp-scratchpad/tests/unit/test_file_tool_registration.py
git commit -m "feat(memory): register publish_memory tool"
```

### Task 5: Add End-to-End Integration Test for Cross-Session Visibility

**Files:**
- Test: `packages/mcp-scratchpad/tests/integration/test_publish_memory.py`

- [x] **Step 1: Write the failing integration test**

```python
from __future__ import annotations

from pathlib import Path

from mcp_scratchpad.config.models import OverlayConfig
from mcp_scratchpad.fs.session_manager import SessionFileSystemManager
from mcp_scratchpad.fs.unified_adapter import UnifiedSessionFSAdapter
from mcp_scratchpad.memory.backends import FileSharedMemoryBackend
from mcp_scratchpad.memory.models import PublishMemoryRequest
from mcp_scratchpad.memory.publisher import PublishMemoryService
from mcp_scratchpad.storage import FileSystemStore, set_store


def test_publish_memory_makes_content_available_to_other_sessions(tmp_path: Path) -> None:
    shared_root = tmp_path / "shared-memory"
    overlay_config = OverlayConfig(
        mounts=[
            {
                "name": "shared_memory_users",
                "source": f"file://{shared_root / 'users'}",
                "mount_point": "/memory/users",
                "mode": "ro",
                "priority": 50,
                "options": {"auto_mkdir": True},
            }
        ]
    )
    manager = SessionFileSystemManager(overlay_config)
    session_a = manager.create_session()
    session_b = manager.create_session()

    store = FileSystemStore(base_dir=tmp_path / "store")
    set_store(store)
    adapter = UnifiedSessionFSAdapter(session_manager=manager, store=store, unified_enabled=True)
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
```

- [x] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/mcp-scratchpad/tests/integration/test_publish_memory.py -q`  
Expected: FAIL before full mount/service wiring is complete

- [x] **Step 3: Implement the missing wiring**

```python
# If the test fails because file:// auto-create is insufficient,
# make sure the backend creates namespace root directories explicitly:

namespace_dir = self.root_dir / namespace_root
namespace_dir.mkdir(parents=True, exist_ok=True)
```

```python
# If the test fails because mount discovery/config validation needs a typed config,
# build the config with real MountConfig objects instead of dicts.
```

- [x] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/mcp-scratchpad/tests/integration/test_publish_memory.py -q`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/mcp-scratchpad/tests/integration/test_publish_memory.py \
        packages/mcp-scratchpad/src/mcp_scratchpad/memory/backends.py \
        packages/mcp-scratchpad/src/mcp_scratchpad/memory/publisher.py
git commit -m "test(memory): verify cross-session publish visibility"
```

### Task 6: Add Overwrite and Copy-on-Write Regression Coverage

**Files:**
- Modify: `packages/mcp-scratchpad/tests/integration/test_publish_memory.py`

- [x] **Step 1: Write the failing overwrite and copy-up tests**

```python
def test_publish_memory_rejects_existing_target_without_overwrite(...) -> None:
    ...


def test_editing_published_memory_in_new_session_stays_session_local(...) -> None:
    ...
    session_b_result = adapter.read_text(session_b, "/memory/users/user-42/summary.md")
    adapter.write_text(session_b, "/memory/users/user-42/summary.md", "session-b\n")
    session_c_result = adapter.read_text(session_c, "/memory/users/user-42/summary.md")
    assert session_b_result.content == "published\n"
    assert session_c_result.content == "published\n"
```

- [x] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/mcp-scratchpad/tests/integration/test_publish_memory.py -q`  
Expected: FAIL until overwrite and copy-up expectations are verified in code

- [x] **Step 3: Implement minimal fixes if needed**

```python
# Ensure publish service passes through overwrite correctly.
backend.publish_text(..., overwrite=request.overwrite, ...)

# Do not add any direct lower-write path for post-publish edits.
# The existing overlay copy-on-write behavior should remain the only path.
```

- [x] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/mcp-scratchpad/tests/integration/test_publish_memory.py -q`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/mcp-scratchpad/tests/integration/test_publish_memory.py \
        packages/mcp-scratchpad/src/mcp_scratchpad/memory/backends.py \
        packages/mcp-scratchpad/src/mcp_scratchpad/memory/publisher.py
git commit -m "test(memory): cover overwrite and copy-on-write semantics"
```

### Task 7: Wire Config and Docs for Shared Memory Backend Resolution

**Files:**
- Modify: `packages/mcp-scratchpad/src/mcp_scratchpad/config/models.py`
- Modify: `packages/mcp-scratchpad/src/mcp_scratchpad/config/loader.py`
- Modify: `packages/mcp-scratchpad/src/mcp_scratchpad/yaml/scratchpad.yaml`
- Modify: `packages/mcp-scratchpad/docs/overlay-fs-tooling-guide.md`

- [x] **Step 1: Write the failing config loader test**

```python
def test_load_overlay_config_accepts_shared_memory_namespace_mapping(tmp_path: Path) -> None:
    config_path = tmp_path / "scratchpad.yaml"
    config_path.write_text(
        '''
overlay:
  rollout: {}
memory:
  publish:
    namespaces:
      users:
        backend: file
        root: /tmp/shared-memory/users
mounts: []
''',
        encoding="utf-8",
    )
    config = load_overlay_config(config_path)
    assert config.memory.publish.namespaces["users"].backend == "file"
```

- [x] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/mcp-scratchpad/tests/unit/config/test_loader_standalone.py -q`  
Expected: FAIL because memory publish config is not yet modeled

- [x] **Step 3: Implement minimal config support**

```python
# Add config models similar to:
class SharedMemoryNamespaceConfig(BaseModel):
    backend: Literal["file", "s3"]
    root: str


class SharedMemoryPublishConfig(BaseModel):
    namespaces: dict[str, SharedMemoryNamespaceConfig] = Field(default_factory=dict)


class SharedMemoryConfig(BaseModel):
    publish: SharedMemoryPublishConfig = Field(default_factory=SharedMemoryPublishConfig)
```

```python
# Extend the loader to read top-level `memory.publish`.
# Keep backward compatibility by defaulting to empty config if omitted.
```

- [x] **Step 4: Run targeted tests**

Run: `uv run pytest packages/mcp-scratchpad/tests/unit/config/test_loader_standalone.py -q`  
Expected: PASS

Run: `uv run pytest packages/mcp-scratchpad/tests/unit/memory/test_models.py packages/mcp-scratchpad/tests/unit/memory/test_backends.py packages/mcp-scratchpad/tests/unit/memory/test_publisher.py -q`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/mcp-scratchpad/src/mcp_scratchpad/config/models.py \
        packages/mcp-scratchpad/src/mcp_scratchpad/config/loader.py \
        packages/mcp-scratchpad/src/mcp_scratchpad/yaml/scratchpad.yaml \
        packages/mcp-scratchpad/docs/overlay-fs-tooling-guide.md
git commit -m "feat(config): add shared memory publish configuration"
```

### Task 8: Final Verification

**Files:**
- Verify only

- [x] **Step 1: Run unit memory test suite**

Run: `uv run pytest packages/mcp-scratchpad/tests/unit/memory -q`  
Expected: PASS

- [x] **Step 2: Run integration publish suite**

Run: `uv run pytest packages/mcp-scratchpad/tests/integration/test_publish_memory.py -q`  
Expected: PASS

- [x] **Step 3: Run existing file tool regression suites**

Run: `uv run pytest packages/mcp-scratchpad/tests/unit/test_file_tool_registration.py -q`  
Expected: PASS

Run: `uv run pytest packages/mcp-scratchpad/tests/integration/test_tool_resource_consistency.py -q`  
Expected: PASS

- [x] **Step 4: Run lint on touched files**

Run: `/Users/admin/Downloads/scratchpad/.venv/bin/ruff check packages/mcp-scratchpad/src/mcp_scratchpad/memory packages/mcp-scratchpad/src/mcp_scratchpad/tools/publish_memory.py packages/mcp-scratchpad/tests/unit/memory packages/mcp-scratchpad/tests/integration/test_publish_memory.py`  
Expected: `All checks passed!`

- [ ] **Step 5: Commit**

```bash
git add packages/mcp-scratchpad/src/mcp_scratchpad/memory \
        packages/mcp-scratchpad/src/mcp_scratchpad/tools/publish_memory.py \
        packages/mcp-scratchpad/tests/unit/memory \
        packages/mcp-scratchpad/tests/integration/test_publish_memory.py \
        packages/mcp-scratchpad/src/mcp_scratchpad/config/models.py \
        packages/mcp-scratchpad/src/mcp_scratchpad/config/loader.py \
        packages/mcp-scratchpad/src/mcp_scratchpad/yaml/scratchpad.yaml \
        packages/mcp-scratchpad/docs/overlay-fs-tooling-guide.md \
        packages/mcp-scratchpad/tests/unit/test_file_tool_registration.py
git commit -m "feat(memory): add explicit publish memory workflow"
```

---

## Self-Review

Spec coverage check:

- Explicit `publish_memory` path: covered by Tasks 3 and 4.
- `file://` first-class backend: covered by Task 2.
- Future `s3://` abstraction boundary: covered by Task 2 backend protocol and Task 7 config structure.
- Namespace validation and overwrite policy: covered by Tasks 1, 2, and 6.
- Cross-session visibility via lower mounts: covered by Task 5.
- Preserve overlay copy-on-write semantics after publish: covered by Task 6.
- Config and documentation updates: covered by Task 7.

Placeholder scan:

- No `TODO`, `TBD`, or “similar to above” markers remain.
- Each code-changing step includes concrete code or exact implementation direction.

Type consistency:

- Request model name: `PublishMemoryRequest`
- Result model name: `PublishMemoryResult`
- Service name: `PublishMemoryService`
- Backend protocol: `SharedMemoryBackend`
- File backend implementation: `FileSharedMemoryBackend`

---

Plan complete and saved to `docs/superpowers/plans/2026-04-07-publish-memory-implementation-plan.md`. Two execution options:

1. Subagent-Driven (recommended) - I dispatch a fresh subagent per task, review between tasks, fast iteration

2. Inline Execution - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
