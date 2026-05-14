# Module: Proposals

## Purpose
Approval workflow. Durable memory and code changes must go through a proposal before taking effect.

## Owns
- `Proposal` model (generalized, any type)
- `ApprovalEvent`, `ProposalArtifact`
- `Artifact` (persistent output of agent runs)
- `Approval` (per-item approval record)

## Key Models

```
Proposal:
  id, space_id, workspace_id
  type (memory_update|code_patch)
  title, summary, rationale, payload_json
  risk_level (low|medium|high|critical)
  status (pending|accepted|rejected|superseded|expired)
  created_by_agent_id, created_by_run_id, created_by_user_id
  required_approver_role, created_at, decided_at

ApprovalEvent:
  proposal_id, user_id
  decision (accepted|rejected|requested_changes)
  comment, created_at
```

## Main Flow

1. Product code creates a `Proposal`
2. User reviews and approves/rejects via `/api/v1/proposals`
3. `ApprovalEvent` created
4. Owning module executes the change

## Invariants
- No irreversible change executes without an approved Proposal
- Agents generate proposals; humans approve
- Proposals are never auto-applied
- Artifacts linked to proposals survive sandbox cleanup

## Related Files
- `core/backend/app/models.py`
- `core/backend/app/proposals/`
- `core/backend/app/artifacts/`
- `core/backend/app/memory/reflector.py`

## Related Decisions
- [0003-memory-proposal-flow.md](../decisions/0003-memory-proposal-flow.md)
