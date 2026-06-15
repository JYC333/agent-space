# Security and Access Boundaries

This document records the durable access control principles for the agent-space backend.
It covers authentication boundaries, space isolation, object visibility, session and task
policy, activity policy, proposal/memory governance, intentional cross-space exceptions,
credential secrecy, path safety, and current dogfooding readiness.

---

## 1. Authentication Boundary

All durable-data API routes require authentication via `get_identity()` or
`get_current_user()`. An unauthenticated request to any such route must return 401.

### Intentional public endpoints

| Endpoint | Rationale |
|---|---|
| `GET /health` | Health probe for load balancers and monitoring |
| `GET /api/v1/features` | Frontend feature-gating bootstrap |
| `GET /api/v1/auth/google-configured` | OAuth login flow bootstrap (boolean only) |
| `GET /auth/google` | OAuth redirect initiation |
| `GET /auth/google/callback` | OAuth callback; CSRF state validated by cookie |
| `POST /auth/logout` | Cookie deletion only; no secret access |

All other routes, including system-metadata endpoints, are auth-gated:

- `GET /capabilities`, `GET /capabilities/{id}`, `POST /capabilities/reload`
- `GET /jobs/handlers`
- `GET /workspace-console/runtimes`
- `GET /runtime-tools...`, `POST /runtime-tools/{runtime}/install`, `POST /runtime-tools/{runtime}/activate`
- `GET /providers/litellm-providers`, `/providers/catalog`

---

## 2. Space Isolation

Durable objects are scoped by `space_id`. All service queries that look up objects by ID
must include a `space_id` filter. A cross-space lookup must return 404 — not 403 — so
the response does not reveal whether an object exists in another space.

Rules:
- Raw `Model.id == id` queries without a `space_id` filter are forbidden in authenticated
  service methods.
- Space_id comes from `get_identity()`, not from a request body field or a fetched object.
- User-space authority comes from `SpaceMembership`. `User.space_id`,
  `User.default_space_id`, and global `User.role` are not part of the backend
  schema.
- Cross-space access fails closed (404) unless the route is an intentional exception
  documented in section 8.

---

## 3. Object Visibility

The visibility values `private`, `restricted`, and `space_shared` are enforced by
`can_read_scoped_object()` (`visibility/auth.py`). Unknown visibility values fail closed
(return False). Enforcement must be applied at:

- list endpoints
- detail endpoints
- sub-resource endpoints (runs, artifacts, proposals attached to a parent object)
- export endpoints
- mutation endpoints (PATCH, DELETE)
- consolidation / process endpoints

Denials return 404 ("not found"), not 403 ("forbidden"). This is the correct fail-closed,
no-oracle behavior — the caller cannot distinguish "not found" from "not permitted."

`private` objects are accessible only to their `owner_user_id` (or `instructed_by_user_id`
for runs). `restricted` objects behave like private for same-space non-owners. `space_shared`
objects are accessible to all authenticated members of the same space.

---

## 4. Session Access Policy

Sessions are user-owned within a space.

- `GET /sessions/{id}` requires authentication. `space_id` and `user_id` are extracted from
  the request identity and forwarded to `SessionService.get_session()` as SQL filters.
- `GET /sessions/{id}/messages` follows the same pattern.
- A cross-space request returns 404 (session not found in that space).
- A same-space non-owner request returns 404 (session belongs to a different user).
- An unauthorized request must not return any message content.

Enforcement is at the SQL query layer: `Session.space_id == space_id` and
`Session.user_id == user_id` are both applied as WHERE-clause filters.

---

## 5. Task Access Policy

Tasks enforce visibility on all read, mutation, and sub-resource paths.

- `GET /tasks` and `GET /tasks/{id}`: visibility enforced via `_can_read_task()`.
- `PATCH /tasks/{id}` and `POST /tasks/{id}/runs`: visibility enforced before mutation.
- Sub-resource endpoints (`GET /tasks/{id}/runs`, `/artifacts`, `/proposals`): `user_id`
  is forwarded to `TaskService.get()` so `_can_read_task()` runs before the sub-resource
  query.
- `GET /boards/{board_id}/tasks`: `_can_read_task()` is applied per-row to the result set
  before returning. Private and restricted tasks are filtered from the board view for
  non-owners.

Private and restricted tasks are not readable or mutable by same-space non-owners.

---

## 6. Activity Access Policy

Activity records enforce visibility on read, mutation, and consolidation paths.

- `GET /activity` and `GET /activity/{id}`: `can_read_scoped_object()` applied with
  `viewer_user_id`.
- `PATCH /activity/{id}/review` and `PATCH /activity/{id}/archive`: `viewer_user_id`
  forwarded to the service; non-owners of a private record receive 404.
- `POST /activity/{id}/consolidate`: `svc.get(activity_id, space_id, viewer_user_id=…)` is
  called before consolidation begins; non-owners of a private record receive 404.

An unauthorized consolidation attempt must not create proposals. If visibility check fails,
the handler returns 404 before calling the consolidation service.

---

## 7. Proposal and Memory Boundary

Activity does not directly become active memory:

1. `ActivityConsolidationService` creates **proposals** from activity records.
2. Proposals must be reviewed and accepted via `POST /proposals/{id}/accept`.
3. `ProposalApplyService` handles the durable mutation — the only path through which
   activity-derived content becomes memory.

Additional invariants:
- Proposal apply is space-scoped: `accept(id, space_id=…)` returns None on space mismatch.
- Unsupported proposal types (`task_create`, `plan_create`, and any unknown
  type) raise `UnsupportedProposalTypeError` and leave the proposal in `pending` status.
  The fail-closed behavior is tested.
- Memory writes require policy/proposal gating: `MemoryStore` has no bypass path (no
  `direct_write()` equivalent accessible without policy enforcement).
- `MemoryProposalApplier.apply_create()` and `apply_update()` block grant-derived proposals
  from applying to non-personal target spaces without prior egress approval.

---

## 8. Intentional Cross-Space Exceptions

These routes intentionally ignore or discard the request `space_id`. Each has its own
authority mechanism in place of space-scoped auth.

### 8a. Personal Memory Egress Approval

**Route:** `POST /proposals/{proposal_id}/approvals/egress-granting-user`

The proposal lives in the **target space** (the space where the run executed). The granting
user authenticates from their **personal space**. These are structurally different spaces.
Requiring `proposal.space_id == request_space_id` would make granting-user approval
impossible in the standard case.

**Do not add `proposal.space_id == request_space_id` to this route.**

Authority comes from the guard chain inside `record_egress_granting_user_approval()`:

| Guard | Invariant |
|---|---|
| `grant.granting_user_id == approver_user_id` | Only the exact user who created the grant may approve |
| `proposal.space_id == grant.target_space_id` | Proposal must belong to the specific target space |
| `source_run_id == grant.target_run_id` | Proposal must trace back to the specific run the grant covered |
| `run.space_id == grant.target_space_id` | Source run must be in the same target space as the grant |
| `run.instructed_by_user_id == grant.granting_user_id` | Run must have been instructed by the granting user |
| Deadline check (`egress_review_expires_at`, `proposal.expires_at`) | Approval window enforced |
| Payload safety markers | `raw_private_memory_included`, `personal_summary_persisted`, public `target_visibility` all blocked |

Request `space_id` is intentionally discarded (`_, user_id = ids`). Security authority is
user-centered, not request-space-centered.

### 8b. PersonalView (`/me`) Cross-Space Aggregation

`GET /me/summary`, `/me/timeline`, `/me/tasks`, `/me/pending` are intentionally cross-space.
They aggregate across all spaces the user is a member of (`_member_space_ids(db, user_id)`).
Visibility filter (`can_read_scoped_object`) is applied to tasks and proposals. No raw
artifact payloads or full memory content is returned — pointer metadata only in timeline.

### 8c. Source Pointers

All `/source-pointers` routes discard request `_auth_space_id`. Authority is user membership
in `owner_space_id` (and `source_space_id` for creation). Source pointers are provenance
metadata only — no source object content is resolved or returned. They do not grant read
access to cross-space content and do not activate `memory.cross_space_read`.

### 8d. PersonalMemoryGrants

All five `/personal-memory-grants` routes discard request `space_id`. Grants are
user-centered objects that span two spaces by design: the personal space (where private
memory lives) and the target space (where the run executes). Authority is `granting_user_id`
throughout.

---

## 9. Credential, Provider, and Runtime Secrecy

- `ProviderConfigOut` explicitly excludes `api_key`. The internal `ProviderConfigDB` model
  (which carries the decrypted key) must not be exposed outside the service/adapter layer.
- `GET /providers/{id}` constructs `ProviderConfigOut` manually — no `api_key` field included.
- CLI credentials are stored as filesystem-managed paths; no secret material appears in API
  responses or SSE event streams.
- `AgentVersionOut`, `RunOut`, and `ArtifactOut` schemas contain no credential fields.
- Run trace exposes AgentVersion system prompt presence/hash metadata only; it
  does not inline raw system prompt text, raw rendered context text, or artifact
  content.
- Agent/run/artifact/proposal outputs must not expose secret material.

---

## 10. Workspace and Artifact Path Safety

**Workspace file access** (`workspace_console/api.py`):
- `PathPolicy` (`workspace/path_policy.py`) is enforced before any disk access.
- `workspace.read` policy is enforced before tree/file/status/diff reads.
- system_core, external-root, protected/restricted, full-diff, and secret-like
  path reads force a durable `PolicyDecisionRecord`.
- Forbidden path patterns include `.ssh`, `.aws`, `.gcp`, `.azure`,
  `credentials`, `instance/secrets`, `config/secrets`, `.git/config`,
  `.env`, `.env.*` except template examples, private key filenames, and
  `*.pem` / `*.key`.
- Full git diff output is bounded; secret-like diff paths are denied and
  secret-like key/value lines are redacted.
- Forbidden write suffixes: `.py`, `.sh`, `.bash`, `.zsh`, `.fish`.
- Paths resolved to absolute before validation; no symlink race conditions.

**Artifact export** (`artifacts/service.py — resolve_stored_file()`):
- `candidate.relative_to(artifact_storage_root)` — paths escaping the root return None.
- Paths resolving into `sandbox_root` are also rejected.
- `ArtifactReadService.get()` with `user_id` is called to verify space and visibility
  before the path is resolved.

---

## 11. Dogfooding Readiness

| Use case | Status |
|---|---|
| Personal dogfooding (single user per space) | **Ready** |
| Family / shared-space dogfooding | **Ready** |
| Internal team / workspace dogfooding | **Ready** |

All durable-data API routes are authenticated and space-scoped. Session conversation history
is protected by auth + space + user scoping. Activity → proposal → memory boundary is
enforced. Workspace path traversal is blocked. Artifact export is space- and
visibility-gated. Credential secrets are not exposed in API responses. Egress approval for
personal memory is enforced and tested.

Test coverage: 1127 passing tests (unit / contracts / invariants / workflows).

---

## See Also

- `docs/POLICY_AND_PRIVACY_BOUNDARIES.md` — canonical stable policy reference
- `docs/PERSONAL_MEMORY_GRANT.md` — personal memory grant lifecycle
- `docs/THREAT_MODEL.md` — threat model
- `.agent/architecture/POLICY_ENFORCEMENT_INVENTORY.md` — per-domain enforcement status
  and PersonalMemoryGrant implementation detail
- `docs/TARGET_VIEW_MODEL.md` — ExecutionContext and cross-space aggregation design
