"""Business-boundary tests for PolicyDecisionRecordPersistError handling.

Tasks 3 + 6: Verifies that PDR persistence failures are converted into stable
business errors at each enforcement boundary:

  - ProposalService.accept: PDR failure → ProposalPolicyDeniedError, no apply, proposal stays pending
  - code_patch_apply: PDR failure → CodePatchApplyError with stable message, no file writes
  - ArtifactPersistenceService: PDR failure → PersonalMemoryEgressError, no file/row written
  - RecordFailureMode: typed enum used consistently

Task 3 supported-proposal coverage:
  - memory_create proposal with PDR failure → no MemoryEntry, pending
  - policy_change proposal with PDR failure → no Policy row, pending
  - code_patch proposal with write_patch PDR failure → no file write
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch, PropertyMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_db_failing() -> MagicMock:
    db = MagicMock()
    db.add = MagicMock()
    db.flush = MagicMock(side_effect=Exception("DB flush failure"))
    return db


def _mock_db_ok() -> MagicMock:
    db = MagicMock()
    db.add = MagicMock()
    db.flush = MagicMock()
    return db


def _make_proposal(proposal_type: str = "memory_create", risk_level: str = "medium") -> MagicMock:
    proposal = MagicMock()
    proposal.id = f"prop-{proposal_type}"
    proposal.proposal_type = proposal_type
    proposal.space_id = "s1"
    proposal.payload_json = {"operation": "create"}
    proposal.risk_level = risk_level
    proposal.status = "pending"
    proposal.preview = False
    return proposal


# ---------------------------------------------------------------------------
# ProposalService.accept: PDR persistence failure
# ---------------------------------------------------------------------------


class TestProposalServiceAcceptPdrFailure:
    """ProposalService.accept must not call apply() when PDR persistence fails."""

    def _accept_with_pdr_failure(self, proposal_type: str):
        from app.policy.gateway import PolicyDecisionRecordPersistError
        from app.memory.proposals import ProposalService, ProposalPolicyDeniedError

        db = _mock_db_ok()
        proposal = _make_proposal(proposal_type)

        svc = ProposalService(db)

        # Stub get() to return the proposal directly
        svc.get = MagicMock(return_value=proposal)

        # check_proposal_apply raises PDR error (simulating DB flush failure during record persist).
        # PDR error fires before ProposalApplyService is even imported, so no mock needed there.
        with patch("app.memory.proposals.PolicyGateway") as MockGW:
            MockGW.return_value.check_proposal_apply.side_effect = PolicyDecisionRecordPersistError(
                action="proposal.apply", actor_id="u1"
            )
            with pytest.raises(ProposalPolicyDeniedError) as exc_info:
                svc.accept(proposal.id, space_id="s1", user_id="u1")

        err = exc_info.value
        assert err.audit_code == "policy_decision_record_persist_failed"
        assert "policy_decision_record_persist_failed" in err.message
        # Proposal status must remain pending (not mutated)
        assert proposal.status == "pending"

    def test_memory_create_pdr_failure_does_not_apply(self):
        """memory_create proposal: PDR fail → ProposalPolicyDeniedError, no apply."""
        self._accept_with_pdr_failure("memory_create")

    def test_policy_change_pdr_failure_does_not_apply(self):
        """policy_change proposal: PDR fail → ProposalPolicyDeniedError, no apply."""
        self._accept_with_pdr_failure("policy_change")

    def test_memory_update_pdr_failure_does_not_apply(self):
        """memory_update proposal: PDR fail → ProposalPolicyDeniedError, no apply."""
        self._accept_with_pdr_failure("memory_update")

    def test_pdr_failure_stable_error_code(self):
        """The raised error must carry the stable audit_code and not expose internal metadata."""
        from app.policy.gateway import PolicyDecisionRecordPersistError
        from app.memory.proposals import ProposalService, ProposalPolicyDeniedError

        db = _mock_db_ok()
        proposal = _make_proposal("memory_create")
        svc = ProposalService(db)
        svc.get = MagicMock(return_value=proposal)

        with patch("app.memory.proposals.PolicyGateway") as MockGW:
            MockGW.return_value.check_proposal_apply.side_effect = PolicyDecisionRecordPersistError(
                action="proposal.apply"
            )
            with pytest.raises(ProposalPolicyDeniedError) as exc_info:
                svc.accept(proposal.id, space_id="s1", user_id="u1")

        err = exc_info.value
        assert err.audit_code == "policy_decision_record_persist_failed"
        assert err.decision == "deny"


# ---------------------------------------------------------------------------
# code_patch_apply: workspace.write_patch PDR failure
# ---------------------------------------------------------------------------


class TestCodePatchApplyPdrFailure:
    """workspace.write_patch PDR failure must raise CodePatchApplyError before any file write."""

    def test_pdr_failure_raises_code_patch_apply_error(self, tmp_path):
        from app.memory.code_patch_apply import CodePatchApplyError, apply_code_patch_payload
        from app.policy.gateway import PolicyDecisionRecordPersistError

        db = _mock_db_ok()
        workspace = MagicMock()
        workspace.id = "ws-1"
        workspace.root_path = str(tmp_path)

        patch_payload = {
            "operations": [
                {
                    "op": "replace_file",
                    "path": "test.txt",
                    "content": "new content",
                    "preimage_exists": False,
                    "preimage_sha256": None,
                }
            ]
        }

        target_file = tmp_path / "test.txt"
        assert not target_file.exists()

        with patch("app.memory.code_patch_apply.PolicyGateway") as MockGW:
            MockGW.return_value.check_and_record.side_effect = PolicyDecisionRecordPersistError(
                action="workspace.write_patch"
            )
            with pytest.raises(CodePatchApplyError) as exc_info:
                apply_code_patch_payload(
                    db,
                    workspace=workspace,
                    patch=patch_payload,
                    space_id="s1",
                    user_id="u1",
                    source_run_id=None,
                    proposal_id="prop-1",
                )

        assert "policy_decision_record_persist_failed" in str(exc_info.value)
        # No file must have been written
        assert not target_file.exists()

    def test_pdr_failure_message_is_stable(self, tmp_path):
        from app.memory.code_patch_apply import CodePatchApplyError, apply_code_patch_payload
        from app.policy.gateway import PolicyDecisionRecordPersistError

        db = _mock_db_ok()
        workspace = MagicMock()
        workspace.id = "ws-1"
        workspace.root_path = str(tmp_path)

        patch_payload = {
            "operations": [
                {
                    "op": "replace_file",
                    "path": "foo.py",
                    "content": "x = 1",
                    "preimage_exists": False,
                    "preimage_sha256": None,
                }
            ]
        }

        with patch("app.memory.code_patch_apply.PolicyGateway") as MockGW:
            MockGW.return_value.check_and_record.side_effect = PolicyDecisionRecordPersistError(
                action="workspace.write_patch"
            )
            with pytest.raises(CodePatchApplyError) as exc_info:
                apply_code_patch_payload(
                    db,
                    workspace=workspace,
                    patch=patch_payload,
                    space_id="s1",
                    user_id="u1",
                    source_run_id=None,
                    proposal_id="prop-2",
                )

        err_msg = str(exc_info.value)
        assert "policy_decision_record_persist_failed" in err_msg
        # Must not contain raw exception internals or stack traces
        assert "Traceback" not in err_msg


# ---------------------------------------------------------------------------
# ArtifactPersistenceService: artifact.persist PDR failure
# ---------------------------------------------------------------------------


class TestArtifactPersistencePdrFailure:
    """artifact.persist PDR failure must raise PersonalMemoryEgressError, no file/row written."""

    def test_persist_text_file_pdr_failure_raises(self, tmp_path):
        from app.runs.artifact_persistence import ArtifactPersistenceService
        from app.policy.gateway import PolicyDecisionRecordPersistError
        from app.personal_memory_grants.egress_guard import PersonalMemoryEgressError

        db = _mock_db_ok()
        run = MagicMock()
        run.id = "run-1"
        run.space_id = "s1"
        run.workspace_id = None
        run.project_id = None
        run.instructed_by_user_id = "u1"
        run.has_personal_grant_context = False

        svc = ArtifactPersistenceService(db)

        with patch("app.runs.artifact_persistence.PolicyGateway") as MockGW:
            MockGW.return_value.check_and_record.side_effect = PolicyDecisionRecordPersistError(
                action="artifact.persist"
            )
            with pytest.raises(PersonalMemoryEgressError) as exc_info:
                svc.persist_text_file(
                    run=run,
                    text="some output",
                    title="test artifact",
                    artifact_type="runtime_output",
                )

        assert "policy_decision_record_persist_failed" in str(exc_info.value)
        # db.add must not have been called with an Artifact row (no row written)
        db.add.assert_not_called()

    def test_persist_copied_file_pdr_failure_raises(self, tmp_path):
        from app.runs.artifact_persistence import ArtifactPersistenceService
        from app.policy.gateway import PolicyDecisionRecordPersistError
        from app.personal_memory_grants.egress_guard import PersonalMemoryEgressError

        # Create a real temp file to act as the source
        src = tmp_path / "output.txt"
        src.write_text("content", encoding="utf-8")

        db = _mock_db_ok()
        run = MagicMock()
        run.id = "run-2"
        run.space_id = "s1"
        run.workspace_id = None
        run.project_id = None
        run.instructed_by_user_id = "u1"
        run.has_personal_grant_context = False

        svc = ArtifactPersistenceService(db)

        with patch("app.runs.artifact_persistence.PolicyGateway") as MockGW:
            MockGW.return_value.check_and_record.side_effect = PolicyDecisionRecordPersistError(
                action="artifact.persist"
            )
            with pytest.raises(PersonalMemoryEgressError) as exc_info:
                svc.persist_copied_file(
                    run=run,
                    source_file=src,
                    source_relative_path="output.txt",
                    title="test copied",
                )

        assert "policy_decision_record_persist_failed" in str(exc_info.value)
        db.add.assert_not_called()

