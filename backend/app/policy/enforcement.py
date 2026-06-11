from __future__ import annotations

"""Enforcement helpers — hard invariants plus Policy row audit trail."""

from typing import TYPE_CHECKING, Any

from .access import (
    ActivePolicyDecision,
    ActivePolicyMatch,
    get_active_policy_match,
    policy_denies,
)
from .domains import MEMORY_CROSS_SPACE_READ, MEMORY_PRIVATE_PLACEMENT, RUN_USER_PRIVATE_SCOPE
from .trace import record_policy_decision_trace

if TYPE_CHECKING:
    from ..models import MemoryEntry

_PLACEMENT_ENFORCEMENT = "app.memory.store.MemoryStore.create"
_RUN_CONTEXT_ENFORCEMENT = "app.memory.retriever.MemoryRetriever._hard_filter_row"


def _trace(
    *,
    db: Any,
    space_id: str,
    domain: str,
    match: ActivePolicyMatch,
    enforcement_point: str,
    subject_type: str,
    subject_id: str | None,
    actor_user_id: str | None,
    outcome: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    if match.decision == ActivePolicyDecision.NO_POLICY:
        return
    record_policy_decision_trace(
        db=db,
        space_id=space_id,
        domain=domain,
        decision=match.decision,
        enforcement_point=enforcement_point,
        subject_type=subject_type,
        subject_id=subject_id,
        actor_user_id=actor_user_id,
        policy_id=match.policy_id,
        policy_key=match.policy_key,
        outcome=outcome,
        metadata=metadata,
    )


def check_private_memory_placement(
    db: Any,
    *,
    space_id: str,
    visibility: str,
    acting_user_id: str | None = None,
) -> None:
    """
    Hard invariant: visibility=private only in personal spaces.

    Active Policy rows may document or reinforce denial; allow rows cannot weaken
    the invariant for non-personal spaces.
    """
    match = get_active_policy_match(
        db,
        space_id=space_id,
        domain=MEMORY_PRIVATE_PLACEMENT,
        action_context={"visibility": visibility},
    )
    vis = (visibility or "").lower()

    if vis != "private":
        if match.decision == ActivePolicyDecision.ALLOW_WITH_LOG:
            _trace(
                db=db,
                space_id=space_id,
                domain=MEMORY_PRIVATE_PLACEMENT,
                match=match,
                enforcement_point=_PLACEMENT_ENFORCEMENT,
                subject_type="memory_write",
                subject_id=space_id,
                actor_user_id=acting_user_id,
                outcome="allowed",
                metadata={"visibility": vis, "note": "non-private write"},
            )
        return

    from ..models import Space

    space = db.query(Space).filter(Space.id == space_id).first()
    space_type = space.type if space else "unknown"

    if space_type != "personal":
        trace_match = (
            match
            if match.decision != ActivePolicyDecision.NO_POLICY
            else ActivePolicyMatch(decision=ActivePolicyDecision.DENY, policy_key="hard_invariant")
        )
        _trace(
            db=db,
            space_id=space_id,
            domain=MEMORY_PRIVATE_PLACEMENT,
            match=trace_match,
            enforcement_point=_PLACEMENT_ENFORCEMENT,
            subject_type="memory_write",
            subject_id=space_id,
            actor_user_id=acting_user_id,
            outcome="denied",
            metadata={"visibility": vis, "space_type": space_type, "hard_invariant": True},
        )
        msg = (
            f"visibility='private' is only permitted in personal spaces; "
            f"space {space_id!r} has type {space_type!r}"
        )
        if policy_denies(match.decision):
            msg = f"{msg} (policy domain {MEMORY_PRIVATE_PLACEMENT})"
        raise ValueError(msg)

    if policy_denies(match.decision):
        _trace(
            db=db,
            space_id=space_id,
            domain=MEMORY_PRIVATE_PLACEMENT,
            match=match,
            enforcement_point=_PLACEMENT_ENFORCEMENT,
            subject_type="memory_write",
            subject_id=space_id,
            actor_user_id=acting_user_id,
            outcome="denied",
            metadata={"visibility": vis, "space_type": space_type},
        )
        raise ValueError(
            f"visibility='private' write denied by active policy "
            f"({MEMORY_PRIVATE_PLACEMENT}) in space {space_id!r}"
        )

    if match.decision == ActivePolicyDecision.ALLOW_WITH_LOG:
        _trace(
            db=db,
            space_id=space_id,
            domain=MEMORY_PRIVATE_PLACEMENT,
            match=match,
            enforcement_point=_PLACEMENT_ENFORCEMENT,
            subject_type="memory_write",
            subject_id=space_id,
            actor_user_id=acting_user_id,
            outcome="allowed",
            metadata={"visibility": vis, "space_type": space_type},
        )


def can_read_memory_in_run_context(
    memory: "MemoryEntry",
    *,
    user_id: str,
    space_id: str,
    workspace_id: str | None,
    db: Any,
    include_system_scope: bool = False,
) -> bool:
    """
    Run retrieval gate: same-space hard filter, owner-private rules, Policy rows.

    Cross-space reads are always denied (memory.cross_space_read remains deferred).
    """
    if memory.space_id != space_id:
        cross_match = get_active_policy_match(
            db,
            space_id=space_id,
            domain=MEMORY_CROSS_SPACE_READ,
            action_context={
                "requesting_space_id": space_id,
                "resource_space_id": memory.space_id,
            },
        )
        if cross_match.decision in (
            ActivePolicyDecision.ALLOW,
            ActivePolicyDecision.ALLOW_WITH_LOG,
        ):
            _trace(
                db=db,
                space_id=space_id,
                domain=MEMORY_CROSS_SPACE_READ,
                match=cross_match,
                enforcement_point=_RUN_CONTEXT_ENFORCEMENT,
                subject_type="memory",
                subject_id=memory.id,
                actor_user_id=user_id,
                outcome="denied",
                metadata={"reason": "cross_space_hard_filter"},
            )
        return False

    from ..memory import can_read_memory

    if not can_read_memory(
        memory,
        user_id=user_id,
        space_id=space_id,
        workspace_id=workspace_id,
        include_system_scope=include_system_scope,
    ):
        return False

    vis = (memory.visibility or "").lower()
    if vis != "private":
        return True

    if not user_id or user_id == "system":
        return False
    if memory.owner_user_id != user_id:
        return False

    scope_match = get_active_policy_match(
        db,
        space_id=space_id,
        domain=RUN_USER_PRIVATE_SCOPE,
        action_context={
            "user_id": user_id,
            "owner_user_id": memory.owner_user_id,
            "memory_space_id": memory.space_id,
            "run_space_id": space_id,
        },
    )
    if policy_denies(scope_match.decision):
        _trace(
            db=db,
            space_id=space_id,
            domain=RUN_USER_PRIVATE_SCOPE,
            match=scope_match,
            enforcement_point=_RUN_CONTEXT_ENFORCEMENT,
            subject_type="memory",
            subject_id=memory.id,
            actor_user_id=user_id,
            outcome="denied",
            metadata={
                "memory_space_id": memory.space_id,
                "run_space_id": space_id,
            },
        )
        return False

    if scope_match.decision == ActivePolicyDecision.ALLOW_WITH_LOG:
        _trace(
            db=db,
            space_id=space_id,
            domain=RUN_USER_PRIVATE_SCOPE,
            match=scope_match,
            enforcement_point=_RUN_CONTEXT_ENFORCEMENT,
            subject_type="memory",
            subject_id=memory.id,
            actor_user_id=user_id,
            outcome="allowed",
            metadata={
                "memory_space_id": memory.space_id,
                "run_space_id": space_id,
            },
        )

    return True
