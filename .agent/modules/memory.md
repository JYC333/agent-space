# Module: Memory

## Purpose
Scoped, long-term context for agents and users. Not raw data — curated, approved, versioned knowledge.

## Owns
- `MemoryEntry` model, `MemoryStore` CRUD
- `MemoryReadTrace` (every read recorded)
- Memory write governance: public writes create Proposals, `ProposalApplyService` is the only durable write path
- `MemoryProvider` ABC + `LocalMemoryProvider`
- `ContextBuilder` — assembles ContextPackage; hard-filters before ranking; resolves ContextAttachments; logs injected memory
- `ContextCompiler` — security-scans, budget-trims, writes vendor files to sandbox
- `MemoryEvolver` — fitness-based memory lifecycle; produces archive Proposals, not direct writes
- `ContextSnapshot` — frozen audit record of run input; populated before adapter execution
- `MemoryCandidateValidator` — gates activity-sourced candidates before Proposal creation
- `MemoryProposalProducer` — creates Proposals from validated candidates
- `SourceMonitoringService` — gates semantic/policy proposal acceptance by source trust
- `security.py` — secret/injection scanning, path policy

## Key Models

```
MemoryEntry:
  id, space_id, owner_user_id, workspace_id
  agent_id, capability_id           (nullable; FK-style links for scope=agent/capability)
  scope_type (system|space|user|workspace|capability|agent)
  memory_layer (episodic|semantic), memory_kind
  namespace, memory_type, title, content
  status (active|archived|proposed|rejected|superseded)
  visibility (private|space_shared|workspace_shared|restricted|public_template)
  confidence, importance, version, tags
  source_proposal_id, created_from_proposal_id  (provenance — required on accepted writes)
  source_activity_id, source_artifact_id  (nullable provenance)
  source_trust
  created_by, approved_by
  access_count, last_accessed_at, fitness_score

Proposal (memory_create | memory_update | memory_archive | policy_change):
  id, space_id, workspace_id, proposal_type, status, risk_level, urgency
  payload_json  — carries proposed content, provenance_entries, source evidence
  created_by_agent_id, created_by_run_id, created_by_user_id
  required_approver_role, created_at, decided_at

MemoryReadTrace:
  memory_id, user_id, agent_id, space_id, access_type, reason, created_at
```

## Memory Architecture Layers

- **L0** — `ActivityRecord`: raw event intake; never active Memory.
- **L2/L3** — `MemoryEntry`: episodic and semantic long-term memory.
- **L4** — `Policy`: system rules; separate lifecycle, versioning, and enforcement.

## Main Flows

**Context assembly:**
1. `ContextBuilder.build(space_id, user_id, workspace_id, attachments=[...])`
2. Hard-filters by space/scope/subject/visibility before ranking; logs all injected memory
3. Returns `ContextPackage`; populates `ContextSnapshot` before adapter execution
4. `ContextCompiler.compile()` → scans content → applies budget → writes CLAUDE.md / SOUL.md to sandbox

**Public write → Proposal flow:**
1. `POST /memory` → `memory_create` Proposal (pending, not active MemoryEntry)
2. `PATCH /memory/{id}` → `memory_update` Proposal
3. `DELETE /memory/{id}` → `memory_archive` Proposal
4. User approves via `POST /api/v1/proposals/{id}/accept`
5. `ProposalApplyService.apply()` validates source trust, writes provenance links, then calls internal writer
6. `MemoryInternalWriter` creates/supersedes/archives the `MemoryEntry`

**Activity → Proposal flow:**
1. `ActivityRecord` created with raw content and `source_trust`
2. `POST /api/v1/activity/{id}/consolidate` or `POST /api/v1/memory/consolidation/run` runs `ActivityConsolidationService`
3. Classifier → `MemoryCandidateValidator` (rejects cross-space, missing provenance, agent_inferred semantic, invalid scope)
4. `MemoryProposalProducer` creates reviewable Proposals with `provenance_entries`
5. Normal approval flow proceeds; `SourceMonitoringService` gates acceptance

## Invariants
- `space_id` required; `ContextBuilder` raises without it
- Public `POST /memory` does not create an active `MemoryEntry` — it creates a pending Proposal
- Public `PATCH /memory/{id}` does not mutate a `MemoryEntry` — it creates a pending Proposal
- Public `DELETE /memory/{id}` does not archive a `MemoryEntry` — it creates a pending Proposal
- `ProposalApplyService` is the only durable write path; accepted changes require `provenance_links`
- `agent_inferred`-only evidence cannot become active semantic memory or policy
- `untrusted_external` semantic/policy proposals require explicit user accept with source monitoring recorded
- Every memory read during context assembly logs to `MemoryReadTrace`; filtered-out memories are not logged
- Memory from space A never appears in a context built for space B
- Archived/superseded memory is excluded from context and list by default
- Executed runs must have a non-empty `ContextSnapshot`; snapshot population failure blocks execution
- All content passes security scanning before entering compiled context

## ContextDigest cache

`ContextDigest` is a versioned derived cache of approved Memory/Policy content. It is **not** Memory and **not** Policy.

- Supported `digest_type` values: `policy_bundle`, `workspace`, `agent`.
- Digest content is rendered from active `MemoryEntry` + active `Policy` rows only. Unapproved proposal content is never included.
- `ContextDigestService` generates/versions digests deterministically (no LLM required).
- Source hash versioning: if source IDs + version signals are unchanged, the existing digest is reused. If sources changed, old digest is marked `superseded` and a new version is created.
- `ContextCompiler` may use active digests in `stable_prefix`; `ContextSnapshot` records full source traceability.
- Digest can be deleted and regenerated. Digest does not create Proposal.
- Personal Radius / external sources are out of scope.

### Dirty tracking
`ProposalApplyService` marks affected digests `dirty` after accepted proposals:
- `memory_create/update/archive` → marks `workspace` and/or `agent` digest dirty based on the memory's scope.
- `policy_change` → marks `policy_bundle` digest dirty; also workspace/agent digests if policy `applies_to_json` specifies those scopes.

## Related Files
- `core/backend/app/memory/store.py`
- `core/backend/app/memory/provider.py`
- `core/backend/app/memory/internal_writer.py`
- `core/backend/app/memory/apply_service.py`
- `core/backend/app/memory/source_monitoring.py`
- `core/backend/app/memory/retriever.py`
- `core/backend/app/memory/context_builder.py`
- `core/backend/app/memory/context_compiler.py`
- `core/backend/app/memory/digest_service.py` — `ContextDigestService`
- `core/backend/app/memory/consolidation/service.py`
- `core/backend/app/memory/evolver.py`
- `core/backend/app/memory/access_log.py`
- `core/backend/app/runs/context_snapshot_populator.py`
- `core/backend/app/schemas.py`

## Related Decisions
- [0003-memory-proposal-flow.md](../decisions/0003-memory-proposal-flow.md)
- [0004-context-wrapper.md](../decisions/0004-context-wrapper.md)
