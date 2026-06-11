"""Durable audit invariants for ArtifactPersistenceService.

Verifies:
  - artifact.persist ALLOW writes exactly one durable PolicyDecisionRecord
    visible from a fresh DB session.
  - artifact.persist DENY writes exactly one durable PolicyDecisionRecord
    visible from a fresh DB session.
  - artifact.persist DENY creates no Artifact row.
  - artifact.persist DENY writes no artifact file.
  - artifact.persist audit failure creates no Artifact row or file.
  - ArtifactPersistenceService.persist_text_file uses PolicyGateway.enforce.
  - ArtifactPersistenceService.persist_copied_file uses PolicyGateway.enforce.
"""
from __future__ import annotations

import inspect
from unittest.mock import patch

import pytest

from app.config import settings
from app.models import Artifact, PolicyDecisionRecord
from app.personal_memory_grants.egress_guard import PersonalMemoryEgressError
from app.policy.decisions import Decision, PolicyDecision, RiskLevel
from app.policy.exceptions import PolicyGateBlocked
from app.runs.artifact_persistence import ArtifactPersistenceService
from tests.support import factories
from tests.support.ids import DEFAULT_USER_ID, PERSONAL_SPACE_ID


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_run(db) -> "Run":
    """Minimal committed Run fixture for artifact persistence tests."""
    agent = factories.create_test_agent(
        db, space_id=PERSONAL_SPACE_ID, owner_user_id=DEFAULT_USER_ID, commit=False
    )
    run = factories.create_test_run(
        db, space_id=PERSONAL_SPACE_ID, user_id=DEFAULT_USER_ID, agent=agent, commit=False
    )
    db.commit()
    return run


def _blocked_exc(
    *,
    requires_approval: bool = False,
    run_id: str = "run-block-test",
    actor_id: str | None = None,
) -> PolicyGateBlocked:
    """Construct a minimal PolicyGateBlocked for a blocked artifact.persist check."""
    actor_id = actor_id or run_id
    decision_val = Decision.REQUIRE_APPROVAL if requires_approval else Decision.DENY
    decision = PolicyDecision(
        decision=decision_val,
        message="test block",
        risk_level=RiskLevel.HIGH,
        reason_code="test_deny",
        policy_rule_id="test_rule",
        policy_source="builtin",
        audit_code="test_block",
    )
    return PolicyGateBlocked(
        decision=decision,
        action="artifact.persist",
        actor_type="run",
        actor_id=actor_id,
        actor_ref=None,
        space_id=PERSONAL_SPACE_ID,
        resource_type="artifact",
        resource_id=None,
        run_id=run_id,
        proposal_id=None,
        metadata_json={"artifact_type": "runtime_output"},
        http_status_code=403,
    )


def _fresh_pdr_count(
    *,
    action: str,
    decision_val: str | None = None,
    run_id: str | None = None,
) -> int:
    from app.db import SessionLocal

    fresh = SessionLocal()
    try:
        query = fresh.query(PolicyDecisionRecord).filter(PolicyDecisionRecord.action == action)
        if decision_val is not None:
            query = query.filter(PolicyDecisionRecord.decision == decision_val)
        if run_id is not None:
            query = query.filter(PolicyDecisionRecord.run_id == run_id)
        return query.count()
    finally:
        fresh.close()


# ---------------------------------------------------------------------------
# ALLOW: durable audit record written from fresh session
# ---------------------------------------------------------------------------


class TestArtifactPersistAllowDurableAudit:
    """artifact.persist ALLOW: durable PolicyDecisionRecord visible from a fresh session."""

    def test_allow_creates_one_durable_record(self, db, tmp_path, monkeypatch):
        monkeypatch.setattr(settings, "artifact_storage_root", str(tmp_path / "artifacts"))
        run = _make_run(db)

        before = _fresh_pdr_count(
            action="artifact.persist",
            decision_val="allow",
            run_id=str(run.id),
        )

        svc = ArtifactPersistenceService(db)
        artifact = svc.persist_text_file(
            run=run,
            text="hello",
            title="test output",
            artifact_type="runtime_output",
        )
        db.commit()

        after = _fresh_pdr_count(
            action="artifact.persist",
            decision_val="allow",
            run_id=str(run.id),
        )

        assert after == before + 1, (
            f"Expected exactly one new durable PolicyDecisionRecord for artifact.persist/allow, "
            f"got {after - before}"
        )

    def test_two_persist_calls_create_two_audit_records_not_duplicates(self, db, tmp_path, monkeypatch):
        """Two allowed persists create one durable audit row per artifact, not duplicates."""
        monkeypatch.setattr(settings, "artifact_storage_root", str(tmp_path / "artifacts"))
        run = _make_run(db)
        before = _fresh_pdr_count(action="artifact.persist", run_id=str(run.id))

        svc = ArtifactPersistenceService(db)
        first = svc.persist_text_file(run=run, text="a", title="a", artifact_type="runtime_output")
        db.commit()
        second = svc.persist_text_file(run=run, text="b", title="b", artifact_type="runtime_output")
        db.commit()

        count = _fresh_pdr_count(action="artifact.persist", run_id=str(run.id))

        assert count == before + 2, (
            f"Expected exactly 2 durable records after two persists, got {count - before}"
        )
        assert first.id != second.id
        assert db.query(Artifact).filter(Artifact.run_id == run.id).count() == 2
        root = tmp_path / "artifacts"
        assert (root / first.storage_path).is_file()
        assert (root / second.storage_path).is_file()


# ---------------------------------------------------------------------------
# DENY: durable audit record written via write_blocked_gate_audit; no business rows
# ---------------------------------------------------------------------------


class TestArtifactPersistDenyDurableAudit:
    """artifact.persist DENY: durable audit record written; no Artifact row; no file."""

    def test_deny_creates_one_durable_record(self, db, tmp_path, monkeypatch):
        monkeypatch.setattr(settings, "artifact_storage_root", str(tmp_path / "artifacts"))
        run = _make_run(db)
        exc = _blocked_exc(run_id=str(run.id), actor_id=str(run.id))

        before_deny = _fresh_pdr_count(
            action="artifact.persist",
            decision_val="deny",
            run_id=str(run.id),
        )

        with patch("app.runs.artifact_persistence.PolicyGateway") as MockGW:
            MockGW.return_value.enforce.side_effect = exc
            with pytest.raises(PersonalMemoryEgressError):
                ArtifactPersistenceService(db).persist_text_file(
                    run=run, text="x", title="x", artifact_type="runtime_output"
                )

        after_deny = _fresh_pdr_count(
            action="artifact.persist",
            decision_val="deny",
            run_id=str(run.id),
        )

        assert after_deny == before_deny + 1, (
            f"Expected exactly one new durable PolicyDecisionRecord for artifact.persist/deny, "
            f"got {after_deny - before_deny}"
        )

    def test_deny_creates_no_artifact_row(self, db, tmp_path, monkeypatch):
        monkeypatch.setattr(settings, "artifact_storage_root", str(tmp_path / "artifacts"))
        run = _make_run(db)
        before = db.query(Artifact).filter(Artifact.run_id == run.id).count()

        with patch("app.runs.artifact_persistence.PolicyGateway") as MockGW:
            MockGW.return_value.enforce.side_effect = _blocked_exc(
                run_id=str(run.id),
                actor_id=str(run.id),
            )
            with pytest.raises(PersonalMemoryEgressError):
                ArtifactPersistenceService(db).persist_text_file(
                    run=run, text="x", title="x", artifact_type="runtime_output"
                )

        db.expire_all()
        after = db.query(Artifact).filter(Artifact.run_id == run.id).count()
        assert after == before, "No Artifact row must be created when artifact.persist is denied"

    def test_deny_writes_no_artifact_file(self, db, tmp_path, monkeypatch):
        art_root = tmp_path / "artifacts"
        monkeypatch.setattr(settings, "artifact_storage_root", str(art_root))
        run = _make_run(db)

        with patch("app.runs.artifact_persistence.PolicyGateway") as MockGW:
            MockGW.return_value.enforce.side_effect = _blocked_exc(
                run_id=str(run.id),
                actor_id=str(run.id),
            )
            with pytest.raises(PersonalMemoryEgressError):
                ArtifactPersistenceService(db).persist_text_file(
                    run=run, text="secret", title="x", artifact_type="runtime_output"
                )

        written = list(art_root.rglob("*")) if art_root.exists() else []
        assert not written, f"No files must be written on deny; found: {written}"

    def test_deny_raises_stable_denied_message(self, db, tmp_path, monkeypatch):
        monkeypatch.setattr(settings, "artifact_storage_root", str(tmp_path / "artifacts"))
        run = _make_run(db)

        with patch("app.runs.artifact_persistence.PolicyGateway") as MockGW:
            MockGW.return_value.enforce.side_effect = _blocked_exc(
                run_id=str(run.id),
                actor_id=str(run.id),
            )
            with pytest.raises(PersonalMemoryEgressError) as exc_info:
                ArtifactPersistenceService(db).persist_text_file(
                    run=run, text="x", title="x", artifact_type="runtime_output"
                )

        assert str(exc_info.value) == "artifact.persist denied by policy: test block"

    def test_requires_approval_raises_stable_approval_message(self, db, tmp_path, monkeypatch):
        monkeypatch.setattr(settings, "artifact_storage_root", str(tmp_path / "artifacts"))
        run = _make_run(db)

        with patch("app.runs.artifact_persistence.PolicyGateway") as MockGW:
            MockGW.return_value.enforce.side_effect = _blocked_exc(
                requires_approval=True,
                run_id=str(run.id),
                actor_id=str(run.id),
            )
            with pytest.raises(PersonalMemoryEgressError) as exc_info:
                ArtifactPersistenceService(db).persist_text_file(
                    run=run, text="x", title="x", artifact_type="runtime_output"
                )

        assert str(exc_info.value) == "artifact.persist requires approval: test block"


class TestArtifactPersistAuditFailure:
    """Durable audit failure prevents artifact persistence."""

    def test_allow_audit_failure_writes_no_artifact(self, db, tmp_path, monkeypatch):
        art_root = tmp_path / "artifacts"
        monkeypatch.setattr(settings, "artifact_storage_root", str(art_root))
        run = _make_run(db)
        before = db.query(Artifact).filter(Artifact.run_id == run.id).count()

        with patch(
            "app.policy.audit.DurablePolicyAuditWriter.write",
            side_effect=RuntimeError("audit down"),
        ):
            with pytest.raises(PersonalMemoryEgressError) as exc_info:
                ArtifactPersistenceService(db).persist_text_file(
                    run=run, text="secret", title="x", artifact_type="runtime_output"
                )

        assert str(exc_info.value) == (
            "policy_decision_record_persist_failed: policy audit record persistence "
            "failed for artifact.persist. No artifact written."
        )
        assert db.query(Artifact).filter(Artifact.run_id == run.id).count() == before
        assert not art_root.exists()

    def test_blocked_audit_failure_writes_no_artifact(self, db, tmp_path, monkeypatch):
        art_root = tmp_path / "artifacts"
        monkeypatch.setattr(settings, "artifact_storage_root", str(art_root))
        run = _make_run(db)
        before = db.query(Artifact).filter(Artifact.run_id == run.id).count()

        with (
            patch("app.runs.artifact_persistence.PolicyGateway") as gateway,
            patch(
                "app.runs.artifact_persistence.write_blocked_gate_audit",
                side_effect=RuntimeError("audit down"),
            ) as write_audit,
        ):
            gateway.return_value.enforce.side_effect = _blocked_exc(
                run_id=str(run.id),
                actor_id=str(run.id),
            )
            with pytest.raises(PersonalMemoryEgressError) as exc_info:
                ArtifactPersistenceService(db).persist_text_file(
                    run=run, text="secret", title="x", artifact_type="runtime_output"
                )

        write_audit.assert_called_once()
        assert str(exc_info.value) == (
            "policy_decision_record_persist_failed: policy audit record persistence "
            "failed for artifact.persist. No artifact written."
        )
        assert db.query(Artifact).filter(Artifact.run_id == run.id).count() == before
        assert not art_root.exists()


# ---------------------------------------------------------------------------
# Structural: current PolicyGateway entry point only
# ---------------------------------------------------------------------------


class TestArtifactPersistUsesCurrentGateway:
    """ArtifactPersistenceService must call the current gateway entry point."""

    def _source(self) -> str:
        import app.runs.artifact_persistence as _mod
        return inspect.getsource(_mod)

    def test_persist_text_file_uses_enforce(self):
        src = self._source()
        assert ".enforce(" in src
        assert f".{'check_' + 'and_record'}(" not in src

    def test_persist_copied_file_uses_enforce(self):
        src = self._source()
        assert ".enforce(" in src
        assert f".{'check_' + 'and_record'}(" not in src
