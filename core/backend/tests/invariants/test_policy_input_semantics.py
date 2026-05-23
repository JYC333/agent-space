"""
Invariant tests: PolicyGateway context vs metadata_json input semantics.

Verifies that:
  - metadata_json is audit-only and never drives authorization decisions.
  - context is the sole source of decision inputs for HardInvariantGuard and
    PolicyEngine rules.
  - Defense-in-depth redaction still fires for personal_context_block even when
    it arrives accidentally in metadata_json.
  - Existing allow/deny paths are unaffected (regression coverage).

These tests complement test_policy_hard_invariants.py (pure guard unit tests)
and test_policy_gateway_workflow.py (gateway + DB persistence tests).
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.policy.decisions import Decision
from app.policy.gateway import PolicyGateway, PolicyCheckRequest
from app.policy.hard_invariants import HardInvariantGuard


# ---------------------------------------------------------------------------
# Invariant 4 input semantics: raw_private_memory_included
# ---------------------------------------------------------------------------


class TestRawPrivateMemoryInputSemantics:
    """raw_private_memory_included must come from context, not metadata_json."""

    def test_metadata_json_raw_private_memory_alone_does_not_block(self):
        """Invariant 4 must NOT fire when raw_private_memory_included=True is
        only in metadata_json and absent from context."""
        guard = HardInvariantGuard()
        result = guard.check({
            "action": "artifact.persist",
            "space_id": "s1",
            "metadata_json": {"raw_private_memory_included": True},
            # context is absent — the flag in metadata_json must not drive the decision
        })
        assert result is None, (
            "metadata_json is audit-only; raw_private_memory_included in metadata_json "
            "alone must not block egress"
        )

    def test_context_raw_private_memory_blocks_egress(self):
        """Invariant 4 fires when raw_private_memory_included=True is in context."""
        guard = HardInvariantGuard()
        result = guard.check({
            "action": "artifact.persist",
            "space_id": "s1",
            "context": {"raw_private_memory_included": True},
            "raw_private_memory_included": True,  # flattened from context
        })
        assert result is not None
        assert result.denied
        assert result.audit_code == "raw_private_memory_egress_blocked"

    def test_metadata_json_raw_private_memory_false_still_passes(self):
        """Invariant 4 does not fire when flag is False regardless of location."""
        guard = HardInvariantGuard()
        result = guard.check({
            "action": "artifact.persist",
            "space_id": "s1",
            "metadata_json": {"raw_private_memory_included": False},
            "context": {"raw_private_memory_included": False},
            "raw_private_memory_included": False,
        })
        assert result is None


# ---------------------------------------------------------------------------
# Invariant 5 input semantics: target_visibility + derived_from_personal_memory_grant
# ---------------------------------------------------------------------------


class TestPublicVisibilityInputSemantics:
    """target_visibility/public must come from context, not metadata_json."""

    def test_metadata_json_target_visibility_public_alone_is_not_decision_proof(self):
        """Invariant 5 must NOT fire when target_visibility=public is only in
        metadata_json and derived_from_personal_memory_grant is also only there."""
        guard = HardInvariantGuard()
        result = guard.check({
            "action": "artifact.persist",
            "space_id": "s1",
            "metadata_json": {
                "target_visibility": "public",
                "derived_from_personal_memory_grant": True,
            },
            # Neither field is in context — invariant must not fire
        })
        assert result is None, (
            "metadata_json is audit-only; target_visibility and "
            "derived_from_personal_memory_grant in metadata_json alone must not "
            "trigger the public-visibility hard invariant"
        )

    def test_context_target_visibility_public_with_grant_triggers_invariant(self):
        """Invariant 5 fires when both target_visibility=public and
        derived_from_personal_memory_grant=True are in context."""
        guard = HardInvariantGuard()
        result = guard.check({
            "action": "artifact.persist",
            "space_id": "s1",
            # Flattened from context (as _guard_ctx does with ctx.update(req.context))
            "target_visibility": "public",
            "derived_from_personal_memory_grant": True,
            "context": {
                "target_visibility": "public",
                "derived_from_personal_memory_grant": True,
            },
        })
        assert result is not None
        assert result.denied
        assert result.audit_code == "grant_derived_public_visibility_blocked"

    def test_context_public_visibility_without_grant_passes(self):
        """Public visibility without grant derivation must pass Invariant 5."""
        guard = HardInvariantGuard()
        result = guard.check({
            "action": "artifact.persist",
            "space_id": "s1",
            "target_visibility": "public",
            "derived_from_personal_memory_grant": False,
            "context": {
                "target_visibility": "public",
                "derived_from_personal_memory_grant": False,
            },
        })
        assert result is None

    def test_context_grant_derived_without_public_visibility_passes(self):
        """Grant-derived output with non-public visibility must pass Invariant 5."""
        guard = HardInvariantGuard()
        result = guard.check({
            "action": "artifact.persist",
            "space_id": "s1",
            "target_visibility": "space_shared",
            "derived_from_personal_memory_grant": True,
            "context": {
                "target_visibility": "space_shared",
                "derived_from_personal_memory_grant": True,
            },
        })
        assert result is None


# ---------------------------------------------------------------------------
# Invariant 7 input semantics: target_space_id
# ---------------------------------------------------------------------------


class TestTargetSpaceInputSemantics:
    """target_space_id must come from context, not metadata_json."""

    def test_empty_context_target_space_denies_artifact_persist(self, db: Session):
        """An empty decision input fails closed for egress-sensitive persistence."""
        decision = PolicyGateway(db).check_and_record(
            PolicyCheckRequest(
                action="artifact.persist",
                actor_type="run",
                actor_id="run-target-empty-ctx",
                space_id="space_a",
                run_id="run-target-empty-ctx",
                context={
                    "target_space_id": "",
                    "derived_from_personal_memory_grant": False,
                    "raw_private_memory_included": False,
                },
                metadata_json={
                    "artifact_type": "runtime_output",
                    "target_space_id": "space_a",
                    "source_run_id": "run-target-empty-ctx",
                },
            )
        )
        assert decision.denied
        assert decision.policy_source == "hard_invariant"
        assert decision.policy_rule_id == "hard_invariant_unknown_target_space"
        assert decision.audit_code == "unknown_target_space_egress"

    def test_empty_target_space_only_in_metadata_json_does_not_drive_decision(
        self, db: Session
    ):
        """An audit-only empty target does not satisfy or fail the invariant."""
        decision = PolicyGateway(db).check_and_record(
            PolicyCheckRequest(
                action="artifact.persist",
                actor_type="run",
                actor_id="run-target-empty-meta",
                space_id="space_a",
                run_id="run-target-empty-meta",
                context={
                    "derived_from_personal_memory_grant": False,
                    "raw_private_memory_included": False,
                },
                metadata_json={
                    "artifact_type": "runtime_output",
                    "target_space_id": "",
                    "source_run_id": "run-target-empty-meta",
                },
            )
        )
        assert decision.allowed


# ---------------------------------------------------------------------------
# Invariant 3 input semantics: personal_context_block
# ---------------------------------------------------------------------------


class TestPersonalContextBlockInputSemantics:
    """personal_context_block triggers Invariant 3 from context (decision input)
    and also from metadata_json (defense-in-depth redaction)."""

    def test_artifact_persist_denies_when_context_contains_personal_context_block(
        self, db: Session
    ):
        """artifact.persist with personal_context_block in context → DENY via
        HardInvariantGuard and the record has it redacted."""
        gw = PolicyGateway(db)
        decision = gw.check_and_record(
            PolicyCheckRequest(
                action="artifact.persist",
                actor_type="run",
                actor_id="run-pcb-ctx",
                space_id="space_a",
                run_id="run-pcb-ctx",
                context={
                    "target_space_id": "space_a",
                    "personal_context_block": "private ephemeral content",
                    "derived_from_personal_memory_grant": False,
                    "raw_private_memory_included": False,
                },
                metadata_json={
                    "artifact_type": "runtime_output",
                    "source_run_id": "run-pcb-ctx",
                    "preview": False,
                },
            )
        )
        assert decision.denied
        assert decision.policy_source == "hard_invariant"
        assert decision.audit_code == "personal_context_block_persist_attempt"

        from app.models import PolicyDecisionRecord
        record = db.query(PolicyDecisionRecord).filter(
            PolicyDecisionRecord.run_id == "run-pcb-ctx",
            PolicyDecisionRecord.action == "artifact.persist",
        ).first()
        assert record is not None
        assert record.decision == "deny"

    def test_artifact_persist_redacts_personal_context_block_from_metadata_json(
        self, db: Session
    ):
        """artifact.persist with personal_context_block accidentally in metadata_json →
        defense-in-depth: DENY and record has [REDACTED], not the raw value."""
        gw = PolicyGateway(db)
        decision = gw.check_and_record(
            PolicyCheckRequest(
                action="artifact.persist",
                actor_type="run",
                actor_id="run-pcb-meta",
                space_id="space_a",
                run_id="run-pcb-meta",
                context={
                    "target_space_id": "space_a",
                    "derived_from_personal_memory_grant": False,
                    "raw_private_memory_included": False,
                },
                metadata_json={
                    "artifact_type": "runtime_output",
                    "personal_context_block": "private ephemeral content",
                    "source_run_id": "run-pcb-meta",
                    "preview": False,
                },
            )
        )
        assert decision.denied
        assert decision.policy_source == "hard_invariant"
        assert decision.audit_code == "personal_context_block_persist_attempt"

        from app.models import PolicyDecisionRecord
        record = db.query(PolicyDecisionRecord).filter(
            PolicyDecisionRecord.run_id == "run-pcb-meta",
            PolicyDecisionRecord.action == "artifact.persist",
        ).first()
        assert record is not None
        assert record.decision == "deny"
        meta = record.metadata_json or {}
        pcb_val = meta.get("personal_context_block")
        assert pcb_val == "[REDACTED]", (
            "personal_context_block must be redacted before persistence, "
            f"got: {pcb_val!r}"
        )
        assert pcb_val != "private ephemeral content"


# ---------------------------------------------------------------------------
# Regression: existing allow/deny paths still work
# ---------------------------------------------------------------------------


class TestExistingPathsUnaffected:
    """Regression: code changes must not alter existing allow/deny outcomes."""

    def test_runtime_execute_denies_disabled_agent_from_context(self, db: Session):
        """agent_status='disabled' in context still denies runtime.execute.

        This verifies the field is read from context (decision input), not
        metadata_json, and that the rule fires before any credential resolution
        or adapter invocation could occur.
        """
        from app.policy.engine import PolicyEngine

        engine = PolicyEngine()
        decision = engine.check({
            "action": "runtime.execute",
            "space_id": "s1",
            "agent_status": "disabled",  # in context (flattened)
        })
        assert decision.denied
        assert decision.policy_rule_id == "agent_status"

    def test_runtime_execute_disabled_agent_not_triggered_by_metadata_only(self):
        """agent_status in metadata_json only must NOT deny runtime.execute.

        The rule reads agent_status from the engine context, which is built from
        req.context (not metadata_json). If agent_status is absent from context,
        the rule must not fire.
        """
        from app.policy.engine import PolicyEngine

        engine = PolicyEngine()
        # agent_status is NOT in the engine context — only metadata_json carries it.
        # _build_engine_ctx merges req.context into the engine context, so if the
        # caller only puts agent_status in metadata_json it will be absent here.
        decision = engine.check({
            "action": "runtime.execute",
            "space_id": "s1",
            # agent_status absent → rule_agent_status does not fire
        })
        assert decision.allowed

    def test_runtime_use_credential_cross_space_denied_before_secret_resolution(
        self, db: Session
    ):
        """Cross-space credential access fires via resource_space_id (top-level
        PolicyCheckRequest field) before any Credential.secret_value is resolved.

        This test uses PolicyGateway.check_and_record() directly, which is the
        gate that fires before resolve_runtime_credentials() in RunExecutionService.
        """
        gw = PolicyGateway(db)
        decision = gw.check_and_record(
            PolicyCheckRequest(
                action="runtime.use_credential",
                actor_type="run",
                actor_id="run-cred-cross",
                space_id="space_a",
                resource_type="credential",
                resource_space_id="space_b",  # cross-space → deny
                run_id="run-cred-cross",
                context={
                    "trigger_origin": "manual",
                    "instructed_by_user_id": "user1",
                },
                metadata_json={
                    "resolution_source": "run.model_provider_id",
                    "adapter_type": "echo",
                },
            )
        )
        assert decision.denied, (
            "Cross-space credential use must be denied before secret resolution"
        )

        from app.models import PolicyDecisionRecord
        record = db.query(PolicyDecisionRecord).filter(
            PolicyDecisionRecord.run_id == "run-cred-cross",
            PolicyDecisionRecord.action == "runtime.use_credential",
        ).first()
        assert record is not None
        assert record.decision == "deny"

    def test_artifact_persist_safe_context_allows(self, db: Session):
        """artifact.persist with safe context fields and no flags set → ALLOW."""
        gw = PolicyGateway(db)
        decision = gw.check_and_record(
            PolicyCheckRequest(
                action="artifact.persist",
                actor_type="run",
                actor_id="run-art-safe-ctx",
                space_id="space_a",
                run_id="run-art-safe-ctx",
                context={
                    "target_space_id": "space_a",
                    "derived_from_personal_memory_grant": False,
                    "raw_private_memory_included": False,
                },
                metadata_json={
                    "artifact_type": "runtime_output",
                    "target_space_id": "space_a",
                    "source_run_id": "run-art-safe-ctx",
                    "preview": False,
                },
            )
        )
        assert decision.allowed

        from app.models import PolicyDecisionRecord
        record = db.query(PolicyDecisionRecord).filter(
            PolicyDecisionRecord.run_id == "run-art-safe-ctx",
            PolicyDecisionRecord.action == "artifact.persist",
        ).first()
        assert record is not None, "artifact.persist is audit_required — must record ALLOW"
        assert record.decision == "allow"
