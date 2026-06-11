from __future__ import annotations
"""
Deterministic source monitoring gate.

Inspects normalized ``provenance_entries`` on proposals before durable apply.
Not a scoring engine — only trust presence / composition rules.

---------------------------------------------------------------------------
Accept context (``accept_context``) — *not* exposed on public HTTP bodies
---------------------------------------------------------------------------

These values are **Python-only** parameters to ``ProposalApplyService.apply`` and
``SourceMonitoringService.evaluate_*``. They MUST NOT be read from request JSON,
query params, runtime adapter payloads, or agent tools.

- ``explicit_user_accept`` — reserved for human/admin proposal-accept API paths
  (e.g. ``ProposalService.accept``). This is the only context that may satisfy
  ``require_review`` outcomes for ``untrusted_external``-only provenance, and
  must persist ``source_monitoring_result`` on the proposal payload when used.

- ``internal_seed`` — reserved for DB seed scripts, migrations, and isolated
  tests that intentionally bypass monitoring. Never use for normal user-facing
  acceptance.

- ``direct_apply`` — default for in-process callers (e.g. tests invoking
  ``apply`` directly). MUST NOT be used to stand in for a real user accept on
  production proposal flows. Future ``auto_accept`` must **not** pass
  ``explicit_user_accept`` without a true human/admin accept boundary.

Hard rules enforced here:

- ``agent_inferred`` alone cannot back active semantic memory or policy (reject).
- ``untrusted_external`` alone yields ``require_review``; apply proceeds only
  under ``explicit_user_accept`` with ``source_monitoring_result`` recorded
  beforehand on the proposal row.
"""

from dataclasses import dataclass
from typing import Any, Literal

from .proposal_payload import provenance_entries_from_payload

AcceptContext = Literal["explicit_user_accept", "internal_seed", "direct_apply"]


@dataclass(frozen=True)
class SourceMonitoringOutcome:
    action: Literal["allow", "require_review", "reject"]
    reason_code: str
    message: str
    details: dict[str, Any]


_TRUST_ALLOW_CORE = frozenset({"user_confirmed", "internal_system", "trusted_external"})


class SourceMonitoringService:
    """Deterministic gate for semantic memory and policy proposals."""

    def evaluate_memory_proposal(
        self,
        *,
        proposal_type: str,
        payload: dict[str, Any] | None,
        accept_context: AcceptContext,
    ) -> SourceMonitoringOutcome:
        p = dict(payload or {})
        entries = provenance_entries_from_payload(p)

        if accept_context == "internal_seed":
            return SourceMonitoringOutcome("allow", "bypass", "internal seed bypass", {"entries": len(entries)})

        if proposal_type == "memory_archive":
            return SourceMonitoringOutcome("allow", "archive_light", "archive uses lighter monitoring", {})

        mem_type = (p.get("memory_type") or "semantic").lower()
        layer = (p.get("target_layer") or p.get("memory_layer") or "").lower()
        is_episodic = mem_type == "episodic" or layer == "episodic"
        is_semantic = not is_episodic

        trusts = {e.get("source_trust") for e in entries if isinstance(e.get("source_trust"), str)}
        trusts.discard(None)

        if not entries:
            if is_semantic:
                return SourceMonitoringOutcome(
                    "reject",
                    "missing_provenance",
                    "semantic memory proposals require provenance_entries",
                    {},
                )
            return SourceMonitoringOutcome(
                "reject",
                "missing_provenance",
                "episodic memory proposals require provenance_entries",
                {},
            )

        has_core = bool(trusts & _TRUST_ALLOW_CORE)
        only_agent = trusts <= {"agent_inferred"} and bool(trusts)
        has_untrusted = "untrusted_external" in trusts
        has_agent = "agent_inferred" in trusts

        if is_semantic or proposal_type == "policy_change":
            if only_agent or (has_agent and not has_core):
                return SourceMonitoringOutcome(
                    "reject",
                    "agent_inferred_only",
                    "agent_inferred cannot be the sole trusted basis for active semantic fact or policy",
                    {"trusts": sorted(trusts)},
                )
            if not has_core:
                if has_untrusted and trusts <= {"untrusted_external"}:
                    return SourceMonitoringOutcome(
                        "require_review",
                        "untrusted_external_only",
                        "untrusted_external requires explicit approval before apply",
                        {"trusts": sorted(trusts)},
                    )
                return SourceMonitoringOutcome(
                    "reject",
                    "no_trusted_provenance",
                    "semantic/policy proposals require user_confirmed, internal_system, or trusted_external evidence",
                    {"trusts": sorted(trusts)},
                )
            if has_untrusted and not has_core:
                # unreachable given has_core
                pass
            return SourceMonitoringOutcome("allow", "ok", "trusted provenance present", {"trusts": sorted(trusts)})

        # episodic
        episodic_ok = trusts & {"user_confirmed", "internal_system"}
        if episodic_ok or ("trusted_external" in trusts):
            return SourceMonitoringOutcome("allow", "ok_episodic", "episodic provenance acceptable", {})

        if only_agent or (has_agent and not episodic_ok and "trusted_external" not in trusts):
            return SourceMonitoringOutcome(
                "reject",
                "agent_inferred_episodic",
                "episodic memory requires user_confirmed or internal_system (or trusted_external)",
                {"trusts": sorted(trusts)},
            )

        if has_untrusted and not episodic_ok:
            return SourceMonitoringOutcome(
                "require_review",
                "untrusted_external_episodic",
                "untrusted_external episodic change requires explicit approval",
                {"trusts": sorted(trusts)},
            )

        return SourceMonitoringOutcome("reject", "episodic_weak", "insufficient provenance for episodic memory", {})

    def evaluate_policy_proposal(
        self,
        *,
        payload: dict[str, Any] | None,
        accept_context: AcceptContext,
    ) -> SourceMonitoringOutcome:
        p = dict(payload or {})
        if accept_context == "internal_seed":
            return SourceMonitoringOutcome("allow", "bypass", "internal seed bypass", {})

        entries = provenance_entries_from_payload(p)
        trusts = {e.get("source_trust") for e in entries if isinstance(e.get("source_trust"), str)}
        trusts.discard(None)

        if not entries:
            return SourceMonitoringOutcome("reject", "missing_provenance", "policy_change requires provenance", {})

        has_core = bool(trusts & _TRUST_ALLOW_CORE)
        only_agent = trusts <= {"agent_inferred"} and bool(trusts)
        has_agent = "agent_inferred" in trusts

        if only_agent or (has_agent and not has_core):
            return SourceMonitoringOutcome(
                "reject",
                "agent_inferred_only",
                "agent_inferred cannot be the sole basis for active policy",
                {"trusts": sorted(trusts)},
            )

        if not has_core:
            if trusts <= {"untrusted_external"}:
                return SourceMonitoringOutcome(
                    "require_review",
                    "untrusted_external_only",
                    "untrusted_external policy requires explicit approval",
                    {"trusts": sorted(trusts)},
                )
            return SourceMonitoringOutcome(
                "reject",
                "no_trusted_provenance",
                "policy_change requires trusted provenance",
                {"trusts": sorted(trusts)},
            )

        return SourceMonitoringOutcome("allow", "ok_policy", "policy provenance acceptable", {})


def monitoring_snapshot(outcome: SourceMonitoringOutcome) -> dict[str, Any]:
    return {
        "action": outcome.action,
        "reason_code": outcome.reason_code,
        "message": outcome.message,
        "details": dict(outcome.details),
    }
