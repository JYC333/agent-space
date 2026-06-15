from __future__ import annotations

"""Durable policy audit writer — independent of the request/business transaction.

DurablePolicyAuditWriter uses its own short-lived SQLAlchemy session from
SessionLocal so that PolicyDecisionRecord rows are committed atomically
regardless of whether the business transaction is rolled back.

Usage (blocking decision, from global exception handler or local catch):

    from app.policy.audit import DurablePolicyAuditWriter, PolicyAuditEnvelope
    envelope = PolicyAuditEnvelope(...)
    record_id = DurablePolicyAuditWriter().write(envelope)

Usage (allow decision with audit_required, from PolicyGateway.enforce):

    record_id = DurablePolicyAuditWriter().write(envelope)

The writer must only write PolicyDecisionRecord.
It must not write Automation, Run, Proposal, MemoryEntry, Policy, Artifact,
Workspace, Credential, or Capability rows.
It must not call PolicyEngine.
It must not inspect raw proposal payload except already-sanitized metadata.
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Optional

log = logging.getLogger(__name__)


@dataclass
class PolicyAuditEnvelope:
    """Full safe input needed to create a PolicyDecisionRecord.

    Fields mirror PolicyDecisionRecord columns.  Dangerous fields have already
    been stripped by sanitize_policy_metadata() before this envelope is built.
    No raw payload, raw memory, prompt, patch body, stdout/stderr, credentials,
    secret refs, or personal_context_block may appear here.
    """

    action: str
    decision: str
    risk_level: str
    space_id: Optional[str] = None
    actor_type: Optional[str] = None
    actor_id: Optional[str] = None
    actor_ref_json: Optional[dict[str, Any]] = None
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    required_approver_role: Optional[str] = None
    approval_capability: Optional[str] = None
    policy_rule_id: Optional[str] = None
    policy_source: Optional[str] = None
    policy_id: Optional[str] = None
    audit_code: Optional[str] = None
    run_id: Optional[str] = None
    proposal_id: Optional[str] = None
    metadata_json: Optional[dict[str, Any]] = None
    created_at: Optional[datetime] = None


class DurablePolicyAuditWriter:
    """Writes a single PolicyDecisionRecord in an independent session.

    - Uses its own short-lived SQLAlchemy session from SessionLocal.
    - Never uses the request/business DB session.
    - Sanitizes metadata via sanitize_policy_metadata() before persistence.
    - Inserts exactly one PolicyDecisionRecord.
    - Commits the audit record independently.
    - Rolls back and closes its own session on error.
    - Returns the created record id on success.
    - Raises the original exception on failure (callers decide fail_closed vs best_effort).
    """

    def write(self, envelope: PolicyAuditEnvelope) -> str:
        """Persist one PolicyDecisionRecord in a fresh committed transaction.

        Returns the record id (str) on success.
        Raises on any persistence failure so callers can apply fail_closed logic.
        """
        from ..db import SessionLocal
        from ..models import PolicyDecisionRecord
        from .sanitizer import sanitize_policy_metadata

        db = SessionLocal()
        try:
            safe_meta = sanitize_policy_metadata(envelope.metadata_json)
            record = PolicyDecisionRecord(
                space_id=envelope.space_id,
                actor_type=envelope.actor_type,
                actor_id=envelope.actor_id,
                actor_ref_json=envelope.actor_ref_json,
                action=envelope.action,
                resource_type=envelope.resource_type,
                resource_id=envelope.resource_id,
                decision=envelope.decision,
                risk_level=envelope.risk_level,
                required_approver_role=envelope.required_approver_role,
                approval_capability=envelope.approval_capability,
                policy_rule_id=envelope.policy_rule_id,
                policy_source=envelope.policy_source,
                policy_id=envelope.policy_id,
                audit_code=envelope.audit_code,
                run_id=envelope.run_id,
                proposal_id=envelope.proposal_id,
                metadata_json=safe_meta,
                created_at=envelope.created_at or datetime.now(UTC),
            )
            db.add(record)
            db.commit()
            db.refresh(record)
            return record.id
        except Exception:
            log.error(
                "DurablePolicyAuditWriter failed: action=%s actor=%s decision=%s",
                envelope.action,
                envelope.actor_id,
                envelope.decision,
                exc_info=True,
            )
            try:
                db.rollback()
            except Exception:
                pass
            raise
        finally:
            try:
                db.close()
            except Exception:
                pass


def envelope_from_blocked_gate(exc: Any) -> PolicyAuditEnvelope:
    """Construct the durable record for one PolicyGateBlocked exception."""
    return PolicyAuditEnvelope(
        space_id=exc.space_id,
        actor_type=exc.actor_type,
        actor_id=exc.actor_id,
        actor_ref_json=exc.actor_ref,
        action=exc.action,
        resource_type=exc.resource_type,
        resource_id=exc.resource_id,
        decision=exc.decision.decision.value,
        risk_level=exc.decision.risk_level.value,
        required_approver_role=exc.decision.required_approver_role,
        approval_capability=exc.decision.approval_capability,
        policy_rule_id=exc.decision.policy_rule_id,
        policy_source=exc.decision.policy_source,
        policy_id=exc.decision.policy_id,
        audit_code=exc.decision.audit_code,
        run_id=exc.run_id,
        proposal_id=exc.proposal_id,
        metadata_json=exc.metadata_json,
    )


def write_blocked_gate_audit(exc: Any) -> str:
    """Durably record a blocked gate exactly once for HTTP or local handling."""
    if getattr(exc, "audit_already_persisted", False):
        return "already_persisted"
    return DurablePolicyAuditWriter().write(envelope_from_blocked_gate(exc))
