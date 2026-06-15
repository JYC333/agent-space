from __future__ import annotations

"""Policy exception types for blocking decisions and durable audit failures.

PolicyGateBlocked
    Raised by PolicyGateway.enforce() when a sensitive action is denied or
    requires approval.  Carries a sanitized audit envelope so the global
    exception handler can write a durable PolicyDecisionRecord independently
    of the business/request transaction.

PolicyAuditPersistError
    Raised when durable audit persistence fails for a fail-closed decision.
    The sensitive action must not proceed when this is raised.

Neither exception carries raw payload, raw memory, prompt, patch body,
stdout/stderr, credentials, secret refs, or personal_context_block.
"""

from typing import Any, Optional

from .decisions import Decision, PolicyDecision


class PolicyGateBlocked(Exception):
    """Raised by PolicyGateway.enforce() on a blocking policy decision.

    Blocking decisions: DENY or REQUIRE_APPROVAL.

    The global exception handler (app.main) catches this, rolls back the
    request/business DB session via request.state.db, writes the
    PolicyDecisionRecord through DurablePolicyAuditWriter in an independent
    transaction, and returns an HTTP 403 response.

    Call sites must not catch this and manually raise HTTPException for
    sensitive actions — let it propagate to the global handler.

    Attributes
    ----------
    decision        Full PolicyDecision object (read-only; never stored in DB).
    action          Registered policy action name.
    actor_type      "user" | "run" | "agent" | None.
    actor_id        Opaque actor identifier.
    actor_ref       Structured actor reference (audit-only, sanitized).
    space_id        Space scope of the action.
    resource_type   Resource type being acted on.
    resource_id     Resource being acted on.
    run_id          Run context if applicable.
    proposal_id     Proposal context if applicable.
    metadata_json   Sanitized audit-only metadata bag (no secrets / raw payload).
    audit_already_persisted True when the authority already handled durable audit.
    http_status_code HTTP status code for the response (default 403).
    error_code      "policy_denied" | "policy_requires_approval".
    """

    def __init__(
        self,
        *,
        decision: PolicyDecision,
        action: str,
        actor_type: Optional[str],
        actor_id: Optional[str],
        actor_ref: Optional[dict[str, Any]],
        space_id: Optional[str],
        resource_type: Optional[str],
        resource_id: Optional[str],
        run_id: Optional[str],
        proposal_id: Optional[str],
        metadata_json: Optional[dict[str, Any]],
        http_status_code: int = 403,
        audit_already_persisted: bool = False,
    ) -> None:
        self.decision = decision
        self.action = action
        self.actor_type = actor_type
        self.actor_id = actor_id
        self.actor_ref = actor_ref
        self.space_id = space_id
        self.resource_type = resource_type
        self.resource_id = resource_id
        self.run_id = run_id
        self.proposal_id = proposal_id
        self.metadata_json = metadata_json
        self.http_status_code = http_status_code
        self.audit_already_persisted = audit_already_persisted

        if decision.decision == Decision.DENY:
            self.error_code = "policy_denied"
        else:
            self.error_code = "policy_requires_approval"

        super().__init__(
            f"Policy gate blocked: action={action!r} "
            f"decision={decision.decision.value!r} "
            f"actor={actor_id!r} "
            f"reason={decision.reason_code!r}"
        )


class PolicyAuditPersistError(Exception):
    """Raised when durable audit persistence fails for a fail-closed action.

    The sensitive action that triggered this check must not proceed.
    """

    def __init__(self, action: str, actor_id: Optional[str] = None) -> None:
        self.action = action
        self.actor_id = actor_id
        self.audit_code = "policy_decision_record_persist_failed"
        super().__init__(
            f"Policy audit persistence failed for fail-closed action {action!r}. "
            "Sensitive action must not proceed. "
            "audit_code='policy_decision_record_persist_failed'"
        )
