# RFC-0001: Overlay Filesystem Architecture Implementation

## TL;DR

> **Quick Summary**: Implement a multi-layer overlay filesystem architecture for MCP Scratchpad using fsspec, supporting S3/Local/Memory backends with session-scoped Copy-on-Write and MCP Resources integration via `scratchpad://` URI scheme.
>
> **Deliverables**:
> - Config-driven mount system with overlay semantics
> - SessionFileSystemManager with per-session overlay views
> - OverlayFileSystem with COW and whiteout support
> - MCP Resources handlers for `scratchpad://` URIs
> - Multi-modal file support (images, PDFs) with client capability detection
> - Directory index caching for performance
> - Full test coverage with TDD approach
>
> **Estimated Effort**: Large (5 weeks, 5 phases)
> **Parallel Execution**: YES - Waves within each phase
> **Critical Path**: Config → SessionManager → OverlayFS → Resources → Integration

---

## Context

### Original Request
Implement RFC-0001: MCP Scratchpad Overlay Filesystem Architecture using TDD approach.

### Interview Summary
**Key Discussions**:
- User provided comprehensive RFC document at `/packages/mcp-scratchpad/docs/rfcs/draft/RFC-0001-scratchpad-overlay-fs.md`
- Explicitly requested TDD (Test-Driven Development) approach
- Implementation aligns with existing FastMCP-based mcp-scratchpad service

**Research Findings**:
- Current codebase uses FileSystemStore with local filesystem only
- pytest testing infrastructure already exists
- Pydantic models for request validation in place
- FastMCP framework for MCP server implementation
- No current fsspec dependency (needs to be added)

### Metis Review
**Identified Gaps** (addressed in this plan):
- [x] Acceptance Criteria defined for each phase
- [x] TDD approach specified with test hierarchy
- [x] Scope boundaries explicitly locked down
- [x] Risk areas documented with mitigation strategies
- [x] Security considerations integrated into tasks
- [x] Edge cases (whiteout cascade, memory overflow, S3 failure) included in test plan

---

## Work Objectives

### Core Objective
Replace the current FileSystemStore with a multi-layer overlay filesystem architecture supporting multiple backends (Local, S3, Memory) while maintaining backward compatibility with existing MCP Tools and adding full MCP Resources support.

### Concrete Deliverables
- `config/models.py`: MountConfig and OverlayConfig Pydantic models
- `fs/session_manager.py`: SessionFileSystemManager for per-session FS management
- `fs/overlay.py`: OverlayFileSystem with COW and whiteout implementation
- `fs/cache.py`: Directory index caching with TTL and event-driven invalidation
- `resources/scratchpad_resources.py`: MCP Resource handlers for `scratchpad://` URIs
- `security/path_validation.py`: Path traversal protection
- Complete test suite: unit/, integration/, e2e/, performance/, security/

### Definition of Done
- [ ] All acceptance criteria for each phase pass
- [ ] Test coverage > 85% for all new code
- [ ] Security review checklist completed
- [ ] Performance benchmarks meet or exceed RFC targets
- [ ] Backward compatibility verified with existing tool APIs
- [ ] Documentation updated (API docs, migration guide, security guide)

### Must Have (In Scope)
- Multi-layer overlay filesystem with upper (RW) and lower (RO) layers
- Session-scoped filesystem isolation
- Copy-on-Write (COW) semantics
- Whiteout mechanism for file deletion
- Directory index caching
- Local, S3, Memory backend support
- MCP Resources with `scratchpad://` URI scheme
- Multi-modal file support (images, PDFs)
- Path traversal protection
- Configuration-driven mount system

### Must NOT Have (Guardrails - Out of Scope)
- **NFS/SMB Support**: Explicitly deferred to future RFC
- **Real-time Collaboration**: No live concurrent editing or WebSocket sync
- **Built-in Migration Tool**: Breaking change from .metadata.json, manual export only
- **Git Integration**: Versioning limited to optimistic locking
- **File-level ACLs**: Only mount-level RO/RW permissions
- **Encryption at Rest**: Storage layer responsibility
- **Distributed Consistency**: Single-node deployment assumption
- **Cross-Session Resource Subscriptions**: Subscriptions stay within single session

---

## Verification Strategy (MANDATORY)

> **ZERO HUMAN INTERVENTION** — ALL verification is agent-executed. No exceptions.

### Test Strategy
- **Approach**: TDD (Test-Driven Development)
- **Infrastructure**: pytest with existing configuration
- **Structure**: RED → GREEN → REFACTOR for each component

### Test Categories
```
tests/
├── unit/                    # Fast, isolated tests
│   ├── fs/
│   ├── resources/
│   ├── cache/
│   └── security/
├── integration/             # Component interactions
├── e2e/                     # Full stack tests
├── performance/             # Benchmarks
└── security/                # Security tests
```

### QA Policy
Every task MUST include agent-executed QA scenarios:
- **Unit tests**: pytest with coverage
- **Integration tests**: Component interaction verification
- **Performance tests**: Benchmark with concurrent sessions
- **Security tests**: Path traversal, session isolation

### Coverage Requirements
- Phase 1: > 90% line coverage
- Phase 2: > 85% line coverage
- Phase 2b: > 85% line coverage
- Phase 3+: > 80% line coverage

---

## Execution Strategy

### Parallel Execution Waves

This is a 5-phase implementation. Each phase consists of multiple waves for parallel execution.

**Phase 1: Foundation (Week 1)**
```
Wave 1 (Foundation Layer - All Parallel):
├── Task 1: Add fsspec dependencies [quick]
├── Task 2: MountConfig Pydantic models [quick]
├── Task 3: OverlayConfig validation [quick]
├── Task 4: Basic SessionFileSystemManager skeleton [quick]
└── Task 5: Configuration loader with env var support [quick]

Wave 2 (Core Manager - Parallel):
├── Task 6: Session lifecycle management [medium]
├── Task 7: Per-session MemoryFileSystem initialization [medium]
├── Task 8: Shared mount COW support [medium]
└── Task 9: Session cleanup and resource management [medium]

Wave 3 (Cache Foundation):
├── Task 10: Directory index cache with TTL [medium]
├── Task 11: Cache invalidation strategy (hybrid mode) [medium]
└── Task 12: Memory management for cache [quick]

Wave FINAL (Phase 1 Verification):
├── Task F1.1: Unit tests for all Phase 1 components [deep]
└── Task F1.2: Integration tests for SessionManager [unspecified-high]
```

**Phase 2: Overlay FS Core (Week 2)**
```
Wave 1 (Overlay Foundation):
├── Task 13: OverlayFileSystem class skeleton [quick]
├── Task 14: Multi-layer path resolution [deep]
├── Task 15: Read operations (ls, exists, isfile, isdir) [medium]
└── Task 16: File info and metadata merging [medium]

Wave 2 (Write Operations):
├── Task 17: Copy-on-Write implementation [deep]
├── Task 18: Write file operations [medium]
├── Task 19: Directory creation [medium]
└── Task 20: File deletion with whiteout markers [deep]

Wave 3 (Backend Abstraction):
├── Task 21: Local filesystem backend [quick]
├── Task 22: S3 backend with fsspec [medium]
└── Task 23: Backend factory and configuration [quick]

Wave FINAL (Phase 2 Verification):
├── Task F2.1: OverlayFS unit tests (all methods) [deep]
├── Task F2.2: COW semantics tests [deep]
└── Task F2.3: Backend integration tests [unspecified-high]
```

**Phase 2b: Extended Overlay (Week 3)**
```
Wave 1 (Whiteout & Edge Cases):
├── Task 24: Complete whiteout lifecycle [deep]
├── Task 25: Whiteout cleanup and stale detection [medium]
├── Task 26: Edge case: recreate after delete [medium]
├── Task 27: Edge case: rename with COW [medium]
└── Task 28: Directory whiteout handling [medium]

Wave 2 (Performance):
├── Task 29: Large file streaming support [medium]
├── Task 30: Cache performance tuning [medium]
└── Task 31: Memory pressure handling [deep]

Wave 3 (Stress Testing):
├── Task 32: Concurrent session stress tests [unspecified-high]
└── Task 33: Performance benchmark suite [unspecified-high]

Wave FINAL (Phase 2b Verification):
├── Task F3.1: Whiteout comprehensive tests [deep]
└── Task F3.2: Performance benchmark validation [unspecified-high]
```

**Phase 3: MCP Resources (Week 4)**
```
Wave 1 (Resource Foundation):
├── Task 34: FastMCP resource handler registration [quick]
├── Task 35: scratchpad:// URI parser [quick]
└── Task 36: Resource read handler [medium]

Wave 2 (Resource Features):
├── Task 37: Directory resource listing [medium]
├── Task 38: Large file resource (metadata + preview) [medium]
└── Task 39: Resource subscription and notifications [unspecified-high]

Wave 3 (Multi-modal):
├── Task 40: Client capability detection [medium]
├── Task 41: Image resource handler with thumbnails [medium]
├── Task 42: Binary file (PDF) resource handler [medium]
└── Task 43: XML wrapper format for all resources [medium]

Wave FINAL (Phase 3 Verification):
├── Task F4.1: Resource handler tests [unspecified-high]
├── Task F4.2: Multi-modal tests [unspecified-high]
└── Task F4.3: E2E resource tests [unspecified-high]
```

**Phase 4: Integration & Security (Week 4-5)**
```
Wave 1 (Security):
├── Task 44: Path traversal protection [deep]
├── Task 45: Session isolation validation [medium]
├── Task 46: Credential security (masking in logs) [medium]
└── Task 47: Resource limit enforcement [medium]

Wave 2 (Backward Compatibility):
├── Task 48: Tool API adapter layer [medium]
├── Task 49: Existing FileSystemStore compatibility [medium]
└── Task 50: Migration verification tests [unspecified-high]

Wave FINAL (Phase 4 Verification):
├── Task F5.1: Security audit tests [deep]
└── Task F5.2: Backward compatibility tests [unspecified-high]
```

**Phase 5: Release Preparation (Week 5)**
```
Wave 1 (Documentation & Benchmarks):
├── Task 51: API documentation [writing]
├── Task 52: Migration guide [writing]
├── Task 53: Security guide [writing]
└── Task 54: Performance benchmark report [unspecified-high]

Wave 2 (Release):
├── Task 55: CHANGELOG with breaking changes [writing]
├── Task 56: Feature flag implementation [quick]
└── Task 57: Final release preparation [unspecified-high]

Wave FINAL (Overall Verification):
├── Task F6.1: Plan compliance audit (oracle)
├── Task F6.2: Code quality review (unspecified-high)
├── Task F6.3: Security review checklist [deep]
└── Task F6.4: Performance benchmark final validation [unspecified-high]
```

### Dependency Matrix

```
Phase 1:
  Task 1 → Tasks 2-5
  Task 2 → Tasks 6-8
  Task 3 → Tasks 6-8
  Tasks 6-9 → Task 10-12
  Tasks 10-12 → F1.1, F1.2

Phase 2:
  F1.1, F1.2 → Task 13
  Task 13 → Tasks 14-16
  Tasks 14-16 → Tasks 17-20
  Task 17 → Tasks 18-20
  Tasks 21-23 → F2.1-F2.3

Phase 2b:
  F2.1-F2.3 → Task 24
  Task 24 → Tasks 25-28
  Tasks 25-28 → Tasks 29-31
  Tasks 29-31 → Tasks 32-33
  Tasks 32-33 → F3.1, F3.2

Phase 3:
  F3.1, F3.2 → Task 34
  Task 34 → Tasks 35-36
  Tasks 35-36 → Tasks 37-39
  Tasks 37-39 → Tasks 40-43
  Tasks 40-43 → F4.1-F4.3

Phase 4:
  F4.1-F4.3 → Tasks 44-47
  Tasks 44-47 → Tasks 48-50
  Tasks 48-50 → F5.1, F5.2

Phase 5:
  F5.1, F5.2 → Tasks 51-57
  Tasks 51-57 → F6.1-F6.4
```

---

## TODOs

### Phase 1: Foundation (Week 1)

#### Wave 1: Dependencies and Configuration

- [x] **Task 1: Add fsspec dependencies to pyproject.toml**

  **What to do**:
  - Add `fsspec>=2024.1.0` to main dependencies
  - Add `s3fs>=2024.1.0` to optional-dependencies.s3
  - Verify dependencies resolve with `uv sync`

  **TDD Approach**:
  1. Write test that imports fsspec and checks version
  2. Watch test fail (fsspec not installed)
  3. Add dependency and sync
  4. Verify test passes

  **Must NOT do**:
  - Don't add fsspec-union (we'll use custom OverlayFS per RFC DEC-1)
  - Don't pin to exact versions (use >= constraints)

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []
  - Reason: Simple dependency management, no complex logic

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 2-5)
  - **Blocks**: Tasks 6-12 (all require fsspec)
  - **Blocked By**: None

  **References**:
  - `/packages/mcp-scratchpad/pyproject.toml` - existing dependency structure
  - RFC Appendix A - dependency specifications

  **Acceptance Criteria**:
  - [ ] `uv sync` completes without errors
  - [ ] `python -c "import fsspec; print(fsspec.__version__)"` succeeds
  - [ ] Test file `tests/unit/fs/test_dependencies.py` passes

  **QA Scenarios**:
  ```
  Scenario: fsspec imports correctly
    Tool: Bash (python)
    Steps:
      1. cd /packages/mcp-scratchpad
      2. uv run python -c "from fsspec import AbstractFileSystem; print('OK')"
    Expected Result: Output contains "OK"
    Evidence: .sisyphus/evidence/task-1-fsspec-import.txt
  ```

  **Commit**: YES
  - Message: `deps: add fsspec>=2024.1.0 and s3fs dependencies`
  - Files: `pyproject.toml`

- [x] **Task 2: Implement MountConfig Pydantic models**

  **What to do**:
  - Create `src/mcp_scratchpad/config/models.py`
  - Implement `MountConfig` Pydantic model with:
    - name: str (validated format)
    - source: str (URI with scheme validation)
    - mount_point: str (path validation)
    - mode: Literal["ro", "rw"]
    - priority: int
    - options: dict
  - Implement `OverlayConfig` root model

  **TDD Approach**:
  1. Write tests for all validation rules first
  2. Watch tests fail (models don't exist)
  3. Implement models to make tests pass
  4. Add edge case tests

  **Must NOT do**:
  - Don't implement actual filesystem creation (that's Task 8)
  - Don't add YAML loading yet (that's Task 5)

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []
  - Reason: Data validation models, clear requirements from RFC

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1
  - **Blocks**: Tasks 3, 6-8
  - **Blocked By**: None (can start immediately)

  **References**:
  - RFC Section "Configuration Schema" - validation rules
  - RFC config/validator.py - example validation logic
  - `/packages/mcp-scratchpad/src/mcp_scratchpad/models.py` - existing Pydantic patterns

  **Acceptance Criteria (TDD)**:
  - [ ] Test: Valid MountConfig creates successfully
  - [ ] Test: Invalid name format raises ValidationError
  - [ ] Test: Invalid source scheme raises ValidationError
  - [ ] Test: Path traversal in mount_point raises ValidationError
  - [ ] Test: Duplicate mount names in OverlayConfig raises error
  - [ ] Test: Multiple RW mounts raises error

  **QA Scenarios**:
  ```
  Scenario: Valid mount configuration
    Tool: Bash (python)
    Steps:
      1. uv run python -c "
           from mcp_scratchpad.config.models import MountConfig
           m = MountConfig(name='templates', source='file:///tmp/templates', mount_point='/templates', mode='ro')
           print(m.name)
         "
    Expected Result: Output contains "templates"
    Evidence: .sisyphus/evidence/task-2-valid-mount.txt

  Scenario: Invalid name format rejected
    Tool: Bash (python)
    Steps:
      1. uv run python -c "
           from mcp_scratchpad.config.models import MountConfig
           MountConfig(name='123invalid', source='file:///tmp', mount_point='/tmp', mode='ro')
         "
    Expected Result: Script exits with ValidationError
    Evidence: .sisyphus/evidence/task-2-invalid-name.txt
  ```

  **Commit**: YES
  - Message: `feat(config): add MountConfig and OverlayConfig models with validation`
  - Files: `src/mcp_scratchpad/config/models.py`, `tests/unit/config/test_models.py`

- [x] **Task 3: Implement configuration validation logic**

  **What to do**:
  - Extend Task 2 models with cross-field validators
  - Implement mount point conflict detection (prefix overlap)
  - Add priority ordering validation
  - Create `ConfigValidationError` exception

  **TDD Approach**:
  1. Write tests for validator edge cases
  2. Implement validators
  3. Verify all validation scenarios covered

  **Must NOT do**:
  - Don't implement file loading yet
  - Don't add environment variable expansion

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []
  - Reason: Validation logic, clear specifications from RFC

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1
  - **Blocks**: Task 5
  - **Blocked By**: Task 2

  **References**:
  - RFC config/validator.py - validation patterns
  - RFC Section "Configuration Validation" - rules table

  **Acceptance Criteria**:
  - [ ] Test: Overlapping mount points detected
  - [ ] Test: Prefix conflict raises error
  - [ ] Test: Valid non-overlapping mounts pass

  **QA Scenarios**:
  ```
  Scenario: Detect mount point overlap
    Tool: Bash (python)
    Steps:
      1. Create test with mounts at /templates and /templates/subdir
      2. Expect ConfigValidationError
    Expected Result: ValidationError raised with clear message
    Evidence: .sisyphus/evidence/task-3-overlap-detection.txt
  ```

  **Commit**: YES (groups with Task 2)
  - Message: `feat(config): add cross-field validation for mount conflicts`

- [x] **Task 4: Create SessionFileSystemManager skeleton**

  **What to do**:
  - Create `src/mcp_scratchpad/fs/session_manager.py`
  - Implement `SessionFileSystemManager` class skeleton:
    - __init__ with OverlayConfig
    - _initialize_mounts() stub
    - get_session_fs(session_id) stub
    - cleanup_session(session_id) stub
  - Add protocol definition for OverlayFileSystem

  **TDD Approach**:
  1. Write tests for manager instantiation and basic methods
  2. Create skeleton class
  3. Tests pass (stubs return expected types)

  **Must NOT do**:
  - Don't implement actual filesystem logic (Phase 2)
  - Don't add real overlay semantics yet

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []
  - Reason: Class structure, no complex logic yet

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1
  - **Blocks**: Tasks 6-9
  - **Blocked By**: Tasks 2-3

  **References**:
  - RFC fs/session_manager.py - example implementation
  - RFC Section "Session FileSystem Manager" - architecture

  **Acceptance Criteria**:
  - [ ] Test: Manager instantiates with OverlayConfig
  - [ ] Test: get_session_fs returns filesystem instance
  - [ ] Test: cleanup_session removes session
  - [ ] All methods have type hints

  **QA Scenarios**:
  ```
  Scenario: Manager instantiation
    Tool: Bash (python)
    Steps:
      1. from mcp_scratchpad.fs.session_manager import SessionFileSystemManager
      2. from mcp_scratchpad.config.models import OverlayConfig
      3. manager = SessionFileSystemManager(OverlayConfig(mounts=[]))
      4. print(type(manager))
    Expected Result: Shows SessionFileSystemManager type
    Evidence: .sisyphus/evidence/task-4-manager-skeleton.txt
  ```

  **Commit**: YES
  - Message: `feat(fs): add SessionFileSystemManager skeleton`
  - Files: `src/mcp_scratchpad/fs/session_manager.py`, `tests/unit/fs/test_session_manager.py`

- [x] **Task 5: Configuration loader with environment variable support**

  **What to do**:
  - Create `src/mcp_scratchpad/config/loader.py`
  - Implement `load_overlay_config()` function:
    - Search standard config locations
    - Parse YAML files
    - Expand environment variables (${VAR} syntax)
    - Return OverlayConfig instance
  - Add default config generation

  **TDD Approach**:
  1. Write tests for config loading scenarios
  2. Implement loader with env var expansion
  3. Test with actual YAML files in temp directory

  **Must NOT do**:
  - Don't implement credential encryption
  - Don't add hot-reload logic

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []
  - Reason: File I/O, environment handling, error cases

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1
  - **Blocks**: None (independent)
  - **Blocked By**: Task 3

  **References**:
  - RFC config/loader.py - example
  - RFC Section "Configuration Loading"
  - RFC Section "Environment Variable Mapping" - table

  **Acceptance Criteria**:
  - [ ] Test: Load config from YAML file
  - [ ] Test: Expand environment variables (${VAR})
  - [ ] Test: Use default values (${VAR:default})
  - [ ] Test: Search standard locations
  - [ ] Test: Missing file returns default config
  - [ ] Test: Invalid YAML raises clear error

  **QA Scenarios**:
  ```
  Scenario: Load config with env vars
    Tool: Bash (python)
    Steps:
      1. export TEST_MOUNT_PATH=/tmp/test
      2. Create YAML: mounts: [{name: test, source: "file://${TEST_MOUNT_PATH}", mount_point: /test, mode: ro}]
      3. Load config and verify path expanded
    Expected Result: Config has source="file:///tmp/test"
    Evidence: .sisyphus/evidence/task-5-env-expansion.txt
  ```

  **Commit**: YES
  - Message: `feat(config): add YAML config loader with env var expansion`
  - Files: `src/mcp_scratchpad/config/loader.py`, `tests/unit/config/test_loader.py`

#### Wave 2: Core Session Manager

- [x] **Task 6: Session lifecycle management**

  **What to do**:
  - Implement session tracking in SessionFileSystemManager
  - Add session creation with unique ID generation
  - Implement session metadata storage
  - Add session expiration/expiry tracking

  **TDD Approach**:
  1. Write tests for session lifecycle
  2. Implement session tracking dict
  3. Add session metadata dataclass
  4. Verify session creation/retrieval

  **Must NOT do**:
  - Don't implement filesystem operations (Phase 2)
  - Don't add actual MemoryFileSystem yet

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []
  - Reason: State management, lifecycle logic

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Tasks 7-9)
  - **Parallel Group**: Wave 2
  - **Blocks**: Task F1.1, F1.2
  - **Blocked By**: Task 4

  **References**:
  - RFC fs/session_manager.py - session tracking
  - Existing FileSystemStore session handling in storage.py

  **Acceptance Criteria**:
  - [ ] Test: Create new session returns unique ID
  - [ ] Test: Retrieve existing session by ID
  - [ ] Test: Session metadata stored correctly
  - [ ] Test: List active sessions

  **QA Scenarios**:
  ```
  Scenario: Session creation and retrieval
    Tool: Bash (python)
    Steps:
      1. manager.create_session() → returns session_id
      2. manager.get_session(session_id) → returns session
      3. Verify session ID format
    Expected Result: Session created and retrieved successfully
    Evidence: .sisyphus/evidence/task-6-session-lifecycle.txt
  ```

  **Commit**: YES (groups with Tasks 7-9)
  - Message: `feat(fs): implement session lifecycle management`

- [x] **Task 7: Per-session MemoryFileSystem initialization**

  **What to do**:
  - Create per-session MemoryFileSystem instances
  - Initialize session workspace directory structure
  - Integrate with SessionFileSystemManager
  - Add session directory isolation

  **TDD Approach**:
  1. Write tests for MemoryFileSystem creation
  2. Implement per-session filesystem initialization
  3. Test isolation between sessions
  4. Verify write/read in each session

  **Must NOT do**:
  - Don't implement overlay with lower layers yet
  - Don't add shared mounts yet (that's Task 8)

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []
  - Reason: fsspec integration, session isolation

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Tasks 6, 8-9)
  - **Parallel Group**: Wave 2
  - **Blocks**: Task F1.2 (integration tests)
  - **Blocked By**: Task 4

  **References**:
  - RFC fs/session_manager.py:645-653 - MemoryFileSystem initialization
  - fsspec documentation for MemoryFileSystem

  **Acceptance Criteria**:
  - [ ] Test: Each session gets unique MemoryFileSystem
  - [ ] Test: Files written in session A not visible in session B
  - [ ] Test: Session workspace directory auto-created

  **QA Scenarios**:
  ```
  Scenario: Session filesystem isolation
    Tool: Bash (python)
    Steps:
      1. fs_a = manager.get_session_fs("sess_a")
      2. fs_b = manager.get_session_fs("sess_b")
      3. fs_a.write_text("/test.txt", "A")
      4. fs_b.write_text("/test.txt", "B")
      5. Verify fs_a reads "A", fs_b reads "B"
    Expected Result: Sessions are properly isolated
    Evidence: .sisyphus/evidence/task-7-session-isolation.txt
  ```

  **Commit**: YES (groups with Tasks 6, 8-9)

- [x] **Task 8: Shared mount Copy-on-Write support**

  **What to do**:
  - Initialize shared read-only mounts from configuration
  - Implement basic COW detection (file exists in lower?)
  - Add mount priority ordering
  - Test COW file copying to upper layer

  **TDD Approach**:
  1. Write tests for shared mount initialization
  2. Implement mount loading from config
  3. Test COW detection logic
  4. Verify proper layer ordering

  **Must NOT do**:
  - Don't implement full OverlayFileSystem (Phase 2)
  - Don't implement whiteout yet (Phase 2b)

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []
  - Reason: COW logic, mount management

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Tasks 6-7, 9)
  - **Parallel Group**: Wave 2
  - **Blocks**: Phase 2 tasks
  - **Blocked By**: Tasks 2-4

  **References**:
  - RFC Section "Shared Mount COW Support"
  - RFC Technical Design - Multi-layer architecture

  **Acceptance Criteria**:
  - [ ] Test: Shared mounts initialized from config
  - [ ] Test: COW detection works for existing files
  - [ ] Test: Mount priority ordering respected
  - [ ] Test: File copied to upper layer on write

  **QA Scenarios**:
  ```
  Scenario: Basic COW from shared mount
    Tool: Bash (python)
    Steps:
      1. Create local mount with file at /templates/readme.md
      2. Initialize session with this as lower layer
      3. Read file (from lower)
      4. Write to same path (copy to upper)
      5. Verify upper layer has modified copy
    Expected Result: COW works correctly
    Evidence: .sisyphus/evidence/task-8-cow-basic.txt
  ```

  **Commit**: YES (groups with Tasks 6-7, 9)

- [x] **Task 9: Session cleanup and resource management**

  **What to do**:
  - Implement proper session cleanup
  - Close filesystem handles
  - Free memory from MemoryFileSystem
  - Add cleanup on session expiration

  **TDD Approach**:
  1. Write tests for session cleanup
  2. Implement cleanup methods
  3. Test resource freeing
  4. Verify no memory leaks

  **Must NOT do**:
  - Don't implement automatic timeout cleanup (out of scope)
  - Don't add persistence on cleanup

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []
  - Reason: Resource management, cleanup logic

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Tasks 6-8)
  - **Parallel Group**: Wave 2
  - **Blocks**: Task F1.2
  - **Blocked By**: Task 4

  **References**:
  - RFC fs/session_manager.py:655-659 - cleanup_session

  **Acceptance Criteria**:
  - [ ] Test: cleanup_session removes session
  - [ ] Test: Filesystem resources freed
  - [ ] Test: Cannot access session after cleanup

  **QA Scenarios**:
  ```
  Scenario: Session cleanup
    Tool: Bash (python)
    Steps:
      1. session_id = manager.create_session()
      2. manager.cleanup_session(session_id)
      3. Try to access session → expect KeyError
    Expected Result: Session properly cleaned up
    Evidence: .sisyphus/evidence/task-9-cleanup.txt
  ```

  **Commit**: YES (groups with Tasks 6-8)
  - Message: `feat(fs): implement session cleanup and resource management`

#### Wave 3: Cache Foundation

- [x] **Task 10: Directory index cache with TTL**

  **What to do**:
  - Create `src/mcp_scratchpad/fs/cache.py`
  - Implement `DirectoryIndexCache` class:
    - Cache directory listings with TTL
    - Store cache entries with timestamps
    - Implement cache lookup with expiration check
  - Add cache configuration (TTL, max size)

  **TDD Approach**:
  1. Write tests for cache operations
  2. Implement cache with TTL
  3. Test expiration logic
  4. Verify cache hit/miss tracking

  **Must NOT do**:
  - Don't implement event-driven invalidation yet (Task 11)
  - Don't integrate with OverlayFileSystem yet (Phase 2)

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []
  - Reason: Cache logic, expiration handling

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Tasks 11-12)
  - **Parallel Group**: Wave 3
  - **Blocks**: Phase 2b cache integration
  - **Blocked By**: None

  **References**:
  - RFC DEC-8 - Cache implementation
  - RFC config/models.py - cache configuration

  **Acceptance Criteria**:
  - [ ] Test: Cache stores and retrieves directory listings
  - [ ] Test: Expired entries return None
  - [ ] Test: Cache respects TTL configuration
  - [ ] Test: Cache size limits enforced

  **QA Scenarios**:
  ```
  Scenario: Cache with TTL
    Tool: Bash (python)
    Steps:
      1. cache.set("/test", ["file1", "file2"], ttl=1)
      2. cache.get("/test") → returns listing
      3. time.sleep(2)
      4. cache.get("/test") → returns None (expired)
    Expected Result: TTL expiration works
    Evidence: .sisyphus/evidence/task-10-cache-ttl.txt
  ```

  **Commit**: YES (groups with Tasks 11-12)
  - Message: `feat(fs): implement directory index cache with TTL`
  - Files: `src/mcp_scratchpad/fs/cache.py`, `tests/unit/fs/test_cache.py`

- [x] **Task 11: Cache invalidation strategy (hybrid mode)**

  **What to do**:
  - Implement hybrid cache invalidation (TTL + event-driven)
  - Add dirty marking for cache entries
  - Implement _get_affected_paths() for invalidation
  - Add cache flush for specific paths

  **TDD Approach**:
  1. Write tests for invalidation logic
  2. Implement event-driven invalidation
  3. Test hybrid mode (TTL + dirty marking)
  4. Verify affected path calculation

  **Must NOT do**:
  - Don't implement background preloading yet
  - Don't add cache persistence

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []
  - Reason: Invalidation logic, path calculations

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Tasks 10, 12)
  - **Parallel Group**: Wave 3
  - **Blocks**: Phase 2b cache integration
  - **Blocked By**: Task 10

  **References**:
  - RFC DEC-8 - CacheInvalidationStrategy class
  - RFC Security section - cache consistency

  **Acceptance Criteria**:
  - [ ] Test: mark_dirty() invalidates affected paths
  - [ ] Test: Parent directories invalidated on child change
  - [ ] Test: Hybrid mode prefers dirty over TTL
  - [ ] Test: Cache flush clears all entries

  **QA Scenarios**:
  ```
  Scenario: Event-driven invalidation
    Tool: Bash (python)
    Steps:
      1. cache.set("/parent", ["child/"], ttl=60)
      2. cache.invalidate_on_event("write", "/parent/child/file.txt")
      3. cache.get("/parent") → returns None (invalidated)
    Expected Result: Parent directory cache invalidated
    Evidence: .sisyphus/evidence/task-11-invalidation.txt
  ```

  **Commit**: YES (groups with Tasks 10, 12)

- [x] **Task 12: Memory management for cache**

  **What to do**:
  - Implement memory usage estimation
  - Add LRU eviction for memory limit
  - Add cache statistics (hit/miss ratio)
  - Add memory pressure handling

  **TDD Approach**:
  1. Write tests for memory estimation
  2. Implement LRU eviction
  3. Test memory limit enforcement
  4. Verify statistics tracking

  **Must NOT do**:
  - Don't implement complex memory tracking
  - Don't add external dependencies

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []
  - Reason: Memory management, statistics

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Tasks 10-11)
  - **Parallel Group**: Wave 3
  - **Blocks**: None
  - **Blocked By**: Task 10

  **References**:
  - RFC DEC-8 - CacheEntry dataclass

  **Acceptance Criteria**:
  - [ ] Test: Memory usage estimated
  - [ ] Test: LRU eviction removes oldest
  - [ ] Test: Hit/miss statistics tracked

  **QA Scenarios**:
  ```
  Scenario: LRU eviction
    Tool: Bash (python)
    Steps:
      1. Set memory limit to small value
      2. Add many cache entries
      3. Verify oldest entries evicted
    Expected Result: LRU eviction works
    Evidence: .sisyphus/evidence/task-12-lru.txt
  ```

  **Commit**: YES (groups with Tasks 10-11)
  - Message: `feat(fs): add cache memory management and LRU eviction`

#### Phase 1 Final Verification

- [x] **Task F1.1: Unit tests for all Phase 1 components**

  **What to do**:
  - Ensure all Phase 1 components have >90% test coverage
  - Add edge case tests
  - Add error condition tests
  - Verify test isolation

  **TDD Approach**:
  This IS the verification task - no new code, just ensure tests are complete.

  **Must NOT do**:
  - Don't add integration tests (that's F1.2)
  - Don't start Phase 2 code

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: []
  - Reason: Comprehensive test review, coverage analysis

  **Parallelization**:
  - **Can Run In Parallel**: NO (depends on all Phase 1 tasks)
  - **Blocks**: Phase 2 start
  - **Blocked By**: Tasks 1-12

  **Acceptance Criteria**:
  - [ ] Overall line coverage >90%
  - [ ] All unit tests pass
  - [ ] No flaky tests
  - [ ] Test suite runs in < 30 seconds

  **QA Scenarios**:
  ```
  Scenario: Verify test coverage
    Tool: Bash
    Steps:
      1. uv run pytest --cov=src --cov-report=term-missing
      2. Check coverage >= 90%
    Expected Result: Coverage meets threshold
    Evidence: .sisyphus/evidence/task-f11-coverage.txt
  ```

  **Commit**: NO (tests already committed)

- [x] **Task F1.2: Integration tests for SessionManager**

  **What to do**:
  - Add integration tests for SessionFileSystemManager
  - Test session creation → file operations → cleanup flow
  - Test with multiple concurrent sessions
  - Test session isolation end-to-end

  **TDD Approach**:
  Integration tests validate the whole subsystem works together.

  **Must NOT do**:
  - Don't test overlay semantics (Phase 2)
  - Don't add S3 backend tests yet

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []
  - Reason: Integration testing, session flow

  **Parallelization**:
  - **Can Run In Parallel**: NO (must run after all Phase 1 tasks)
  - **Blocks**: Phase 2 start
  - **Blocked By**: Tasks 1-12, F1.1

  **Acceptance Criteria**:
  - [ ] Test: Full session lifecycle (create → use → cleanup)
  - [ ] Test: Concurrent sessions (10+ sessions)
  - [ ] Test: Session isolation (files don't leak)
  - [ ] Test: Resource cleanup (no memory leaks)

  **QA Scenarios**:
  ```
  Scenario: Concurrent session stress
    Tool: Bash (python)
    Steps:
      1. Create 10 sessions concurrently
      2. Each writes unique files
      3. Verify no cross-contamination
      4. Cleanup all sessions
    Expected Result: Sessions properly isolated
    Evidence: .sisyphus/evidence/task-f12-concurrent.txt
  ```

  **Commit**: YES
  - Message: `test(fs): add integration tests for SessionManager`
  - Files: `tests/integration/test_session_manager.py`

### Phase 2: Overlay FS Core (Week 2)

#### Wave 1: Overlay Foundation

- [x] **Task 13: OverlayFileSystem class skeleton**

  **What to do**:
  - Create `src/mcp_scratchpad/fs/overlay.py`
  - Implement `OverlayFileSystem` class extending AbstractFileSystem
  - Add constructor accepting upper and lowers
  - Define protocol = "overlay"

  **TDD Approach**:
  1. Write tests verifying OverlayFileSystem is AbstractFileSystem
  2. Create class with required attributes
  3. Verify instantiation with upper/lower layers

  **Recommended Agent Profile**: `quick`
  **Parallelization**: Wave 1 - Parallel with Tasks 14-16

  **References**: RFC fs/overlay.py - OverlayFileSystem implementation

  **QA Scenarios**:
  ```
  Scenario: OverlayFS instantiation
    Tool: Bash (python)
    Steps:
      1. from fsspec.implementations.memory import MemoryFileSystem
      2. upper = MemoryFileSystem()
      3. lowers = [MemoryFileSystem()]
      4. overlay = OverlayFileSystem(upper, lowers)
      5. print(overlay.protocol)
    Expected Result: protocol == "overlay"
    Evidence: .sisyphus/evidence/task-13-skeleton.txt
  ```

  **Commit**: YES

- [x] **Task 14: Multi-layer path resolution**

  **What to do**:
  - Implement `_resolve(path)` method
  - Check layers in priority order (upper first, then lowers)
  - Return (filesystem, relative_path, layer_index)
  - Handle "not found" case

  **TDD Approach**:
  1. Write tests for path resolution
  2. Implement layer iteration
  3. Test with files in different layers
  4. Verify correct layer identification

  **Recommended Agent Profile**: `deep`
  **Parallelization**: Wave 1 - Parallel with Tasks 13, 15-16

  **References**: RFC fs/overlay.py:702-716

  **Acceptance Criteria**:
  - [ ] Test: File in upper layer resolves to upper
  - [ ] Test: File in lower layer resolves to lower
  - [ ] Test: File in multiple layers resolves to highest priority
  - [ ] Test: Non-existent file returns "not found"

  **Commit**: YES (groups with Tasks 13, 15-16)

- [x] **Task 15: Read operations (ls, exists, isfile, isdir)**

  **What to do**:
  - Implement `ls()`, `exists()`, `isfile()`, `isdir()` methods
  - Merge directory listings from all layers
  - Remove duplicates (highest priority wins)
  - Test with whiteout consideration

  **TDD Approach**:
  1. Write tests for each read operation
  2. Implement merged directory listing
  3. Test edge cases (empty dirs, non-existent)
  4. Verify duplicate handling

  **Recommended Agent Profile**: `unspecified-high`
  **Parallelization**: Wave 1 - Parallel with Tasks 13-14, 16

  **References**: RFC fs/overlay.py:722-776

  **Commit**: YES (groups with Tasks 13-14, 16)

- [x] **Task 16: File info and metadata merging**

  **What to do**:
  - Implement `info()` method
  - Return file metadata from source layer
  - Add layer source indicator (_layer field)
  - Handle directories and files

  **TDD Approach**:
  1. Write tests for info() method
  2. Implement metadata retrieval
  3. Test layer indicator
  4. Verify directory info handling

  **Recommended Agent Profile**: `unspecified-high`
  **Parallelization**: Wave 1 - Parallel with Tasks 13-15

  **References**: RFC fs/overlay.py:758-763

  **Commit**: YES (groups with Tasks 13-15)
  - Message: `feat(fs): implement overlay read operations and path resolution`

#### Wave 2: Write Operations

- [x] **Task 17: Copy-on-Write implementation**

  **What to do**:
  - Implement `_copy_up()` method
  - Copy file from lower layer to upper before write
  - Ensure parent directories exist in upper
  - Handle binary content correctly

  **TDD Approach**:
  1. Write tests for COW behavior
  2. Implement file copying
  3. Test parent directory creation
  4. Verify lower layer unchanged

  **Must NOT do**:
  - Don't implement whiteout (Task 20)

  **Recommended Agent Profile**: `deep`
  **Parallelization**: Wave 2 - Blocks Tasks 18-20

  **References**: RFC fs/overlay.py:791-803

  **Acceptance Criteria**:
  - [ ] Test: File copied to upper on write open
  - [ ] Test: Parent directories created
  - [ ] Test: Lower layer unchanged after COW
  - [ ] Test: Binary content preserved

  **Commit**: YES

- [x] **Task 18: Write file operations**

  **What to do**:
  - Implement `open()` with write modes
  - Handle "w", "a", "+" modes
  - Trigger COW when needed
  - Return file handle from upper layer

  **TDD Approach**:
  1. Write tests for write operations
  2. Implement open() with mode detection
  3. Test COW triggering
  4. Verify writes go to upper layer

  **Recommended Agent Profile**: `unspecified-high`
  **Parallelization**: Wave 2 - Depends on Task 17

  **References**: RFC fs/overlay.py:765-789

  **Commit**: YES (groups with Task 19)

- [x] **Task 19: Directory creation**

  **What to do**:
  - Implement `mkdir()` and `makedirs()`
  - Create directories in upper layer only
  - Handle exist_ok parameter
  - Test recursive creation

  **TDD Approach**:
  1. Write tests for directory creation
  2.Implement mkdir/makedirs
  3. Test recursive and non-recursive
  4. Verify directories in upper only

  **Recommended Agent Profile**: `unspecified-high`
  **Parallelization**: Wave 2 - Parallel with Task 18

  **References**: RFC fs/overlay.py:809-815

  **Commit**: YES (groups with Task 18)

- [x] **Task 20: File deletion with whiteout markers**

  **What to do**:
  - Implement `rm()` with whiteout support
  - Create whiteout marker when deleting lower layer file
  - Handle rm_file() method
  - Test whiteout creation

  **TDD Approach**:
  1. Write tests for deletion and whiteout
  2. Implement _create_whiteout()
  3. Test whiteout in ls() filtering
  4. Verify file appears deleted

  **Must NOT do**:
  - Don't implement full whiteout lifecycle (Phase 2b)
  - Don't handle directory whiteout yet

  **Recommended Agent Profile**: `deep`
  **Parallelization**: Wave 2 - Parallel with Tasks 18-19

  **References**: RFC fs/overlay.py:817-830
  **Acceptance Criteria**: Whiteout created for lower layer files, ls() filters whiteouts

  **Commit**: YES
  - Message: `feat(fs): implement COW, write operations, and basic whiteout`

#### Wave 3: Backend Abstraction

- [x] **Task 21: Local filesystem backend**

  **What to do**:
  - Implement LocalFileSystem backend support
  - Add DirFileSystem wrapper for path prefix
  - Test with local directories
  - Verify file operations work

  **Recommended Agent Profile**: `unspecified-high`
  **Parallelization**: Wave 3

  **Commit**: YES

- [x] **Task 22: S3 backend with fsspec**

  **What to do**:
  - Add S3FileSystem backend support
  - Handle credential configuration
  - Test with moto (mock S3)
  - Verify error handling

  **Recommended Agent Profile**: `unspecified-high`
  **Parallelization**: Wave 3

  **Commit**: YES

- [x] **Task 23: Backend factory and configuration**

  **What to do**:
  - Create filesystem factory
  - Map config to fsspec filesystems
  - Handle backend-specific options
  - Test factory with all backends

  **Recommended Agent Profile**: `quick`
  **Parallelization**: Wave 3

  **Commit**: YES (groups with Tasks 21-22)
  - Message: `feat(fs): add local and S3 backend support with factory`

#### Phase 2 Final Verification

- [x] **Task F2.1: OverlayFS unit tests (all methods)**

  **Verify**: All AbstractFileSystem methods tested, >85% coverage
  **Result**: PASSED - 95% coverage achieved
  **Evidence**: .sisyphus/evidence/task-f21-coverage.txt

- [x] **Task F2.2: COW semantics tests**

  **Verify**: COW works correctly, lower layers unchanged
  **Result**: PASSED - 47 COW-related tests passed
  **Evidence**: .sisyphus/evidence/task-f22-cow.txt

- [x] **Task F2.3: Backend integration tests**

  **Verify**: Local and S3 backends work with overlay
  **Result**: PASSED - 36 tests passed (4 skipped for S3 mocks)
  **Evidence**: .sisyphus/evidence/task-f23-backend.txt

### Phase 2b: Extended Overlay (Week 3)

- [x] **Task 24: Complete whiteout lifecycle** (Deep)
  - Methods: `rmdir()`, `rm(recursive=True)`, `clean_whiteout()`, `is_whited_out()`
  - Evidence: `.sisyphus/evidence/task-24-whiteout-lifecycle.txt`
  
- [x] **Task 25: Whiteout cleanup and stale detection** (Medium)
  - Methods: `find_stale_whiteouts()`, `cleanup_stale_whiteouts()`, `get_whiteout_stats()`
  - Evidence: `.sisyphus/evidence/task-25-whiteout-cleanup.txt`
  
- [x] **Task 26: Edge case: recreate after delete** (Medium)
  - Added `_remove_whiteout()` for file recreation
  - Evidence: `.sisyphus/evidence/task-26-recreate.txt`
  
- [x] **Task 27: Edge case: rename with COW** (Medium)
  - Method: `rename()` with COW semantics
  - Evidence: Implementation verified in overlay.py
  
- [x] **Task 28: Directory whiteout handling** (Medium)
  - Method: `rmdir()` with directory whiteout support
  - Evidence: `.sisyphus/evidence/task-28-dir-whiteout.txt`

**Wave 2 (Performance):**
- [x] **Task 29: Large file streaming support** (Medium)
  - Methods: `cat_file()`, `cat()`, `_cat_file_streaming()`, `size()`, `is_streaming_file()`
  - Threshold: 1MB, Chunk: 64KB, Performance: 0.1ms for 1MB, 1.4ms for 10MB
  - Evidence: `.sisyphus/evidence/task-29-streaming.txt`
  
- [x] **Task 30: Cache performance tuning** (Medium)
  - O(1) lookup, 99.8% performance improvement, 780 bytes/entry
  - Features: Access tracking, cache warming, adaptive TTL
  - Evidence: `.sisyphus/evidence/task-30-cache-tuning.txt`
  
- [x] **Task 31: Memory pressure handling** (Deep)
  - Classes: `MemoryPressureConfig`, `MemoryStats`, `MemoryPressureError`
  - Auto eviction at 90%, warnings at 80%, graceful degradation
  - Evidence: `.sisyphus/evidence/task-31-memory-pressure.txt`

**Wave 3 (Stress Testing):**
- [x] **Task 32: Concurrent session stress tests** (Unspecified-high) ✅
  - Created `tests/stress/test_concurrent_sessions.py` with 50+ concurrent session tests
  - File operations stress test (60% reads, 30% writes, 10% deletes)
  - COW operations during concurrent access
  - Session isolation verification under load
  - Memory stability testing (50, 100, 200 sessions)
  - Evidence: `.sisyphus/evidence/task-32-concurrent-stress.txt`
  
- [x] **Task 33: Performance benchmark suite** (Unspecified-high)
  - 56 benchmark tests using pytest-benchmark
  - All RFC targets exceeded (Read 1MB: 0.124ms, Write 1MB: 0.008ms)
  - Evidence: `.sisyphus/evidence/task-33-benchmarks.txt`

**Phase 2b Verification:**
- [x] **Task F3.1: Whiteout comprehensive tests** (Deep)
  - 218/218 tests pass (100%)
  - All whiteout methods tested: _create_whiteout, _has_whiteout, clean_whiteout, is_whited_out, find_stale_whiteouts, cleanup_stale_whiteouts, rmdir with whiteout
  - Evidence: `.sisyphus/evidence/task-f31-whiteout-tests.txt`
  
- [x] **Task F3.2: Performance benchmark validation** (Unspecified-high)
  - 55 passed, 1 skipped
  - All RFC targets exceeded by 300x-6,000x
  - Evidence: `.sisyphus/evidence/task-f32-benchmark-validation.txt`

### Phase 3: MCP Resources (Week 4)

**Wave 1 (Resource Foundation):**
- [x] **Task 34: FastMCP resource handler registration** (Quick)
  - FastMCP resource decorators configured, 37 tests passing
  - Evidence: `.sisyphus/evidence/task-34-resource-registration.txt`
  
- [x] **Task 35: scratchpad:// URI parser** (Quick)
  - URI parser with UUID validation and path traversal protection
  - 68 tests passing
  - Evidence: `.sisyphus/evidence/task-35-uri-parser.txt`
  
- [x] **Task 36: Resource read handler** (Medium)
  - MIME type detection, text/binary handling, 56 tests, 87% coverage
  - Evidence: `.sisyphus/evidence/task-36-read-handler.txt`

**Wave 2 (Resource Features):**
- [x] **Task 37: Directory resource listing** (Medium)
  - `read_directory_resource()` with pagination, 17 tests, 73 total tests
  - Evidence: `.sisyphus/evidence/task-37-directory-listing.txt`
  
- [x] **Task 38: Large file resource (metadata + preview)** (Medium)
  - Large file preview (>1MB), streaming support, metadata API, 83 tests
  - Evidence: `.sisyphus/evidence/task-38-large-file.txt`
  
- [x] **Task 39: Resource subscription and notifications** (Unspecified-high)
  - ResourceSubscriptionManager with polling, 43 tests
  - Evidence: `.sisyphus/evidence/task-39-subscription.txt`

**Wave 3 (Multi-modal):**
- [x] **Task 40: Client capability detection** (Medium)
  - `ClientCapability` enum, `detect_client_capabilities()`, format negotiation, 57 tests
  - Evidence: `.sisyphus/evidence/task-40-capabilities.txt`
  
- [x] **Task 41: Image resource handler with thumbnails** (Medium)
  - `ImageResource` with PIL thumbnail generation (128x128, 256x256, 512x512), 53 tests
  - Evidence: `.sisyphus/evidence/task-41-image-handler.txt`
  
- [x] **Task 42: Binary file (PDF) resource handler** (Medium)
  - PDF metadata extraction with PyPDF2, Base64 encoding, 32 tests
  - Evidence: `.sisyphus/evidence/task-42-binary-handler.txt`
  
- [x] **Task 43: XML wrapper format for all resources** (Medium)
  - `XMLResourceWrapper`, XML serialization/parsing, validation, 37 tests
  - Evidence: `.sisyphus/evidence/task-43-xml-wrapper.txt`

**Phase 3 Verification:**
- [x] **Task F4.1: Resource handler tests** (Unspecified-high)
  - 63 new tests added, coverage >80% for all handlers, 574 tests passing
  - Evidence: `.sisyphus/evidence/task-f41-handler-tests.txt`
  
- [x] **Task F4.2: Multi-modal tests** (Unspecified-high)
  - 96+ multimodal tests, coverage >85% for capabilities, image, binary, XML wrapper
  - Evidence: `.sisyphus/evidence/task-f42-multimodal-tests.txt`
  
- [x] **Task F4.3: E2E resource tests** (Unspecified-high)
  - 28 E2E integration tests in `tests/integration/test_resource_e2e.py`
  - Evidence: `.sisyphus/evidence/task-f43-e2e-tests.txt`

### Phase 4: Integration & Security (Week 4-5)

**Wave 1 (Security):**
- [x] **Task 44: Path traversal protection** (Deep)
- [x] **Task 45: Session isolation validation** (Medium)
- [x] **Task 46: Credential security (masking in logs)** (Medium)
- [ ] **Task 47: Resource limit enforcement** (Medium)

**Wave 2 (Backward Compatibility):**
- [ ] **Task 48: Tool API adapter layer** (Medium)
- [ ] **Task 49: Existing FileSystemStore compatibility** (Medium)
- [ ] **Task 50: Migration verification tests** (Unspecified-high)

**Phase 4 Verification:**
- [ ] **Task F5.1: Security audit tests** (Deep)
- [ ] **Task F5.2: Backward compatibility tests** (Unspecified-high)

### Phase 5: Release Preparation (Week 5)

**Wave 1 (Documentation & Benchmarks):**
- [ ] **Task 51: API documentation** (Writing)
- [ ] **Task 52: Migration guide** (Writing)
- [ ] **Task 53: Security guide** (Writing)
- [ ] **Task 54: Performance benchmark report** (Unspecified-high)

**Wave 2 (Release):**
- [ ] **Task 55: CHANGELOG with breaking changes** (Writing)
- [ ] **Task 56: Feature flag implementation** (Quick)
- [ ] **Task 57: Final release preparation** (Unspecified-high)

**Phase 5 Verification:**
- [ ] **Task F6.1: Plan compliance audit** (Oracle)
- [ ] **Task F6.2: Code quality review** (Unspecified-high)
- [ ] **Task F6.3: Security review checklist** (Deep)
- [ ] **Task F6.4: Performance benchmark final validation** (Unspecified-high)

---

## Final Verification Wave (MANDATORY)

> 4 review agents run in PARALLEL. ALL must APPROVE.
> Wait for explicit user okay before marking complete.

- [ ] **F1. Plan Compliance Audit** - `oracle`
  Read the plan end-to-end. For each "Must Have": verify implementation exists. For each "Must NOT Have": search codebase for forbidden patterns. Compare deliverables against plan.
  Output: `Must Have [N/N] | Must NOT Have [N/N] | Tasks [N/N] | VERDICT: APPROVE/REJECT`

- [ ] **F2. Code Quality Review** - `unspecified-high`
  Run `tsc --noEmit` + linter + `bun test`. Review all changed files for: `as any`/`@ts-ignore`, empty catches, console.log in prod, unused imports. Check AI slop patterns.
  Output: `Build [PASS/FAIL] | Lint [PASS/FAIL] | Tests [N pass/N fail] | Files [N clean/N issues] | VERDICT`

- [ ] **F3. Security Review** - `unspecified-high`
  Verify path traversal protection, session isolation, credential masking. Run security test suite. Check for hardcoded secrets.
  Output: `Security Tests [N/N pass] | Path Traversal [PASS/FAIL] | Isolation [PASS/FAIL] | VERDICT`

- [ ] **F4. Performance Validation** - `deep`
  Run full benchmark suite. Verify: Read 1MB < 50ms, Write 1MB < 50ms, List 1000 files < 100ms, 100 concurrent sessions stable.
  Output: `Benchmarks [N/N pass] | Memory [STABLE/LEAK] | Concurrency [PASS/FAIL] | VERDICT`

**Wait for user explicit "okay" before completing.**

---

## Commit Strategy

**Phase 1**:
- Task 1: `deps: add fsspec>=2024.1.0 and s3fs dependencies`
- Task 2-3: `feat(config): add MountConfig and OverlayConfig with validation`
- Task 4: `feat(fs): add SessionFileSystemManager skeleton`
- Task 5: `feat(config): add YAML config loader with env var expansion`
- Tasks 6-9: `feat(fs): implement session lifecycle and COW support`
- Tasks 10-12: `feat(fs): implement directory index cache`
- Task F1.2: `test(fs): add integration tests for SessionManager`

**Phase 2**:
- Tasks 13-16: `feat(fs): implement overlay filesystem skeleton and read operations`
- Tasks 17-20: `feat(fs): implement COW, write operations, and basic whiteout`
- Tasks 21-23: `feat(fs): add local and S3 backend support`
- Tasks F2.1-F2.3: `test(fs): add overlay filesystem and backend tests`

**Phase 2b**:
- Tasks 24-28: `feat(fs): complete whiteout lifecycle and edge cases`
- Tasks 29-31: `feat(fs): add large file streaming and cache tuning`
- Tasks 32-33: `test(fs): add stress tests and benchmarks`

**Phase 3**:
- Tasks 34-36: `feat(resources): implement MCP resource handlers`
- Tasks 37-39: `feat(resources): add directory listing and subscriptions`
- Tasks 40-43: `feat(resources): add multi-modal support`
- Tasks F4.1-F4.3: `test(resources): add comprehensive resource tests`

**Phase 4**:
- Tasks 44-47: `feat(security): implement path validation and isolation`
- Tasks 48-50: `feat(integration): add backward compatibility layer`
- Tasks F5.1-F5.2: `test(integration): add security and compatibility tests`

**Phase 5**:
- Tasks 51-53: `docs: add API, migration, and security documentation`
- Task 54: `docs: add performance benchmark report`
- Task 55: `docs: add CHANGELOG with breaking changes`
- Task 56: `feat: add feature flag for overlay filesystem`
- Tasks F6.1-F6.4: Final verification

---

## Success Criteria

### Verification Commands

```bash
# Run all tests
cd /packages/mcp-scratchpad
uv run pytest --cov=src --cov-report=term-missing

# Run specific test suites
uv run pytest tests/unit/ -v
uv run pytest tests/integration/ -v
uv run pytest tests/e2e/ -v
uv run pytest tests/security/ -v

# Run benchmarks
uv run pytest tests/performance/ -v --benchmark-only

# Security audit
uv run pytest tests/security/test_path_traversal.py -v
uv run pytest tests/security/test_session_isolation.py -v

# Check coverage
uv run pytest --cov=src --cov-report=html
# Open htmlcov/index.html and verify >= 85%
```

### Final Checklist

- [ ] All "Must Have" present and tested
- [ ] All "Must NOT Have" absent from codebase
- [ ] Test coverage >= 85% for all new code
- [ ] All performance benchmarks meet RFC targets
- [ ] Security review passed (all checklist items)
- [ ] Backward compatibility verified
- [ ] Documentation complete (API, migration, security)
- [ ] CHANGELOG updated with breaking changes
- [ ] Feature flag implemented for safe rollout


