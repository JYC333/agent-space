# Shared-Space Assistant and User-Level Memory Isolation

Status: **design + initial implementation** (2026-06-22). The default-visibility
and owner-attribution changes (§5.1) and the promotion path (§5.2) have landed;
§7 tracks per-item status. Sections marked _Current state_ describe shipped
behavior.

This document answers a recurring question: in a household/team space where
several people talk to **one** shared system assistant, how should conversation
history and derived memory be isolated, and do we need user-level memory
isolation in addition to the project-level ACL?

---

## 1. Problem

A `team`/`household` space has multiple members. They may share a single
"system assistant" agent. If each member's chat turns flow into a single shared
memory pool, members read each other's private context and the shared memory
"错位" — cross-contaminates. We want:

- Personal cognition stays personal by default.
- Space-level memory is shared, but only reached by an **explicit promotion**
  of a personal memory, not automatically.
- The project ACL (`project_members`) is a separate, orthogonal axis.

The user's intuition — promotion-gated sharing rather than default sharing — is
the correct model. This document grounds it in the existing substrate and names
the concrete gaps.

---

## 2. The space is a collaboration boundary, not a shared mind

This is the durable principle already recorded in [MEMORY_MODEL.md](MEMORY_MODEL.md):
a Space is a collaboration boundary, and private cognition must remain
enforceable at **read time**. Two isolation axes already exist and **compose**:

| Axis | Mechanism | Gates |
|---|---|---|
| **User isolation** (this doc) | `memory_entries.owner_user_id` + `visibility` | personal vs space-shared memory |
| **Project isolation** | `project_members` ACL on `memory_entries.project_id` | which project's concrete memory a member may read |

User isolation is expressed by an **owner + visibility**, not by a membership
table. A per-user ACL table mirroring `project_members` is **not** needed —
`owner_user_id` already identifies the single controlling user, and
`visibility` already encodes who else may read. `project_members` exists only
because a project is a many-users-to-one-resource grouping that a single owner
cannot express.

---

## 3. Current state

### 3a. Conversation history is already per-user

Sessions are user-owned within a space. `Session.space_id` **and**
`Session.user_id` are both applied as SQL filters on every session read (see
[SECURITY_AND_ACCESS_BOUNDARIES.md](SECURITY_AND_ACCESS_BOUNDARIES.md) §4).
A same-space non-owner gets 404. So **sharing one assistant agent does not share
conversation history** — history is already isolated per user, regardless of
which agent answered. No change needed here.

### 3b. Memory read authorization already supports user isolation

`canReadMemory` (`server/src/modules/memory/memoryReadAuth.ts`):

- `visibility = private` → readable only by `owner_user_id`.
- `visibility = space_shared` → readable by any space member.
- `restricted` / `selected_users` → owner plus `selected_user_ids`.
- `sensitivity_level = highly_restricted` → owner-only regardless of visibility.

The chat candidate collector (`selectMemories`) and the per-run `ContextBuilder`
both run `canReadMemory` for the requesting user, so **user B's private memory
never enters user A's chat context or run context.** The substrate is correct.

### 3c. The gap was in the write-side defaults (now fixed)

The isolation primitives always existed; the **default visibility for derived
memory was wrong for multi-member spaces**. Previously:

- `memoryApplyRepository.applyCreate` defaulted to
  `target_visibility ?? visibility ?? "space_shared"`.
- The intake/consolidation summary proposal
  (`server/src/modules/intake/repository.ts`) emits memory proposals with
  `target_scope: "user"` but no explicit visibility, so they landed on that
  `space_shared` default.
- `proposalRepository.createMemoryProposal` defaulted to `"private"` — both
  inconsistent and unusable in a shared space (the placement invariant rejects
  `private` there on apply).

Net effect was: in a shared space, assistant/intake-derived memory tended to
become `space_shared` on apply — exactly the "错位" the user worried about. This
is now corrected by the space-type-aware defaults in §5; the problem was
**specific to multi-member spaces** (a single-member `personal` space is
unaffected).

---

## 4. Proposed model

### 4a. One shared assistant, per-user isolation enforced below the agent

Keep **one** space-owned system assistant (do not fork a private agent per
user — that fights `B6`–`B8` and multiplies cost). Isolation lives in two
places, both of which already enforce it:

1. **Session** — conversation history is user-owned (3a).
2. **Memory read** — `canReadMemory` filters per user (3b).

The agent identity being shared is independent of whose memory/history is
visible.

### 4b. The private-placement invariant constrains the design

There is a hard invariant in the applier (`assertPrivatePlacement`):
`visibility = private` is **only permitted in `personal` spaces**. The intended
model is that truly private cognition lives in your own personal space; a
household/team space holds collaborative memory. So inside a multi-member space
the owner-only tier **cannot** use `private` — it uses `restricted` with an
empty `selected_user_ids`, which `canReadMemory` resolves to owner-only
(`owner` reads; non-owners are not in the selected list → denied).

### 4c. Three memory tiers

| Tier | Shape | Visible to |
|---|---|---|
| **Personal (owner-only)** | `owner_user_id = U`; `private` in a personal space, `restricted` + empty `selected_user_ids` in a multi-member space | only U |
| **Space** | `scope_type = space`, `visibility = space_shared` | all space members |
| **Project** | any tier **plus** `project_id`, gated by `project_members` | per project ACL |

The personal/owner-only tier is the **default** for anything derived from a
user's conversation with the shared assistant in a multi-member space. The space
tier is reached only by promotion (4d). Project tier is the orthogonal
horizontal slice already shipped.

### 4d. Promotion is explicit and owner-gated

Promoting a personal memory to the space tier is an explicit action that reuses
the existing **proposal → approval** flow (`B10`) — no new proposal type is
needed. A `memory_update` proposal flips `visibility` from `restricted` (or
`private`) to `space_shared` (and may re-scope `scope_type` `user → space`).
Because the update proposal is created through `getVisibleTargetMemory`
(`canReadMemory`-gated), only the owner of an owner-only memory can initiate the
promotion; the normal proposal approval then applies it. The promoter stays the
owner/steward of the resulting `space_shared` row. Until promotion, the memory
is owner-only.

This is the user's preferred "latter scheme" and is the safe default: nothing
becomes shared by accident.

### 4e. Space-type-aware defaults

`spaces.type ∈ {personal, household, team}`. The default derived-memory
visibility is:

- `personal` space → `space_shared` (sole member; equivalent to owner-only).
- `household` / `team` space → `restricted` owner-only, `owner_user_id` = the
  conversing/creating user.

---

## 5. Implementation status

1. **Default visibility by space type — done.** The memory_create applier
   (`memoryApplyRepository.applyCreate`) now computes the no-visibility default
   from `spaces.type`: personal → `space_shared` (unchanged), multi-member →
   `restricted` owner-only, with `owner_user_id` attributed to the proposal's
   creating user (`created_by_user_id`). This covers the intake/consolidation
   and runtime-materialized paths, which do not set an explicit visibility. The
   public-API `proposalRepository.createMemoryProposal` default was reconciled
   the same way (personal → `private`, multi-member → `restricted`) so an
   explicit-private create no longer fails the placement invariant in a shared
   space.
2. **Promotion path — done (reuses memory_update).** No new proposal type:
   promotion is a `memory_update` flipping visibility to `space_shared`,
   owner-gated by `getVisibleTargetMemory` and applied through the normal
   approval flow (see 4d).
3. **Regression tests — done.** `memoryApplyIntegration.test.ts` covers the
   multi-member owner-only default, the unchanged personal default, and the
   promotion. `chatContextCandidateCollector.test.ts` asserts another user's
   owner-only `restricted` (and `private`) memory never enters the requesting
   user's chat candidates.
4. **No new table — by construction.** User isolation is `owner_user_id` +
   `visibility`; no per-user memory ACL table was added.

Remaining / optional follow-ups: an explicit `POST /memory/{id}/promote`
convenience endpoint (the generic `PATCH /memory/{id}` already supports it); and
a dedicated audit code for promotion events.

---

## 6. Non-goals

- No full RBAC and no `MemoryAccessGrant` table for within-space isolation.
- No per-user agent forking.
- No change to the cross-space `PersonalMemoryGrant` egress flow — that governs
  memory crossing **space** boundaries, which is a different problem from
  within-space user isolation.
- No change to project public summaries: those remain a deliberately sanitized,
  space-public discovery layer (see [PROJECTS.md](PROJECTS.md)).

---

## See Also

- [MEMORY_MODEL.md](MEMORY_MODEL.md) — memory scopes, visibility, read rules.
- [SECURITY_AND_ACCESS_BOUNDARIES.md](SECURITY_AND_ACCESS_BOUNDARIES.md) — session
  user-scoping (§4), project memory ACL and public summaries (§7).
- [PROPOSALS.md](PROPOSALS.md) — proposal lifecycle used by the promotion action.
