# Publish Memory Design

> Status: Draft for implementation approval
> Date: 2026-04-07
> Branch: `overlay-fs-integration-spec`
> Scope: Add explicit shared-memory publish path on top of session overlay filesystem

## 1. Problem Summary

Current overlay filesystem behavior is session-scoped:

1. All file tools operate against the session-visible overlay view.
2. All writes land in the session `upper layer`.
3. Shared `lower layers` are readable but not directly mutated by normal tools.

This is correct for isolation, but it leaves a gap:

1. A session can produce valuable working outputs such as summaries, extracted facts, or user preferences.
2. Other sessions should be able to read those outputs as shared memory.
3. We do not want to break overlay semantics by making ordinary `write/edit/patch/remove` mutate `lower`.

We therefore need an explicit publish path that promotes selected session outputs into a shared memory backend.

## 2. Design Goals

1. Preserve current session overlay semantics.
2. Keep normal file tools session-local.
3. Introduce a clear and explicit “publish” action for shared memory.
4. Support both `file://` and `s3://` backends behind one publish interface.
5. Make published memory visible to all sessions through existing lower mounts.
6. Keep namespace, path, and overwrite behavior deterministic and auditable.

## 3. Non-Goals

1. Real-time collaborative shared upper layers.
2. Direct lower-layer mutation through existing file tools.
3. Automatic background promotion of all session outputs.
4. New vector retrieval, semantic indexing, or ranking logic.
5. Cross-region distributed consistency guarantees beyond backend behavior.

## 4. Recommended Approach

Adopt an explicit `publish_memory` service and tool.

This tool:

1. Reads a source file from the current session-visible overlay view.
2. Validates a target namespace and target key.
3. Resolves the namespace to a configured shared memory backend.
4. Writes the content into the backend’s real persistent storage.
5. Returns canonical metadata for the published shared file.

This approach is preferred over extending `write/edit/patch/remove` because it keeps:

1. Working memory and shared memory separate.
2. Overlay semantics stable.
3. Permission and governance logic concentrated in one place.

## 5. Target Architecture

## 5.1 Separation of Concerns

The architecture is split into three planes:

1. Session working plane
   - existing overlay filesystem
   - current session `upper layer`
   - normal file tools

2. Publish plane
   - new `publish_memory` tool
   - namespace validation
   - backend resolution
   - overwrite and metadata policy

3. Shared memory plane
   - real persistent backend
   - local filesystem (`file://`) or object storage (`s3://`)
   - mounted back into sessions as read-only lower layers

## 5.2 Publish Flow

Logical flow:

1. User or agent creates a session-local artifact, for example `/workspace/summary.md`.
2. `publish_memory` reads that file from the session overlay view.
3. `publish_memory` writes the content to shared backend storage.
4. Shared backend content becomes visible through a lower mount such as `/memory/users/...`.
5. Other sessions can `list/read` the published file.
6. If another session modifies the published file, copy-on-write creates a private upper copy in that session.

## 6. Namespace Model

## 6.1 Root Mount

Introduce one logical shared memory root:

1. `/memory`

This root is populated by one or more lower mounts backed by `file://` or `s3://`.

## 6.2 Namespaces

Supported initial namespaces:

1. `shared`
2. `users`
3. `agents`
4. `teams`

These map to logical paths:

1. `/memory/shared/...`
2. `/memory/users/...`
3. `/memory/agents/...`
4. `/memory/teams/...`

## 6.3 Why Namespaces Matter

Namespaces are required to:

1. prevent arbitrary free-form writes into the shared area
2. enable permission policy per namespace
3. make retention and indexing manageable
4. keep path ownership and semantics obvious

## 6.4 Why These Four Namespaces

The initial namespace set is intentionally small:

1. `shared`
2. `users`
3. `agents`
4. `teams`

The purpose of this split is to answer one core question clearly:

1. who owns this memory
2. who should normally consume it
3. who should eventually have authority to publish or overwrite it

### `shared`

`shared` is the global public memory layer.

Use it for:

1. common rules
2. product terminology
3. reusable summaries
4. global FAQs
5. public prompt or workflow references

Why it exists:

1. some shared memory has no natural user, agent, or team owner
2. forcing these records into another namespace would blur ownership semantics

### `users`

`users` is the user-centered memory layer.

Use it for:

1. user profile summaries
2. user preferences
3. stable user facts
4. user-specific historical summaries

Why it exists:

1. user memory is distinct from agent memory
2. it gives us a clean future permission boundary based on user identity
3. it keeps “memory about the subject being served” separate from execution state

### `agents`

`agents` is the execution-identity memory layer.

Use it for:

1. agent-specific history
2. long-running agent context
3. agent-specific derived working knowledge worth retaining
4. reusable agent summaries that do not belong to a specific user

Why it exists:

1. agents may span many users and sessions
2. agent operating context should not be mixed into user profiles
3. it creates a future-ready boundary for agent-scoped permissions and retention

### `teams`

`teams` is the organizational shared memory layer.

Use it for:

1. project context
2. team policies
3. tenant-level background
4. shared collaboration notes
5. group-owned memory that is not globally public

Why it exists:

1. many shared records belong to an organization, not to an individual user or agent
2. it provides a clean multi-tenant boundary
3. it avoids overloading `shared` with content that should only be visible within a team or project group

## 6.5 Why Not Fewer or More Namespaces in V1

Why not fewer:

1. collapsing everything into `shared` and `users` would mix agent state and team context into the wrong ownership buckets
2. that would make permission, retention, and indexing harder later

Why not more:

1. adding first-class namespaces like `projects`, `tenants`, or `sessions` too early increases complexity without enough benefit
2. most of those can be represented as subpaths under `teams` or `agents` in v1

Recommendation:

1. keep the top-level namespace set small and stable
2. express finer semantics in deeper path structure

Examples:

1. `/memory/users/user-42/profile.md`
2. `/memory/agents/research-bot/history/2026-04-08.md`
3. `/memory/teams/team-a/projects/project-x/context.md`

## 7. Tool Contract

## 7.1 Proposed Tool Signature

```python
publish_memory(
    session_id: str,
    source_path: str,
    target_namespace: str,
    target_key: str,
    overwrite: bool = False,
    content_type: str | None = None,
    metadata: dict[str, Any] | None = None,
)
```

## 7.2 Parameter Semantics

### `session_id`

Identifies which session overlay view to read from.

### `source_path`

The source file path in the current session view, for example:

1. `/workspace/summary.md`
2. `/workspace/facts/user.json`

### `target_namespace`

Must be one of the configured supported namespaces:

1. `shared`
2. `users`
3. `agents`
4. `teams`

### `target_key`

The relative path within the namespace, for example:

1. `user-42/profile.md`
2. `research-bot/projects/project-x/summary.json`

### `overwrite`

Controls whether an existing shared artifact may be replaced.

Default should be `False`.

### `content_type`

Optional content hint for metadata or future downstream processing.

Examples:

1. `text/markdown`
2. `application/json`

### `metadata`

Optional structured metadata to persist alongside the published content.

Examples:

1. `source_agent`
2. `source_user`
3. `labels`
4. `summary`
5. `published_at`

## 7.3 Return Shape

The tool should return structured metadata like:

```json
{
  "session_id": "abc",
  "source_path": "/workspace/summary.md",
  "target_namespace": "users",
  "target_key": "user-42/summary.md",
  "shared_path": "/memory/users/user-42/summary.md",
  "backend_uri": "file:///shared-memory/users/user-42/summary.md",
  "content_type": "text/markdown",
  "published": true,
  "overwrote_existing": false
}
```

## 8. Backend Model

## 8.1 Supported Backends

Initial supported backends:

1. Local filesystem via `file://`
2. Object storage via `s3://`

## 8.2 Backend Abstraction

Add a dedicated backend-facing abstraction, for example:

1. `SharedMemoryPublisher`
2. `SharedMemoryBackend`

Responsibility:

1. map namespace to backend
2. resolve final backend target path
3. write content
4. optionally write metadata sidecar
5. report whether target already existed

## 8.3 Why Not Write Through Overlay Lower Directly

We should not attempt to mutate the `lower` overlay view itself because:

1. `lower` is a resolved read-only view, not a publish API
2. direct lower mutation would blur overlay semantics
3. file and s3 backends have different write mechanics
4. publish policy should remain separate from normal editing semantics

Therefore, “publish to lower” is implemented as:

1. write to the lower mount’s real storage source
2. let lower mounts expose that data back into sessions

## 9. Data Model and Layout

## 9.1 Recommended Shared Layout

```text
/memory/
  shared/
  users/
  agents/
  teams/
```

Recommended sub-layout examples:

```text
/memory/users/<user_id>/
  profile.md
  preferences.json
  facts/
  summaries/

/memory/agents/<agent_id>/
  profile.md
  history/
  projects/

/memory/teams/<team_id>/
  context.md
  policies.json
  projects/
```

## 9.2 Metadata Storage

Two acceptable initial options:

1. Sidecar metadata files such as `<filename>.meta.json`
2. Minimal metadata only in tool response, with richer metadata postponed

Recommendation:

Start with sidecar JSON metadata for published artifacts because it keeps:

1. backend portability
2. auditability
3. future indexing options

## 10. Detailed Runtime Behavior

## 10.1 Publish Path Resolution

At publish time:

1. normalize `source_path`
2. read source content from session overlay using the unified adapter
3. normalize `target_key`
4. validate target namespace
5. compute shared logical path `/memory/<namespace>/<target_key>`
6. resolve backend destination URI/path
7. check existence and overwrite policy
8. write content
9. optionally write metadata sidecar
10. return canonical published metadata

## 10.2 Visibility After Publish

After successful publish:

1. new sessions should always see the new shared file
2. existing sessions should see it subject to backend listing/cache behavior
3. direct reads to the fully resolved path should work as soon as backend consistency allows

## 10.3 Consumption by Other Sessions

Other sessions interact with published memory normally:

1. `list` sees `/memory/...`
2. `read` reads lower-backed shared memory
3. `edit/write/patch` on that path triggers copy-on-write into the current session upper

That means:

1. shared memory stays a shared read baseline
2. every further mutation remains session-local unless republished

## 11. Permission and Policy Model

## 11.1 Write Policy

Initial policy should be conservative:

1. only allow publish into known namespaces
2. reject path traversal and absolute `target_key`
3. default to `overwrite=False`
4. require explicit overwrite opt-in

## 11.2 Namespace Ownership

Future-ready ownership rules:

1. `users` namespace may require a matching or permitted user identity
2. `agents` namespace may require the current agent identity
3. `teams` namespace may require team-scoped authorization

For the first implementation, identity may be carried through optional metadata if the runtime does not yet have a stronger auth model.

## 11.3 Why Governance Belongs Here

This is the correct place for governance because:

1. it is the one path that writes shared memory
2. normal file tools remain free of shared-write logic
3. auditability becomes much easier

## 12. Failure Semantics

`publish_memory` should fail atomically from the caller’s point of view.

## 12.1 Failure Cases

1. `session_id` not found
2. `source_path` not found in session view
3. invalid namespace
4. invalid target key
5. target exists and overwrite is false
6. backend write failure
7. metadata sidecar write failure

## 12.2 Recommended Semantics

1. no partial success should be reported
2. if content write succeeds but metadata write fails, either:
   - roll back content if backend makes rollback practical, or
   - return explicit partial-failure state with strong logging

Recommendation:

For the first implementation, prefer:

1. write content
2. write metadata
3. if metadata write fails:
   - log a hard error
   - return failure
   - best-effort cleanup content for `file://`
   - document weaker cleanup guarantees for `s3://`

## 13. Caching and Consistency

## 13.1 File Backend

For `file://`:

1. newly written files are usually visible immediately at the storage layer
2. session visibility still depends on directory listing cache behavior

## 13.2 S3 Backend

For `s3://`:

1. visibility depends on object store consistency semantics
2. mount listing cache can delay discovery

## 13.3 Configuration Guidance

For shared memory mounts:

1. use shorter `listings_expiry_time`
2. consider disabling listing cache for highly dynamic memory areas

This is particularly important if publish operations are expected to be observed quickly by other sessions.

## 14. Alternatives Considered

## 14.1 Extend Existing Write Tool

Rejected because:

1. it mixes working writes with shared writes
2. it breaks clear session-local semantics
3. it complicates permissions and rollback

## 14.2 Background Sync Without Explicit Publish

Rejected for now because:

1. it removes user/agent intent
2. it creates ambiguous promotion rules
3. it makes debugging and auditability worse

## 14.3 Shared Writable Upper Layer

Rejected because:

1. it conflicts with session isolation
2. it turns the system into a collaborative multi-writer filesystem
3. conflict semantics become substantially harder

## 15. Implementation Breakdown

Recommended work breakdown:

1. add shared memory mount conventions in config/docs
2. add namespace resolution configuration
3. build shared backend publisher abstraction
4. add `publish_memory` service layer
5. register `publish_memory` tool
6. add metadata sidecar support
7. add tests for file backend
8. add tests for s3 backend
9. document visibility and cache behavior

## 16. Testing Strategy

## 16.1 Unit Tests

1. namespace validation
2. target key normalization
3. overwrite policy
4. backend path resolution
5. file publisher writes content and metadata correctly
6. s3 publisher request shaping

## 16.2 Integration Tests

1. publish from session file to shared file backend
2. another session can read published memory
3. editing published memory in another session copy-ups into upper
4. overwrite false rejects existing target
5. overwrite true replaces target deterministically

## 16.3 Error Tests

1. missing source file
2. invalid namespace
3. traversal in `target_key`
4. backend failure during content write
5. backend failure during metadata write

## 17. Observability

Recommended logging and metrics:

1. publish success count by namespace
2. publish failure count by reason
3. overwrite attempts and approvals
4. backend latency by backend type
5. shared memory visibility lag if measured in integration tests

## 18. Open Decisions

These remain explicit follow-up design choices:

1. whether metadata sidecar is mandatory in v1
2. whether identity checks are enforced in v1 or deferred
3. whether publish should support binary payloads in v1
4. whether publish should support directory promotion or file-only in v1

Recommendation:

Keep v1 minimal:

1. file-only publish
2. text-first support, binary allowed if transport already supports bytes safely
3. sidecar metadata included
4. identity policy lightweight but path/namespace policy strict

## 19. Final Recommendation

Implement `publish_memory` as a dedicated publish path, not as an extension of ordinary file tools.

This preserves the current architecture:

1. session upper remains working memory
2. shared lower remains published baseline memory
3. published files are consumed read-first and modified via copy-on-write

This design is the cleanest way to add cross-session shared memory without breaking the overlay filesystem model.
