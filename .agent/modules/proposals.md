# Module: Proposals

## Purpose
Approval workflow. Durable memory and code changes must go through a Proposal before taking effect. `ProposalApplyService` is the only normal durable write path.

## Owns
- `Proposal` model (generalized, any type)
- `ProposalApproval` — egress_granting_user approval gate (MVP: this approval type only)
- `Artifact` (persistent output of agent runs)
- `ProposalApplyService` — validates source trust, writes provenance links, dispatches to type-specific applier
- `SourceMonitoringService` — gates semantic/policy acceptance by source trust

## Key Models

```
Proposal:
  id, space_id, workspace_id
  proposal_type (memory_create|memory_update|memory_archive|policy_change|code_patch|egress_review|follow_up_task)
  title, summary, rationale, payload_json
  risk_level (low|medium|high|critical)
  status (pending|accepted|rejected|superseded|expired)
  preview  — if true, cannot be accepted
  created_by_agent_id, created_by_run_id, created_by_user_id
  required_approver_role, created_at, decided_at

  payload_json carries:
    proposed_content, memory_type, target_scope, target_namespace, target_visibility
    provenance_entries  — required for memory_create/update; links to source ActivityRecord, Run, etc.
    source_evidence, sensitivity_level
    owner_user_id, subject_user_id, selected_user_ids

ProposalApproval:
  id, proposal_id, approval_type ('egress_granting_user')
  approver_user_id, grant_id, target_space_id
  status (approved|revoked)
  metadata_json, created_at, revoked_at
```

## Main Flow

1. Product code creates a `Proposal` (pending, not active memory)
2. User reviews and approves/rejects via `/api/v1/proposals/{id}/accept` or `/reject`
3. `ProposalApplyService.apply(proposal, accept_context="explicit_user_accept")`:
   - Rejects preview proposals
   - Rejects already-accepted or rejected proposals
   - Enforces `SourceMonitoringService` for semantic/policy types
   - Writes `ProvenanceLink` rows for accepted memory/policy changes
   - Dispatches to type-specific applier (`MemoryUpdateProposalApplier`, `PolicyChangeApplier`, etc.)
4. `proposal.status = "accepted"`, `decided_at` set, commit — durable write completes. No separate approval-event row is created for normal accept/reject. `ProposalApproval` rows are a distinct gate for `egress_review` proposals only (written via `/proposals/{id}/approvals/egress-granting-user`).

## `accept_context` Values

| Value | Caller |
|-------|--------|
| `explicit_user_accept` | User/admin proposal-accept HTTP paths |
| `internal_seed` | DB seed, migration, or tests that intentionally bypass monitoring |
| `direct_apply` | In-process tests/tools; must not be used on public acceptance paths |

## Source Trust Gate

- `agent_inferred`-only provenance cannot become active semantic memory or policy.
- `untrusted_external` semantic/policy proposals may proceed only under `explicit_user_accept` with `source_monitoring_result` recorded on the proposal payload.
- `bypass_source_monitoring` is for tests/seeds only — not bound to HTTP request bodies or runtime adapters.

## Invariants
- No irreversible change executes without an approved Proposal
- Preview proposals cannot be accepted
- Accepted proposals cannot be re-applied
- Rejected proposals do not create memory or relations
- `ProposalApplyService` is the only normal durable write path
- `provenance_links` are required for accepted memory and policy changes
- Agents generate Proposals; humans approve

## Related Files
- `core/backend/app/models.py`
- `core/backend/app/proposals/`
- `core/backend/app/memory/apply_service.py`
- `core/backend/app/memory/source_monitoring.py`
- `core/backend/app/memory/internal_writer.py`
- `core/backend/app/artifacts/`
- `core/backend/app/memory/reflector.py`

## Related Decisions
- [0003-memory-proposal-flow.md](../decisions/0003-memory-proposal-flow.md)
