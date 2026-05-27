"""Unit tests for DurablePolicyAuditWriter.

A. Unit tests for audit writer:
  1. Writer creates PolicyDecisionRecord in an independent session.
  2. Metadata is sanitized (no credentials, prompt, patch body, stdout/stderr, raw memory,
     personal_context_block).
  3. Writer rollback/close behavior on failure.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from app.policy.audit import DurablePolicyAuditWriter, PolicyAuditEnvelope
from app.models import PolicyDecisionRecord
from tests.support.ids import DEFAULT_USER_ID, PERSONAL_SPACE_ID


def _make_envelope(**overrides) -> PolicyAuditEnvelope:
    defaults = dict(
        space_id=PERSONAL_SPACE_ID,
        actor_type="user",
        actor_id=DEFAULT_USER_ID,
        actor_ref_json=None,
        action="automation.create",
        resource_type="automation",
        resource_id="auto-123",
        decision="deny",
        risk_level="high",
        required_approver_role="owner",
        approval_capability=None,
        policy_rule_id="automation_insufficient_role",
        policy_source="builtin",
        policy_id=None,
        audit_code="automation_insufficient_role",
        run_id=None,
        proposal_id=None,
        metadata_json={"automation_name": "test"},
    )
    defaults.update(overrides)
    return PolicyAuditEnvelope(**defaults)


class TestDurablePolicyAuditWriterCreatesRecord:
    """A1. DurablePolicyAuditWriter creates PolicyDecisionRecord in an independent session."""

    def test_creates_record_visible_from_fresh_session(self, db):
        envelope = _make_envelope(decision="deny", action="automation.create")
        record_id = DurablePolicyAuditWriter().write(envelope)

        assert record_id is not None

        # Verify via fresh query (writer committed in its own session)
        from app.db import SessionLocal
        fresh = SessionLocal()
        try:
            record = fresh.query(PolicyDecisionRecord).filter(
                PolicyDecisionRecord.id == record_id
            ).first()
            assert record is not None
            assert record.action == "automation.create"
            assert record.decision == "deny"
            assert record.actor_id == DEFAULT_USER_ID
            assert record.space_id == PERSONAL_SPACE_ID
            assert record.risk_level == "high"
        finally:
            fresh.close()

    def test_returns_string_id(self, db):
        envelope = _make_envelope()
        record_id = DurablePolicyAuditWriter().write(envelope)
        assert isinstance(record_id, str)
        assert len(record_id) > 0

    def test_does_not_use_request_session(self, db):
        """The writer uses its own session; the request db is never touched."""
        flush_called = []
        original_flush = db.flush

        def spy_flush():
            flush_called.append(True)
            return original_flush()

        db.flush = spy_flush

        DurablePolicyAuditWriter().write(_make_envelope())
        assert flush_called == [], "Writer must not use the request/business db session"

        db.flush = original_flush  # restore


class TestMetadataSanitization:
    """A2. Metadata is sanitized before persistence."""

    def _write_and_fetch(self, metadata_json: dict) -> PolicyDecisionRecord:
        from app.db import SessionLocal

        envelope = _make_envelope(metadata_json=metadata_json)
        record_id = DurablePolicyAuditWriter().write(envelope)

        fresh = SessionLocal()
        try:
            record = fresh.query(PolicyDecisionRecord).filter(
                PolicyDecisionRecord.id == record_id
            ).first()
            return record
        finally:
            fresh.close()

    def test_credentials_redacted(self):
        record = self._write_and_fetch({"credential": "secret-key", "safe_key": "safe"})
        meta = record.metadata_json or {}
        assert meta.get("credential") == "[REDACTED]"
        assert meta.get("safe_key") == "safe"

    def test_prompt_redacted(self):
        record = self._write_and_fetch({"prompt": "system prompt content"})
        meta = record.metadata_json or {}
        assert meta.get("prompt") == "[REDACTED]"

    def test_patch_body_redacted(self):
        record = self._write_and_fetch({"patch": "--- a/file.py\n+++ b/file.py"})
        meta = record.metadata_json or {}
        assert meta.get("patch") == "[REDACTED]"

    def test_stdout_redacted(self):
        record = self._write_and_fetch({"stdout": "output text"})
        meta = record.metadata_json or {}
        assert meta.get("stdout") == "[REDACTED]"

    def test_stderr_redacted(self):
        record = self._write_and_fetch({"stderr": "error text"})
        meta = record.metadata_json or {}
        assert meta.get("stderr") == "[REDACTED]"

    def test_raw_memory_redacted(self):
        record = self._write_and_fetch({"raw_memory": "private memory content"})
        meta = record.metadata_json or {}
        assert meta.get("raw_memory") == "[REDACTED]"

    def test_personal_context_block_redacted(self):
        record = self._write_and_fetch({"personal_context_block": "private block"})
        meta = record.metadata_json or {}
        assert meta.get("personal_context_block") == "[REDACTED]"

    def test_safe_metadata_preserved(self):
        record = self._write_and_fetch({"automation_name": "my-auto", "trigger_type": "manual"})
        meta = record.metadata_json or {}
        assert meta.get("automation_name") == "my-auto"
        assert meta.get("trigger_type") == "manual"

    def test_none_metadata_stored_as_none(self):
        envelope = _make_envelope(metadata_json=None)
        record_id = DurablePolicyAuditWriter().write(envelope)
        from app.db import SessionLocal
        fresh = SessionLocal()
        try:
            record = fresh.query(PolicyDecisionRecord).filter(
                PolicyDecisionRecord.id == record_id
            ).first()
            assert record.metadata_json is None
        finally:
            fresh.close()


class TestWriterFailureBehavior:
    """A3. Writer rollback/close behavior on failure."""

    def test_raises_on_db_failure(self):
        """Writer raises the original exception so callers can apply fail_closed logic."""
        envelope = _make_envelope()

        with patch("app.db.SessionLocal") as mock_session_local:
            mock_db = MagicMock()
            mock_db.add = MagicMock()
            mock_db.commit = MagicMock(side_effect=Exception("simulated commit failure"))
            mock_db.rollback = MagicMock()
            mock_db.close = MagicMock()
            mock_session_local.return_value = mock_db

            with pytest.raises(Exception, match="simulated commit failure"):
                DurablePolicyAuditWriter().write(envelope)

            mock_db.rollback.assert_called_once()
            mock_db.close.assert_called_once()

    def test_close_called_even_on_failure(self):
        """Session is always closed even when commit raises."""
        envelope = _make_envelope()

        with patch("app.db.SessionLocal") as mock_session_local:
            mock_db = MagicMock()
            mock_db.commit = MagicMock(side_effect=RuntimeError("db error"))
            mock_db.rollback = MagicMock()
            mock_db.close = MagicMock()
            mock_session_local.return_value = mock_db

            with pytest.raises(RuntimeError):
                DurablePolicyAuditWriter().write(envelope)

            mock_db.close.assert_called_once()

    def test_rollback_called_on_failure(self):
        envelope = _make_envelope()

        with patch("app.db.SessionLocal") as mock_session_local:
            mock_db = MagicMock()
            mock_db.commit = MagicMock(side_effect=RuntimeError("db error"))
            mock_db.rollback = MagicMock()
            mock_db.close = MagicMock()
            mock_session_local.return_value = mock_db

            with pytest.raises(RuntimeError):
                DurablePolicyAuditWriter().write(envelope)

            mock_db.rollback.assert_called_once()
