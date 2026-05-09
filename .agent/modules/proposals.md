# Module: Proposals

## Purpose
Approval workflow. Any consequential change — memory, code, capability, schema, policy — must go through a proposal before taking effect.

## Owns
- `Proposal` model (generalized, any type)
- `ApprovalEvent`, `ProposalArtifact`
- `Artifact` (persistent output of agent runs)
- `MemoryProposal` (memory-specific, predates generalized Proposal)
- `Approval` (per-item approval record)

## Key Models

```
Proposal:
  id, space_id, workspace_id
  type (memory_update|code_patch|capability_install|schema_migration|policy_change|report|classification|other)
  title, summary, rationale, payload_json
  risk_level (low|medium|high|critical)
  status (pending|accepted|rejected|superseded|expired)
  created_by_agent_id, created_by_run_id, created_by_user_id
  required_approver_role, created_at, decided_at

ApprovalEvent:
  proposal_id, user_id
  decision (accepted|rejected|requested_changes)
  comment, created_at

MemoryProposal:
  id, space_id, user_id, workspace_id
  source_session_id, source_task_id, source_run_id, source_activity_id
  target_scope, target_namespace, target_visibility, memory_type
  proposed_title, proposed_content
  rationale, source_evidence
  risk_level (low|medium|high|critical)
  status (pending|accepted|rejected|needs_changes)
  review_metadata, approved_by, resulting_memory_id
```

## Main Flow

1. Agent creates `Proposal` or `MemoryProposal`
2. User reviews and approves/rejects via API
3. `ApprovalEvent` created
4. Owning module executes the change

## Invariants
- No irreversible change executes without an approved Proposal
- Agents generate proposals; humans approve
- Artifacts linked to proposals survive sandbox cleanup

## Related Files
- `core/backend/app/models.py`
- `core/backend/app/memory/proposals.py`
- `core/backend/app/memory/reflector.py`

## TODO
- Generalized Proposal API routes not fully implemented
- Notification system not yet implemented
- `code_patch` and `capability_install` types not yet handled by executors

## Related Decisions
- [0003-memory-proposal-flow.md](../decisions/0003-memory-proposal-flow.md)
