"""
Invariant tests for HardInvariantGuard.

Every test here protects a hard security/privacy invariant that policy rows
or caller context must never be able to override.
"""

from __future__ import annotations

import pytest

from app.policy.decisions import Decision, PolicyDecision, RiskLevel
from app.policy.hard_invariants import HardInvariantGuard


def _guard():
    return HardInvariantGuard()


# ---------------------------------------------------------------------------
# Invariant 1: cross-space memory read is denied without explicit grant
# ---------------------------------------------------------------------------


class TestCrossSpaceMemoryReadInvariant:
    def test_cross_space_context_inject_denied(self):
        d = _guard().check({
            "action": "context.inject_memory",
            "space_id": "space_a",
            "resource_space_id": "space_b",
        })
        assert d is not None
        assert d.denied
        assert d.audit_code == "cross_space_memory_denied"

    def test_same_space_context_inject_allowed(self):
        d = _guard().check({
            "action": "context.inject_memory",
            "space_id": "space_a",
            "resource_space_id": "space_a",
        })
        assert d is None

    def test_cross_space_with_grant_passes_invariant(self):
        d = _guard().check({
            "action": "context.inject_memory",
            "space_id": "space_a",
            "resource_space_id": "space_b",
            "has_personal_memory_grant": True,
        })
        assert d is None

    def test_cross_space_use_personal_grant_denied_without_grant(self):
        d = _guard().check({
            "action": "context.use_personal_grant",
            "space_id": "space_a",
            "resource_space_id": "space_b",
        })
        assert d is not None
        assert d.denied


# ---------------------------------------------------------------------------
# Invariant 2: SourcePointer does not grant read access
# ---------------------------------------------------------------------------


class TestSourcePointerNotAuthInvariant:
    def test_authorized_by_source_pointer_denies(self):
        d = _guard().check({
            "action": "context.inject_memory",
            "space_id": "space_a",
            "authorized_by_source_pointer": True,
        })
        assert d is not None
        assert d.denied
        assert d.audit_code == "source_pointer_used_as_auth"

    def test_no_source_pointer_auth_passes(self):
        d = _guard().check({
            "action": "context.inject_memory",
            "space_id": "space_a",
        })
        # No invariant fired (cross-space check also not fired since no resource_space_id)
        assert d is None


# ---------------------------------------------------------------------------
# Invariant 3: personal_context_block is never persisted
# ---------------------------------------------------------------------------


class TestPersonalContextBlockNotPersisted:
    def test_persist_with_pcb_in_metadata_denies(self):
        d = _guard().check({
            "action": "artifact.persist",
            "space_id": "s1",
            "metadata_json": {"personal_context_block": "sensitive text"},
        })
        assert d is not None
        assert d.denied
        assert d.audit_code == "personal_context_block_persist_attempt"

    def test_persist_with_pcb_in_context_denies(self):
        d = _guard().check({
            "action": "memory.create",
            "space_id": "s1",
            "context": {"personal_context_block": "sensitive"},
        })
        assert d is not None
        assert d.denied

    def test_read_action_with_pcb_passes_invariant(self):
        d = _guard().check({
            "action": "workspace.read",
            "space_id": "s1",
            "metadata_json": {"personal_context_block": "ok for read"},
        })
        assert d is None

    def test_persist_without_pcb_passes(self):
        d = _guard().check({
            "action": "artifact.persist",
            "space_id": "s1",
            "metadata_json": {"safe_key": "safe_value"},
        })
        assert d is None


# ---------------------------------------------------------------------------
# Invariant 4: raw_private_memory_included=true always blocks egress
# ---------------------------------------------------------------------------


class TestRawPrivateMemoryBlocksEgress:
    def test_artifact_persist_with_raw_private_memory_in_context_denies(self):
        """raw_private_memory_included=True in context (decision input) → DENY."""
        d = _guard().check({
            "action": "artifact.persist",
            "space_id": "s1",
            # Flattened from req.context (as _guard_ctx does with ctx.update(req.context))
            "raw_private_memory_included": True,
            "context": {"raw_private_memory_included": True},
        })
        assert d is not None
        assert d.denied
        assert d.audit_code == "raw_private_memory_egress_blocked"

    def test_artifact_persist_with_raw_private_memory_only_in_metadata_json_passes(self):
        """raw_private_memory_included in metadata_json alone must not trigger
        Invariant 4.  metadata_json is audit-only; decisions require context."""
        d = _guard().check({
            "action": "artifact.persist",
            "space_id": "s1",
            "metadata_json": {"raw_private_memory_included": True},
        })
        assert d is None, (
            "metadata_json is audit-only; raw_private_memory_included there "
            "must not drive the egress-block decision"
        )

    def test_proposal_apply_with_raw_private_memory_denies(self):
        d = _guard().check({
            "action": "proposal.apply",
            "space_id": "s1",
            "context": {"raw_private_memory_included": True},
        })
        assert d is not None
        assert d.denied

    def test_raw_private_memory_false_passes(self):
        d = _guard().check({
            "action": "artifact.persist",
            "space_id": "s1",
            "metadata_json": {"raw_private_memory_included": False},
        })
        assert d is None

    def test_raw_private_memory_in_non_egress_action_passes(self):
        d = _guard().check({
            "action": "workspace.read",
            "space_id": "s1",
            "metadata_json": {"raw_private_memory_included": True},
        })
        assert d is None


# ---------------------------------------------------------------------------
# Invariant 5: public target visibility blocks grant-derived output
# ---------------------------------------------------------------------------


class TestPublicTargetBlocksGrantDerived:
    def test_public_visibility_grant_derived_artifact_persist_denies(self):
        d = _guard().check({
            "action": "artifact.persist",
            "space_id": "s1",
            "derived_from_personal_memory_grant": True,
            "target_visibility": "public",
        })
        assert d is not None
        assert d.denied
        assert d.audit_code == "grant_derived_public_visibility_blocked"

    def test_private_visibility_grant_derived_passes(self):
        d = _guard().check({
            "action": "artifact.persist",
            "space_id": "s1",
            "derived_from_personal_memory_grant": True,
            "target_visibility": "private",
        })
        assert d is None

    def test_non_grant_derived_public_passes(self):
        d = _guard().check({
            "action": "artifact.persist",
            "space_id": "s1",
            "derived_from_personal_memory_grant": False,
            "target_visibility": "public",
        })
        assert d is None


# ---------------------------------------------------------------------------
# Invariant 6: payload metadata is never approval proof
# ---------------------------------------------------------------------------


class TestPayloadFlagsNotApprovalProof:
    @pytest.mark.parametrize("flag", [
        "approved_by_user",
        "approved_by_granting_user",
        "approval_status",
        "is_approved",
        "auto_approved",
        "pre_approved",
    ])
    def test_approval_flag_in_payload_denies(self, flag):
        d = _guard().check({
            "action": "proposal.apply",
            "space_id": "s1",
            "payload": {flag: True},
        })
        assert d is not None
        assert d.denied
        assert d.audit_code == "payload_flag_as_approval_proof"

    def test_clean_proposal_apply_passes_invariant(self):
        d = _guard().check({
            "action": "proposal.apply",
            "space_id": "s1",
            "payload": {"proposal_type": "memory_create"},
        })
        assert d is None

    def test_policy_change_with_approval_flag_denies(self):
        d = _guard().check({
            "action": "policy.change",
            "space_id": "s1",
            "metadata_json": {"approved_by_user": True},
        })
        assert d is not None
        assert d.denied

    def test_non_apply_action_with_approval_flag_passes(self):
        d = _guard().check({
            "action": "workspace.read",
            "space_id": "s1",
            "payload": {"approved_by_user": True},
        })
        assert d is None


# ---------------------------------------------------------------------------
# Guard returns None for clean contexts (no false positives)
# ---------------------------------------------------------------------------


class TestHardInvariantNoFalsePositives:
    def test_clean_runtime_execute_context_passes(self):
        d = _guard().check({
            "action": "runtime.execute",
            "space_id": "s1",
            "actor_id": "user1",
        })
        assert d is None

    def test_clean_memory_create_passes(self):
        d = _guard().check({
            "action": "memory.create",
            "space_id": "s1",
            "resource_space_id": "s1",
            "actor_id": "user1",
        })
        assert d is None


# ---------------------------------------------------------------------------
# Action set consistency: every action in hard invariant sets is registered
# ---------------------------------------------------------------------------


class TestHardInvariantActionSetConsistency:
    """Every action name referenced in hard invariant action sets must be
    registered in the canonical policy action registry (or explicitly
    acknowledged as intentionally unregistered / fail-closed).

    This prevents stale action names from silently becoming dead code that
    never fires — which would weaken security invariants.
    """

    def test_persistence_actions_all_registered(self):
        from app.policy.actions import is_known_action
        from app.policy.hard_invariants import _PERSISTENCE_ACTIONS

        for action in _PERSISTENCE_ACTIONS:
            assert is_known_action(action), (
                f"_PERSISTENCE_ACTIONS contains {action!r} which is not registered. "
                "Either register it in the canonical action registry or remove it."
            )

    def test_egress_sensitive_actions_all_registered(self):
        from app.policy.actions import is_known_action
        from app.policy.hard_invariants import _EGRESS_SENSITIVE_ACTIONS

        for action in _EGRESS_SENSITIVE_ACTIONS:
            assert is_known_action(action), (
                f"_EGRESS_SENSITIVE_ACTIONS contains {action!r} which is not registered. "
                "Either register it in the canonical action registry or remove it."
            )

    def test_memory_read_actions_all_registered(self):
        from app.policy.actions import is_known_action
        from app.policy.hard_invariants import _MEMORY_READ_ACTIONS

        for action in _MEMORY_READ_ACTIONS:
            assert is_known_action(action), (
                f"_MEMORY_READ_ACTIONS contains {action!r} which is not registered."
            )

    def test_cross_space_export_not_in_egress_sensitive(self):
        """cross_space_export was the old unregistered name — must not appear."""
        from app.policy.hard_invariants import _EGRESS_SENSITIVE_ACTIONS

        assert "cross_space_export" not in _EGRESS_SENSITIVE_ACTIONS, (
            "cross_space_export is not a registered action. "
            "Use artifact.export (registered reserved action) instead."
        )

    def test_artifact_export_in_egress_sensitive(self):
        """artifact.export (the canonical registered reserved action) must be in egress set."""
        from app.policy.hard_invariants import _EGRESS_SENSITIVE_ACTIONS

        assert "artifact.export" in _EGRESS_SENSITIVE_ACTIONS

    def test_memory_archive_in_persistence_actions(self):
        """memory.archive is a durable mutation and must be in _PERSISTENCE_ACTIONS."""
        from app.policy.hard_invariants import _PERSISTENCE_ACTIONS

        assert "memory.archive" in _PERSISTENCE_ACTIONS


# ---------------------------------------------------------------------------
# PolicyDecision field completeness
# ---------------------------------------------------------------------------


class TestPolicyDecisionFields:
    """Hard invariant denials must carry all stable machine-readable fields."""

    def test_hard_invariant_denial_carries_stable_codes(self):
        """Hard invariant denials must have policy_source, audit_code, policy_rule_id, and reason_code."""
        d = _guard().check({
            "action": "context.inject_memory",
            "space_id": "space_a",
            "resource_space_id": "space_b",
        })
        assert d is not None
        assert d.policy_source == "hard_invariant"
        assert d.audit_code == "cross_space_memory_denied"
        assert d.policy_rule_id == "hard_invariant_cross_space_memory"
        assert d.reason_code == "hard_invariant_cross_space_memory"
        assert d.message  # non-empty human-readable message
