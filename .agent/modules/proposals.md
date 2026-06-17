# Module: Proposals

## Purpose
Approval workflow. Durable memory and code changes must go through a Proposal before taking effect. `ProposalApplyService` is the only normal durable write path.

## Owns
- `Proposal` model (generalized, any type)
- `ProposalApproval` — egress_granting_user approval gate (MVP: this approval type only)
- `Artifact` (persistent output of agent runs)
- `ProposalApplyService` — validates source trust, writes provenance links, and dispatches through `ProposalApplierRegistry` to module-owned appliers
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
   - Dispatches through `ProposalApplierRegistry` to the target module's registered applier
4. `proposal.status = "accepted"`, `decided_at` set, commit — durable write completes. No separate approval-event row is created for normal accept/reject. `ProposalApproval` rows are a distinct gate for `egress_review` proposals only (written via `/proposals/{id}/approvals/egress-granting-user`).

## TypeScript Migration Boundary

The public proposal review/apply surface is fixed TS-owned in the control plane:

- TS owns external `/api/v1/proposals` list/get routes and mirrors the Python
  read model/visibility rule.
- TS owns the external accept/reject/egress-approval HTTP routes and the
  proposal-apply transaction boundary for registered appliers.
- TS runs the `proposal.apply` policy gate before dispatching through its
  `ProposalApplierRegistry`.
- The currently registered TS appliers are `memory_create`, `memory_update`, and
  `memory_archive`. Unregistered proposal types fail closed until their owning
  domain migrates and registers a TS applier.
- Python remains the reference owner for non-memory target-module appliers until
  their domains migrate; the control-plane public route does not fall back to
  Python proposal ports.
- Proposal creation entrypoints remain in their product modules
  (`memory`, `knowledge`, `agents`, `runs`, etc.) until those contexts migrate.

This is intentional: the TS migration removes the fallback proxy from the
user-facing proposal review API while keeping non-migrated proposal mutations
fail-closed instead of silently no-oping or crossing back into Python.

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
- Target modules own proposal business mutations; `proposals` owns the registry and approval/apply orchestration
- `provenance_links` are required for accepted memory and policy changes
- Agents generate Proposals; humans approve

## Related Files
- `backend/app/models.py`
- `backend/app/proposals/`
- `backend/app/proposals/apply_service.py`
- `backend/app/*/proposal_appliers.py`
- `backend/app/memory/source_monitoring.py`
- `backend/app/memory/internal_writer.py`
- `backend/app/artifacts/`
- `backend/app/memory/reflector.py`

## Related Decisions
- [0003-memory-proposal-flow.md](../decisions/0003-memory-proposal-flow.md)
