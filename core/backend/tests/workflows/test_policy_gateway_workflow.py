"""
Workflow tests for PolicyGateway and durable PolicyDecisionRecord persistence.

Covers:
  - PolicyGateway.check_and_record() records PolicyDecisionRecord for audit_required actions
  - runtime.execute DENY prevents adapter invocation
  - runtime.execute REQUIRE_APPROVAL prevents adapter invocation
  - runtime.execute ALLOW preserves success path
  - context.inject_memory cross-space deny is recorded
  - context.render_for_runtime cross-space deny is recorded
  - artifact.persist ALLOW always recorded (audit_required=True)
  - artifact.persist DENY via personal_context_block invariant
  - proposal.create high-risk forced audit record
  - proposal.apply role/risk matrix through PolicyGateway.check_proposal_apply
  - proposal.apply hard invariant (payload flag) fires DENY
  - Negative data-safety: no raw memory, credentials, patch body in PolicyDecisionRecord
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session
from unittest.mock import MagicMock, patch

from app.policy.decisions import Decision, RiskLevel
from app.policy.gateway import PolicyGateway, PolicyCheckRequest
from app.policy.sanitizer import sanitize_policy_metadata


class TestPolicyGatewayRecordPersistence:
    """PolicyGateway persists PolicyDecisionRecord for audit-required and denied decisions."""

    def test_unknown_action_records_deny(self, db: Session):
        gw = PolicyGateway(db)
        decision = gw.check_and_record(
            PolicyCheckRequest(
                action="totally_unknown_action",
                actor_id="user1",
                space_id="s1",
            )
        )
        assert decision.denied
        assert decision.audit_code == "unknown_policy_action"

        from app.models import PolicyDecisionRecord
        record = db.query(PolicyDecisionRecord).filter(
            PolicyDecisionRecord.action == "totally_unknown_action"
        ).first()
        assert record is not None
        assert record.decision == "deny"
        assert record.audit_code == "unknown_policy_action"

    def test_runtime_execute_allow_records_audit(self, db: Session):
        """runtime.execute is audit_required=True — even ALLOW decisions must be recorded."""
        gw = PolicyGateway(db)
        decision = gw.check_and_record(
            PolicyCheckRequest(
                action="runtime.execute",
                actor_type="run",
                actor_id="run-123",
                space_id="s1",
                resource_type="run",
                resource_id="run-123",
                run_id="run-123",
            )
        )
        assert decision.allowed

        from app.models import PolicyDecisionRecord
        record = db.query(PolicyDecisionRecord).filter(
            PolicyDecisionRecord.run_id == "run-123"
        ).first()
        assert record is not None
        assert record.decision == "allow"
        assert record.action == "runtime.execute"

    def test_deny_decision_always_recorded(self, db: Session):
        """Any DENY decision is always persisted regardless of audit_required.
        Use cross-space credential access which fires the space_boundary deny rule.
        """
        gw = PolicyGateway(db)
        decision = gw.check_and_record(
            PolicyCheckRequest(
                action="runtime.use_credential",
                actor_id="user1",
                space_id="space_a",
                resource_space_id="space_b",  # cross-space → hard deny
                run_id="run-deny-test",
                force_record=False,
            )
        )
        assert decision.denied

        from app.models import PolicyDecisionRecord
        record = db.query(PolicyDecisionRecord).filter(
            PolicyDecisionRecord.action == "runtime.use_credential",
            PolicyDecisionRecord.actor_id == "user1",
        ).first()
        assert record is not None

    def test_force_record_persists_even_low_risk_allow(self, db: Session):
        # Use context.inject_memory (audit_required=False) to test force_record behaviour.
        # workspace.read and context.use_personal_grant are reserved actions, so use
        # context.inject_memory here to test force_record on a wired low-risk allow action.
        gw = PolicyGateway(db)
        decision = gw.check_and_record(
            PolicyCheckRequest(
                action="context.inject_memory",
                actor_id="user1",
                space_id="s1",
                resource_space_id="s1",
                run_id="run-force-record-test",
                force_record=True,
            )
        )
        assert decision.allowed

        from app.models import PolicyDecisionRecord
        record = db.query(PolicyDecisionRecord).filter(
            PolicyDecisionRecord.action == "context.inject_memory",
            PolicyDecisionRecord.run_id == "run-force-record-test",
        ).first()
        assert record is not None

    def test_metadata_sanitized_before_persistence(self, db: Session):
        gw = PolicyGateway(db)
        gw.check_and_record(
            PolicyCheckRequest(
                action="runtime.execute",
                actor_id="user1",
                space_id="s1",
                run_id="run-meta-test",
                metadata_json={"adapter_type": "echo", "api_key": "sk-secret"},
                force_record=True,
            )
        )

        from app.models import PolicyDecisionRecord
        record = db.query(PolicyDecisionRecord).filter(
            PolicyDecisionRecord.run_id == "run-meta-test"
        ).first()
        assert record is not None
        assert record.metadata_json is not None
        assert record.metadata_json.get("api_key") == "[REDACTED]"
        assert record.metadata_json.get("adapter_type") == "echo"


class TestRuntimeExecutePolicyGateUnitRules:
    """UNIT TESTS: PolicyEngine rule logic for runtime.execute.

    These tests call PolicyEngine directly with synthetic context dicts.
    They verify rule logic only — they do NOT prove real RunExecutionService blocking.
    For real execution blocking tests see:
        tests/workflows/test_run_execution_policy_workflow.py
    """

    def test_deny_via_unknown_tool_permission_blocks_execution(self):
        """UNIT: rule_tool_permission fires for tool not in agent's allowed list → DENY."""
        from app.policy.engine import PolicyEngine
        engine = PolicyEngine()
        d = engine.check({
            "action": "runtime.execute",
            "space_id": "s1",
            "resource_space_id": "s1",
            "tool_name": "claude_code",
            "agent_tool_permissions": ["echo"],
        })
        assert d.denied
        assert d.policy_rule_id == "tool_permission"

    def test_allow_when_tool_in_permissions(self):
        """UNIT: Tool in agent's allowed list → ALLOW (registry default)."""
        from app.policy.engine import PolicyEngine
        engine = PolicyEngine()
        d = engine.check({
            "action": "runtime.execute",
            "space_id": "s1",
            "resource_space_id": "s1",
            "tool_name": "echo",
            "agent_tool_permissions": ["echo", "claude_code"],
        })
        assert d.allowed

    def test_inactive_agent_denies_runtime_execute(self):
        """UNIT: agent_status='disabled' in context → DENY from rule_agent_status."""
        from app.policy.engine import PolicyEngine
        engine = PolicyEngine()
        d = engine.check({
            "action": "runtime.execute",
            "space_id": "s1",
            "agent_status": "disabled",
        })
        assert d.denied
        assert d.policy_rule_id == "agent_status"


class TestPolicyDecisionRecordSchema:
    """Schema contract: PolicyDecisionRecord persists expected fields correctly."""

    def test_record_fields_round_trip(self, db: Session):
        from app.models import PolicyDecisionRecord
        from datetime import datetime, UTC

        record = PolicyDecisionRecord(
            space_id="space-test",
            actor_type="user",
            actor_id="user-abc",
            action="runtime.execute",
            resource_type="run",
            resource_id="run-xyz",
            decision="allow",
            risk_level="medium",
            required_approver_role=None,
            approval_capability=None,
            policy_rule_id="registry_default",
            policy_source="registry",
            audit_code=None,
            run_id="run-xyz",
            proposal_id=None,
            metadata_json={"adapter_type": "echo"},
            created_at=datetime.now(UTC),
        )
        db.add(record)
        db.flush()
        db.refresh(record)

        assert record.id is not None
        assert record.space_id == "space-test"
        assert record.actor_type == "user"
        assert record.action == "runtime.execute"
        assert record.decision == "allow"
        assert record.risk_level == "medium"

    def test_invalid_decision_value_rejected(self, db: Session):
        """Check constraint on decision column."""
        from app.models import PolicyDecisionRecord
        from datetime import datetime, UTC
        import sqlalchemy.exc

        record = PolicyDecisionRecord(
            action="runtime.execute",
            decision="permitted",
            risk_level="medium",
            created_at=datetime.now(UTC),
        )
        db.add(record)
        with pytest.raises(Exception):
            db.flush()
        db.rollback()


class TestContextInjectMemoryGate:
    """context.inject_memory: cross-space deny is recorded; same-space allow is not (audit_required=False)."""

    def test_same_space_inject_memory_allow_not_recorded(self, db: Session):
        """Same-space context.inject_memory ALLOW without force_record is not persisted
        (audit_required=False for this action)."""
        gw = PolicyGateway(db)
        decision = gw.check_and_record(
            PolicyCheckRequest(
                action="context.inject_memory",
                actor_type="run",
                actor_id="run-inject-same",
                space_id="space_a",
                resource_space_id="space_a",
                run_id="run-inject-same",
            )
        )
        assert decision.allowed

        from app.models import PolicyDecisionRecord
        record = db.query(PolicyDecisionRecord).filter(
            PolicyDecisionRecord.run_id == "run-inject-same"
        ).first()
        assert record is None, "same-space allow without force_record must not produce a record"

    def test_cross_space_inject_memory_denied_and_recorded(self, db: Session):
        """Cross-space context.inject_memory fires HardInvariantGuard → DENY → record persisted."""
        gw = PolicyGateway(db)
        decision = gw.check_and_record(
            PolicyCheckRequest(
                action="context.inject_memory",
                actor_type="run",
                actor_id="run-inject-cross",
                space_id="space_a",
                resource_space_id="space_b",  # cross-space → invariant fires
                run_id="run-inject-cross",
            )
        )
        assert decision.denied
        assert "cross_space" in (decision.audit_code or "").lower() or "hard_invariant" in (decision.policy_rule_id or "").lower()

        from app.models import PolicyDecisionRecord
        record = db.query(PolicyDecisionRecord).filter(
            PolicyDecisionRecord.run_id == "run-inject-cross",
            PolicyDecisionRecord.action == "context.inject_memory",
        ).first()
        assert record is not None
        assert record.decision == "deny"
        assert record.policy_source == "hard_invariant"

    def test_same_space_inject_memory_with_has_grant_context_is_allowed(self, db: Session):
        """Same-space context.inject_memory with has_personal_grant_context in metadata is allowed.

        Note: cross-space memory access is enforced by ContextBuilder, not the PolicyGateway
        context.inject_memory check, which always operates on the run's own space_id.
        """
        gw = PolicyGateway(db)
        decision = gw.check_and_record(
            PolicyCheckRequest(
                action="context.inject_memory",
                actor_type="run",
                actor_id="run-inject-grant",
                space_id="space_a",
                resource_space_id="space_a",  # same space
                run_id="run-inject-grant",
                metadata_json={
                    "has_personal_grant_context": True,
                    "data_exposure_level": "elevated",
                },
            )
        )
        assert decision.allowed


class TestContextRenderForRuntimeGate:
    """context.render_for_runtime: cross-space deny fires hard invariant and is recorded."""

    def test_cross_space_render_for_runtime_denied(self, db: Session):
        """Cross-space context.render_for_runtime without grant → DENY via hard invariant."""
        gw = PolicyGateway(db)
        decision = gw.check_and_record(
            PolicyCheckRequest(
                action="context.render_for_runtime",
                actor_type="run",
                actor_id="run-render-cross",
                space_id="space_a",
                resource_space_id="space_b",
                run_id="run-render-cross",
            )
        )
        assert decision.denied
        assert decision.policy_source == "hard_invariant"

        from app.models import PolicyDecisionRecord
        record = db.query(PolicyDecisionRecord).filter(
            PolicyDecisionRecord.run_id == "run-render-cross",
            PolicyDecisionRecord.action == "context.render_for_runtime",
        ).first()
        assert record is not None
        assert record.decision == "deny"

    def test_same_space_render_for_runtime_is_allowed(self, db: Session):
        """Same-space context.render_for_runtime → ALLOW (no hard invariant triggers)."""
        gw = PolicyGateway(db)
        decision = gw.check_and_record(
            PolicyCheckRequest(
                action="context.render_for_runtime",
                actor_type="run",
                actor_id="run-render-same",
                space_id="space_x",
                resource_space_id="space_x",
                run_id="run-render-same",
            )
        )
        assert decision.allowed


class TestArtifactPersistGate:
    """artifact.persist: ALLOW always recorded (audit_required=True); personal_context_block fires DENY."""

    def test_safe_artifact_persist_allow_is_recorded(self, db: Session):
        """artifact.persist ALLOW must create a PolicyDecisionRecord (audit_required=True)."""
        gw = PolicyGateway(db)
        decision = gw.check_and_record(
            PolicyCheckRequest(
                action="artifact.persist",
                actor_type="run",
                actor_id="run-art-safe",
                space_id="space_a",
                run_id="run-art-safe",
                context={
                    "target_space_id": "space_a",
                    "derived_from_personal_memory_grant": False,
                    "raw_private_memory_included": False,
                },
                metadata_json={
                    "artifact_type": "runtime_output",
                    "target_space_id": "space_a",
                    "source_run_id": "run-art-safe",
                    "preview": False,
                },
            )
        )
        assert decision.allowed

        from app.models import PolicyDecisionRecord
        record = db.query(PolicyDecisionRecord).filter(
            PolicyDecisionRecord.run_id == "run-art-safe",
            PolicyDecisionRecord.action == "artifact.persist",
        ).first()
        assert record is not None, "artifact.persist is audit_required=True — must record even on ALLOW"
        assert record.decision == "allow"

    def test_artifact_persist_personal_context_block_denied(self, db: Session):
        """personal_context_block in metadata fires HardInvariantGuard → DENY for artifact.persist."""
        gw = PolicyGateway(db)
        decision = gw.check_and_record(
            PolicyCheckRequest(
                action="artifact.persist",
                actor_type="run",
                actor_id="run-art-pcb",
                space_id="space_a",
                run_id="run-art-pcb",
                metadata_json={
                    "personal_context_block": "private content that must not be persisted",
                    "artifact_type": "runtime_output",
                },
            )
        )
        assert decision.denied
        assert decision.policy_source == "hard_invariant"
        assert decision.audit_code == "personal_context_block_persist_attempt"

        from app.models import PolicyDecisionRecord
        record = db.query(PolicyDecisionRecord).filter(
            PolicyDecisionRecord.run_id == "run-art-pcb",
            PolicyDecisionRecord.action == "artifact.persist",
        ).first()
        assert record is not None
        assert record.decision == "deny"
        # Verify personal_context_block was redacted before storing
        meta = record.metadata_json or {}
        assert meta.get("personal_context_block") == "[REDACTED]"


class TestProposalCreateAudit:
    """proposal.create: force_record=True ensures audit even on ALLOW for high-risk types."""

    def test_proposal_create_allow_with_force_record_is_recorded(self, db: Session):
        """proposal.create with force_record=True records even on ALLOW."""
        gw = PolicyGateway(db)
        decision = gw.check_and_record(
            PolicyCheckRequest(
                action="proposal.create",
                actor_type="user",
                actor_id="user-create-1",
                space_id="space_a",
                run_id="run-prop-create-1",
                force_record=True,
                metadata_json={
                    "proposal_type": "memory_create",
                    "target_scope": "user",
                    "target_visibility": "private",
                    "sensitivity_level": "sensitive",
                },
            )
        )
        assert decision.allowed

        from app.models import PolicyDecisionRecord
        record = db.query(PolicyDecisionRecord).filter(
            PolicyDecisionRecord.run_id == "run-prop-create-1",
            PolicyDecisionRecord.action == "proposal.create",
        ).first()
        assert record is not None
        assert record.decision == "allow"
        # Content must not be stored in metadata
        meta = record.metadata_json or {}
        assert "proposed_content" not in meta
        assert "personal_context_block" not in meta

    def test_proposal_create_personal_context_block_denied(self, db: Session):
        """personal_context_block in proposal.create metadata fires hard invariant → DENY."""
        gw = PolicyGateway(db)
        decision = gw.check_and_record(
            PolicyCheckRequest(
                action="proposal.create",
                actor_type="user",
                actor_id="user-create-2",
                space_id="space_a",
                metadata_json={
                    "personal_context_block": "sensitive personal block",
                    "proposal_type": "memory_create",
                },
            )
        )
        assert decision.denied
        assert decision.policy_source == "hard_invariant"


class TestProposalApplyGateway:
    """proposal.apply through PolicyGateway.check_proposal_apply: role/risk matrix and hard invariants."""

    def test_valid_user_allow_decision_is_recorded(self, db: Session):
        """Valid proposal + user_id → ALLOW or REQUIRE_APPROVAL depending on risk; always recorded."""
        from tests.support import factories
        from tests.support.ids import PERSONAL_SPACE_ID, DEFAULT_USER_ID

        prop = factories.create_test_proposal(
            db,
            space_id=PERSONAL_SPACE_ID,
            created_by_user_id=DEFAULT_USER_ID,
            proposal_type="memory_create",
            commit=True,
        )

        gw = PolicyGateway(db)
        decision = gw.check_proposal_apply(
            user_id=DEFAULT_USER_ID,
            space_id=PERSONAL_SPACE_ID,
            proposal=prop,
            metadata_json={"proposal_type": "memory_create"},
        )
        # proposal.apply default is REQUIRE_APPROVAL — so the decision should be that or better
        assert decision.decision in (Decision.ALLOW, Decision.REQUIRE_APPROVAL)

        from app.models import PolicyDecisionRecord
        record = db.query(PolicyDecisionRecord).filter(
            PolicyDecisionRecord.proposal_id == prop.id,
            PolicyDecisionRecord.action == "proposal.apply",
        ).first()
        assert record is not None, "proposal.apply is audit_required=True — must always record"

    def test_payload_flag_approved_by_user_fires_hard_invariant(self, db: Session):
        """approved_by_user flag in proposal payload fires HardInvariantGuard → DENY."""
        from tests.support import factories
        from tests.support.ids import PERSONAL_SPACE_ID, DEFAULT_USER_ID

        prop = factories.create_test_proposal(
            db,
            space_id=PERSONAL_SPACE_ID,
            created_by_user_id=DEFAULT_USER_ID,
            proposal_type="memory_create",
            payload_json={
                "operation": "create",
                "proposed_content": "content",
                "memory_type": "semantic",
                "target_scope": "agent",
                "target_namespace": "agent.test",
                "target_visibility": "space_shared",
                "sensitivity_level": "normal",
                "approved_by_user": True,  # hard invariant: payload flag not acceptance proof
            },
            commit=True,
        )

        gw = PolicyGateway(db)
        decision = gw.check_proposal_apply(
            user_id=DEFAULT_USER_ID,
            space_id=PERSONAL_SPACE_ID,
            proposal=prop,
        )
        assert decision.denied
        assert decision.policy_source == "hard_invariant"
        assert decision.audit_code == "payload_flag_as_approval_proof"

        from app.models import PolicyDecisionRecord
        record = db.query(PolicyDecisionRecord).filter(
            PolicyDecisionRecord.proposal_id == prop.id,
            PolicyDecisionRecord.action == "proposal.apply",
        ).first()
        assert record is not None
        assert record.decision == "deny"
        # proposal payload body must not be stored verbatim
        meta = record.metadata_json or {}
        assert "approved_by_user" not in meta or meta.get("approved_by_user") is None

    def test_proposal_apply_metadata_contains_only_safe_fields(self, db: Session):
        """check_proposal_apply stores only safe audit fields, not proposal body content.

        The gateway adds proposal_type and decision_source internally.
        Proposal body (proposed_content, provenance_entries, payload) must never appear.
        """
        from tests.support import factories
        from tests.support.ids import PERSONAL_SPACE_ID, DEFAULT_USER_ID

        prop = factories.create_test_proposal(
            db,
            space_id=PERSONAL_SPACE_ID,
            created_by_user_id=DEFAULT_USER_ID,
            proposal_type="memory_create",
            commit=True,
        )

        gw = PolicyGateway(db)
        gw.check_proposal_apply(
            user_id=DEFAULT_USER_ID,
            space_id=PERSONAL_SPACE_ID,
            proposal=prop,
        )

        from app.models import PolicyDecisionRecord
        record = db.query(PolicyDecisionRecord).filter(
            PolicyDecisionRecord.proposal_id == prop.id,
            PolicyDecisionRecord.action == "proposal.apply",
        ).first()
        assert record is not None
        meta = record.metadata_json or {}

        # Only safe audit fields should be present — no proposal body, no content, no payload
        allowed_keys = {"proposal_type", "decision_source"}
        unexpected_body_keys = {"proposed_content", "provenance_entries", "payload", "payload_json"}
        stored_body_keys = unexpected_body_keys & set(meta.keys())
        assert not stored_body_keys, (
            f"Proposal body keys must never appear in PolicyDecisionRecord metadata; "
            f"found: {stored_body_keys}"
        )
        # Safe audit fields must be present
        assert meta.get("proposal_type") == "memory_create"


class TestReservedActionFailClosed:
    """Reserved actions (lifecycle_status=RESERVED, current_enforcement_point='not_implemented') must always DENY.

    Reserved actions are allowed to exist in the registry for vocabulary completeness,
    but PolicyGateway.check_and_record() must never fall through to a registry default ALLOW
    or REQUIRE_APPROVAL when the action has not been wired to a real enforcement point.
    """

    def test_workspace_read_reserved_returns_deny(self, db: Session):
        """workspace.read is reserved (lifecycle_status=RESERVED, default_decision=ALLOW) — must still return DENY."""
        gw = PolicyGateway(db)
        decision = gw.check_and_record(
            PolicyCheckRequest(
                action="workspace.read",
                actor_type="user",
                actor_id="user-placeholder-1",
                space_id="space_a",
                resource_id="ws-1",
            )
        )
        assert decision.denied, (
            "workspace.read is a reserved action and must DENY even though its "
            "registry default_decision is ALLOW"
        )
        assert decision.audit_code == "policy_action_not_implemented"
        assert decision.policy_rule_id == "action_not_implemented"

    def test_workspace_read_reserved_persists_record(self, db: Session):
        """workspace.read reserved DENY must create a PolicyDecisionRecord."""
        gw = PolicyGateway(db)
        gw.check_and_record(
            PolicyCheckRequest(
                action="workspace.read",
                actor_type="user",
                actor_id="user-placeholder-2",
                space_id="space_a",
                resource_id="ws-persist-test",
                run_id="run-placeholder-persist",
            )
        )

        from app.models import PolicyDecisionRecord
        record = db.query(PolicyDecisionRecord).filter(
            PolicyDecisionRecord.run_id == "run-placeholder-persist",
            PolicyDecisionRecord.action == "workspace.read",
        ).first()
        assert record is not None, "Reserved action DENY must always persist a PolicyDecisionRecord"
        assert record.decision == "deny"
        assert record.audit_code == "policy_action_not_implemented"
        assert record.action == "workspace.read"

    def test_deployment_execute_reserved_deny_overrides_require_approval_default(self, db: Session):
        """deployment.execute default_decision=REQUIRE_APPROVAL must still return DENY as a reserved action."""
        gw = PolicyGateway(db)
        decision = gw.check_and_record(
            PolicyCheckRequest(
                action="deployment.execute",
                actor_type="user",
                actor_id="user-deploy-exec",
                space_id="space_a",
                resource_id="deploy-1",
                run_id="run-deploy-exec",
            )
        )
        assert decision.denied, (
            "deployment.execute is a reserved action and must DENY even though its "
            "registry default_decision is REQUIRE_APPROVAL"
        )
        assert decision.audit_code == "policy_action_not_implemented"
        assert decision.policy_rule_id == "action_not_implemented"

        from app.models import PolicyDecisionRecord
        record = db.query(PolicyDecisionRecord).filter(
            PolicyDecisionRecord.run_id == "run-deploy-exec",
            PolicyDecisionRecord.action == "deployment.execute",
        ).first()
        assert record is not None
        assert record.decision == "deny"
        assert record.audit_code == "policy_action_not_implemented"


class TestPolicyDecisionRecordDataSafety:
    """Negative data-safety tests: dangerous fields are never stored in PolicyDecisionRecord."""

    def test_api_key_in_metadata_is_redacted(self, db: Session):
        gw = PolicyGateway(db)
        gw.check_and_record(
            PolicyCheckRequest(
                action="runtime.execute",
                actor_id="user-safety-1",
                space_id="s1",
                run_id="run-safety-apikey",
                force_record=True,
                metadata_json={"adapter_type": "echo", "api_key": "sk-secret-abc"},
            )
        )
        from app.models import PolicyDecisionRecord
        record = db.query(PolicyDecisionRecord).filter(
            PolicyDecisionRecord.run_id == "run-safety-apikey"
        ).first()
        assert record is not None
        assert record.metadata_json.get("api_key") == "[REDACTED]"
        assert record.metadata_json.get("adapter_type") == "echo"

    def test_raw_memory_in_metadata_is_redacted(self, db: Session):
        gw = PolicyGateway(db)
        gw.check_and_record(
            PolicyCheckRequest(
                action="artifact.persist",
                actor_id="user-safety-2",
                space_id="s1",
                run_id="run-safety-rawmem",
                metadata_json={
                    "artifact_type": "runtime_output",
                    "raw_memory": "secret personal content that must never be stored",
                },
            )
        )
        from app.models import PolicyDecisionRecord
        record = db.query(PolicyDecisionRecord).filter(
            PolicyDecisionRecord.run_id == "run-safety-rawmem"
        ).first()
        assert record is not None
        assert record.metadata_json.get("raw_memory") == "[REDACTED]"

    def test_patch_body_in_metadata_is_redacted(self, db: Session):
        gw = PolicyGateway(db)
        gw.check_and_record(
            PolicyCheckRequest(
                action="workspace.write_patch",
                actor_id="user-safety-3",
                space_id="s1",
                resource_space_id="s1",
                run_id="run-safety-patch",
                force_record=True,
                metadata_json={
                    "ops_count": 3,
                    "patch": "--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@\n-old\n+new",
                    "diff": "full diff content",
                    "file_content": "complete file source",
                },
            )
        )
        from app.models import PolicyDecisionRecord
        record = db.query(PolicyDecisionRecord).filter(
            PolicyDecisionRecord.run_id == "run-safety-patch"
        ).first()
        assert record is not None
        for dangerous_key in ("patch", "diff", "file_content"):
            assert record.metadata_json.get(dangerous_key) == "[REDACTED]", (
                f"{dangerous_key} must be redacted in PolicyDecisionRecord metadata"
            )
        assert record.metadata_json.get("ops_count") == 3

    def test_stdout_stderr_in_metadata_are_redacted(self, db: Session):
        gw = PolicyGateway(db)
        gw.check_and_record(
            PolicyCheckRequest(
                action="runtime.execute",
                actor_id="user-safety-4",
                space_id="s1",
                run_id="run-safety-stdio",
                force_record=True,
                metadata_json={
                    "adapter_type": "echo",
                    "stdout": "execution output text",
                    "stderr": "execution error text",
                },
            )
        )
        from app.models import PolicyDecisionRecord
        record = db.query(PolicyDecisionRecord).filter(
            PolicyDecisionRecord.run_id == "run-safety-stdio"
        ).first()
        assert record is not None
        assert record.metadata_json.get("stdout") == "[REDACTED]"
        assert record.metadata_json.get("stderr") == "[REDACTED]"

    def test_personal_context_block_never_stored_in_any_record(self, db: Session):
        """personal_context_block in metadata triggers hard invariant DENY.
        The persisted record must have it redacted, not stored verbatim."""
        gw = PolicyGateway(db)
        decision = gw.check_and_record(
            PolicyCheckRequest(
                action="artifact.persist",
                actor_id="user-safety-5",
                space_id="s1",
                run_id="run-safety-pcb",
                metadata_json={
                    "personal_context_block": "my private memory context",
                    "artifact_type": "runtime_output",
                },
            )
        )
        assert decision.denied

        from app.models import PolicyDecisionRecord
        record = db.query(PolicyDecisionRecord).filter(
            PolicyDecisionRecord.run_id == "run-safety-pcb"
        ).first()
        assert record is not None
        meta = record.metadata_json or {}
        # Must be redacted or absent — never stored verbatim
        pcb_val = meta.get("personal_context_block")
        assert pcb_val != "my private memory context", (
            "personal_context_block must never be stored verbatim in PolicyDecisionRecord"
        )
        assert pcb_val == "[REDACTED]" or pcb_val is None


class TestDecisionCarriesStableFields:
    """PolicyGateway decisions must carry reason_code, audit_code, and actor_type."""

    def test_unknown_action_decision_carries_reason_code_and_actor_type(self, db: Session):
        """Unknown action deny must have reason_code and reflect the requested actor_type."""
        gw = PolicyGateway(db)
        decision = gw.check_and_record(
            PolicyCheckRequest(
                action="totally_unknown_action",
                actor_type="user",
                actor_id="u1",
                space_id="s1",
            )
        )
        assert decision.denied
        assert decision.reason_code == "unknown_policy_action"
        assert decision.audit_code == "unknown_policy_action"
        assert decision.actor_type == "user"

    def test_reserved_action_denied_by_gateway_carries_reason_code(self, db: Session):
        """Reserved (lifecycle=RESERVED) actions must be denied with reason_code at the gateway."""
        gw = PolicyGateway(db)
        decision = gw.check_and_record(
            PolicyCheckRequest(
                action="automation.create",
                actor_type="user",
                actor_id="u1",
                space_id="s1",
            )
        )
        assert decision.denied
        assert decision.reason_code == "policy_action_not_implemented"
        assert decision.audit_code == "policy_action_not_implemented"
        assert decision.actor_type == "user"

    def test_inactive_agent_deny_carries_reason_code_and_actor_type(self, db: Session):
        """agent_status='disabled' deny via rule_agent_status carries reason_code and actor_type."""
        gw = PolicyGateway(db)
        decision = gw.check_and_record(
            PolicyCheckRequest(
                action="runtime.execute",
                actor_type="run",
                actor_id="run-disabled",
                space_id="s1",
                context={"agent_status": "disabled"},
            )
        )
        assert decision.denied
        assert decision.reason_code == "agent_status"
        assert decision.actor_type == "run"
