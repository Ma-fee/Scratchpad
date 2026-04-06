# Overlay FS Unified Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unify tools and resources on a single session-scoped overlay filesystem path, standardize canonical `scratchpad://{session_id}/{path}` URIs, and complete capability/subscription/migration wiring with rollout-safe feature flags.

**Architecture:** Introduce a single `UnifiedSessionFSAdapter` abstraction that all tools/resources use for IO and metadata normalization. Move session filesystem creation to true overlay instances in `SessionFileSystemManager`, then migrate tools/resources incrementally behind feature flags (`unified fs`, `canonical uri`, `event-driven subscriptions`, `dual-write legacy`). Deliver with TDD at each slice and staged rollout validation.

**Tech Stack:** Python 3.10, FastMCP, fsspec, pytest, pydantic, ruff, mypy, uv.

---

## File Structure and Ownership

### New Files

1. `packages/mcp-scratchpad/src/mcp_scratchpad/fs/unified_adapter.py`
   - Single adapter API for all session IO and metadata shape.
2. `packages/mcp-scratchpad/src/mcp_scratchpad/events/bus.py`
   - In-process event bus contract for resource change events.
3. `packages/mcp-scratchpad/src/mcp_scratchpad/events/__init__.py`
   - Event bus exports.
4. `packages/mcp-scratchpad/tests/unit/fs/test_unified_adapter.py`
   - Adapter behavior and metadata normalization tests.
5. `packages/mcp-scratchpad/tests/integration/test_tool_resource_consistency.py`
   - End-to-end tool-write/resource-read consistency tests.
6. `packages/mcp-scratchpad/tests/integration/test_subscription_event_flow.py`
   - Event-driven subscription notification tests.

### Modified Files

1. `packages/mcp-scratchpad/src/mcp_scratchpad/fs/session_manager.py`
   - Ensure per-session overlay FS creation and retrieval.
2. `packages/mcp-scratchpad/src/mcp_scratchpad/server.py`
   - Wire adapter + event bus + directory resources + feature flags.
3. `packages/mcp-scratchpad/src/mcp_scratchpad/path_resolver.py`
   - Canonical URI builder/parser compatibility.
4. `packages/mcp-scratchpad/src/mcp_scratchpad/tools/file_tools.py`
   - Route read/write/list/remove/edit/multiedit/patch via adapter; canonical URI response.
5. `packages/mcp-scratchpad/src/mcp_scratchpad/tools/edit.py`
   - Session-aware behavior and adapter integration.
6. `packages/mcp-scratchpad/src/mcp_scratchpad/tools/apply_diff.py`
   - Session-aware behavior and adapter integration.
7. `packages/mcp-scratchpad/src/mcp_scratchpad/tools/read.py`
   - Session-aware read and canonical URI parity.
8. `packages/mcp-scratchpad/src/mcp_scratchpad/resources/scratchpad_resources.py`
   - Canonical file+directory resources and adapter usage.
9. `packages/mcp-scratchpad/src/mcp_scratchpad/resources/read_handler.py`
   - Capability negotiation entrypoint + metadata parity.
10. `packages/mcp-scratchpad/src/mcp_scratchpad/resources/subscription.py`
    - Event-driven path (primary) + polling fallback.
11. `packages/mcp-scratchpad/src/mcp_scratchpad/config/settings.py`
    - Feature flag fields and defaults.
12. `packages/mcp-scratchpad/src/mcp_scratchpad/config/models.py`
    - Optional compatibility/rollout config sections.
13. `packages/mcp-scratchpad/src/mcp_scratchpad/config/loader.py`
    - Load rollout/flag sections.
14. `packages/mcp-scratchpad/tests/integration/test_server_integration.py`
    - Validate default registration and unified path wiring.

---

### Task 1: Add Feature Flags and Config Wiring

Status: Completed on 2026-04-07 (`9d751ca`, `999e3c2`, `39ac3ed`)

**Files:**
- Modify: `packages/mcp-scratchpad/src/mcp_scratchpad/config/settings.py`
- Modify: `packages/mcp-scratchpad/src/mcp_scratchpad/config/models.py`
- Modify: `packages/mcp-scratchpad/src/mcp_scratchpad/config/loader.py`
- Test: `packages/mcp-scratchpad/tests/unit/config/test_loader_standalone.py`

- [x] **Step 1: Write failing tests for new flag defaults and loading**

```python
def test_unified_overlay_flags_default_false() -> None:
    from mcp_scratchpad.config.settings import config

    assert config.feature_unified_overlay_fs is False
    assert config.feature_canonical_uri_only is False
    assert config.feature_event_driven_subscriptions is False
    assert config.feature_dual_write_legacy_store is False
```

```python
def test_loader_reads_rollout_flags(tmp_path: Path) -> None:
    config_file = tmp_path / "scratchpad.yaml"
    config_file.write_text(
        """
overlay:
  rollout:
    unified_overlay_fs: true
    canonical_uri_only: false
""".strip()
    )

    cfg = load_overlay_config(config_file)
    assert cfg.rollout.unified_overlay_fs is True
    assert cfg.rollout.canonical_uri_only is False
```

- [x] **Step 2: Run tests to verify failures**

Run:
```bash
cd packages/mcp-scratchpad
uv run pytest tests/unit/config/test_loader_standalone.py -q
```

Expected: tests fail with missing config fields.

- [x] **Step 3: Implement minimal config fields and loader mapping**

```python
# settings.py
feature_unified_overlay_fs: bool = False
feature_canonical_uri_only: bool = False
feature_event_driven_subscriptions: bool = False
feature_dual_write_legacy_store: bool = False
```

```python
# models.py
class OverlayRolloutConfig(BaseModel):
    unified_overlay_fs: bool = False
    canonical_uri_only: bool = False
    event_driven_subscriptions: bool = False
    dual_write_legacy_store: bool = False

class OverlayConfig(BaseModel):
    ...
    rollout: OverlayRolloutConfig = Field(default_factory=OverlayRolloutConfig)
```

- [x] **Step 4: Re-run tests and verify green**

Run:
```bash
cd packages/mcp-scratchpad
uv run pytest tests/unit/config/test_loader_standalone.py -q
```

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add packages/mcp-scratchpad/src/mcp_scratchpad/config/settings.py \
        packages/mcp-scratchpad/src/mcp_scratchpad/config/models.py \
        packages/mcp-scratchpad/src/mcp_scratchpad/config/loader.py \
        packages/mcp-scratchpad/tests/unit/config/test_loader_standalone.py
git commit -m "feat(config): add rollout feature flags for unified overlay migration"
```

---

### Task 2: Introduce UnifiedSessionFSAdapter

Status: Completed on 2026-04-07 (`c30ec5a`)

**Files:**
- Create: `packages/mcp-scratchpad/src/mcp_scratchpad/fs/unified_adapter.py`
- Modify: `packages/mcp-scratchpad/src/mcp_scratchpad/fs/__init__.py`
- Test: `packages/mcp-scratchpad/tests/unit/fs/test_unified_adapter.py`

- [x] **Step 1: Write failing adapter tests**

```python
def test_builds_canonical_uri() -> None:
    adapter = UnifiedSessionFSAdapter(session_manager=..., store=...)
    assert adapter.build_uri("sess-1", "/workspace/a.txt") == "scratchpad://sess-1/workspace/a.txt"
```

```python
def test_read_prefers_session_overlay_when_unified_enabled() -> None:
    adapter = UnifiedSessionFSAdapter(session_manager=..., store=..., unified_enabled=True)
    adapter.write_text("sess-1", "/workspace/a.txt", "hello")
    result = adapter.read_text("sess-1", "/workspace/a.txt")
    assert result.content == "hello"
    assert result.layer == "upper"
```

- [x] **Step 2: Run tests to verify red**

Run:
```bash
cd packages/mcp-scratchpad
uv run pytest tests/unit/fs/test_unified_adapter.py -q
```

Expected: FAIL, module/class missing.

- [x] **Step 3: Implement minimal adapter**

```python
@dataclass
class UnifiedReadResult:
    session_id: str
    path: str
    uri: str
    content: str
    layer: str
    version: int | None


class UnifiedSessionFSAdapter:
    def __init__(self, session_manager: SessionFileSystemManager | None, store: FileSystemStore, unified_enabled: bool) -> None:
        self._session_manager = session_manager
        self._store = store
        self._unified_enabled = unified_enabled

    def build_uri(self, session_id: str, path: str) -> str:
        return f"scratchpad://{session_id}/{path.lstrip('/')}"
```

- [x] **Step 4: Re-run tests to green**

Run:
```bash
cd packages/mcp-scratchpad
uv run pytest tests/unit/fs/test_unified_adapter.py -q
```

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add packages/mcp-scratchpad/src/mcp_scratchpad/fs/unified_adapter.py \
        packages/mcp-scratchpad/src/mcp_scratchpad/fs/__init__.py \
        packages/mcp-scratchpad/tests/unit/fs/test_unified_adapter.py
git commit -m "feat(fs): add unified session filesystem adapter"
```

---

### Task 3: Make Session Manager Return True Overlay FS for Sessions

Status: Completed on 2026-04-07 (`4b13bbd`)

**Files:**
- Modify: `packages/mcp-scratchpad/src/mcp_scratchpad/fs/session_manager.py`
- Test: `packages/mcp-scratchpad/tests/unit/fs/test_session_manager.py`

- [x] **Step 1: Write failing tests for overlay session FS**

```python
def test_get_session_fs_returns_overlay_filesystem() -> None:
    manager = SessionFileSystemManager(config_with_mounts())
    session_id = manager.create_session()
    fs = manager.get_session_fs(session_id)

    assert isinstance(fs, OverlayFileSystem)
```

```python
def test_session_overlay_reads_from_lower_and_writes_to_upper() -> None:
    manager = SessionFileSystemManager(config_with_ro_lower())
    session_id = manager.create_session()
    fs = manager.get_session_fs(session_id)

    assert fs.exists("/templates/base.txt")
    with fs.open("/workspace/new.txt", "w") as f:
        f.write("hi")
    assert fs.exists("/workspace/new.txt")
```

- [x] **Step 2: Run failing tests**

Run:
```bash
cd packages/mcp-scratchpad
uv run pytest tests/unit/fs/test_session_manager.py -q
```

Expected: FAIL due to non-overlay session FS.

- [x] **Step 3: Implement overlay-backed session creation**

```python
# session_manager.py (concept)
upper = self._create_session_upper_backend(session_id)
lowers = self._build_lower_layers_for_session(session_id)
overlay = OverlayFileSystem(upper=upper, lowers=lowers, session_id=session_id)
self._sessions[session_id] = overlay
```

- [x] **Step 4: Re-run tests to green**

Run:
```bash
cd packages/mcp-scratchpad
uv run pytest tests/unit/fs/test_session_manager.py -q
```

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add packages/mcp-scratchpad/src/mcp_scratchpad/fs/session_manager.py \
        packages/mcp-scratchpad/tests/unit/fs/test_session_manager.py
git commit -m "feat(fs): back sessions with overlay filesystem instances"
```

---

### Task 4: Canonical URI Migration in Path Resolver and Response Metadata

Status: Completed on 2026-04-07 (`8430286`)

**Files:**
- Modify: `packages/mcp-scratchpad/src/mcp_scratchpad/path_resolver.py`
- Modify: `packages/mcp-scratchpad/src/mcp_scratchpad/tools/file_tools.py`
- Test: `packages/mcp-scratchpad/tests/unit/test_path_resolver.py`

- [x] **Step 1: Write failing canonical URI tests**

```python
def test_build_uri_requires_session_and_returns_canonical() -> None:
    assert build_uri("reports/a.md", session_id="sess-1") == "scratchpad://sess-1/reports/a.md"
```

```python
def test_parse_uri_accepts_legacy_form_for_compat() -> None:
    scheme, path, session_id = parse_uri_compat("scratchpad:///reports/a.md", default_session_id="sess-1")
    assert scheme == "scratchpad"
    assert session_id == "sess-1"
    assert path == "/reports/a.md"
```

- [x] **Step 2: Run tests to verify red**

Run:
```bash
cd packages/mcp-scratchpad
uv run pytest tests/unit/test_path_resolver.py -q
```

Expected: FAIL with old signature/behavior.

- [x] **Step 3: Implement canonical URI helpers and compatibility parser**

```python
def build_uri(relative_path: str, session_id: str) -> str:
    clean_path = relative_path.lstrip("/")
    return f"scratchpad://{session_id}/{clean_path}"
```

- [x] **Step 4: Update tool responses to emit canonical URI only**

```python
structured["uri"] = build_uri(record.file_path, session_id=get_store().session_id)
```

- [x] **Step 5: Re-run tests**

Run:
```bash
cd packages/mcp-scratchpad
uv run pytest tests/unit/test_path_resolver.py -q
```

Expected: PASS.

- [x] **Step 6: Commit**

```bash
git add packages/mcp-scratchpad/src/mcp_scratchpad/path_resolver.py \
        packages/mcp-scratchpad/src/mcp_scratchpad/tools/file_tools.py \
        packages/mcp-scratchpad/tests/unit/test_path_resolver.py
git commit -m "feat(uri): standardize canonical scratchpad session uri format"
```

---

### Task 5: Migrate Tools to Unified Adapter (including edit and patch)

**Files:**
- Modify: `packages/mcp-scratchpad/src/mcp_scratchpad/tools/file_tools.py`
- Modify: `packages/mcp-scratchpad/src/mcp_scratchpad/tools/edit.py`
- Modify: `packages/mcp-scratchpad/src/mcp_scratchpad/tools/apply_diff.py`
- Modify: `packages/mcp-scratchpad/src/mcp_scratchpad/tools/read.py`
- Test: `packages/mcp-scratchpad/tests/integration/test_tool_resource_consistency.py`

- [ ] **Step 1: Add failing tests for session-aware edit/patch and tool-resource parity**

```python
def test_edit_requires_session_context(client):
    result = client.call_tool("edit", {"file_path": "/workspace/a.txt", "old_string": "a", "new_string": "b"})
    assert "session" in result.error.lower()
```

```python
def test_patch_writes_visible_to_resource_read(client, session_id):
    client.call_tool("write", {"session_id": session_id, "file_path": "/workspace/a.txt", "content": "hello"})
    client.call_tool("patch", {"session_id": session_id, "file_path": "/workspace/a.txt", "diff": "@@ -1 +1 @@\n-hello\n+world\n"})

    content = client.read_resource(f"scratchpad://{session_id}/workspace/a.txt")
    assert "world" in content
```

- [ ] **Step 2: Run tests to verify red**

Run:
```bash
cd packages/mcp-scratchpad
uv run pytest tests/integration/test_tool_resource_consistency.py -q
```

Expected: FAIL for missing session-aware wiring.

- [ ] **Step 3: Route tool operations through adapter and require session for mutating tools**

```python
# edit tool signature
async def edit(..., session_id: str | None = Field(default=None, ...)) -> str:
    if not session_id:
        raise ValueError("session_id is required")
    adapter = get_unified_adapter()
    adapter.edit_text(session_id=session_id, path=file_path, old=old_string, new=new_string, replace_all=replace_all)
```

```python
# patch tool signature
async def patch(..., session_id: str | None = None, ...):
    if not session_id:
        raise ValueError("session_id is required")
    adapter.apply_diff(session_id=session_id, path=file_path, diff_text=diff, expected_version=expected_version)
```

- [ ] **Step 4: Re-run tests to green**

Run:
```bash
cd packages/mcp-scratchpad
uv run pytest tests/integration/test_tool_resource_consistency.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/mcp-scratchpad/src/mcp_scratchpad/tools/file_tools.py \
        packages/mcp-scratchpad/src/mcp_scratchpad/tools/edit.py \
        packages/mcp-scratchpad/src/mcp_scratchpad/tools/apply_diff.py \
        packages/mcp-scratchpad/src/mcp_scratchpad/tools/read.py \
        packages/mcp-scratchpad/tests/integration/test_tool_resource_consistency.py
git commit -m "feat(tools): route all file tools through unified session adapter"
```

---

### Task 6: Register Directory Resources and Unify Resource Adapter Path

**Files:**
- Modify: `packages/mcp-scratchpad/src/mcp_scratchpad/resources/scratchpad_resources.py`
- Modify: `packages/mcp-scratchpad/src/mcp_scratchpad/server.py`
- Test: `packages/mcp-scratchpad/tests/integration/test_resource_e2e.py`

- [ ] **Step 1: Write failing tests for default directory resource registration**

```python
def test_directory_resource_registered_by_default(mcp_client, session_id):
    payload = mcp_client.read_resource(f"scratchpad://{session_id}/workspace/")
    assert "entries" in payload
```

- [ ] **Step 2: Run failing tests**

Run:
```bash
cd packages/mcp-scratchpad
uv run pytest tests/integration/test_resource_e2e.py -q
```

Expected: FAIL because directory resource not wired in default server registration.

- [ ] **Step 3: Register directory resources by default and route reads via adapter**

```python
# server.py
register_scratchpad_resources(mcp, self._session_manager)
register_directory_resources(mcp, self._session_manager)
```

- [ ] **Step 4: Re-run tests**

Run:
```bash
cd packages/mcp-scratchpad
uv run pytest tests/integration/test_resource_e2e.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/mcp-scratchpad/src/mcp_scratchpad/resources/scratchpad_resources.py \
        packages/mcp-scratchpad/src/mcp_scratchpad/server.py \
        packages/mcp-scratchpad/tests/integration/test_resource_e2e.py
git commit -m "feat(resources): register directory handlers and unify resource adapter path"
```

---

### Task 7: Wire Capability Negotiation into Resource Entrypoint

**Files:**
- Modify: `packages/mcp-scratchpad/src/mcp_scratchpad/resources/read_handler.py`
- Modify: `packages/mcp-scratchpad/src/mcp_scratchpad/resources/scratchpad_resources.py`
- Test: `packages/mcp-scratchpad/tests/unit/resources/test_multimodal.py`

- [ ] **Step 1: Add failing tests for capability-driven output shape**

```python
def test_resource_response_uses_text_fallback_without_image_capability(...):
    result = read_resource(uri, client_context={"headers": {"Accept": "text/plain"}})
    assert result.metadata.mime_type.startswith("text/")
```

```python
def test_resource_response_uses_image_payload_when_supported(...):
    result = read_resource(uri, client_context={"headers": {"Accept": "image/png"}})
    assert result.metadata.content_type in {"image", "binary"}
```

- [ ] **Step 2: Run tests to confirm failure**

Run:
```bash
cd packages/mcp-scratchpad
uv run pytest tests/unit/resources/test_multimodal.py -q
```

Expected: FAIL on missing request-context capability wiring.

- [ ] **Step 3: Implement capability detection in resource entrypoint**

```python
caps = detect_client_capabilities(headers=request_headers, user_agent=user_agent)
selected_format = negotiate_format(preferred=detected_resource_kind, client_caps=caps)
```

- [ ] **Step 4: Re-run unit tests**

Run:
```bash
cd packages/mcp-scratchpad
uv run pytest tests/unit/resources/test_multimodal.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/mcp-scratchpad/src/mcp_scratchpad/resources/read_handler.py \
        packages/mcp-scratchpad/src/mcp_scratchpad/resources/scratchpad_resources.py \
        packages/mcp-scratchpad/tests/unit/resources/test_multimodal.py
git commit -m "feat(resources): negotiate multimodal response by client capability"
```

---

### Task 8: Event-Driven Subscription Notifications

**Files:**
- Create: `packages/mcp-scratchpad/src/mcp_scratchpad/events/bus.py`
- Create: `packages/mcp-scratchpad/src/mcp_scratchpad/events/__init__.py`
- Modify: `packages/mcp-scratchpad/src/mcp_scratchpad/resources/subscription.py`
- Modify: `packages/mcp-scratchpad/src/mcp_scratchpad/tools/file_tools.py`
- Test: `packages/mcp-scratchpad/tests/integration/test_subscription_event_flow.py`

- [ ] **Step 1: Add failing integration tests for write-triggered notifications**

```python
def test_write_emits_subscription_notification(session_id, client, collector):
    uri = f"scratchpad://{session_id}/workspace/live.md"
    collector.subscribe(uri)

    client.call_tool("write", {"session_id": session_id, "file_path": "/workspace/live.md", "content": "v1"})

    assert collector.wait_for(uri, timeout=2.0)
```

- [ ] **Step 2: Run tests to verify red**

Run:
```bash
cd packages/mcp-scratchpad
uv run pytest tests/integration/test_subscription_event_flow.py -q
```

Expected: FAIL because direct event path not wired.

- [ ] **Step 3: Implement event bus and publish on mutating operations**

```python
@dataclass(frozen=True)
class ResourceChangedEvent:
    session_id: str
    path: str
    uri: str
    operation: str


bus.publish(ResourceChangedEvent(...))
```

- [ ] **Step 4: Integrate subscription manager consumer and keep polling fallback**

```python
if config.feature_event_driven_subscriptions:
    bus.subscribe("resource_changed", self._on_resource_changed)
```

- [ ] **Step 5: Re-run tests**

Run:
```bash
cd packages/mcp-scratchpad
uv run pytest tests/integration/test_subscription_event_flow.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add packages/mcp-scratchpad/src/mcp_scratchpad/events/bus.py \
        packages/mcp-scratchpad/src/mcp_scratchpad/events/__init__.py \
        packages/mcp-scratchpad/src/mcp_scratchpad/resources/subscription.py \
        packages/mcp-scratchpad/src/mcp_scratchpad/tools/file_tools.py \
        packages/mcp-scratchpad/tests/integration/test_subscription_event_flow.py
git commit -m "feat(subscriptions): add event-driven resource change notifications"
```

---

### Task 9: Migration Controls, Dual-Write, and Rollback Validation

**Files:**
- Modify: `packages/mcp-scratchpad/src/mcp_scratchpad/fs/unified_adapter.py`
- Modify: `packages/mcp-scratchpad/src/mcp_scratchpad/server.py`
- Modify: `packages/mcp-scratchpad/src/mcp_scratchpad/monitoring/health.py`
- Test: `packages/mcp-scratchpad/tests/integration/test_server_integration.py`

- [ ] **Step 1: Add failing tests for flag-driven path selection and dual-write behavior**

```python
def test_dual_write_updates_legacy_store_when_enabled(...):
    adapter = UnifiedSessionFSAdapter(..., dual_write_enabled=True)
    adapter.write_text("sess-1", "/workspace/a.txt", "abc")
    assert legacy_store_contains("sess-1", "workspace/a.txt", "abc")
```

- [ ] **Step 2: Run tests to verify red**

Run:
```bash
cd packages/mcp-scratchpad
uv run pytest tests/integration/test_server_integration.py -q
```

Expected: FAIL due to missing rollout behavior.

- [ ] **Step 3: Implement stage-aware adapter behavior and health metrics**

```python
if self._dual_write_enabled:
    self._write_overlay(...)
    self._write_legacy_store(...)
else:
    self._write_overlay(...)
```

```python
return {
    "rollout": {
        "unified_overlay_fs": config.feature_unified_overlay_fs,
        "dual_write_legacy_store": config.feature_dual_write_legacy_store,
    }
}
```

- [ ] **Step 4: Re-run integration tests**

Run:
```bash
cd packages/mcp-scratchpad
uv run pytest tests/integration/test_server_integration.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/mcp-scratchpad/src/mcp_scratchpad/fs/unified_adapter.py \
        packages/mcp-scratchpad/src/mcp_scratchpad/server.py \
        packages/mcp-scratchpad/src/mcp_scratchpad/monitoring/health.py \
        packages/mcp-scratchpad/tests/integration/test_server_integration.py
git commit -m "feat(migration): add rollout flags, dual-write controls, and health visibility"
```

---

### Task 10: Full Verification Gate and Release Candidate Checklist

**Files:**
- Modify: `packages/mcp-scratchpad/README.md`
- Create: `packages/mcp-scratchpad/docs/current-behavior-user-guide.md` (if not present in branch)

- [ ] **Step 1: Add release checklist documentation updates**

```markdown
## Unified Overlay Rollout Checklist
1. Enable `FEATURE_UNIFIED_OVERLAY_FS` in staging.
2. Verify tool/resource consistency suite passes.
3. Verify event-driven subscription delivery metrics.
4. Enable canonical URI-only mode.
5. Disable dual-write after consistency burn-in.
```

- [ ] **Step 2: Run full verification suite**

Run:
```bash
cd packages/mcp-scratchpad
uv run pytest -q
uv run ruff check src/ tests/
uv run mypy src/
```

Expected: all commands exit 0.

- [ ] **Step 3: Commit docs and verification results summary**

```bash
git add packages/mcp-scratchpad/README.md \
        packages/mcp-scratchpad/docs/current-behavior-user-guide.md
git commit -m "docs(release): add unified overlay rollout and verification checklist"
```

---

## Spec Coverage Self-Review

1. Unified single source path: covered by Tasks 2, 3, 5.
2. Canonical URI standardization: covered by Task 4.
3. Resource parity (file + directory + large-file handling baseline): covered by Tasks 6 and 7.
4. Capability negotiation wiring: covered by Task 7.
5. Event-driven subscriptions: covered by Task 8.
6. Migration/rollback with feature flags and dual-write: covered by Task 9.
7. Acceptance verification and release controls: covered by Task 10.

## Placeholder and Consistency Self-Review

1. Placeholder scan complete: no `TBD`, `TODO`, or deferred-action placeholders in execution steps.
2. Naming consistency checked:
   - `UnifiedSessionFSAdapter`
   - Canonical URI `scratchpad://{session_id}/{path}`
   - Feature flags use consistent names across tasks.
3. Scope check passed: plan remains in one subsystem family (filesystem unification + protocol parity + rollout controls).
