# Space Model

## Concept

A **space** is the primary collaboration and permission boundary in agent-space. One deployment
instance can host many spaces:

```
Deployment Instance
  ├── Personal Space   (type=personal, exactly one member: the owner)
  ├── Family Space     (type=household, multi-member)
  └── Team Space       (type=team, multi-member)
```

A space is **not** the only meaningful worldview for a user. A user may belong to several spaces
simultaneously. Future model concepts (PersonalView, ExecutionContext) will make cross-space
aggregation explicit without breaking the per-space permission boundary. See
`docs/TARGET_VIEW_MODEL.md` for the target concepts.

## Database model

```sql
CREATE TABLE spaces (
  id TEXT PRIMARY KEY,           -- e.g. "personal", "family", "acme-team"
  name TEXT NOT NULL,
  type TEXT NOT NULL,            -- personal | household | team
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE space_memberships (
  id TEXT PRIMARY KEY,
  space_id TEXT NOT NULL REFERENCES spaces(id),
  user_id TEXT NOT NULL,
  role TEXT NOT NULL,            -- owner | admin | member | guest
  status TEXT NOT NULL,          -- active | invited | suspended
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE workspace_memberships (
  id TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  role TEXT NOT NULL,            -- owner | editor | viewer | agent_operator
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
```

## Personal space convention

- A personal space has **exactly one member**: the space owner.
- `Space.type = "personal"` is the structural marker; it is not redundant with membership.
- Do not infer that a user has no personal space from the absence of a `SpaceMembership` row —
  the canonical personal space may be implicit in single-user deployments.

## Private memory definition

"User-private memory" means **all three** of the following are true:

1. `MemoryEntry.visibility = "private"`
2. `MemoryEntry.space_id = <the user's personal space id>`
3. `MemoryEntry.owner_user_id = <that user's id>`

If any condition is absent, the memory is not correctly private:
- `visibility=private` in a shared space is an anti-pattern (see below).
- Missing `owner_user_id` is rejected by `MemoryStore.create()`.

## Anti-pattern: private memory in shared spaces

Storing `visibility=private` memory in a household, team, or other multi-member space is an
anti-pattern.

- **Write-layer enforcement (active):** `MemoryStore.create()` raises `ValueError` when
  `visibility=private` and the target space is not of type `personal`. All write routes are
  covered because they share this path.
- **Read-time safety net (active):** `can_read_memory()` in `memory/read_auth.py` blocks
  non-owner reads for private visibility regardless of space type. This catches any
  private memories that were written before enforcement was added.

Team / family / lab spaces **must not** read any user's private memory unless that memory has
been explicitly granted through `PersonalMemoryGrant` (run-scoped, summary-only, one-time)
or a future publish mechanism. See `docs/PERSONAL_MEMORY_GRANT.md`.

## Personal ledger / participation records

A "participation record" or "personal ledger entry" for shared-space activity is a **future
model concept** (see `docs/TARGET_VIEW_MODEL.md` → `ParticipationRecord`). It is not
implemented. When built, it must **not** copy raw shared-space content into a user's personal
space; it records only a pointer and the user's personal context around the activity.

## Rules

- Every data record (Memory, Session, Task, Run, etc.) carries a `space_id`.
- The ContextBuilder requires `space_id` and `user_id` — it will raise if either is missing.
- Memory queries filter by `space_id` first. No query can retrieve memory across spaces.
- `space_shared` visibility means visible to all members of the same space.
- `workspace_shared` visibility means visible to workspace members only.
- `private` visibility means visible to the owner only, and must only be written to personal spaces.

## Roles

Space-level roles:
- `owner` — full control, can delete the space
- `admin` — manage members and workspaces
- `member` — normal access
- `guest` — read-only, limited access

Workspace-level roles:
- `owner` — full workspace control
- `editor` — read/write
- `viewer` — read-only
- `agent_operator` — can trigger agent runs

## Cross-space provenance

`source_pointers` records metadata that an object in one space references an object in another.
The `/api/v1/source-pointers` API is membership-gated and metadata-only.
**SourcePointer does not grant read access** — all reads still require membership, visibility,
and policy checks in the source space. `memory.cross_space_read` remains deny-by-default.
`PersonalMemoryGrant` is the explicit grant mechanism for allowing a shared-space run to use
a user's personal-space private memory as reasoning-only context. Federation and
`visibility=public` remain deferred. See `docs/PERSONAL_MEMORY_GRANT.md`,
`docs/SOURCE_POINTER.md`, `docs/TARGET_VIEW_MODEL.md`, and `docs/FEDERATED_ACCESS_MODEL.md`.

## See also

- `docs/README.md` — full documentation index
- `docs/TARGET_VIEW_MODEL.md` — target model concepts (PersonalView, ExecutionContext, etc.)
- `docs/PERSONAL_MEMORY_GRANT.md` — explicit personal memory grant mechanism
- `docs/SOURCE_POINTER.md` — cross-space provenance metadata
- `docs/POLICY_AND_PRIVACY_BOUNDARIES.md` — policy enforcement inventory
- `docs/FEDERATED_ACCESS_MODEL.md` — federated access (deferred)
- `docs/PUBLISH_PROJECTION.md` — public publish pipeline (deferred)
- `core/backend/app/memory/read_auth.py` — `can_read_memory()` implementation
- `core/backend/app/memory/store.py` — `MemoryStore.create()` write-layer enforcement
