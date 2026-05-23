from __future__ import annotations

"""PolicyGateway — enforcement entry point for sensitive policy checks.

Usage:

    from app.policy.gateway import PolicyGateway, PolicyCheckRequest

    decision = PolicyGateway(db).check_and_record(
        PolicyCheckRequest(
            actor_type="user",
            actor_id=user_id,
            space_id=space_id,
            action="runtime.execute",
            resource_type="run",
            resource_id=run_id,
            run_id=run_id,
        )
    )
    if decision.denied:
        # ... handle denial

Stack:
    HardInvariantGuard → PolicyEngine → PolicyDecisionRecord (persisted when needed)

Field semantics for context vs metadata_json:

    context       — bounded decision inputs consumed by HardInvariantGuard and
                    PolicyEngine rules (e.g. agent_status, tool_name, trigger_origin,
                    derived_from_personal_memory_grant, raw_private_memory_included,
                    target_visibility, target_space_id).  Flattened into the guard
                    context so invariants and rules read top-level keys.

    metadata_json — sanitized audit-only metadata written to PolicyDecisionRecord.
                    Never grants permission or satisfies approval. Forbidden sentinel
                    fields may still cause a defensive hard DENY (e.g. a
                    personal_context_block or approval-proof flag in the audit bag).

    payload       — proposal or policy payload; only used by HardInvariantGuard
                    invariants that scan for approval-proof flags (proposal.apply,
                    policy.change).  Not a decision input for any other action.

Action lifecycle:

    wired_direct       — action has a real direct PolicyGateway.check_and_record() call
                         site; HardInvariantGuard and PolicyEngine are run normally.
    wired_via_proposal — action is protected via the proposal.apply gate only; must
                         not be called directly through check_and_record(). Doing so
                         always fails closed with reason_code="policy_action_via_proposal_only".
    reserved           — action is registered for vocabulary completeness but has no
                         enforcement point; PolicyGateway always denies reserved actions
                         (fail-closed) before running HardInvariantGuard or PolicyEngine.

record_failure_mode (RecordFailureMode):

    BEST_EFFORT — if PolicyDecisionRecord persistence fails, log a warning and continue.
    FAIL_CLOSED — if PolicyDecisionRecord persistence fails, raise
                  PolicyDecisionRecordPersistError. The sensitive action must not
                  proceed. Actions with FAIL_CLOSED: runtime.use_credential,
                  workspace.write_patch, proposal.apply, policy.change.
                  Additional dynamic escalation to FAIL_CLOSED:
                    - automation-origin (trigger_origin="automation") + audit_required=True,
                      regardless of ALLOW/DENY/REQUIRE_APPROVAL.
                    - CRITICAL risk level + audit_required=True,
                      regardless of ALLOW/DENY/REQUIRE_APPROVAL.
                    - automation-origin + non-ALLOW (legacy rule for non-audit-required).
                    - CRITICAL risk level + non-ALLOW (legacy rule for non-audit-required).
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Optional

from .actions import PolicyActionLifecycle, RecordFailureMode, get_action_definition, require_action_definition, UnknownPolicyActionError
from .decisions import Decision, PolicyDecision, RiskLevel
from .engine import PolicyEngine
from .hard_invariants import HardInvariantGuard
from .sanitizer import sanitize_policy_metadata

log = logging.getLogger(__name__)

_engine = PolicyEngine()
_guard = HardInvariantGuard()


class PolicyDecisionRecordPersistError(Exception):
    """Raised when PolicyDecisionRecord persistence fails for a fail_closed action.

    The sensitive action that triggered this check must not proceed when this is raised.
    Callers should treat this as a hard policy error and surface it as a denial.
    """

    def __init__(self, action: str, actor_id: Optional[str] = None):
        self.action = action
        self.actor_id = actor_id
        super().__init__(
            f"PolicyDecisionRecord persistence failed for fail_closed action {action!r}. "
            "Sensitive action must not proceed. audit_code='policy_decision_record_persist_failed'"
        )


@dataclass
class PolicyCheckRequest:
    """Structured request for PolicyGateway.check_and_record().

    Field semantics:

    context (dict | None):
        Bounded decision inputs consumed by HardInvariantGuard and PolicyEngine
        rules.  Keys are flattened into the guard context so invariants can read
        them at the top level.  Fields like agent_status, tool_name, trigger_origin,
        derived_from_personal_memory_grant, raw_private_memory_included,
        target_visibility, and target_space_id belong here.

    metadata_json (dict | None):
        Sanitized audit-only metadata persisted in PolicyDecisionRecord.  It never
        grants permission or satisfies approval.  Forbidden sentinel fields may
        still cause a defensive hard DENY, such as personal_context_block or
        approval-proof flags.  Dangerous fields (credentials, raw memory,
        personal_context_block, patch bodies, stdout/stderr) are stripped by
        sanitize_policy_metadata() before storage.

    payload (dict | None):
        Proposal or policy payload.  Only HardInvariantGuard inspects payload
        (to block approval-proof flags in proposal.apply / policy.change).  Not
        a decision input for any other action.
    """

    action: str
    actor_type: Optional[str] = None
    actor_id: Optional[str] = None
    actor_ref: Optional[dict[str, Any]] = None
    space_id: Optional[str] = None
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    resource_space_id: Optional[str] = None
    run_id: Optional[str] = None
    proposal_id: Optional[str] = None
    context: Optional[dict[str, Any]] = None
    payload: Optional[dict[str, Any]] = None
    metadata_json: Optional[dict[str, Any]] = None
    force_record: bool = False


def _should_record(defn, decision: PolicyDecision, force: bool) -> bool:
    """Return True when the decision should be persisted as a PolicyDecisionRecord."""
    if force:
        return True
    if defn is not None and defn.audit_required:
        return True
    if decision.denied or decision.requires_approval:
        return True
    return False


def _build_engine_ctx(req: PolicyCheckRequest) -> dict[str, Any]:
    ctx: dict[str, Any] = {"action": req.action}
    if req.space_id:
        ctx["space_id"] = req.space_id
    if req.resource_space_id:
        ctx["resource_space_id"] = req.resource_space_id
    if req.actor_id:
        ctx["actor_id"] = req.actor_id
    if req.actor_ref:
        ctx["actor_ref"] = req.actor_ref
    if req.resource_type:
        ctx["resource_type"] = req.resource_type
    if req.resource_id:
        ctx["resource_id"] = req.resource_id
    if req.proposal_id:
        ctx["proposal_id"] = req.proposal_id
    if req.context:
        ctx.update(req.context)
    return ctx


def _guard_ctx(req: PolicyCheckRequest) -> dict[str, Any]:
    """Build the context dict passed to HardInvariantGuard.

    Decision inputs come exclusively from req.context (flattened to top level
    and also stored under the "context" key for invariants that need the
    structured bag).  req.metadata_json is stored under "metadata_json" for
    defensive sentinel checks only — it never grants permission or satisfies
    approval.
    """
    ctx: dict[str, Any] = {"action": req.action}
    if req.space_id:
        ctx["space_id"] = req.space_id
    if req.resource_space_id:
        ctx["resource_space_id"] = req.resource_space_id
    if req.metadata_json:
        ctx["metadata_json"] = req.metadata_json
    if req.payload:
        ctx["payload"] = req.payload
    if req.context:
        # Flatten decision inputs to top level so invariants read them as simple
        # keys.  Also keep the structured bag under "context" for invariants that
        # explicitly access it (e.g. _personal_context_block_not_persisted).
        ctx.update(req.context)
        ctx["context"] = req.context
    return ctx


def _persist_record(
    db: Any,
    req: PolicyCheckRequest,
    decision: PolicyDecision,
    failure_mode: RecordFailureMode = RecordFailureMode.BEST_EFFORT,
) -> None:
    """Persist a PolicyDecisionRecord.

    failure_mode=BEST_EFFORT — log warning and continue on error (never raises).
    failure_mode=FAIL_CLOSED — raise PolicyDecisionRecordPersistError on error;
                               callers must treat this as a hard policy error and
                               not proceed with the sensitive action.
    """
    try:
        from ..models import PolicyDecisionRecord

        safe_meta = sanitize_policy_metadata(req.metadata_json)
        record = PolicyDecisionRecord(
            space_id=req.space_id,
            actor_type=req.actor_type,
            actor_id=req.actor_id,
            actor_ref_json=req.actor_ref,
            action=req.action,
            resource_type=req.resource_type or decision.resource_type,
            resource_id=req.resource_id or decision.resource_id,
            decision=decision.decision.value,
            risk_level=decision.risk_level.value,
            required_approver_role=decision.required_approver_role,
            approval_capability=decision.approval_capability,
            policy_rule_id=decision.policy_rule_id,
            policy_source=decision.policy_source,
            policy_id=decision.policy_id,
            audit_code=decision.audit_code,
            run_id=req.run_id,
            proposal_id=req.proposal_id or decision.resource_id,
            metadata_json=safe_meta,
            created_at=datetime.now(UTC),
        )
        db.add(record)
        db.flush()
    except Exception:
        if failure_mode == RecordFailureMode.FAIL_CLOSED:
            log.error(
                "PolicyDecisionRecord persist failed (fail_closed) action=%s actor=%s — "
                "sensitive action will not proceed",
                req.action,
                req.actor_id,
                exc_info=True,
            )
            raise PolicyDecisionRecordPersistError(action=req.action, actor_id=req.actor_id)
        log.warning(
            "PolicyDecisionRecord persist failed (best-effort) action=%s actor=%s",
            req.action,
            req.actor_id,
            exc_info=True,
        )


def _resolve_failure_mode(
    defn: Any,
    decision: PolicyDecision,
    req: PolicyCheckRequest,
) -> RecordFailureMode:
    """Resolve effective record_failure_mode for this (defn, decision, req) combination.

    Priority (first match wins):
      1. Per-action definition's record_failure_mode (already FAIL_CLOSED for
         runtime.use_credential, workspace.write_patch, proposal.apply, policy.change).
      2. Escalate to FAIL_CLOSED when trigger_origin="automation" and the action
         has audit_required=True — applies regardless of ALLOW/DENY/REQUIRE_APPROVAL.
      3. Escalate to FAIL_CLOSED when risk_level=CRITICAL and the action has
         audit_required=True — applies regardless of ALLOW/DENY/REQUIRE_APPROVAL.
      4. Escalate to FAIL_CLOSED when trigger_origin="automation" and decision is
         non-ALLOW (legacy rule, covers non-audit-required automation actions).
      5. Escalate to FAIL_CLOSED when risk_level=CRITICAL and decision is non-ALLOW
         (legacy rule, covers non-audit-required critical actions).
      6. Default: BEST_EFFORT.
    """
    if defn is not None and defn.record_failure_mode == RecordFailureMode.FAIL_CLOSED:
        return RecordFailureMode.FAIL_CLOSED
    _audit_required = defn is not None and defn.audit_required
    trigger_origin = (req.context or {}).get("trigger_origin", "")
    if _audit_required:
        if trigger_origin == "automation":
            return RecordFailureMode.FAIL_CLOSED
        if decision.risk_level == RiskLevel.CRITICAL:
            return RecordFailureMode.FAIL_CLOSED
    is_non_allow = decision.decision != Decision.ALLOW
    if is_non_allow:
        if trigger_origin == "automation":
            return RecordFailureMode.FAIL_CLOSED
        if decision.risk_level == RiskLevel.CRITICAL:
            return RecordFailureMode.FAIL_CLOSED
    return RecordFailureMode.BEST_EFFORT


class PolicyGateway:
    """Main entry point for sensitive policy decisions.

    Call check_and_record() from business code before performing a sensitive action.
    Actual sensitive-action enforcement must not call PolicyEngine directly.
    PreflightService's non-mutating PolicyEngine simulation is not enforcement.
    """

    def __init__(self, db: Any):
        self.db = db

    def _persist_record_from_decision(
        self,
        decision: PolicyDecision,
        *,
        actor_type: Optional[str] = None,
        actor_id: Optional[str] = None,
        actor_ref: Optional[dict[str, Any]] = None,
        space_id: Optional[str] = None,
        run_id: Optional[str] = None,
        proposal_id: Optional[str] = None,
        metadata_json: Optional[dict[str, Any]] = None,
        failure_mode: RecordFailureMode = RecordFailureMode.BEST_EFFORT,
    ) -> None:
        """Persist a PolicyDecisionRecord from an already-computed PolicyDecision.

        Use this when a policy check was done outside check_and_record() (e.g.
        check_proposal_apply_policy) and you need to record its outcome.

        failure_mode=FAIL_CLOSED raises PolicyDecisionRecordPersistError on error.
        """
        action_label = decision.action or "proposal.apply"
        try:
            from ..models import PolicyDecisionRecord

            safe_meta = sanitize_policy_metadata(metadata_json)
            record = PolicyDecisionRecord(
                space_id=space_id or decision.space_id,
                actor_type=actor_type,
                actor_id=actor_id or decision.actor_id,
                actor_ref_json=actor_ref or decision.actor_ref,
                action=action_label,
                resource_type=decision.resource_type,
                resource_id=decision.resource_id or proposal_id,
                decision=decision.decision.value,
                risk_level=decision.risk_level.value,
                required_approver_role=decision.required_approver_role,
                approval_capability=decision.approval_capability,
                policy_rule_id=decision.policy_rule_id,
                policy_source=decision.policy_source,
                policy_id=decision.policy_id,
                audit_code=decision.audit_code,
                run_id=run_id,
                proposal_id=proposal_id or decision.resource_id,
                metadata_json=safe_meta,
                created_at=datetime.now(UTC),
            )
            self.db.add(record)
            self.db.flush()
        except PolicyDecisionRecordPersistError:
            raise
        except Exception:
            if failure_mode == RecordFailureMode.FAIL_CLOSED:
                log.error(
                    "PolicyDecisionRecord persist failed (fail_closed) action=%s actor=%s — "
                    "sensitive action will not proceed",
                    action_label,
                    actor_id,
                    exc_info=True,
                )
                raise PolicyDecisionRecordPersistError(action=action_label, actor_id=actor_id)
            log.warning(
                "PolicyDecisionRecord persist failed (best-effort) action=%s",
                action_label,
                exc_info=True,
            )

    def check_proposal_apply(
        self,
        user_id: str,
        space_id: str,
        proposal: Any,
        metadata_json: Optional[dict[str, Any]] = None,
    ) -> PolicyDecision:
        """Evaluate the proposal.apply gate and persist the decision.

        Steps:
          1. Run HardInvariantGuard — payload flags or egress violations deny immediately.
          2. Compute effective proposal risk.
          3. Check user approval authority (role vs risk matrix).
          4. Persist PolicyDecisionRecord.
          5. Return PolicyDecision (ALLOW / REQUIRE_APPROVAL / DENY).

        The returned decision always has actor_type="user", actor_id, space_id,
        resource_type="proposal", resource_id, and proposal_type populated.

        Never calls ProposalApplyService — this is a pure gate.
        """
        from .hard_invariants import HardInvariantGuard
        from .proposal_apply import check_proposal_apply_policy

        guard = HardInvariantGuard()
        guard_ctx: dict[str, Any] = {
            "action": "proposal.apply",
            "space_id": space_id,
            "payload": proposal.payload_json or {},
        }
        invariant_denial = guard.check(guard_ctx)
        if invariant_denial is not None:
            # Attach actor and resource fields to the returned decision object.
            invariant_denial.actor_type = invariant_denial.actor_type or "user"
            invariant_denial.actor_id = invariant_denial.actor_id or user_id
            invariant_denial.space_id = invariant_denial.space_id or space_id
            invariant_denial.resource_type = invariant_denial.resource_type or "proposal"
            invariant_denial.resource_id = invariant_denial.resource_id or proposal.id
            invariant_denial.proposal_type = invariant_denial.proposal_type or proposal.proposal_type
            safe_meta = sanitize_policy_metadata({
                **(metadata_json or {}),
                "proposal_type": proposal.proposal_type,
                "decision_source": "hard_invariant_guard",
            })
            # proposal.apply is fail_closed — invariant denial must be persisted or abort.
            self._persist_record_from_decision(
                invariant_denial,
                actor_type="user",
                actor_id=user_id,
                space_id=space_id,
                proposal_id=proposal.id,
                metadata_json=safe_meta,
                failure_mode=RecordFailureMode.FAIL_CLOSED,
            )
            return invariant_denial

        decision = check_proposal_apply_policy(
            self.db, user_id=user_id, space_id=space_id, proposal=proposal
        )
        # Ensure actor_type and resource fields are populated on returned object.
        decision.actor_type = decision.actor_type or "user"
        decision.actor_id = decision.actor_id or user_id
        decision.space_id = decision.space_id or space_id
        decision.resource_type = decision.resource_type or "proposal"
        decision.resource_id = decision.resource_id or proposal.id
        decision.proposal_type = decision.proposal_type or proposal.proposal_type
        # proposal.apply is fail_closed — if record cannot be persisted, the apply must not proceed.
        self._persist_record_from_decision(
            decision,
            actor_type="user",
            actor_id=user_id,
            space_id=space_id,
            proposal_id=proposal.id,
            metadata_json={
                **(metadata_json or {}),
                "proposal_type": proposal.proposal_type,
                "decision_source": "check_proposal_apply_policy",
            },
            failure_mode="fail_closed",
        )
        return decision

    def check_and_record(self, req: PolicyCheckRequest) -> PolicyDecision:
        """Evaluate hard invariants, then PolicyEngine, then persist the record.

        Steps:
          1. Validate action is registered (unknown → DENY, record if needed).
          2. RESERVED action → DENY, record, return.
          3. WIRED_VIA_PROPOSAL action → DENY with reason_code="policy_action_via_proposal_only",
             record, return.  These actions are enforced only via the proposal.apply gate.
          4. WIRED_DIRECT: Run HardInvariantGuard — if denial, persist and return.
          5. Call PolicyEngine.
          6. Attach actor/resource fields to decision.
          7. Persist PolicyDecisionRecord if audit_required, DENY, REQUIRE_APPROVAL, or forced,
             using the resolved failure_mode for the action.
          8. Return PolicyDecision.

        failure_mode resolution (for step 7):
          - Starts from defn.record_failure_mode (per-action default).
          - Escalates to FAIL_CLOSED when trigger_origin="automation" and audit_required=True
            (regardless of ALLOW/DENY/REQUIRE_APPROVAL).
          - Escalates to FAIL_CLOSED when risk_level=CRITICAL and audit_required=True
            (regardless of ALLOW/DENY/REQUIRE_APPROVAL).
          - Escalates to FAIL_CLOSED when trigger_origin="automation" and non-ALLOW
            (legacy rule for non-audit-required actions).
          - Escalates to FAIL_CLOSED when risk_level=CRITICAL and non-ALLOW
            (legacy rule for non-audit-required actions).

        The returned decision always has actor_type, actor_id, actor_ref, space_id,
        resource_type, and resource_id populated from req where not already set.
        """
        try:
            defn = require_action_definition(req.action)
        except (UnknownPolicyActionError, TypeError):
            denial = PolicyDecision(
                decision=Decision.DENY,
                message=f"Unknown policy action {req.action!r}.",
                risk_level=RiskLevel.HIGH,
                reason_code="unknown_policy_action",
                policy_rule_id="unknown_action_deny",
                policy_source="builtin",
                audit_code="unknown_policy_action",
                action=req.action,
                space_id=req.space_id,
                actor_type=req.actor_type,
                actor_id=req.actor_id,
                actor_ref=req.actor_ref,
                resource_type=req.resource_type,
                resource_id=req.resource_id,
            )
            _persist_record(self.db, req, denial)
            return denial

        if defn.lifecycle_status == PolicyActionLifecycle.RESERVED:
            reserved_denial = PolicyDecision(
                decision=Decision.DENY,
                message=(
                    f"Policy action {req.action!r} is reserved and has no "
                    "enforcement point. Reserved actions always fail closed until "
                    "the action is wired to a real enforcement point."
                ),
                risk_level=defn.default_risk_level,
                reason_code="policy_action_not_implemented",
                policy_rule_id="action_not_implemented",
                policy_source="registry",
                audit_code="policy_action_not_implemented",
                action=req.action,
                resource_type=defn.resource_type,
                resource_id=req.resource_id,
                actor_type=req.actor_type,
                actor_id=req.actor_id,
                actor_ref=req.actor_ref,
                space_id=req.space_id,
                required_approver_role=defn.default_required_approver_role,
                approval_capability=defn.approval_capability,
            )
            _persist_record(self.db, req, reserved_denial)
            return reserved_denial

        if defn.lifecycle_status == PolicyActionLifecycle.WIRED_VIA_PROPOSAL:
            # WIRED_VIA_PROPOSAL actions must not be called directly.  They are enforced
            # exclusively via check_proposal_apply() / proposal.apply gate.
            via_proposal_denial = PolicyDecision(
                decision=Decision.DENY,
                message=(
                    f"Policy action {req.action!r} is enforced via the proposal.apply gate "
                    "and must not be called directly through check_and_record(). "
                    "Use PolicyGateway.check_proposal_apply() instead."
                ),
                risk_level=defn.default_risk_level,
                reason_code="policy_action_via_proposal_only",
                policy_rule_id="action_via_proposal_only",
                policy_source="registry",
                audit_code="policy_action_via_proposal_only",
                action=req.action,
                resource_type=defn.resource_type,
                resource_id=req.resource_id,
                actor_type=req.actor_type,
                actor_id=req.actor_id,
                actor_ref=req.actor_ref,
                space_id=req.space_id,
                required_approver_role=defn.default_required_approver_role,
                approval_capability=defn.approval_capability,
            )
            _persist_record(self.db, req, via_proposal_denial)
            return via_proposal_denial

        # WIRED_DIRECT: run invariants then engine.
        guard_ctx = _guard_ctx(req)
        invariant_denial = _guard.check(guard_ctx)
        if invariant_denial is not None:
            # Attach actor and resource fields to the returned decision object.
            invariant_denial.actor_type = invariant_denial.actor_type or req.actor_type
            invariant_denial.actor_id = invariant_denial.actor_id or req.actor_id
            invariant_denial.actor_ref = invariant_denial.actor_ref or req.actor_ref
            invariant_denial.space_id = invariant_denial.space_id or req.space_id
            invariant_denial.resource_type = invariant_denial.resource_type or (defn.resource_type if defn else req.resource_type)
            invariant_denial.resource_id = invariant_denial.resource_id or req.resource_id
            failure_mode = _resolve_failure_mode(defn, invariant_denial, req)
            _persist_record(self.db, req, invariant_denial, failure_mode=failure_mode)
            return invariant_denial

        engine_ctx = _build_engine_ctx(req)
        decision = _engine.check(engine_ctx)
        decision.actor_type = decision.actor_type or req.actor_type
        decision.actor_id = decision.actor_id or req.actor_id
        decision.actor_ref = decision.actor_ref or req.actor_ref
        decision.space_id = decision.space_id or req.space_id
        decision.resource_id = decision.resource_id or req.resource_id
        decision.resource_type = decision.resource_type or (defn.resource_type if defn else None)

        if _should_record(defn, decision, req.force_record):
            failure_mode = _resolve_failure_mode(defn, decision, req)
            _persist_record(self.db, req, decision, failure_mode=failure_mode)

        return decision
