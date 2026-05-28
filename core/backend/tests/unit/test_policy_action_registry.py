"""Unit tests for the canonical policy action registry (app/policy/actions.py)."""
from __future__ import annotations

import pytest

from app.policy.actions import (
    PolicyActionDefinition,
    PolicyActionLifecycle,
    UnknownPolicyActionError,
    get_action_definition,
    is_known_action,
    list_action_definitions,
    require_action_definition,
)
from app.policy.decisions import Decision, RiskLevel


# ---------------------------------------------------------------------------
# Registry completeness: wired_direct actions (direct PolicyGateway call site)
# ---------------------------------------------------------------------------

_WIRED_DIRECT_ACTIONS = [
    "runtime.execute",
    "runtime.use_credential",
    "context.inject_memory",
    "context.render_for_runtime",
    "workspace.write_patch",
    "workspace.read",
    "artifact.persist",
    "proposal.create",
    "proposal.apply",
    "agent.config_update",
    "automation.create",
    "automation.update",
    "automation.fire",
]

# Wired via the proposal.apply gate only — must not be called directly.
_WIRED_VIA_PROPOSAL_ACTIONS = [
    "memory.create",
    "memory.update",
    "memory.archive",
    "policy.change",
    "knowledge.create",
    "knowledge.update",
    "knowledge.archive",
    "knowledge.relation_create",
    "knowledge.relation_delete",
]

# Reserved actions (lifecycle_status=RESERVED) — registered for registry completeness
# and fail-closed defence-in-depth, but not yet wired to a preferred
# PolicyGateway enforcement call site.  current_enforcement_point="not_implemented".
_RESERVED_ACTIONS = [
    "context.use_personal_grant",
    "workspace.apply_patch",
    "artifact.export",
    "proposal.approve",
    "memory.read_private",
    "memory.promote_shared",
    "capability.enable",
    "capability.update",
    "tool_binding.enable",
    "deployment.propose",
    "deployment.execute",
]

_WIRED_ACTIONS = _WIRED_DIRECT_ACTIONS + _WIRED_VIA_PROPOSAL_ACTIONS
_EXPECTED_ACTIONS = _WIRED_ACTIONS + _RESERVED_ACTIONS

# Actions that are truly future-only — not in the registry at all.
# Must NOT appear in the registry until they have a real enforcement point or
# at least a reserved entry added here.
_NOT_IN_REGISTRY = [
    "cross_space_export",
    "agent.delegate",
]


def test_all_expected_actions_registered():
    for action in _EXPECTED_ACTIONS:
        assert is_known_action(action), f"Expected action {action!r} not in registry"


def test_truly_future_actions_not_in_registry():
    """Actions without even a reserved entry must not be in the registry."""
    for action in _NOT_IN_REGISTRY:
        assert not is_known_action(action), (
            f"Action {action!r} must not be in the registry — "
            "add a reserved entry first"
        )


def test_no_duplicate_action_names():
    names = [d.action for d in list_action_definitions()]
    assert len(names) == len(set(names)), "Registry contains duplicate action names"


def test_every_action_has_required_fields():
    """Every registered action (wired and reserved) must have non-empty required fields."""
    for defn in list_action_definitions():
        assert defn.action, f"{defn.action}: action must not be empty"
        assert defn.resource_type, f"{defn.action}: resource_type must not be empty"
        assert defn.default_risk_level in RiskLevel, (
            f"{defn.action}: default_risk_level must be a RiskLevel"
        )
        assert defn.default_decision in Decision, (
            f"{defn.action}: default_decision must be a Decision"
        )
        assert isinstance(defn.audit_required, bool), (
            f"{defn.action}: audit_required must be bool"
        )
        assert defn.current_enforcement_point, (
            f"{defn.action}: current_enforcement_point must not be empty"
        )
        assert defn.description, f"{defn.action}: description must not be empty"


def test_no_not_yet_implemented_enforcement_points():
    """The old forbidden sentinel 'not_yet_implemented' must not appear in any action.

    Reserved actions use 'not_implemented' (different, intentional marker).
    'not_yet_implemented' was a historical bad value that must not be re-introduced.
    """
    for defn in list_action_definitions():
        assert defn.current_enforcement_point != "not_yet_implemented", (
            f"{defn.action}: current_enforcement_point='not_yet_implemented' is forbidden. "
            "Wired actions need a real path; reserved actions use 'not_implemented'."
        )


def test_reserved_actions_have_not_implemented_enforcement_point():
    """All reserved actions must use 'not_implemented' as current_enforcement_point."""
    for action in _RESERVED_ACTIONS:
        defn = require_action_definition(action)
        assert defn.current_enforcement_point == "not_implemented", (
            f"{action}: reserved actions must use current_enforcement_point='not_implemented'. "
            f"Got: {defn.current_enforcement_point!r}"
        )


def test_knowledge_actions_are_wired_via_proposal_after_apply_handlers_exist():
    for action in [
        "knowledge.create",
        "knowledge.update",
        "knowledge.archive",
        "knowledge.relation_create",
        "knowledge.relation_delete",
    ]:
        defn = require_action_definition(action)
        assert defn.lifecycle_status == PolicyActionLifecycle.WIRED_VIA_PROPOSAL
        assert "proposal.apply" in defn.current_enforcement_point
        assert defn.default_decision == Decision.REQUIRE_APPROVAL


def test_wired_direct_actions_have_real_enforcement_points():
    """WIRED_DIRECT actions must not use 'not_implemented' as enforcement point."""
    for action in _WIRED_DIRECT_ACTIONS:
        defn = require_action_definition(action)
        assert defn.current_enforcement_point != "not_implemented", (
            f"{action}: wired_direct actions must have a real enforcement point, "
            f"not 'not_implemented'. Got: {defn.current_enforcement_point!r}"
        )


def test_wired_via_proposal_actions_enforcement_point_references_proposal_apply():
    """WIRED_VIA_PROPOSAL actions must reference proposal.apply in their enforcement point."""
    for action in _WIRED_VIA_PROPOSAL_ACTIONS:
        defn = require_action_definition(action)
        assert "proposal.apply" in defn.current_enforcement_point.lower(), (
            f"{action}: wired_via_proposal enforcement point must reference 'proposal.apply'. "
            f"Got: {defn.current_enforcement_point!r}"
        )


def test_registry_action_count():
    """Registry has exactly the expected number of actions (wired_direct + wired_via_proposal + reserved)."""
    actions = list_action_definitions()
    assert len(actions) == len(_EXPECTED_ACTIONS), (
        f"Expected {len(_EXPECTED_ACTIONS)} actions ({len(_WIRED_DIRECT_ACTIONS)} wired_direct + "
        f"{len(_WIRED_VIA_PROPOSAL_ACTIONS)} wired_via_proposal + "
        f"{len(_RESERVED_ACTIONS)} reserved), got {len(actions)}: "
        f"{[d.action for d in actions]}"
    )


# ---------------------------------------------------------------------------
# lifecycle_status: wired_direct vs wired_via_proposal vs reserved
# ---------------------------------------------------------------------------

def test_wired_direct_actions_have_lifecycle_wired_direct():
    """All wired_direct actions must have lifecycle_status == WIRED_DIRECT."""
    for action in _WIRED_DIRECT_ACTIONS:
        defn = require_action_definition(action)
        assert defn.lifecycle_status == PolicyActionLifecycle.WIRED_DIRECT, (
            f"{action}: expected lifecycle_status=WIRED_DIRECT, got {defn.lifecycle_status!r}"
        )


def test_wired_via_proposal_actions_have_lifecycle_wired_via_proposal():
    """All wired_via_proposal actions must have lifecycle_status == WIRED_VIA_PROPOSAL."""
    for action in _WIRED_VIA_PROPOSAL_ACTIONS:
        defn = require_action_definition(action)
        assert defn.lifecycle_status == PolicyActionLifecycle.WIRED_VIA_PROPOSAL, (
            f"{action}: expected lifecycle_status=WIRED_VIA_PROPOSAL, got {defn.lifecycle_status!r}"
        )


def test_reserved_actions_have_lifecycle_reserved():
    """All reserved actions must have lifecycle_status == RESERVED."""
    for action in _RESERVED_ACTIONS:
        defn = require_action_definition(action)
        assert defn.lifecycle_status == PolicyActionLifecycle.RESERVED, (
            f"{action}: expected lifecycle_status=RESERVED, got {defn.lifecycle_status!r}"
        )


def test_every_action_has_lifecycle_status():
    """Every registered action must have an explicit lifecycle_status."""
    for defn in list_action_definitions():
        assert defn.lifecycle_status in PolicyActionLifecycle, (
            f"{defn.action}: lifecycle_status must be a PolicyActionLifecycle value"
        )


def test_no_old_wired_lifecycle_in_registry():
    """The old WIRED lifecycle state must not be used anywhere in the registry."""
    for defn in list_action_definitions():
        assert defn.lifecycle_status != "wired", (
            f"{defn.action}: old lifecycle_status='wired' is forbidden. "
            "Use WIRED_DIRECT or WIRED_VIA_PROPOSAL."
        )
    # Verify the enum itself no longer has the old value.
    assert not hasattr(PolicyActionLifecycle, "WIRED"), (
        "PolicyActionLifecycle must not have a WIRED member — "
        "use WIRED_DIRECT or WIRED_VIA_PROPOSAL"
    )


# ---------------------------------------------------------------------------
# record_failure_mode: fail_closed on sensitive actions
# ---------------------------------------------------------------------------

_FAIL_CLOSED_ACTIONS = [
    "runtime.use_credential",
    "workspace.write_patch",
    "artifact.persist",
    "proposal.apply",
    "policy.change",
]

_BEST_EFFORT_ACTIONS = [
    "runtime.execute",
    "context.inject_memory",
    "context.render_for_runtime",
    "proposal.create",
    "agent.config_update",
]


def test_fail_closed_actions_have_record_failure_mode_fail_closed():
    """Sensitive actions must have record_failure_mode='fail_closed'."""
    for action in _FAIL_CLOSED_ACTIONS:
        defn = require_action_definition(action)
        assert defn.record_failure_mode == "fail_closed", (
            f"{action}: expected record_failure_mode='fail_closed', "
            f"got {defn.record_failure_mode!r}"
        )


def test_best_effort_actions_have_record_failure_mode_best_effort():
    """Lower-sensitivity actions should use record_failure_mode='best_effort'."""
    for action in _BEST_EFFORT_ACTIONS:
        defn = require_action_definition(action)
        assert defn.record_failure_mode == "best_effort", (
            f"{action}: expected record_failure_mode='best_effort', "
            f"got {defn.record_failure_mode!r}"
        )


def test_every_action_has_valid_record_failure_mode():
    """Every action must have record_failure_mode in ('best_effort', 'fail_closed')."""
    valid = {"best_effort", "fail_closed"}
    for defn in list_action_definitions():
        assert defn.record_failure_mode in valid, (
            f"{defn.action}: record_failure_mode must be one of {valid}, "
            f"got {defn.record_failure_mode!r}"
        )


# ---------------------------------------------------------------------------
# WIRED_VIA_PROPOSAL gateway fail-closed: direct enforcement must DENY
# ---------------------------------------------------------------------------

def test_wired_via_proposal_denied_by_gateway_enforce():
    """Direct enforcement of a WIRED_VIA_PROPOSAL action must DENY immediately."""
    from unittest.mock import MagicMock
    from app.policy.gateway import PolicyGateway, PolicyCheckRequest
    from app.policy.exceptions import PolicyGateBlocked

    mock_db = MagicMock()
    mock_db.add = MagicMock()
    mock_db.flush = MagicMock()

    gateway = PolicyGateway(mock_db)
    for action in _WIRED_VIA_PROPOSAL_ACTIONS:
        with pytest.raises(PolicyGateBlocked) as exc_info:
            gateway.enforce(PolicyCheckRequest(
                action=action,
                actor_type="user",
                actor_id="u1",
                space_id="s1",
            ))
        decision = exc_info.value.decision
        assert decision.denied, (
            f"{action}: WIRED_VIA_PROPOSAL must be denied when called directly"
        )
        assert decision.reason_code == "policy_action_via_proposal_only", (
            f"{action}: expected reason_code='policy_action_via_proposal_only', "
            f"got {decision.reason_code!r}"
        )
        assert decision.audit_code == "policy_action_via_proposal_only", (
            f"{action}: expected audit_code='policy_action_via_proposal_only', "
            f"got {decision.audit_code!r}"
        )


# ---------------------------------------------------------------------------
# Unknown-action fail-closed
# ---------------------------------------------------------------------------

def test_get_action_definition_returns_none_for_unknown():
    assert get_action_definition("nonexistent.action") is None


def test_require_action_definition_raises_for_unknown():
    with pytest.raises(UnknownPolicyActionError) as exc_info:
        require_action_definition("nonexistent.action")
    assert exc_info.value.action == "nonexistent.action"
    assert "Unknown policy action" in str(exc_info.value)


def test_unknown_action_fails_closed_at_engine_level():
    """PolicyEngine returns DENY for unregistered actions (unknown-action fail-closed)."""
    from app.policy.engine import PolicyEngine
    engine = PolicyEngine()
    decision = engine.check({"action": "totally.unknown.action", "space_id": "s1"})
    assert decision.denied
    assert decision.audit_code == "unknown_policy_action"


def test_agent_delegate_is_not_registered():
    assert not is_known_action("agent.delegate")
    with pytest.raises(UnknownPolicyActionError):
        require_action_definition("agent.delegate")


def test_is_known_action_false_for_unknown():
    assert not is_known_action("memory.write")
    assert not is_known_action("tool.execute")
    assert not is_known_action("agent.run")


def test_cross_space_export_not_registered():
    """cross_space_export has no real enforcement point and no reserved entry — must not be in registry."""
    assert not is_known_action("cross_space_export")


# ---------------------------------------------------------------------------
# Specific wired_direct action definitions
# ---------------------------------------------------------------------------

def test_proposal_apply_definition():
    defn = require_action_definition("proposal.apply")
    assert defn.resource_type == "proposal"
    assert defn.default_risk_level == RiskLevel.MEDIUM
    assert defn.default_decision == Decision.REQUIRE_APPROVAL
    assert defn.audit_required is True
    assert defn.approval_capability == "approve_proposal"
    assert defn.current_enforcement_point == "app.memory.proposals.ProposalService.accept"
    assert defn.lifecycle_status == PolicyActionLifecycle.WIRED_DIRECT
    assert defn.record_failure_mode == "fail_closed"


def test_runtime_execute_allows_by_default():
    defn = require_action_definition("runtime.execute")
    assert defn.default_decision == Decision.ALLOW
    assert defn.audit_required is True
    assert defn.current_enforcement_point == "app.runs.execution.RunExecutionService.execute"
    assert defn.lifecycle_status == PolicyActionLifecycle.WIRED_DIRECT


def test_runtime_use_credential_is_high_risk():
    defn = require_action_definition("runtime.use_credential")
    assert defn.default_risk_level == RiskLevel.HIGH
    assert defn.default_decision == Decision.REQUIRE_APPROVAL
    assert defn.audit_required is True
    assert defn.current_enforcement_point == "app.runs.execution.RunExecutionService.execute"
    assert defn.lifecycle_status == PolicyActionLifecycle.WIRED_DIRECT
    assert defn.record_failure_mode == "fail_closed"


def test_workspace_write_patch_is_high_risk():
    defn = require_action_definition("workspace.write_patch")
    assert defn.default_risk_level == RiskLevel.HIGH
    assert defn.approval_capability == "approve_code_patch"
    assert defn.lifecycle_status == PolicyActionLifecycle.WIRED_DIRECT
    assert defn.record_failure_mode == "fail_closed"


def test_artifact_persist_is_audit_required():
    defn = require_action_definition("artifact.persist")
    assert defn.audit_required is True
    assert defn.current_enforcement_point == "app.runs.artifact_persistence.ArtifactPersistenceService"
    assert defn.lifecycle_status == PolicyActionLifecycle.WIRED_DIRECT
    assert defn.record_failure_mode == "fail_closed"


def test_context_inject_memory_enforcement_point():
    defn = require_action_definition("context.inject_memory")
    assert defn.default_decision == Decision.ALLOW
    assert defn.current_enforcement_point == "app.runs.context_snapshot_populator.ContextSnapshotPopulator.populate"
    assert defn.lifecycle_status == PolicyActionLifecycle.WIRED_DIRECT


def test_context_render_for_runtime_enforcement_point():
    defn = require_action_definition("context.render_for_runtime")
    assert defn.default_decision == Decision.ALLOW
    assert defn.current_enforcement_point == "app.runs.execution.RunExecutionService.execute"
    assert defn.lifecycle_status == PolicyActionLifecycle.WIRED_DIRECT


def test_proposal_create_covers_both_memory_and_code_patch():
    """proposal.create covers both user-created memory proposals and code_patch proposals."""
    defn = require_action_definition("proposal.create")
    assert defn.default_decision == Decision.ALLOW
    assert defn.lifecycle_status == PolicyActionLifecycle.WIRED_DIRECT
    # Enforcement point must reference both paths
    assert "ProposalService" in defn.current_enforcement_point
    assert "code_patch_collector" in defn.current_enforcement_point
    # Description must clarify both paths
    assert "memory" in defn.description.lower()
    assert "code_patch" in defn.description.lower() or "cli" in defn.description.lower()


def test_agent_config_update_action_is_audited_direct_proposal_boundary():
    defn = require_action_definition("agent.config_update")
    assert defn.resource_type == "agent"
    assert defn.default_risk_level == RiskLevel.HIGH
    assert defn.default_decision == Decision.ALLOW
    assert defn.audit_required is True
    assert defn.lifecycle_status == PolicyActionLifecycle.WIRED_DIRECT
    assert defn.record_failure_mode == "best_effort"
    assert "config_update" in defn.description
    assert "proposal.apply" in defn.description


# ---------------------------------------------------------------------------
# Specific wired_via_proposal action definitions
# ---------------------------------------------------------------------------

def test_memory_create_definition():
    defn = require_action_definition("memory.create")
    assert defn.resource_type == "memory"
    assert defn.default_risk_level == RiskLevel.MEDIUM
    assert defn.default_decision == Decision.REQUIRE_APPROVAL
    assert defn.audit_required is True
    assert defn.approval_capability == "approve_memory_change"
    assert defn.lifecycle_status == PolicyActionLifecycle.WIRED_VIA_PROPOSAL
    assert "proposal.apply" in defn.current_enforcement_point.lower()


def test_memory_update_definition():
    defn = require_action_definition("memory.update")
    assert defn.lifecycle_status == PolicyActionLifecycle.WIRED_VIA_PROPOSAL
    assert "proposal.apply" in defn.current_enforcement_point.lower()


def test_memory_archive_definition():
    defn = require_action_definition("memory.archive")
    assert defn.lifecycle_status == PolicyActionLifecycle.WIRED_VIA_PROPOSAL
    assert "proposal.apply" in defn.current_enforcement_point.lower()


def test_policy_change_is_high_risk():
    defn = require_action_definition("policy.change")
    assert defn.default_risk_level == RiskLevel.HIGH
    assert defn.default_decision == Decision.REQUIRE_APPROVAL
    assert defn.lifecycle_status == PolicyActionLifecycle.WIRED_VIA_PROPOSAL
    assert defn.record_failure_mode == "fail_closed"
    assert "proposal.apply" in defn.current_enforcement_point.lower()


# ---------------------------------------------------------------------------
# Specific reserved action definitions
# ---------------------------------------------------------------------------

def test_deployment_execute_is_critical_risk():
    defn = require_action_definition("deployment.execute")
    assert defn.default_risk_level == RiskLevel.CRITICAL
    assert defn.default_decision == Decision.REQUIRE_APPROVAL
    assert defn.audit_required is True
    assert defn.current_enforcement_point == "not_implemented"


def test_context_use_personal_grant_is_high_risk():
    defn = require_action_definition("context.use_personal_grant")
    assert defn.default_risk_level == RiskLevel.HIGH
    assert defn.default_decision == Decision.REQUIRE_APPROVAL
    assert defn.resource_type == "personal_memory_grant"
    assert defn.current_enforcement_point == "not_implemented"


def test_workspace_read_is_low_risk_allow():
    defn = require_action_definition("workspace.read")
    assert defn.default_risk_level == RiskLevel.LOW
    assert defn.default_decision == Decision.ALLOW
    assert defn.audit_required is False
    assert defn.lifecycle_status == PolicyActionLifecycle.WIRED_DIRECT
    assert "workspace_console" in defn.current_enforcement_point


def test_automation_create_wired():
    defn = require_action_definition("automation.create")
    assert defn.resource_type == "automation"
    assert defn.default_risk_level == RiskLevel.HIGH
    assert defn.lifecycle_status == PolicyActionLifecycle.WIRED_DIRECT
    assert defn.audit_required is True
    assert "AutomationService" in defn.current_enforcement_point


def test_automation_fire_wired():
    defn = require_action_definition("automation.fire")
    assert defn.resource_type == "automation"
    assert defn.lifecycle_status == PolicyActionLifecycle.WIRED_DIRECT
    assert defn.audit_required is True
    assert "AutomationService" in defn.current_enforcement_point


def test_automation_update_wired():
    defn = require_action_definition("automation.update")
    assert defn.resource_type == "automation"
    assert defn.default_risk_level == RiskLevel.HIGH
    assert defn.lifecycle_status == PolicyActionLifecycle.WIRED_DIRECT
    assert defn.audit_required is True
    assert "AutomationService" in defn.current_enforcement_point


def test_capability_enable_reserved():
    defn = require_action_definition("capability.enable")
    assert defn.resource_type == "capability"
    assert defn.default_risk_level == RiskLevel.HIGH
    assert defn.current_enforcement_point == "not_implemented"


def test_tool_binding_enable_reserved():
    defn = require_action_definition("tool_binding.enable")
    assert defn.resource_type == "tool_binding"
    assert defn.default_risk_level == RiskLevel.HIGH
    assert defn.current_enforcement_point == "not_implemented"


# ---------------------------------------------------------------------------
# Forbidden risk level
# ---------------------------------------------------------------------------

def test_forbidden_is_not_a_risk_level():
    with pytest.raises((ValueError, KeyError)):
        RiskLevel("forbidden")
