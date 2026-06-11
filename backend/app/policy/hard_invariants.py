from __future__ import annotations

"""HardInvariantGuard — non-overridable security and privacy invariants.

These checks run before PolicyEngine and cannot be weakened by Policy rows,
runtime configuration, or caller-supplied context. They protect the invariants
listed in docs/POLICY_AND_PRIVACY_BOUNDARIES.md.

Usage (via PolicyGateway for actual enforcement):

    from app.policy.hard_invariants import HardInvariantGuard

    guard = HardInvariantGuard()
    denial = guard.check(request)
    if denial is not None:
        # invariant denied — do not proceed
        return denial

Returns PolicyDecision | None. None means no invariant fired (not ALLOW).
PolicyEngine still runs after a None result.
"""

from typing import Any, Optional

from .decisions import Decision, PolicyDecision, RiskLevel

_PERSISTENCE_ACTIONS = frozenset({
    "artifact.persist",
    "memory.create",
    "memory.update",
    "memory.archive",
    "workspace.write_patch",
    "proposal.create",
    "proposal.apply",
    "policy.change",
    "capability.enable",
    "capability.update",
    "tool_binding.enable",
    "automation.create",
    "automation.fire",
    "automation.update",
    "deployment.propose",
    "deployment.execute",
})

_APPROVAL_PROOF_FLAGS = frozenset({
    "approved_by_user",
    "approved_by_granting_user",
    "approval_status",
    "is_approved",
    "auto_approved",
    "pre_approved",
})

_EGRESS_SENSITIVE_ACTIONS = frozenset({
    "artifact.export",
    "artifact.persist",
    "proposal.apply",
    "context.use_personal_grant",
})

_MEMORY_READ_ACTIONS = frozenset({
    "context.inject_memory",
    "context.use_personal_grant",
})


class HardInvariantGuard:
    """Evaluates non-overridable hard invariants before the PolicyEngine.

    Each check method returns PolicyDecision | None.
    - Non-None: invariant fired — use as the decision, do not call PolicyEngine.
    - None: invariant did not fire — continue to PolicyEngine.

    check() runs all guards in order and returns the first non-None result.
    """

    def check(self, ctx: dict[str, Any]) -> Optional[PolicyDecision]:
        """Run all hard invariants. Returns the first denial or None."""
        for guard in (
            self._cross_space_memory_read,
            self._source_pointer_not_auth,
            self._personal_context_block_not_persisted,
            self._raw_private_memory_blocks_egress,
            self._public_target_blocks_grant_derived,
            self._payload_flags_not_approval_proof,
            self._unknown_target_space_egress_fails_closed,
        ):
            result = guard(ctx)
            if result is not None:
                return result
        return None

    # -----------------------------------------------------------------------
    # Invariant 1: cross-space memory read is denied without explicit grant
    # -----------------------------------------------------------------------

    def _cross_space_memory_read(self, ctx: dict[str, Any]) -> Optional[PolicyDecision]:
        action = ctx.get("action", "")
        if action not in _MEMORY_READ_ACTIONS and action != "context.render_for_runtime":
            return None
        space_id = ctx.get("space_id")
        resource_space_id = ctx.get("resource_space_id")
        if not space_id or not resource_space_id:
            return None
        if space_id == resource_space_id:
            return None
        has_grant = ctx.get("has_personal_memory_grant", False)
        if has_grant:
            return None
        return PolicyDecision(
            decision=Decision.DENY,
            message=(
                f"Cross-space memory read denied: requesting_space={space_id!r}, "
                f"resource_space={resource_space_id!r}. "
                "A PersonalMemoryGrant is required for cross-space personal memory access."
            ),
            risk_level=RiskLevel.CRITICAL,
            reason_code="hard_invariant_cross_space_memory",
            policy_rule_id="hard_invariant_cross_space_memory",
            policy_source="hard_invariant",
            audit_code="cross_space_memory_denied",
            action=action,
            space_id=space_id,
            resource_type=ctx.get("resource_type"),
        )

    # -----------------------------------------------------------------------
    # Invariant 2: SourcePointer does not grant read access
    # -----------------------------------------------------------------------

    def _source_pointer_not_auth(self, ctx: dict[str, Any]) -> Optional[PolicyDecision]:
        if ctx.get("authorized_by_source_pointer"):
            return PolicyDecision(
                decision=Decision.DENY,
                message=(
                    "SourcePointer does not grant read access. "
                    "SourcePointers store provenance metadata only; "
                    "they cannot be used as authorization evidence."
                ),
                risk_level=RiskLevel.CRITICAL,
                reason_code="hard_invariant_source_pointer_not_auth",
                policy_rule_id="hard_invariant_source_pointer_not_auth",
                policy_source="hard_invariant",
                audit_code="source_pointer_used_as_auth",
                action=ctx.get("action"),
                space_id=ctx.get("space_id"),
            )
        return None

    # -----------------------------------------------------------------------
    # Invariant 3: personal_context_block is never persisted
    # -----------------------------------------------------------------------

    def _personal_context_block_not_persisted(self, ctx: dict[str, Any]) -> Optional[PolicyDecision]:
        action = ctx.get("action", "")
        if action not in _PERSISTENCE_ACTIONS:
            return None
        metadata = ctx.get("metadata_json") or {}
        context = ctx.get("context") or {}
        for bag in (metadata, context):
            if isinstance(bag, dict) and "personal_context_block" in bag:
                return PolicyDecision(
                    decision=Decision.DENY,
                    message=(
                        "personal_context_block must never be persisted. "
                        "It is ephemeral and may only be used for runtime reasoning."
                    ),
                    risk_level=RiskLevel.CRITICAL,
                    reason_code="hard_invariant_personal_context_not_persisted",
                    policy_rule_id="hard_invariant_personal_context_not_persisted",
                    policy_source="hard_invariant",
                    audit_code="personal_context_block_persist_attempt",
                    action=action,
                    space_id=ctx.get("space_id"),
                )
        return None

    # -----------------------------------------------------------------------
    # Invariant 4: raw_private_memory_included=true always blocks egress
    # -----------------------------------------------------------------------

    def _raw_private_memory_blocks_egress(self, ctx: dict[str, Any]) -> Optional[PolicyDecision]:
        action = ctx.get("action", "")
        if action not in _EGRESS_SENSITIVE_ACTIONS:
            return None
        # Decision input comes from context only — not from metadata_json.
        # metadata_json is audit-only and must not drive egress decisions.
        # Check both the flattened top-level key (from ctx.update(req.context))
        # and the structured sub-dict, which are the same source.
        context = ctx.get("context") or {}
        raw_private = (
            ctx.get("raw_private_memory_included") is True
            or (isinstance(context, dict) and context.get("raw_private_memory_included") is True)
        )
        if raw_private:
            return PolicyDecision(
                decision=Decision.DENY,
                message=(
                    "raw_private_memory_included=true blocks all egress. "
                    "Private memory content must never leave the personal space context."
                ),
                risk_level=RiskLevel.CRITICAL,
                reason_code="hard_invariant_raw_private_memory_egress",
                policy_rule_id="hard_invariant_raw_private_memory_egress",
                policy_source="hard_invariant",
                audit_code="raw_private_memory_egress_blocked",
                action=action,
                space_id=ctx.get("space_id"),
            )
        return None

    # -----------------------------------------------------------------------
    # Invariant 5: public target visibility blocks grant-derived output
    # -----------------------------------------------------------------------

    def _public_target_blocks_grant_derived(self, ctx: dict[str, Any]) -> Optional[PolicyDecision]:
        action = ctx.get("action", "")
        if action not in _EGRESS_SENSITIVE_ACTIONS:
            return None
        derived_from_grant = ctx.get("derived_from_personal_memory_grant", False)
        if not derived_from_grant:
            return None
        target_visibility = ctx.get("target_visibility", "")
        if (target_visibility or "").lower() == "public":
            return PolicyDecision(
                decision=Decision.DENY,
                message=(
                    "Grant-derived output cannot be published with public visibility. "
                    "Personal memory grant output must remain within approved scopes."
                ),
                risk_level=RiskLevel.CRITICAL,
                reason_code="hard_invariant_public_visibility_grant_derived",
                policy_rule_id="hard_invariant_public_visibility_grant_derived",
                policy_source="hard_invariant",
                audit_code="grant_derived_public_visibility_blocked",
                action=action,
                space_id=ctx.get("space_id"),
            )
        return None

    # -----------------------------------------------------------------------
    # Invariant 6: payload metadata is never approval proof
    # -----------------------------------------------------------------------

    def _payload_flags_not_approval_proof(self, ctx: dict[str, Any]) -> Optional[PolicyDecision]:
        action = ctx.get("action", "")
        if action not in ("proposal.apply", "policy.change"):
            return None
        payload = ctx.get("payload") or {}
        metadata = ctx.get("metadata_json") or {}
        context = ctx.get("context") or {}
        for bag in (payload, metadata, context):
            if not isinstance(bag, dict):
                continue
            for flag in _APPROVAL_PROOF_FLAGS:
                if flag in bag:
                    return PolicyDecision(
                        decision=Decision.DENY,
                        message=(
                            f"Payload flag {flag!r} cannot serve as approval proof. "
                            "Approval requires a real ProposalApproval row with verifiable authority."
                        ),
                        risk_level=RiskLevel.CRITICAL,
                        reason_code="hard_invariant_payload_not_approval_proof",
                        policy_rule_id="hard_invariant_payload_not_approval_proof",
                        policy_source="hard_invariant",
                        audit_code="payload_flag_as_approval_proof",
                        action=action,
                        space_id=ctx.get("space_id"),
                    )
        return None

    # -----------------------------------------------------------------------
    # Invariant 7: unknown target space in egress-sensitive path fails closed
    # -----------------------------------------------------------------------

    def _unknown_target_space_egress_fails_closed(self, ctx: dict[str, Any]) -> Optional[PolicyDecision]:
        action = ctx.get("action", "")
        if action not in _EGRESS_SENSITIVE_ACTIONS:
            return None
        target_space_id = ctx.get("target_space_id")
        if target_space_id is None:
            return None
        if not isinstance(target_space_id, str) or not target_space_id.strip():
            return PolicyDecision(
                decision=Decision.DENY,
                message=(
                    "Unknown or empty target_space_id in egress-sensitive action. "
                    "Cannot resolve target space; failing closed."
                ),
                risk_level=RiskLevel.CRITICAL,
                reason_code="hard_invariant_unknown_target_space",
                policy_rule_id="hard_invariant_unknown_target_space",
                policy_source="hard_invariant",
                audit_code="unknown_target_space_egress",
                action=action,
                space_id=ctx.get("space_id"),
            )
        return None
