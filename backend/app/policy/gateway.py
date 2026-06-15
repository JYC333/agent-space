from __future__ import annotations

"""PolicyGateway — local Python implementation of policy enforcement.

Production services call ``get_policy_port(db)`` so the active authority can be
Python or the TS control-plane. This class remains the local/fallback
implementation. Its ``enforce()`` and ``enforce_proposal_apply()`` methods return
``PolicyDecision`` on ALLOW and raise ``PolicyGateBlocked`` for DENY or
REQUIRE_APPROVAL. Blocking handlers write the durable audit record exactly once.

``PolicyAuditPersistError`` is raised when a fail-closed action requires a
durable ALLOW audit record and that independent write fails. The sensitive
action must not proceed in that case.

``DurablePolicyAuditWriter`` writes only ``PolicyDecisionRecord`` in an
independent transaction. Business transactions are not committed to persist
policy audit.

Stack:
    HardInvariantGuard → PolicyEngine → PolicyDecisionRecord

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

Durable audit required when any of:
    - action definition audit_required=True
    - action definition record_failure_mode=FAIL_CLOSED
    - force_record=True
    - decision is DENY
    - decision is REQUIRE_APPROVAL
    - risk_level is CRITICAL
    - trigger_origin == "automation"

record_failure_mode (RecordFailureMode):
    BEST_EFFORT — if PolicyDecisionRecord persistence fails, log a warning and continue.
    FAIL_CLOSED — if durable audit persistence fails, raise
                  PolicyAuditPersistError. The sensitive action must not proceed.
                  Actions with FAIL_CLOSED: runtime.use_credential,
                  workspace.write_patch, artifact.persist, proposal.apply, policy.change,
                  automation.create, automation.update, automation.fire.
                  Additional dynamic escalation to FAIL_CLOSED:
                    - automation-origin (trigger_origin="automation") + audit_required=True,
                      regardless of ALLOW/DENY/REQUIRE_APPROVAL.
                    - CRITICAL risk level + audit_required=True,
                      regardless of ALLOW/DENY/REQUIRE_APPROVAL.
                    - automation-origin + non-ALLOW on non-audit-required actions.
                    - CRITICAL risk level + non-ALLOW on non-audit-required actions.
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Optional

from .actions import PolicyActionLifecycle, RecordFailureMode, require_action_definition, UnknownPolicyActionError
from .decisions import Decision, PolicyDecision, RiskLevel
from .engine import PolicyEngine
from .hard_invariants import HardInvariantGuard
from .sanitizer import sanitize_policy_metadata

log = logging.getLogger(__name__)

_engine = PolicyEngine()
_guard = HardInvariantGuard()


@dataclass
class PolicyCheckRequest:
    """Structured request for PolicyGateway.enforce().

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


def _is_durable_audit_required(defn, decision: PolicyDecision, req: PolicyCheckRequest) -> bool:
    """Return True when durable (independently committed) audit persistence is required."""
    if req.force_record:
        return True
    if defn is not None and defn.audit_required:
        return True
    if defn is not None and defn.record_failure_mode == RecordFailureMode.FAIL_CLOSED:
        return True
    if decision.denied or decision.requires_approval:
        return True
    if decision.risk_level == RiskLevel.CRITICAL:
        return True
    trigger_origin = (req.context or {}).get("trigger_origin", "")
    if trigger_origin == "automation":
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
    """Build the context dict passed to HardInvariantGuard."""
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
        ctx.update(req.context)
        ctx["context"] = req.context
    return ctx


def _resolve_failure_mode(
    defn: Any,
    decision: PolicyDecision,
    req: PolicyCheckRequest,
) -> RecordFailureMode:
    """Resolve effective record_failure_mode for this (defn, decision, req) combination."""
    if req.force_record:
        return RecordFailureMode.FAIL_CLOSED
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


def _build_audit_envelope(
    req: PolicyCheckRequest,
    decision: PolicyDecision,
    defn: Any = None,
) -> "PolicyAuditEnvelope":
    """Build a PolicyAuditEnvelope from a computed decision and request."""
    from .audit import PolicyAuditEnvelope

    resource_type = req.resource_type or (defn.resource_type if defn else None) or decision.resource_type
    proposal_id = req.proposal_id
    if proposal_id is None and resource_type == "proposal":
        proposal_id = req.resource_id or decision.resource_id

    return PolicyAuditEnvelope(
        space_id=req.space_id or decision.space_id,
        actor_type=req.actor_type or decision.actor_type,
        actor_id=req.actor_id or decision.actor_id,
        actor_ref_json=req.actor_ref or decision.actor_ref,
        action=req.action,
        resource_type=resource_type,
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
        proposal_id=proposal_id,
        metadata_json=sanitize_policy_metadata(req.metadata_json),
        created_at=datetime.now(UTC),
    )


class PolicyGateway:
    """Local Python policy decision implementation.

    Production callers should use get_policy_port(db), which resolves this
    implementation or the TS-backed control-plane client.

    Actual sensitive-action enforcement must not call PolicyEngine directly.
    PreflightService's non-mutating PolicyEngine simulation is not enforcement.
    """

    def __init__(self, db: Any):
        self.db = db

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _compute_decision(
        self, req: PolicyCheckRequest
    ) -> tuple[Any, PolicyDecision]:
        """Run guard + engine and return (defn, decision).

        Handles unknown, RESERVED, and WIRED_VIA_PROPOSAL actions.
        Does NOT write any audit record.
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
            return None, denial

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
            return defn, reserved_denial

        if defn.lifecycle_status == PolicyActionLifecycle.WIRED_VIA_PROPOSAL:
            via_proposal_denial = PolicyDecision(
                decision=Decision.DENY,
                message=(
                    f"Policy action {req.action!r} is enforced via the proposal.apply gate "
                    "and must not be enforced as a standalone action. "
                    "Use PolicyGateway.enforce_proposal_apply() instead."
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
            return defn, via_proposal_denial

        # WIRED_DIRECT: run invariants then engine.
        guard_ctx = _guard_ctx(req)
        invariant_denial = _guard.check(guard_ctx)
        if invariant_denial is not None:
            invariant_denial.actor_type = invariant_denial.actor_type or req.actor_type
            invariant_denial.actor_id = invariant_denial.actor_id or req.actor_id
            invariant_denial.actor_ref = invariant_denial.actor_ref or req.actor_ref
            invariant_denial.space_id = invariant_denial.space_id or req.space_id
            invariant_denial.resource_type = (
                invariant_denial.resource_type or defn.resource_type or req.resource_type
            )
            invariant_denial.resource_id = invariant_denial.resource_id or req.resource_id
            return defn, invariant_denial

        engine_ctx = _build_engine_ctx(req)
        decision = _engine.check(engine_ctx)
        decision.actor_type = decision.actor_type or req.actor_type
        decision.actor_id = decision.actor_id or req.actor_id
        decision.actor_ref = decision.actor_ref or req.actor_ref
        decision.space_id = decision.space_id or req.space_id
        decision.resource_id = decision.resource_id or req.resource_id
        decision.resource_type = decision.resource_type or defn.resource_type
        return defn, decision

    # ------------------------------------------------------------------
    # Production enforcement entry point
    # ------------------------------------------------------------------

    def enforce(self, req: PolicyCheckRequest) -> PolicyDecision:
        """Evaluate hard invariants, then PolicyEngine.

        Returns PolicyDecision on ALLOW.
        Raises PolicyGateBlocked on DENY or REQUIRE_APPROVAL (no audit write here;
            the global exception handler writes the record via DurablePolicyAuditWriter).
        Raises PolicyAuditPersistError if ALLOW + fail_closed audit write fails.

        Steps:
          1. Resolve action definition; fail closed for unknown/reserved/via-proposal-only.
          2. Run HardInvariantGuard.
          3. Run PolicyEngine.
          4. If decision is ALLOW:
             - If durable audit is required: write via DurablePolicyAuditWriter.
             - If write fails and effective failure mode is FAIL_CLOSED:
               raise PolicyAuditPersistError.
             - Otherwise log and continue (BEST_EFFORT).
             - Return decision.
          5. If decision is DENY or REQUIRE_APPROVAL:
             - Do not perform any business write.
             - Do not commit the request db session.
             - Raise PolicyGateBlocked carrying the decision and sanitized audit envelope.
             - The global exception handler writes the durable audit record.
        """
        from .exceptions import PolicyAuditPersistError, PolicyGateBlocked
        from .audit import DurablePolicyAuditWriter

        defn, decision = self._compute_decision(req)
        failure_mode = _resolve_failure_mode(defn, decision, req)

        if decision.denied or decision.requires_approval:
            envelope = _build_audit_envelope(req, decision, defn)
            raise PolicyGateBlocked(
                decision=decision,
                action=req.action,
                actor_type=req.actor_type,
                actor_id=req.actor_id,
                actor_ref=req.actor_ref,
                space_id=req.space_id,
                resource_type=req.resource_type or (defn.resource_type if defn else None),
                resource_id=req.resource_id,
                run_id=req.run_id,
                proposal_id=req.proposal_id,
                metadata_json=envelope.metadata_json,
                http_status_code=403,
            )

        # ALLOW — write durable audit if required.
        if _is_durable_audit_required(defn, decision, req):
            envelope = _build_audit_envelope(req, decision, defn)
            try:
                DurablePolicyAuditWriter().write(envelope)
            except Exception:
                if failure_mode == RecordFailureMode.FAIL_CLOSED:
                    log.error(
                        "PolicyAuditPersistError (fail_closed ALLOW) action=%s actor=%s",
                        req.action, req.actor_id, exc_info=True,
                    )
                    raise PolicyAuditPersistError(action=req.action, actor_id=req.actor_id)
                log.warning(
                    "PolicyDecisionRecord persist failed (best-effort ALLOW) action=%s actor=%s",
                    req.action, req.actor_id, exc_info=True,
                )

        return decision

    # ------------------------------------------------------------------
    # Proposal apply gate — preferred
    # ------------------------------------------------------------------

    def enforce_proposal_apply(
        self,
        user_id: str,
        space_id: str,
        proposal: Any,
        metadata_json: Optional[dict[str, Any]] = None,
    ) -> PolicyDecision:
        """Evaluate the proposal.apply gate.

        Returns PolicyDecision on ALLOW (with durable audit record committed).
        Raises PolicyGateBlocked on DENY or REQUIRE_APPROVAL (global handler writes record).
        Raises PolicyAuditPersistError if ALLOW audit write fails (proposal.apply is FAIL_CLOSED).

        Never calls ProposalApplyService — this is a pure gate.
        """
        from .exceptions import PolicyAuditPersistError, PolicyGateBlocked
        from .audit import DurablePolicyAuditWriter, PolicyAuditEnvelope
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
            # Blocking — raise PolicyGateBlocked; handler writes record.
            raise PolicyGateBlocked(
                decision=invariant_denial,
                action="proposal.apply",
                actor_type="user",
                actor_id=user_id,
                actor_ref=None,
                space_id=space_id,
                resource_type="proposal",
                resource_id=proposal.id,
                run_id=None,
                proposal_id=proposal.id,
                metadata_json=safe_meta,
                http_status_code=403,
            )

        decision = check_proposal_apply_policy(
            self.db, user_id=user_id, space_id=space_id, proposal=proposal
        )
        decision.actor_type = decision.actor_type or "user"
        decision.actor_id = decision.actor_id or user_id
        decision.space_id = decision.space_id or space_id
        decision.resource_type = decision.resource_type or "proposal"
        decision.resource_id = decision.resource_id or proposal.id
        decision.proposal_type = decision.proposal_type or proposal.proposal_type

        safe_meta = sanitize_policy_metadata({
            **(metadata_json or {}),
            "proposal_type": proposal.proposal_type,
            "decision_source": "check_proposal_apply_policy",
        })

        if not decision.allowed:
            raise PolicyGateBlocked(
                decision=decision,
                action="proposal.apply",
                actor_type="user",
                actor_id=user_id,
                actor_ref=None,
                space_id=space_id,
                resource_type="proposal",
                resource_id=proposal.id,
                run_id=None,
                proposal_id=proposal.id,
                metadata_json=safe_meta,
                http_status_code=403,
            )

        # ALLOW — proposal.apply is FAIL_CLOSED + audit_required; must write durably.
        envelope = PolicyAuditEnvelope(
            space_id=space_id,
            actor_type="user",
            actor_id=user_id,
            actor_ref_json=None,
            action="proposal.apply",
            resource_type="proposal",
            resource_id=proposal.id,
            decision=decision.decision.value,
            risk_level=decision.risk_level.value,
            required_approver_role=decision.required_approver_role,
            approval_capability=decision.approval_capability,
            policy_rule_id=decision.policy_rule_id,
            policy_source=decision.policy_source,
            policy_id=decision.policy_id,
            audit_code=decision.audit_code,
            run_id=None,
            proposal_id=proposal.id,
            metadata_json=safe_meta,
            created_at=datetime.now(UTC),
        )
        try:
            DurablePolicyAuditWriter().write(envelope)
        except Exception:
            # proposal.apply is FAIL_CLOSED — audit failure blocks the apply.
            raise PolicyAuditPersistError(action="proposal.apply", actor_id=user_id)

        return decision
