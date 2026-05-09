# Module: Memory

## Purpose
Scoped, long-term context for agents and users. Not raw data — curated, approved, versioned knowledge.

## Owns
- `Memory` model, `MemoryStore` CRUD
- `MemoryAccessLog` (every read recorded)
- `MemoryProposal` model and proposal workflow
- `MemoryProvider` ABC + `LocalMemoryProvider`
- `ContextBuilder` — assembles ContextPackage; resolves ContextAttachments
- `ContextCompiler` — security-scans, budget-trims, writes vendor files to sandbox
- `MemoryEvolver` — fitness-based memory lifecycle
- `security.py` — secret/injection scanning, path policy

## Key Models

```
Memory:
  id, space_id, owner_user_id, workspace_id
  agent_id, capability_id           (nullable; FK-style links for scope=agent/capability)
  scope (system|space|user|workspace|capability|agent)
  namespace, type, title, content
  status (active|archived|proposed|rejected|superseded)
  visibility (private|space_shared|workspace_shared|restricted|public_template)
  confidence, importance, version, tags
  source_activity_id, source_artifact_id  (nullable provenance)
  created_by, approved_by
  access_count, last_accessed_at, fitness_score

MemoryProposal:
  id, space_id, user_id, workspace_id
  source_session_id, source_task_id, source_run_id, source_activity_id
  target_scope, target_namespace, target_visibility, memory_type
  proposed_title, proposed_content
  rationale        — why this should become memory
  source_evidence  — supporting quotes from source
  risk_level (low|medium|high|critical)
  status (pending|accepted|rejected|needs_changes)
  review_metadata  — reviewer notes, requested changes
  approved_by, resulting_memory_id

MemoryAccessLog:
  memory_id, user_id, agent_id, space_id, access_type, reason, created_at
```

## Main Flows

**Context assembly:**
1. `ContextBuilder.build(space_id, user_id, workspace_id, attachments=[...])`
2. Fetches memories by scope; resolves attachments; logs all access
3. Returns `ContextPackage`
4. `ContextCompiler.compile()` → scans content → applies budget → writes CLAUDE.md / SOUL.md to sandbox

**Proposal flow:**
1. Agent creates `MemoryProposal` with rationale + source_evidence
2. User approves via `POST /api/v1/memory/proposals/{id}/accept`
3. `MemoryStore.create()` called; `approved_by` + `resulting_memory_id` set

**Activity → proposal:**
1. `ActivityRecord` created with raw content
2. `POST /api/v1/activity/{id}/proposals` → `MemoryProposal` records with `source_activity_id`
3. Normal approval flow proceeds

## Invariants
- `space_id` required; ContextBuilder raises without it
- Agents never call `MemoryStore.create()` directly — always via proposals
- Every memory read logs to MemoryAccessLog
- Memory from space A never appears in a context built for space B
- All content passes security scanning before entering compiled context

## Related Files
- `core/backend/app/memory/store.py`
- `core/backend/app/memory/provider.py`
- `core/backend/app/memory/security.py`
- `core/backend/app/memory/context_builder.py`
- `core/backend/app/memory/context_compiler.py`
- `core/backend/app/memory/proposals.py`
- `core/backend/app/memory/evolver.py`
- `core/backend/app/memory/reflector.py`
- `core/backend/app/schemas.py`

## Related Decisions
- [0003-memory-proposal-flow.md](../decisions/0003-memory-proposal-flow.md)
- [0004-context-wrapper.md](../decisions/0004-context-wrapper.md)
