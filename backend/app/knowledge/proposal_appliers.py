"""Knowledge-owned proposal appliers — registration hook for the proposal registry.

The knowledge module owns the apply business logic for:

  knowledge_create / knowledge_update / knowledge_archive
  knowledge_relation_create / knowledge_relation_delete

All delegate to :class:`app.knowledge.service.KnowledgeProposalApplier`.
Apply-time failures (validation, missing targets, …) are wrapped in
``ProposalApplyError`` exactly as the pre-registry central dispatch did, so
the accept boundary keeps mapping them to HTTP 422.

Wired through ``app.modules.registry.register_proposal_appliers``. Appliers
run inside the accept transaction owned by ``ProposalService.accept`` and must
not commit; approval governance stays at the policy gate.
"""

from __future__ import annotations

from ..proposals import (
    ProposalApplierRegistry,
    ProposalApplyContext,
    ProposalApplyError,
    ProposalApplyResult,
)


def _apply_knowledge_create(context: ProposalApplyContext) -> ProposalApplyResult:
    from .service import KnowledgeProposalApplier

    try:
        item = KnowledgeProposalApplier(context.db).apply_create(
            context.proposal, user_id=context.user_id
        )
    except Exception as exc:  # noqa: BLE001
        raise ProposalApplyError(str(exc)) from exc
    return ProposalApplyResult(proposal=context.proposal, knowledge_item=item)


def _apply_knowledge_update(context: ProposalApplyContext) -> ProposalApplyResult:
    from .service import KnowledgeProposalApplier

    try:
        item = KnowledgeProposalApplier(context.db).apply_update(
            context.proposal, user_id=context.user_id
        )
    except Exception as exc:  # noqa: BLE001
        raise ProposalApplyError(str(exc)) from exc
    return ProposalApplyResult(proposal=context.proposal, knowledge_item=item)


def _apply_knowledge_archive(context: ProposalApplyContext) -> ProposalApplyResult:
    from .service import KnowledgeProposalApplier

    try:
        item = KnowledgeProposalApplier(context.db).apply_archive(
            context.proposal, user_id=context.user_id
        )
    except Exception as exc:  # noqa: BLE001
        raise ProposalApplyError(str(exc)) from exc
    return ProposalApplyResult(proposal=context.proposal, knowledge_item=item)


def _apply_knowledge_relation_create(context: ProposalApplyContext) -> ProposalApplyResult:
    from .service import KnowledgeProposalApplier

    try:
        relation = KnowledgeProposalApplier(context.db).apply_relation_create(
            context.proposal, user_id=context.user_id
        )
    except Exception as exc:  # noqa: BLE001
        raise ProposalApplyError(str(exc)) from exc
    return ProposalApplyResult(proposal=context.proposal, knowledge_relation=relation)


def _apply_knowledge_relation_delete(context: ProposalApplyContext) -> ProposalApplyResult:
    from .service import KnowledgeProposalApplier

    try:
        relation = KnowledgeProposalApplier(context.db).apply_relation_delete(
            context.proposal, user_id=context.user_id
        )
    except Exception as exc:  # noqa: BLE001
        raise ProposalApplyError(str(exc)) from exc
    return ProposalApplyResult(proposal=context.proposal, knowledge_relation=relation)


def register_proposal_appliers(registry: ProposalApplierRegistry) -> None:
    """Register every knowledge-owned proposal applier."""
    registry.register("knowledge_create", _apply_knowledge_create)
    registry.register("knowledge_update", _apply_knowledge_update)
    registry.register("knowledge_archive", _apply_knowledge_archive)
    registry.register("knowledge_relation_create", _apply_knowledge_relation_create)
    registry.register("knowledge_relation_delete", _apply_knowledge_relation_delete)
