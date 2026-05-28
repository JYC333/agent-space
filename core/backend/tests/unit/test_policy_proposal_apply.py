"""Unit tests for check_proposal_apply_policy, effective_proposal_risk, and ProposalRiskLevelError.

Covers Scopes C, D (effective risk), and J test requirements.
"""
from __future__ import annotations

import pytest
from ulid import ULID

from app.memory.apply_service import ProposalApplyService
from app.policy.decisions import Decision, RiskLevel
from app.policy.proposal_apply import (
    KNOWLEDGE_PROPOSAL_TYPES,
    ProposalRiskLevelError,
    SUPPORTED_PROPOSAL_TYPES,
    check_proposal_apply_policy,
    effective_proposal_risk,
)
from tests.support import factories


def _uid() -> str:
    return str(ULID())


def _make_space_user(db, space_id: str, role: str):
    from app.models import SpaceMembership, User

    uid = _uid()
    db.add(User(id=uid, display_name=role, email=f"{uid}@test.invalid"))
    db.add(SpaceMembership(id=_uid(), space_id=space_id, user_id=uid, role=role, status="active"))
    db.flush()
    return uid


# ---------------------------------------------------------------------------
# effective_proposal_risk
# ---------------------------------------------------------------------------

def test_effective_risk_uses_type_default_when_no_declared():
    assert effective_proposal_risk("memory_create", None) == RiskLevel.MEDIUM
    assert effective_proposal_risk("code_patch", None) == RiskLevel.HIGH
    assert effective_proposal_risk("policy_change", None) == RiskLevel.HIGH
    assert effective_proposal_risk("follow_up_task", None) == RiskLevel.MEDIUM
    assert effective_proposal_risk("knowledge_create", None) == RiskLevel.MEDIUM


def test_effective_risk_uses_higher_of_type_and_declared():
    assert effective_proposal_risk("memory_update", "high") == RiskLevel.HIGH
    assert effective_proposal_risk("memory_update", "critical") == RiskLevel.CRITICAL
    assert effective_proposal_risk("code_patch", "medium") == RiskLevel.HIGH


def test_effective_risk_declared_equals_type_returns_type():
    assert effective_proposal_risk("memory_create", "medium") == RiskLevel.MEDIUM


def test_effective_risk_low_declared_doesnt_downgrade_type():
    assert effective_proposal_risk("memory_create", "low") == RiskLevel.MEDIUM


def test_effective_risk_unknown_type_defaults_to_high():
    assert effective_proposal_risk("workspace_profile_update", None) == RiskLevel.HIGH
    assert effective_proposal_risk("workspace_profile_update", "low") == RiskLevel.HIGH


def test_effective_risk_invalid_declared_raises():
    with pytest.raises(ProposalRiskLevelError) as exc_info:
        effective_proposal_risk("memory_create", "forbidden")
    assert exc_info.value.risk_value == "forbidden"
    assert "Invalid proposal risk_level" in str(exc_info.value)


def test_effective_risk_empty_string_treated_as_none():
    assert effective_proposal_risk("memory_create", "") == RiskLevel.MEDIUM


# ---------------------------------------------------------------------------
# check_proposal_apply_policy — no DB needed (uses SimpleNamespace)
# ---------------------------------------------------------------------------

class _FakeProposal:
    def __init__(self, proposal_type: str, risk_level: str | None, proposal_id: str = "prop-1"):
        self.id = proposal_id
        self.proposal_type = proposal_type
        self.risk_level = risk_level


def test_check_policy_owner_returns_allow(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    prop = _FakeProposal("memory_create", "low")
    decision = check_proposal_apply_policy(db, user_id=ua.id, space_id=a, proposal=prop)
    assert decision.decision == Decision.ALLOW
    assert decision.audit_code == "approved_owner"
    assert decision.action == "proposal.apply"
    assert decision.resource_type == "proposal"
    assert decision.resource_id == "prop-1"
    assert decision.proposal_type == "memory_create"
    assert decision.approval_capability == "approve_proposal"
    assert decision.risk_level == RiskLevel.MEDIUM


def test_check_policy_admin_low_medium_high_returns_allow(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    for proposal_type, risk_level in [
        ("memory_create", None),
        ("memory_update", None),
        ("code_patch", None),
        ("policy_change", None),
    ]:
        admin_id = _make_space_user(db, a, "admin")
        prop = _FakeProposal(proposal_type, risk_level)
        decision = check_proposal_apply_policy(db, user_id=admin_id, space_id=a, proposal=prop)
        assert decision.decision == Decision.ALLOW, f"Admin should approve {proposal_type}"
        assert decision.audit_code == "approved_admin"


def test_check_policy_admin_cannot_approve_critical(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    admin_id = _make_space_user(db, a, "admin")
    prop = _FakeProposal("memory_update", "critical")
    decision = check_proposal_apply_policy(db, user_id=admin_id, space_id=a, proposal=prop)
    assert decision.decision == Decision.REQUIRE_APPROVAL
    assert decision.audit_code == "insufficient_role"
    assert decision.risk_level == RiskLevel.CRITICAL


def test_check_policy_owner_can_approve_critical(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    prop = _FakeProposal("memory_update", "critical")
    decision = check_proposal_apply_policy(db, user_id=ua.id, space_id=a, proposal=prop)
    assert decision.decision == Decision.ALLOW
    assert decision.risk_level == RiskLevel.CRITICAL


def test_check_policy_member_returns_require_approval(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    member_id = _make_space_user(db, a, "member")
    prop = _FakeProposal("memory_create", None)
    decision = check_proposal_apply_policy(db, user_id=member_id, space_id=a, proposal=prop)
    assert decision.decision == Decision.REQUIRE_APPROVAL
    assert decision.audit_code == "insufficient_role"


def test_check_policy_no_membership_returns_require_approval(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    outsider_id = _uid()
    prop = _FakeProposal("memory_create", None)
    decision = check_proposal_apply_policy(db, user_id=outsider_id, space_id=a, proposal=prop)
    assert decision.decision == Decision.REQUIRE_APPROVAL
    assert decision.audit_code == "no_membership"


def test_check_policy_invalid_risk_raises_before_role_check(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    prop = _FakeProposal("memory_create", "forbidden")
    with pytest.raises(ProposalRiskLevelError):
        check_proposal_apply_policy(db, user_id=ua.id, space_id=a, proposal=prop)


def test_check_policy_decision_metadata_json_present(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    prop = _FakeProposal("policy_change", "high")
    decision = check_proposal_apply_policy(db, user_id=ua.id, space_id=a, proposal=prop)
    assert decision.metadata_json is not None
    meta = decision.metadata_json
    assert meta["proposal_type"] == "policy_change"
    assert meta["membership_role"] == "owner"
    assert meta["effective_risk"] == "high"
    assert meta["proposal_declared_risk"] == "high"
    assert meta["default_type_risk"] == "high"
    assert meta["supported_apply_type"] is True


def test_check_policy_metadata_supported_apply_type_true_for_known_types(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    for proposal_type in ["memory_create", "memory_update", "memory_archive", "follow_up_task",
                          "code_patch", "policy_change", "egress_review",
                          "knowledge_create", "knowledge_update", "knowledge_archive",
                          "knowledge_relation_create", "knowledge_relation_delete"]:
        prop = _FakeProposal(proposal_type, None)
        decision = check_proposal_apply_policy(db, user_id=ua.id, space_id=a, proposal=prop)
        assert decision.metadata_json["supported_apply_type"] is True, (
            f"Expected supported_apply_type=True for {proposal_type}"
        )


def test_check_policy_unsupported_type_returns_deny(db, cross_space_pair_db):
    """Unsupported proposal types are denied at the policy gate before any role check."""
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    prop = _FakeProposal("workspace_profile_update", None)
    decision = check_proposal_apply_policy(db, user_id=ua.id, space_id=a, proposal=prop)
    assert decision.decision == Decision.DENY
    assert decision.audit_code == "unsupported_proposal_type"
    assert decision.risk_level == RiskLevel.HIGH
    assert decision.audit_code == "unsupported_proposal_type"
    assert decision.metadata_json["supported_apply_type"] is False


def test_knowledge_proposal_types_are_supported_after_apply_handlers_exist(db, cross_space_pair_db):
    """Knowledge proposal names are supported because ProposalApplyService has handlers."""
    expected = {
        "knowledge_create",
        "knowledge_update",
        "knowledge_archive",
        "knowledge_relation_create",
        "knowledge_relation_delete",
    }
    assert KNOWLEDGE_PROPOSAL_TYPES == expected
    assert KNOWLEDGE_PROPOSAL_TYPES.issubset(SUPPORTED_PROPOSAL_TYPES)
    assert ProposalApplyService.supported_types() == SUPPORTED_PROPOSAL_TYPES

    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    for proposal_type in sorted(KNOWLEDGE_PROPOSAL_TYPES):
        decision = check_proposal_apply_policy(
            db,
            user_id=ua.id,
            space_id=a,
            proposal=_FakeProposal(proposal_type, None),
        )
        assert decision.decision == Decision.ALLOW
        assert decision.audit_code == "approved_owner"
        assert decision.metadata_json["supported_apply_type"] is True


def test_check_policy_unsupported_type_denied_even_for_owner(db, cross_space_pair_db):
    """Owner role does not bypass the unsupported-type gate."""
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    prop = _FakeProposal("publish_content", None)
    decision = check_proposal_apply_policy(db, user_id=ua.id, space_id=a, proposal=prop)
    assert decision.decision == Decision.DENY
    assert decision.audit_code == "unsupported_proposal_type"


# ---------------------------------------------------------------------------
# Stable machine-readable fields: reason_code, policy_rule_id, actor_type
# ---------------------------------------------------------------------------

def test_check_policy_all_decisions_carry_reason_code_actor_type(db, cross_space_pair_db):
    """Every decision returned by check_proposal_apply_policy must carry reason_code,
    policy_rule_id, and actor_type='user'."""
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    outsider_id = _uid()
    admin_id = _make_space_user(db, a, "admin")
    reviewer_id = _make_space_user(db, a, "reviewer")
    member_id = _make_space_user(db, a, "member")

    cases = [
        ("workspace_profile_update", ua.id, "unsupported_proposal_type", "proposal_type_not_supported"),
        ("memory_create", outsider_id, "no_membership", "proposal_apply_no_membership"),
        ("memory_create", ua.id, "approved_owner", "proposal_apply_owner_allow"),
        ("memory_create", admin_id, "approved_admin", "proposal_apply_admin_allow"),
        ("memory_create", reviewer_id, "approved_reviewer", "proposal_apply_reviewer_allow"),
        ("memory_create", member_id, "insufficient_role", "proposal_apply_insufficient_role"),
    ]

    for proposal_type, user_id, expected_reason, expected_rule_id in cases:
        prop = _FakeProposal(proposal_type, None, proposal_id=_uid())
        decision = check_proposal_apply_policy(db, user_id=user_id, space_id=a, proposal=prop)
        assert decision.reason_code == expected_reason, (
            f"case {proposal_type}/{user_id}: expected reason_code={expected_reason!r}, "
            f"got {decision.reason_code!r}"
        )
        assert decision.policy_rule_id == expected_rule_id, (
            f"case {proposal_type}/{user_id}: expected policy_rule_id={expected_rule_id!r}, "
            f"got {decision.policy_rule_id!r}"
        )
        assert decision.actor_type == "user", (
            f"case {proposal_type}/{user_id}: expected actor_type='user', got {decision.actor_type!r}"
        )


# ---------------------------------------------------------------------------
# ProposalService.accept effective risk integration
# ---------------------------------------------------------------------------

def test_accept_with_critical_risk_level_denied_for_admin(db, cross_space_pair_db):
    """memory_update with risk_level=critical cannot be accepted by admin."""
    from app.memory.proposals import ProposalService
    from app.policy.exceptions import PolicyGateBlocked
    from tests.support.factories import create_test_memory_entry, create_test_proposal

    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    admin_id = _make_space_user(db, a, "admin")

    target = create_test_memory_entry(
        db, space_id=a, content="old", scope_type="agent", namespace="ns.critrisk",
        owner_user_id=ua.id, commit=False,
    )
    target.visibility = "space_shared"
    db.flush()

    prop = create_test_proposal(
        db, space_id=a, created_by_user_id=ua.id,
        proposal_type="memory_update",
        payload_json={"target_memory_id": target.id},
        commit=False,
    )
    prop.risk_level = "critical"
    db.flush()

    with pytest.raises(PolicyGateBlocked) as exc_info:
        ProposalService(db).accept(prop.id, space_id=a, user_id=admin_id)

    assert exc_info.value.decision.risk_level.value == "critical"
    assert exc_info.value.decision.proposal_type == "memory_update"
    db.refresh(prop)
    assert prop.status == "pending"


def test_accept_with_critical_risk_level_allowed_for_owner(db, cross_space_pair_db):
    """Owner can accept critical-risk proposal."""
    from app.memory.proposals import ProposalService
    from tests.support.factories import create_test_memory_entry, create_test_proposal

    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]

    target = create_test_memory_entry(
        db, space_id=a, content="old", scope_type="agent", namespace="ns.critowner",
        owner_user_id=ua.id, commit=False,
    )
    target.visibility = "space_shared"
    db.flush()

    prop = create_test_proposal(
        db, space_id=a, created_by_user_id=ua.id,
        proposal_type="memory_update",
        payload_json={"target_memory_id": target.id},
        commit=False,
    )
    prop.risk_level = "critical"
    db.commit()

    result = ProposalService(db).accept(prop.id, space_id=a, user_id=ua.id)
    assert result is not None
    db.refresh(prop)
    assert prop.status == "accepted"


def test_denied_proposal_error_carries_full_fields(db, cross_space_pair_db):
    """PolicyGateBlocked carries proposal context and decision fields."""
    from app.memory.proposals import ProposalService
    from app.policy.exceptions import PolicyGateBlocked
    from tests.support.factories import create_test_proposal

    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    member_id = _make_space_user(db, a, "member")

    prop = create_test_proposal(
        db, space_id=a, created_by_user_id=ua.id,
        proposal_type="memory_create", commit=True,
    )

    with pytest.raises(PolicyGateBlocked) as exc_info:
        ProposalService(db).accept(prop.id, space_id=a, user_id=member_id)

    err = exc_info.value
    assert err.proposal_id == prop.id
    assert err.decision.proposal_type == "memory_create"
    assert err.decision.risk_level.value == "medium"
    assert err.decision.decision.value == "require_approval"
    assert err.decision.audit_code == "insufficient_role"
    assert err.decision.message


# ---------------------------------------------------------------------------
# invalid risk_level unit coverage (DB constraint prevents storage, so tested via fake proposal)
# ---------------------------------------------------------------------------

def test_invalid_risk_level_raises_in_check_policy_before_any_side_effect():
    """ProposalRiskLevelError is raised before role check — no DB needed."""
    prop = _FakeProposal("memory_create", "forbidden")

    class _FakeDB:
        pass

    with pytest.raises(ProposalRiskLevelError):
        check_proposal_apply_policy(_FakeDB(), user_id="any", space_id="any", proposal=prop)


# ---------------------------------------------------------------------------
# Reviewer role — approves low and medium risk, not high or critical
# ---------------------------------------------------------------------------

def test_check_policy_reviewer_can_approve_medium_risk_memory(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    reviewer_id = _make_space_user(db, a, "reviewer")
    prop = _FakeProposal("memory_create", None)  # default risk=medium
    decision = check_proposal_apply_policy(db, user_id=reviewer_id, space_id=a, proposal=prop)
    assert decision.decision == Decision.ALLOW
    assert decision.audit_code == "approved_reviewer"
    assert decision.risk_level == RiskLevel.MEDIUM


def test_check_policy_reviewer_can_approve_low_risk(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    reviewer_id = _make_space_user(db, a, "reviewer")
    prop = _FakeProposal("memory_create", "low")  # declared low, type default medium → stays medium
    # effective risk is max(medium, low) = medium → reviewer can approve
    decision = check_proposal_apply_policy(db, user_id=reviewer_id, space_id=a, proposal=prop)
    assert decision.decision == Decision.ALLOW
    assert decision.audit_code == "approved_reviewer"


def test_check_policy_reviewer_cannot_approve_high_risk_code_patch(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    reviewer_id = _make_space_user(db, a, "reviewer")
    prop = _FakeProposal("code_patch", None)  # default risk=high
    decision = check_proposal_apply_policy(db, user_id=reviewer_id, space_id=a, proposal=prop)
    assert decision.decision == Decision.REQUIRE_APPROVAL
    assert decision.audit_code == "insufficient_role"
    assert decision.risk_level == RiskLevel.HIGH


def test_check_policy_reviewer_cannot_approve_critical(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    reviewer_id = _make_space_user(db, a, "reviewer")
    prop = _FakeProposal("memory_update", "critical")
    decision = check_proposal_apply_policy(db, user_id=reviewer_id, space_id=a, proposal=prop)
    assert decision.decision == Decision.REQUIRE_APPROVAL
    assert decision.audit_code == "insufficient_role"
    assert decision.risk_level == RiskLevel.CRITICAL
