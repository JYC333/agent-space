from .engine import PolicyEngine
from .decisions import PolicyDecision, Decision, RiskLevel
from .access import (
    ActivePolicyDecision,
    ActivePolicyMatch,
    get_active_policy_decision,
    get_active_policy_match,
    load_active_policy_rows,
    policy_allows,
    policy_denies,
)
from .trace import TRACE_LOGGER, record_policy_decision_trace
from .domains import (
    DOMAIN_REGISTRY,
    MEMORY_CROSS_SPACE_READ,
    MEMORY_PRIVATE_PLACEMENT,
    RUN_USER_PRIVATE_SCOPE,
)
from .actions import (
    PolicyActionDefinition,
    UnknownPolicyActionError,
    get_action_definition,
    require_action_definition,
    is_known_action,
    list_action_definitions,
)
from .approval import can_approve_policy_action, get_space_role
from .proposal_apply import (
    ProposalRiskLevelError,
    check_proposal_apply_policy,
    effective_proposal_risk,
)
from .hard_invariants import HardInvariantGuard
from .gateway import PolicyGateway, PolicyCheckRequest
from .roles import (
    CANONICAL_ROLES,
    normalize_role,
    role_rank,
    has_role_at_least,
    can_approve_policy_decision,
    can_approve_proposal_type,
    get_space_role_normalized,
)
from .sanitizer import sanitize_policy_metadata

__all__ = [
    "PolicyEngine",
    "PolicyDecision",
    "Decision",
    "RiskLevel",
    "ActivePolicyDecision",
    "ActivePolicyMatch",
    "get_active_policy_decision",
    "get_active_policy_match",
    "load_active_policy_rows",
    "record_policy_decision_trace",
    "TRACE_LOGGER",
    "policy_allows",
    "policy_denies",
    "DOMAIN_REGISTRY",
    "MEMORY_CROSS_SPACE_READ",
    "MEMORY_PRIVATE_PLACEMENT",
    "RUN_USER_PRIVATE_SCOPE",
    "PolicyActionDefinition",
    "UnknownPolicyActionError",
    "get_action_definition",
    "require_action_definition",
    "is_known_action",
    "list_action_definitions",
    "can_approve_policy_action",
    "get_space_role",
    "ProposalRiskLevelError",
    "check_proposal_apply_policy",
    "effective_proposal_risk",
    "HardInvariantGuard",
    "PolicyGateway",
    "PolicyCheckRequest",
    "CANONICAL_ROLES",
    "normalize_role",
    "role_rank",
    "has_role_at_least",
    "can_approve_policy_decision",
    "can_approve_proposal_type",
    "get_space_role_normalized",
    "sanitize_policy_metadata",
]
