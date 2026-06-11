"""Minimal fake satisfying ``app.policy.PolicyPort`` (no database).

The real :class:`app.policy.gateway.PolicyGateway` runs the hard-invariant guard,
the ``PolicyEngine`` and durable audit against a DB session. This fake lets a
caller that depends only on the :class:`~app.policy.ports.PolicyPort` seam be
exercised without any of that: it records the requests it receives and returns a
scripted decision, or raises ``PolicyGateBlocked`` when configured to deny.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from app.policy.decisions import Decision, PolicyDecision, RiskLevel
from app.policy.exceptions import PolicyGateBlocked


def _allow() -> PolicyDecision:
    return PolicyDecision(
        decision=Decision.ALLOW, message="fake allow", risk_level=RiskLevel.LOW
    )


def _blocked(action: str, actor_id: str, space_id: str | None = None) -> PolicyGateBlocked:
    return PolicyGateBlocked(
        decision=PolicyDecision(
            decision=Decision.DENY, message="fake deny", risk_level=RiskLevel.HIGH
        ),
        action=action,
        actor_type="user",
        actor_id=actor_id,
        actor_ref=None,
        space_id=space_id,
        resource_type=None,
        resource_id=None,
        run_id=None,
        proposal_id=None,
        metadata_json=None,
    )


@dataclass
class FakePolicyGateway:
    """Records ``enforce`` / ``enforce_proposal_apply`` calls.

    ``decision`` is returned on ALLOW. If ``block`` is True the gateway raises
    ``PolicyGateBlocked`` just as the real gateway does on DENY / REQUIRE_APPROVAL.
    """

    decision: PolicyDecision = field(default_factory=_allow)
    block: bool = False
    enforce_calls: list[Any] = field(default_factory=list)
    proposal_apply_calls: list[dict[str, Any]] = field(default_factory=list)

    def enforce(self, req: Any) -> PolicyDecision:
        self.enforce_calls.append(req)
        if self.block:
            raise _blocked(
                getattr(req, "action", "test.action"),
                getattr(req, "actor_id", "tester"),
                getattr(req, "space_id", None),
            )
        return self.decision

    def enforce_proposal_apply(
        self,
        user_id: str,
        space_id: str,
        proposal: Any,
        metadata_json: Optional[dict[str, Any]] = None,
    ) -> PolicyDecision:
        self.proposal_apply_calls.append(
            {
                "user_id": user_id,
                "space_id": space_id,
                "proposal": proposal,
                "metadata_json": metadata_json,
            }
        )
        if self.block:
            raise _blocked("proposal.apply", user_id, space_id)
        return self.decision
