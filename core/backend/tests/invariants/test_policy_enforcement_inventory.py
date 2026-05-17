"""Behavior tests: Phase 6 memory-access policy domains are registered and enforced."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from ulid import ULID

from app.memory.retriever import MemoryRetriever
from app.memory.store import MemoryStore
from app.policy.access import (
    ActivePolicyDecision,
    get_active_policy_decision,
    get_active_policy_match,
    policy_denies,
)
from app.policy.domains import (
    ALL_REGISTERED_DOMAINS,
    DOMAIN_REGISTRY,
    MEMORY_CROSS_SPACE_READ,
    MEMORY_PRIVATE_PLACEMENT,
    MEMORY_WRITE_DIRECT,
    RUN_USER_PRIVATE_SCOPE,
)
from app.schemas import MemoryCreate
from tests.support import factories


def _new_id() -> str:
    return str(ULID())


def _policy_row(
    db,
    *,
    space_id: str,
    domain: str,
    effect: str,
    priority: int = 0,
    status: str = "active",
    enabled: bool = True,
):
    return factories.create_test_policy(
        db,
        space_id=space_id,
        domain=domain.split(".", 1)[0],
        policy_key=domain,
        enforcement_mode=effect,
        priority=priority,
        status=status,
        enabled=enabled,
        rule_json={"policy_domain": domain, "effect": effect},
        commit=True,
    )


def _team_space(db):
    space_id = _new_id()
    factories.create_test_space(db, space_id=space_id, name="Team", space_type="team")
    user = factories.create_test_user(db, space_id=space_id, display_name="Team User")
    db.commit()
    return space_id, user


def _personal_space(db):
    space_id = _new_id()
    factories.create_test_space(db, space_id=space_id, name="Personal", space_type="personal")
    user = factories.create_test_user(db, space_id=space_id, display_name="Personal User")
    db.commit()
    return space_id, user


def _private_memory(db, *, space_id: str, owner_user_id: str, content: str = "secret"):
    from app.models import MemoryEntry

    m = MemoryEntry(
        id=_new_id(),
        space_id=space_id,
        scope_type="user",
        memory_type="semantic",
        content=content,
        status="active",
        visibility="private",
        owner_user_id=owner_user_id,
        subject_user_id=owner_user_id,
    )
    db.add(m)
    db.flush()
    return m


# ---------------------------------------------------------------------------
# Registry and canonical policy lookup
# ---------------------------------------------------------------------------


def test_phase6_domain_constants_registered():
    for domain in (
        MEMORY_WRITE_DIRECT,
        MEMORY_PRIVATE_PLACEMENT,
        RUN_USER_PRIVATE_SCOPE,
        MEMORY_CROSS_SPACE_READ,
    ):
        assert domain in ALL_REGISTERED_DOMAINS
        assert domain in DOMAIN_REGISTRY


def test_policy_lookup_ignores_draft_disabled_superseded(db):
    space_id, _user = _team_space(db)
    _policy_row(db, space_id=space_id, domain=MEMORY_PRIVATE_PLACEMENT, effect="deny", status="draft")
    _policy_row(
        db, space_id=space_id, domain=MEMORY_PRIVATE_PLACEMENT, effect="deny", enabled=False
    )
    _policy_row(
        db,
        space_id=space_id,
        domain=MEMORY_PRIVATE_PLACEMENT,
        effect="deny",
        status="superseded",
    )
    assert (
        get_active_policy_decision(db, space_id=space_id, domain=MEMORY_PRIVATE_PLACEMENT)
        == ActivePolicyDecision.NO_POLICY
    )


def test_highest_priority_active_policy_wins_deterministically(db):
    space_id, _user = _team_space(db)
    low = _policy_row(
        db, space_id=space_id, domain=RUN_USER_PRIVATE_SCOPE, effect="deny", priority=1
    )
    high = _policy_row(
        db, space_id=space_id, domain=RUN_USER_PRIVATE_SCOPE, effect="allow_with_log", priority=99
    )
    match = get_active_policy_match(db, space_id=space_id, domain=RUN_USER_PRIVATE_SCOPE)
    assert match.decision == ActivePolicyDecision.ALLOW_WITH_LOG
    assert match.policy_id == high.id
    assert match.policy_id != low.id


def test_malformed_policy_effect_fails_safe_for_security_sensitive_domain(db):
    space_id, _user = _team_space(db)
    factories.create_test_policy(
        db,
        space_id=space_id,
        domain="memory",
        policy_key=MEMORY_PRIVATE_PLACEMENT,
        enforcement_mode=None,
        rule_json={"policy_domain": MEMORY_PRIVATE_PLACEMENT, "effect": "not-a-real-effect"},
        commit=True,
    )
    assert (
        get_active_policy_decision(db, space_id=space_id, domain=MEMORY_PRIVATE_PLACEMENT)
        == ActivePolicyDecision.DENY
    )


# ---------------------------------------------------------------------------
# A. memory.private_placement
# ---------------------------------------------------------------------------


def test_memory_private_placement_domain_registered():
    assert MEMORY_PRIVATE_PLACEMENT in DOMAIN_REGISTRY
    assert DOMAIN_REGISTRY[MEMORY_PRIVATE_PLACEMENT].status == "enforced"


def test_enforcement_helper_recognizes_private_placement_domain(db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    decision = get_active_policy_decision(db, space_id=a, domain=MEMORY_PRIVATE_PLACEMENT)
    assert decision == ActivePolicyDecision.NO_POLICY


def test_private_memory_write_to_team_space_rejected(db):
    space_id, user = _team_space(db)
    with pytest.raises(ValueError, match="personal"):
        MemoryStore(db).create(
            MemoryCreate(
                title="x",
                space_id=space_id,
                scope="user",
                type="semantic",
                content="nope",
                visibility="private",
                owner_user_id=user.id,
            ),
            acting_user_id=user.id,
        )


def test_private_memory_write_to_personal_space_allowed(db):
    space_id, user = _personal_space(db)
    mem = MemoryStore(db).create(
        MemoryCreate(
            title="ok",
            space_id=space_id,
            scope="user",
            type="semantic",
            content="personal-private",
            visibility="private",
            owner_user_id=user.id,
        ),
        acting_user_id=user.id,
    )
    assert mem.visibility == "private"


def test_space_shared_write_to_team_space_allowed(db):
    space_id, user = _team_space(db)
    mem = MemoryStore(db).create(
        MemoryCreate(
            title="shared",
            space_id=space_id,
            scope="agent",
            type="semantic",
            content="team-shared",
            visibility="space_shared",
        ),
        acting_user_id=user.id,
    )
    assert mem.visibility == "space_shared"


def test_active_deny_policy_does_not_weaken_private_placement_rejection(db):
    space_id, user = _team_space(db)
    _policy_row(db, space_id=space_id, domain=MEMORY_PRIVATE_PLACEMENT, effect="deny")
    with pytest.raises(ValueError, match="personal"):
        MemoryStore(db).create(
            MemoryCreate(
                title="deny policy",
                space_id=space_id,
                scope="user",
                type="semantic",
                content="still blocked",
                visibility="private",
                owner_user_id=user.id,
            ),
            acting_user_id=user.id,
        )


def test_active_allow_policy_cannot_permit_private_in_team_space(db):
    space_id, user = _team_space(db)
    _policy_row(db, space_id=space_id, domain=MEMORY_PRIVATE_PLACEMENT, effect="allow")
    with pytest.raises(ValueError, match="personal"):
        MemoryStore(db).create(
            MemoryCreate(
                title="allow override attempt",
                space_id=space_id,
                scope="user",
                type="semantic",
                content="allow cannot override",
                visibility="private",
                owner_user_id=user.id,
            ),
            acting_user_id=user.id,
        )


def test_no_policy_row_hard_invariant_still_rejects_unsafe_placement(db):
    space_id, user = _team_space(db)
    assert (
        get_active_policy_decision(db, space_id=space_id, domain=MEMORY_PRIVATE_PLACEMENT)
        == ActivePolicyDecision.NO_POLICY
    )
    with pytest.raises(ValueError, match="personal"):
        MemoryStore(db).create(
            MemoryCreate(
                title="hard invariant",
                space_id=space_id,
                scope="user",
                type="semantic",
                content="hard invariant",
                visibility="private",
                owner_user_id=user.id,
            ),
            acting_user_id=user.id,
        )


# ---------------------------------------------------------------------------
# B. run.user_private_scope
# ---------------------------------------------------------------------------


def test_run_user_private_scope_domain_registered():
    assert RUN_USER_PRIVATE_SCOPE in DOMAIN_REGISTRY
    assert DOMAIN_REGISTRY[RUN_USER_PRIVATE_SCOPE].status == "enforced"


def test_enforcement_helper_recognizes_user_private_scope_domain(db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    decision = get_active_policy_decision(db, space_id=a, domain=RUN_USER_PRIVATE_SCOPE)
    assert decision == ActivePolicyDecision.NO_POLICY


def test_run_instructed_user_includes_same_space_private_memory(db):
    space_id, user = _personal_space(db)
    private = _private_memory(db, space_id=space_id, owner_user_id=user.id)
    db.commit()

    result = MemoryRetriever(db).retrieve(space_id=space_id, user_id=user.id)
    assert private.id in {m.id for m in result.memories}


def test_run_other_user_excludes_private_memory(db):
    space_id, user = _personal_space(db)
    private = _private_memory(db, space_id=space_id, owner_user_id=user.id)
    db.commit()

    other_id = _new_id()
    result = MemoryRetriever(db).retrieve(space_id=space_id, user_id=other_id)
    assert private.id not in {m.id for m in result.memories}


def test_run_without_instructed_user_excludes_private_memory(db):
    space_id, user = _personal_space(db)
    private = _private_memory(db, space_id=space_id, owner_user_id=user.id)
    db.commit()

    result = MemoryRetriever(db).retrieve(space_id=space_id, user_id="system")
    assert private.id not in {m.id for m in result.memories}


def test_active_deny_policy_disables_same_space_user_private_inclusion(db):
    space_id, user = _personal_space(db)
    private = _private_memory(db, space_id=space_id, owner_user_id=user.id)
    _policy_row(db, space_id=space_id, domain=RUN_USER_PRIVATE_SCOPE, effect="deny")
    db.commit()

    result = MemoryRetriever(db).retrieve(space_id=space_id, user_id=user.id)
    assert private.id not in {m.id for m in result.memories}
    assert policy_denies(
        get_active_policy_decision(db, space_id=space_id, domain=RUN_USER_PRIVATE_SCOPE)
    )


def test_active_allow_policy_does_not_enable_cross_space_personal_private(db):
    personal_id, user = _personal_space(db)
    shared_id = _new_id()
    factories.create_test_space(db, space_id=shared_id, name="Household", space_type="household")
    from app.models import SpaceMembership

    db.add(
        SpaceMembership(
            id=_new_id(),
            space_id=shared_id,
            user_id=user.id,
            role="member",
            status="active",
        )
    )
    personal_private = _private_memory(
        db, space_id=personal_id, owner_user_id=user.id, content="cross-boundary"
    )
    _policy_row(db, space_id=shared_id, domain=RUN_USER_PRIVATE_SCOPE, effect="allow")
    _policy_row(db, space_id=shared_id, domain=MEMORY_CROSS_SPACE_READ, effect="allow")
    db.commit()

    result = MemoryRetriever(db).retrieve(space_id=shared_id, user_id=user.id)
    assert personal_private.id not in {m.id for m in result.memories}


# ---------------------------------------------------------------------------
# C. memory.cross_space_read
# ---------------------------------------------------------------------------


def test_memory_cross_space_read_domain_deferred():
    assert MEMORY_CROSS_SPACE_READ in DOMAIN_REGISTRY
    spec = DOMAIN_REGISTRY[MEMORY_CROSS_SPACE_READ]
    assert spec.status in ("deferred", "deny_by_default")


def test_allow_with_log_on_space_shared_write_emits_trace(db):
    space_id, user = _team_space(db)
    _policy_row(db, space_id=space_id, domain=MEMORY_PRIVATE_PLACEMENT, effect="allow_with_log")
    with patch("app.policy.enforcement.record_policy_decision_trace") as trace:
        mem = MemoryStore(db).create(
            MemoryCreate(
                title="traced shared",
                space_id=space_id,
                scope="agent",
                type="semantic",
                content="shared ok",
                visibility="space_shared",
            ),
            acting_user_id=user.id,
        )
    assert mem.visibility == "space_shared"
    assert trace.called
    assert any(
        c.kwargs.get("domain") == MEMORY_PRIVATE_PLACEMENT
        and c.kwargs.get("outcome") == "allowed"
        for c in trace.call_args_list
    )


def test_allow_with_log_private_personal_write_emits_trace(db):
    space_id, user = _personal_space(db)
    _policy_row(db, space_id=space_id, domain=MEMORY_PRIVATE_PLACEMENT, effect="allow_with_log")
    with patch("app.policy.enforcement.record_policy_decision_trace") as trace:
        MemoryStore(db).create(
            MemoryCreate(
                title="traced private",
                space_id=space_id,
                scope="user",
                type="semantic",
                content="personal ok",
                visibility="private",
                owner_user_id=user.id,
            ),
            acting_user_id=user.id,
        )
    assert trace.called
    assert any(c.kwargs.get("outcome") == "allowed" for c in trace.call_args_list)


def test_private_placement_deny_emits_trace(db):
    space_id, user = _personal_space(db)
    _policy_row(db, space_id=space_id, domain=MEMORY_PRIVATE_PLACEMENT, effect="deny")
    with patch("app.policy.enforcement.record_policy_decision_trace") as trace:
        with pytest.raises(ValueError, match="denied by active policy"):
            MemoryStore(db).create(
                MemoryCreate(
                    title="denied",
                    space_id=space_id,
                    scope="user",
                    type="semantic",
                    content="nope",
                    visibility="private",
                    owner_user_id=user.id,
                ),
                acting_user_id=user.id,
            )
    assert any(c.kwargs.get("outcome") == "denied" for c in trace.call_args_list)


def test_run_user_private_scope_allow_with_log_traces_inclusion(db):
    space_id, user = _personal_space(db)
    private = _private_memory(db, space_id=space_id, owner_user_id=user.id)
    _policy_row(db, space_id=space_id, domain=RUN_USER_PRIVATE_SCOPE, effect="allow_with_log")
    db.commit()
    with patch("app.policy.enforcement.record_policy_decision_trace") as trace:
        result = MemoryRetriever(db).retrieve(space_id=space_id, user_id=user.id)
    assert private.id in {m.id for m in result.memories}
    assert any(
        c.kwargs.get("domain") == RUN_USER_PRIVATE_SCOPE
        and c.kwargs.get("outcome") == "allowed"
        and c.kwargs.get("subject_id") == private.id
        for c in trace.call_args_list
    )


def test_run_user_private_scope_deny_emits_trace(db):
    space_id, user = _personal_space(db)
    private = _private_memory(db, space_id=space_id, owner_user_id=user.id)
    _policy_row(db, space_id=space_id, domain=RUN_USER_PRIVATE_SCOPE, effect="deny")
    db.commit()
    with patch("app.policy.enforcement.record_policy_decision_trace") as trace:
        result = MemoryRetriever(db).retrieve(space_id=space_id, user_id=user.id)
    assert private.id not in {m.id for m in result.memories}
    assert any(
        c.kwargs.get("domain") == RUN_USER_PRIVATE_SCOPE and c.kwargs.get("outcome") == "denied"
        for c in trace.call_args_list
    )


def test_cross_space_allow_with_log_still_excludes_private_memory(db):
    """Cross-space rows never enter the SQL candidate set; exclusion is structural."""
    personal_id, user = _personal_space(db)
    shared_id = _new_id()
    factories.create_test_space(db, space_id=shared_id, name="Shared", space_type="team")
    from app.models import SpaceMembership

    db.add(
        SpaceMembership(
            id=_new_id(),
            space_id=shared_id,
            user_id=user.id,
            role="member",
            status="active",
        )
    )
    other_private = _private_memory(
        db, space_id=personal_id, owner_user_id=user.id, content="must-stay-personal"
    )
    _policy_row(db, space_id=shared_id, domain=MEMORY_CROSS_SPACE_READ, effect="allow_with_log")
    db.commit()
    result = MemoryRetriever(db).retrieve(space_id=shared_id, user_id=user.id)
    assert other_private.id not in {m.id for m in result.memories}
    assert result.retrieval_trace.get("hard_filter", {}).get("cross_space_blocked") is True


def test_cross_space_allow_policy_does_not_include_other_space_memory(db):
    personal_id, user = _personal_space(db)
    shared_id = _new_id()
    factories.create_test_space(db, space_id=shared_id, name="Shared", space_type="team")
    from app.models import SpaceMembership

    db.add(
        SpaceMembership(
            id=_new_id(),
            space_id=shared_id,
            user_id=user.id,
            role="member",
            status="active",
        )
    )
    other_private = _private_memory(
        db, space_id=personal_id, owner_user_id=user.id, content="must-stay-personal"
    )
    _policy_row(db, space_id=shared_id, domain=MEMORY_CROSS_SPACE_READ, effect="allow")
    db.commit()

    result = MemoryRetriever(db).retrieve(space_id=shared_id, user_id=user.id)
    assert other_private.id not in {m.id for m in result.memories}
