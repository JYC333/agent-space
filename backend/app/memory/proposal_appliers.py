"""Memory-owned proposal appliers — registration hook for the proposal registry.

The memory module owns the apply business logic for:

  memory_create / memory_update / memory_archive — MemoryProposalApplier
  policy_change   — PolicyProposalApplier (Policy rows are written through the
                    memory-owned PolicyInternalWriter; the ``policy`` module
                    owns the approval gate and audit, not the durable write)
  code_patch      — apply_code_patch_payload (workspace file writes)
  follow_up_task  — FollowUpTaskProposalApplier (one Task row)
  egress_review   — metadata-only marker (the egress_review proposal is built
                    by ``app.proposals.build_egress_review_proposal``;
                    apply records no durable object — ``ProposalService.accept``
                    stamps the payload)

Wired through ``app.modules.registry.register_proposal_appliers`` — adding a
new proposal type never edits ``ProposalApplyService`` dispatch internals.
Appliers run inside the accept transaction owned by ``ProposalService.accept``
and must not commit. Cross-cutting governance (policy gate, accept-context
guard, grant egress approval, source monitoring) stays in
``ProposalApplyService`` / the policy gate — never here.
"""

from __future__ import annotations

from ..proposals import (
    ProposalApplierRegistry,
    ProposalApplyContext,
    ProposalApplyError,
    ProposalApplyResult,
)


def _apply_memory_create(context: ProposalApplyContext) -> ProposalApplyResult:
    from ..proposals import MemoryProposalApplier

    r = MemoryProposalApplier(context.db).apply_create(context.proposal, user_id=context.user_id)
    return ProposalApplyResult(proposal=context.proposal, memory=r.memory)


def _apply_memory_update(context: ProposalApplyContext) -> ProposalApplyResult:
    from ..proposals import MemoryProposalApplier

    r = MemoryProposalApplier(context.db).apply_update(context.proposal, user_id=context.user_id)
    return ProposalApplyResult(proposal=context.proposal, memory=r.memory)


def _apply_memory_archive(context: ProposalApplyContext) -> ProposalApplyResult:
    from ..proposals import MemoryProposalApplier

    r = MemoryProposalApplier(context.db).apply_archive(context.proposal, user_id=context.user_id)
    return ProposalApplyResult(proposal=context.proposal, memory=r.memory)


def _apply_policy_change(context: ProposalApplyContext) -> ProposalApplyResult:
    from ..proposals import PolicyProposalApplier

    r = PolicyProposalApplier(context.db).apply(context.proposal, user_id=context.user_id)
    return ProposalApplyResult(proposal=context.proposal, policy=r.policy)


def _apply_follow_up_task(context: ProposalApplyContext) -> ProposalApplyResult:
    from ..proposals import FollowUpTaskProposalApplier

    task = FollowUpTaskProposalApplier(context.db).apply(context.proposal, user_id=context.user_id)
    return ProposalApplyResult(proposal=context.proposal, task=task)


def _apply_egress_review(context: ProposalApplyContext) -> ProposalApplyResult:
    # Metadata-only marker: granting-user approval was already validated by
    # ProposalApplyService._enforce_personal_memory_egress_approval.
    return ProposalApplyResult(proposal=context.proposal, egress_review=True)


def _apply_code_patch(context: ProposalApplyContext) -> ProposalApplyResult:
    from ..models import Workspace
    from .code_patch_apply import CodePatchApplyError, apply_code_patch_payload

    proposal = context.proposal
    if not proposal.workspace_id:
        raise ProposalApplyError("code_patch proposal missing workspace_id")
    ws = (
        context.db.query(Workspace)
        .filter(
            Workspace.id == proposal.workspace_id,
            Workspace.space_id == proposal.space_id,
        )
        .first()
    )
    if not ws:
        raise ProposalApplyError("workspace not found for proposal")

    payload = proposal.payload_json or {}
    patch = payload.get("patch")
    if not isinstance(patch, dict):
        raise ProposalApplyError("invalid patch payload")

    try:
        patch_result = apply_code_patch_payload(
            context.db,
            workspace=ws,
            patch=patch,
            space_id=proposal.space_id,
            user_id=context.user_id,
            source_run_id=payload.get("source_run_id") or proposal.created_by_run_id,
            proposal_id=proposal.id,
        )
    except CodePatchApplyError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ProposalApplyError(str(exc)) from exc

    files = [
        {
            "path": f.path,
            "existed_before": f.existed_before,
            "preimage_sha256": f.preimage_sha256,
            "postimage_sha256": f.postimage_sha256,
        }
        for f in patch_result.files
    ]
    return ProposalApplyResult(
        proposal=proposal,
        updated_paths=patch_result.paths,
        code_patch_files=files,
        code_patch_transaction=patch_result.transaction,
    )


def register_proposal_appliers(registry: ProposalApplierRegistry) -> None:
    """Register every memory-owned proposal applier."""
    registry.register("memory_create", _apply_memory_create)
    registry.register("memory_update", _apply_memory_update)
    registry.register("memory_archive", _apply_memory_archive)
    registry.register("policy_change", _apply_policy_change)
    registry.register("code_patch", _apply_code_patch)
    registry.register("follow_up_task", _apply_follow_up_task)
    registry.register("egress_review", _apply_egress_review)
