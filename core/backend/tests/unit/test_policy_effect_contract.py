from __future__ import annotations

import pytest

from app.memory.apply_service import ProposalApplyError, ProposalApplyService
from app.models import Policy
from app.policy.access import ActivePolicyDecision, get_active_policy_match
from app.policy.domains import MEMORY_PRIVATE_PLACEMENT, RUN_USER_PRIVATE_SCOPE
from app.policy.effects import (
    POLICY_EFFECT_CATALOG,
    get_policy_effect_definition,
    validate_policy_change_payload,
)
from tests.support import factories


def _policy_change(db, space_id: str, user_id: str, **payload):
    base = {
        "operation": "create",
        "domain": "memory.private_placement",
        "policy_key": "effect-contract-test",
        "enforcement_mode": "allow_with_log",
        "rule_json": {"effect": "allow_with_log"},
        "applies_to_json": {"policy_domain": "memory.private_placement"},
    }
    base.update(payload)
    return factories.create_test_proposal(
        db,
        space_id=space_id,
        created_by_user_id=user_id,
        proposal_type="policy_change",
        payload_json=base,
        commit=True,
    )


def _apply(db, proposal, user_id: str):
    return ProposalApplyService(db).apply(
        proposal,
        user_id=user_id,
        bypass_source_monitoring=True,
    )


def test_unsupported_policy_change_domain_is_rejected(db, cross_space_pair_db):
    space_id = cross_space_pair_db["space_a_id"]
    user_id = cross_space_pair_db["user_a"].id
    proposal = _policy_change(db, space_id, user_id, domain="memory")
    before = db.query(Policy).filter(Policy.space_id == space_id).count()

    with pytest.raises(ProposalApplyError, match="no policy effect definition"):
        _apply(db, proposal, user_id)

    assert db.query(Policy).filter(Policy.space_id == space_id).count() == before


def test_reserved_domain_cannot_become_active(db, cross_space_pair_db):
    space_id = cross_space_pair_db["space_a_id"]
    user_id = cross_space_pair_db["user_a"].id
    proposal = _policy_change(db, space_id, user_id, domain="runtime.execute")
    before = db.query(Policy).filter(Policy.space_id == space_id).count()

    with pytest.raises(ProposalApplyError, match="reserved"):
        _apply(db, proposal, user_id)

    assert db.query(Policy).filter(Policy.space_id == space_id).count() == before


@pytest.mark.parametrize("domain", ["memory.private_placement", "run.user_private_scope"])
def test_supported_policy_change_can_apply(db, cross_space_pair_db, domain):
    space_id = cross_space_pair_db["space_a_id"]
    user_id = cross_space_pair_db["user_a"].id
    proposal = _policy_change(
        db,
        space_id,
        user_id,
        domain=domain,
        applies_to_json={"policy_domain": domain},
    )

    result = _apply(db, proposal, user_id)

    assert result.policy is not None
    assert result.policy.status == "active"
    assert result.policy.domain == domain
    assert get_policy_effect_definition(result.policy.domain).supported is True


@pytest.mark.parametrize(
    ("domain", "effect", "decision"),
    [
        (MEMORY_PRIVATE_PLACEMENT, "deny", ActivePolicyDecision.DENY),
        (RUN_USER_PRIVATE_SCOPE, "allow_with_log", ActivePolicyDecision.ALLOW_WITH_LOG),
    ],
)
def test_applied_supported_policy_row_matches_active_lookup(
    db, cross_space_pair_db, domain, effect, decision
):
    space_id = cross_space_pair_db["space_a_id"]
    user_id = cross_space_pair_db["user_a"].id
    proposal = _policy_change(
        db,
        space_id,
        user_id,
        domain=f" {domain} ",
        policy_key=None,
        enforcement_mode=f" {effect.upper()} ",
        rule_json={"effect": f" {effect.upper()} "},
        applies_to_json=None,
    )

    result = _apply(db, proposal, user_id)
    match = get_active_policy_match(db, space_id=space_id, domain=domain)

    assert result.policy is not None
    assert result.policy.domain == domain
    assert result.policy.enforcement_mode == effect
    assert result.policy.rule_json == {"effect": effect}
    assert result.policy.applies_to_json is None
    assert match.policy_id == result.policy.id
    assert match.decision == decision


def test_policy_applier_persists_normalized_effect_contract_fields(db, cross_space_pair_db):
    space_id = cross_space_pair_db["space_a_id"]
    user_id = cross_space_pair_db["user_a"].id
    proposal = _policy_change(
        db,
        space_id,
        user_id,
        domain=" MEMORY.PRIVATE_PLACEMENT ",
        policy_key=None,
        enforcement_mode=" DENY ",
        rule_json={"effect": " DENY ", "policy_domain": " MEMORY.PRIVATE_PLACEMENT "},
        applies_to_json={"policy_domain": " MEMORY.PRIVATE_PLACEMENT "},
    )

    result = _apply(db, proposal, user_id)

    assert result.policy is not None
    assert result.policy.domain == MEMORY_PRIVATE_PLACEMENT
    assert result.policy.enforcement_mode == "deny"
    assert result.policy.rule_json == {
        "effect": "deny",
        "policy_domain": MEMORY_PRIVATE_PLACEMENT,
    }
    assert result.policy.applies_to_json == {"policy_domain": MEMORY_PRIVATE_PLACEMENT}
    assert result.policy.enforcement_mode == result.policy.rule_json["effect"]


def test_invalid_enforcement_mode_is_rejected():
    with pytest.raises(ValueError, match="enforcement_mode"):
        validate_policy_change_payload(
            {
                "domain": "memory.private_placement",
                "enforcement_mode": "observe",
                "rule_json": {"effect": "deny"},
            }
        )


@pytest.mark.parametrize(
    "metadata",
    [
        {"Auto_Approved": True},
        {"APPROVAL_STATUS": "approved"},
        {" nested ": [{" Pre_Approved ": True}]},
    ],
)
def test_approval_proof_flags_are_rejected_case_insensitively_anywhere(metadata):
    with pytest.raises(ValueError, match="approval-proof"):
        validate_policy_change_payload(
            {
                "domain": "memory.private_placement",
                "enforcement_mode": "deny",
                "metadata": metadata,
                "rule_json": {"effect": "deny"},
            }
        )


def test_enforcement_mode_and_rule_json_effect_mismatch_is_rejected():
    with pytest.raises(ValueError, match="must match rule_json.effect"):
        validate_policy_change_payload(
            {
                "domain": "memory.private_placement",
                "enforcement_mode": "deny",
                "rule_json": {"effect": "allow_with_log"},
            }
        )


def test_omitted_enforcement_mode_derives_from_rule_json_effect():
    normalized = validate_policy_change_payload(
        {
            "domain": "memory.private_placement",
            "rule_json": {"effect": " allow_with_log "},
        }
    )

    assert normalized.enforcement_mode == "allow_with_log"
    assert normalized.rule_json["effect"] == "allow_with_log"


def test_matching_enforcement_mode_and_rule_json_effect_passes():
    normalized = validate_policy_change_payload(
        {
            "domain": "memory.private_placement",
            "enforcement_mode": " DENY ",
            "rule_json": {"effect": " deny "},
        }
    )

    assert normalized.enforcement_mode == "deny"
    assert normalized.rule_json["effect"] == "deny"


def test_active_policy_rows_in_fixtures_have_supported_effect_definitions(db):
    active = (
        db.query(Policy)
        .filter(
            Policy.status == "active",
            Policy.enabled.is_(True),
            Policy.created_from_proposal_id.isnot(None),
        )
        .all()
    )
    unsupported = [
        row.domain
        for row in active
        if row.domain not in POLICY_EFFECT_CATALOG
        or not POLICY_EFFECT_CATALOG[row.domain].supported
    ]
    assert unsupported == []
