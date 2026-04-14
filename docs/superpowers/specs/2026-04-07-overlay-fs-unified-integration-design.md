# Overlay FS Unified Integration Design

> Status: Draft for implementation approval
> Date: 2026-04-07
> Branch: `spec/overlay-fs-integration`
> Scope: Full alignment to RFC-0001 target architecture with controlled breaking changes

## 1. Problem Summary

Current behavior has parallel data paths:

1. Tools primarily read/write via `FileSystemStore` (disk session directory).
2. Resources primarily read via `SessionFileSystemManager.get_session_fs(session_id)`.
3. URI formats are inconsistent (`scratchpad:///path` vs `scratchpad://{session_id}/{path}`).
4. `edit`/`patch` are not fully session-aware and can bypass unified semantics.
5. Subscription monitoring observes session manager filesystem, while some writes occur outside that view.

Result: features exist, but the end-to-end model is not a single coherent session filesystem.

## 2. Design Goals

1. Single source of truth for session filesystem view.
2. Full tool/resource behavioral consistency.
3. Standardized URI model.
4. Event-driven resource update notifications with polling fallback.
5. Controlled migration with rollback, observability, and compatibility window.
6. Keep safety requirements: path isolation, session isolation, permission semantics, auditability.

## 3. Non-Goals

1. New product-level UI features.
2. New external storage providers beyond existing supported schemes.
3. Automatic migration of historical legacy metadata formats beyond compatibility window.

## 4. Target Architecture

## 4.1 Runtime Ownership

1. `ScratchpadServer` initializes one `SessionFileSystemManager` with validated `OverlayConfig`.
2. `SessionFileSystemManager` owns mount backend instances and session lifecycle.
3. `SessionFileSystemManager.get_session_fs(session_id)` returns a true session-scoped `OverlayFileSystem` view:
   - upper layer: per-session writable workspace backend (memory/local per config)
   - lower layers: configured shared/read-only mounts
4. Tools and resources both consume this same session filesystem via a shared adapter layer.

## 4.2 Access Path Unification

Unified logical path:

1. request (`tool` or `resource`)
2. session resolution (`session_id` required or deterministic default policy)
3. filesystem adapter (`UnifiedSessionFSAdapter`)
4. overlay filesystem operations
5. metadata normalization (`path`, `uri`, `layer`, `version`, `permission`, `timestamps`)
6. response serialization (tool XML wrapper / resource format)

No direct file writes via raw `open(path, "w")` outside adapter.

## 4.3 URI Standard

Canonical URI:

1. `scratchpad://{session_id}/{path}`

Compatibility handling:

1. Read path parser accepts legacy `scratchpad:///...` for compatibility window.
2. All newly emitted URIs from tools/resources use canonical format.
3. Deprecation warnings emitted for legacy URI usage.

## 5. API and Behavior Changes

## 5.1 Tool Contract Changes

Mandatory session-aware contract:

1. `list`, `read`, `write`, `remove`, `edit`, `multiedit`, `patch` all operate in explicit session context.
2. `edit` and `patch` add `session_id` parameter (breaking change allowed, with compat window policy).
3. `patch` no longer writes directly by raw file path; it writes through unified adapter.
4. Tool responses include consistent metadata fields:
   - `session_id`
   - `path` (session-relative)
   - `uri` (canonical)
   - `layer` (`upper`, `lower_n`, or derived unified label)
   - `version`
   - `permission`

## 5.2 Resource Contract Changes

1. Register file resource and directory resource by default.
2. Directory listing supports pagination limits from config.
3. Large file behavior returns metadata + preview + access method hints.
4. Resource response metadata fields align with tool metadata model.

## 5.3 Capability Negotiation

1. Resource entrypoint computes client capabilities from request context.
2. Output format selection:
   - multimodal native when supported
   - XML/text fallback with embedded canonical URI when not supported
3. Config overrides remain available for client-specific behavior.

## 5.4 Subscription Semantics

1. Event-driven notifications are primary trigger (`resource_changed`).
2. Polling remains fallback for non-tool external mutations.
3. Subscription info remains queryable from resource metadata path.
4. Session cleanup includes subscription cleanup for that session.

## 6. Storage and Metadata Strategy

## 6.1 Role of FileSystemStore

Transition strategy:

1. Move `FileSystemStore` from primary write plane to compatibility/bridge responsibilities.
2. During migration window, optional dual-write mode keeps legacy store updated.
3. After migration completion, disable legacy write path by feature flag.

## 6.2 Version and Permission Model

1. Version increments must be centralized in unified adapter.
2. Permission checks must be performed before writes/deletes, regardless of caller (tool/resource internal path).
3. Metadata persistence backend should be deterministic and session-scoped.

## 7. Migration and Rollback Plan

## 7.1 Feature Flags

Required flags:

1. `FEATURE_UNIFIED_OVERLAY_FS`
2. `FEATURE_CANONICAL_URI_ONLY`
3. `FEATURE_EVENT_DRIVEN_SUBSCRIPTIONS`
4. `FEATURE_DUAL_WRITE_LEGACY_STORE`

## 7.2 Rollout Stages

1. Stage 0: dark launch (new path disabled, instrumentation only)
2. Stage 1: shadow mode (dual-read/dual-write sample comparison)
3. Stage 2: primary new path + legacy fallback enabled
4. Stage 3: canonical URI enforcement + remove legacy emissions
5. Stage 4: disable legacy store write path

## 7.3 Rollback Rules

1. Rollback is config-level toggle, no emergency code patch required.
2. On consistency regression above threshold, switch to previous stable stage.
3. Preserve data visibility guarantees during rollback.

## 8. Security and Isolation Requirements

1. Session boundary enforcement must apply to all tools/resources uniformly.
2. Path traversal checks remain centralized in resolver/adapter.
3. Cross-session URI access denied unless explicitly designed and authorized.
4. Audit log should include tool/resource operation parity fields.

## 9. Test Strategy (Must Pass)

## 9.1 Unit Tests

1. Session manager returns overlay FS with configured layers.
2. Adapter normalization of metadata and canonical URI.
3. Legacy URI parser compatibility behavior.
4. `edit` and `patch` session enforcement and version semantics.

## 9.2 Integration Tests

1. Tool write -> Resource read consistency (same session).
2. Tool edit/patch -> Resource read consistency.
3. Directory resource pagination correctness.
4. Capability negotiation output switching.

## 9.3 E2E Tests

1. Subscription scenario: subscribe -> tool write -> notification delivered.
2. Session cleanup: tools/resources/subscriptions/caches all invalidated.
3. Multi-session isolation with shared lower mounts + COW behavior.
4. Rollback drill across feature-flag stages.

## 9.4 Performance and Reliability

1. Baseline latency targets compared before/after unification.
2. 100+ concurrent sessions stress run.
3. Memory and cache behavior under large-file + multimodal mix.

## 10. Observability and Acceptance Metrics

Required metrics:

1. Cross-path consistency mismatch rate (tool vs resource read)
2. Notification delivery success rate
3. Canonical URI adoption rate
4. Session cleanup residue count
5. P95/P99 tool and resource latency

Acceptance gate for production:

1. Consistency mismatch rate: 0 in controlled test corpus
2. Regression suite pass: 100%
3. Notification delivery success: >= 99.9% in staging load profile
4. No critical security regression findings

## 11. Implementation Work Breakdown (High Level)

1. Build `UnifiedSessionFSAdapter` and route tools/resources through it.
2. Update session manager to return true overlay FS instances.
3. Normalize URI/path metadata API.
4. Migrate edit/patch to session-aware adapter writes.
5. Register directory resources and pagination defaults.
6. Wire capability negotiation into resource entrypoint.
7. Wire event bus into write/delete/edit/patch paths and subscription manager.
8. Add feature flags and staged rollout controls.
9. Add compatibility window and deprecation logging.
10. Complete full test matrix and rollout playbook.

## 12. Risks and Mitigations

1. Risk: Hidden behavioral dependency on `FileSystemStore` path layout.
   Mitigation: staged dual-write and compatibility checks before cutover.
2. Risk: Subscription noise or dropped events under burst updates.
   Mitigation: event debouncing + polling fallback + delivery metrics.
3. Risk: Performance regression in merged directory listing.
   Mitigation: cache tuning and targeted benchmarks before stage advancement.
4. Risk: Breaking API friction for clients.
   Mitigation: explicit compatibility window + clear deprecation schedule.

## 13. Deprecation Schedule (Proposed)

1. Release N: canonical URI emitted, legacy URI accepted with warning.
2. Release N+1: legacy URI support behind compatibility flag default-off.
3. Release N+2: legacy URI parser path removed.

## 14. Open Decisions (Need confirmation during implementation planning)

1. Default behavior when `session_id` omitted on mutating tools.
2. Exact version metadata storage backend after full cutover.
3. Whether dual-write remains optional in self-hosted minimal deployments.

## 15. Approval

This spec is ready for implementation planning once reviewed and approved.
