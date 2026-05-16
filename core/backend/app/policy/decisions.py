from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, UTC
from enum import Enum
from typing import Any, Optional


class Decision(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class PolicyDecision:
    decision: Decision
    reason: str
    risk_level: RiskLevel = RiskLevel.LOW
    required_approver_role: Optional[str] = None
    policy_rule_id: Optional[str] = None
    policy_source: str = "builtin"
    policy_id: Optional[str] = None
    actor_id: Optional[str] = None
    actor_ref: Optional[dict[str, Any]] = None
    space_id: Optional[str] = None
    action: Optional[str] = None
    resource_type: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def allowed(self) -> bool:
        return self.decision == Decision.ALLOW

    @property
    def denied(self) -> bool:
        return self.decision == Decision.DENY

    @property
    def requires_approval(self) -> bool:
        return self.decision == Decision.REQUIRE_APPROVAL
