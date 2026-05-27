from __future__ import annotations

"""Policy row effect catalog.

This is a small contract for persisted ``Policy`` rows, not a general policy DSL.
Only domains with a real enforcement point may be created as active rows through
``policy_change`` proposals.
"""

from dataclasses import dataclass
from typing import Any


class PolicyEffectValidationError(ValueError):
    """Raised when a policy_change payload cannot create an effective Policy row."""


@dataclass(frozen=True)
class PolicyEffectDefinition:
    domain: str
    supported: bool
    enforcement_point: str
    allowed_enforcement_modes: frozenset[str]
    required_rule_keys: frozenset[str]
    optional_rule_keys: frozenset[str]
    description: str


@dataclass(frozen=True)
class NormalizedPolicyChangePayload:
    definition: PolicyEffectDefinition
    domain: str
    enforcement_mode: str
    rule_json: dict[str, Any]
    applies_to_json: dict[str, Any] | None


_EFFECT_MODES = frozenset({"deny", "allow_with_log"})
_RESERVED_MODES = frozenset[str]()
_COMMON_OPTIONAL_RULE_KEYS = frozenset({
    "policy_domain",
    "scope",
    "visibility",
    "reason",
    "note",
})

POLICY_EFFECT_CATALOG: dict[str, PolicyEffectDefinition] = {
    "memory.private_placement": PolicyEffectDefinition(
        domain="memory.private_placement",
        supported=True,
        enforcement_point="app.policy.enforcement.check_private_memory_placement",
        allowed_enforcement_modes=_EFFECT_MODES,
        required_rule_keys=frozenset({"effect"}),
        optional_rule_keys=_COMMON_OPTIONAL_RULE_KEYS,
        description="Controls active Policy row participation in private memory placement checks.",
    ),
    "run.user_private_scope": PolicyEffectDefinition(
        domain="run.user_private_scope",
        supported=True,
        enforcement_point="app.policy.enforcement.can_read_memory_in_run_context",
        allowed_enforcement_modes=_EFFECT_MODES,
        required_rule_keys=frozenset({"effect"}),
        optional_rule_keys=_COMMON_OPTIONAL_RULE_KEYS,
        description="Controls active Policy row participation in same-space private memory inclusion for runs.",
    ),
    "runtime.execute": PolicyEffectDefinition(
        domain="runtime.execute",
        supported=False,
        enforcement_point="reserved",
        allowed_enforcement_modes=_RESERVED_MODES,
        required_rule_keys=frozenset(),
        optional_rule_keys=frozenset(),
        description="Reserved vocabulary; runtime execution is enforced by PolicyGateway built-ins only.",
    ),
    "automation.fire": PolicyEffectDefinition(
        domain="automation.fire",
        supported=False,
        enforcement_point="reserved",
        allowed_enforcement_modes=_RESERVED_MODES,
        required_rule_keys=frozenset(),
        optional_rule_keys=frozenset(),
        description="Reserved vocabulary; automation remains manual-only and gateway-controlled.",
    ),
    "capability.enable": PolicyEffectDefinition(
        domain="capability.enable",
        supported=False,
        enforcement_point="reserved",
        allowed_enforcement_modes=_RESERVED_MODES,
        required_rule_keys=frozenset(),
        optional_rule_keys=frozenset(),
        description="Reserved vocabulary; capability enable policy rows are not wired.",
    ),
    "tool_binding.enable": PolicyEffectDefinition(
        domain="tool_binding.enable",
        supported=False,
        enforcement_point="reserved",
        allowed_enforcement_modes=_RESERVED_MODES,
        required_rule_keys=frozenset(),
        optional_rule_keys=frozenset(),
        description="Reserved vocabulary; tool binding enable policy rows are not wired.",
    ),
    "deployment.execute": PolicyEffectDefinition(
        domain="deployment.execute",
        supported=False,
        enforcement_point="reserved",
        allowed_enforcement_modes=_RESERVED_MODES,
        required_rule_keys=frozenset(),
        optional_rule_keys=frozenset(),
        description="Reserved vocabulary; deployment execution policy rows are not wired.",
    ),
}

APPROVAL_PROOF_FIELDS = frozenset({
    "approved_by_user",
    "approved_by_granting_user",
    "approval_status",
    "is_approved",
    "auto_approved",
    "pre_approved",
})


def get_policy_effect_definition(domain: str | None) -> PolicyEffectDefinition | None:
    if not isinstance(domain, str):
        return None
    return POLICY_EFFECT_CATALOG.get(domain.strip().lower())


def _find_approval_proof_field(value: Any) -> str | None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized_key = str(key).strip().lower()
            if normalized_key in APPROVAL_PROOF_FIELDS:
                return str(key)
            found = _find_approval_proof_field(item)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _find_approval_proof_field(item)
            if found:
                return found
    return None


def _normalize_mode(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    return text or None


def _validate_rule_json(defn: PolicyEffectDefinition, value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PolicyEffectValidationError("policy_change rule_json must be a JSON object")
    missing = sorted(key for key in defn.required_rule_keys if key not in value)
    if missing:
        raise PolicyEffectValidationError(
            f"policy_change rule_json missing required keys for {defn.domain}: {missing}"
        )
    allowed = set(defn.required_rule_keys) | set(defn.optional_rule_keys)
    unknown = sorted(str(key) for key in value if str(key) not in allowed)
    if unknown:
        raise PolicyEffectValidationError(
            f"policy_change rule_json contains unsupported keys for {defn.domain}: {unknown}"
        )
    effect = _normalize_mode(value.get("effect"))
    if effect not in defn.allowed_enforcement_modes:
        raise PolicyEffectValidationError(
            f"policy_change rule_json.effect must be one of {sorted(defn.allowed_enforcement_modes)}"
        )
    normalized = dict(value)
    normalized["effect"] = effect
    policy_domain = normalized.get("policy_domain")
    if isinstance(policy_domain, str):
        normalized["policy_domain"] = policy_domain.strip().lower()
    return normalized


def _normalize_applies_to_json(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    normalized = dict(value)
    policy_domain = normalized.get("policy_domain")
    if isinstance(policy_domain, str):
        normalized["policy_domain"] = policy_domain.strip().lower()
    return normalized


def validate_policy_change_payload(
    payload: dict[str, Any] | None,
) -> NormalizedPolicyChangePayload:
    """Validate a policy_change proposal payload before any active Policy row is created."""
    if not isinstance(payload, dict):
        raise PolicyEffectValidationError("policy_change payload must be a JSON object")

    found = _find_approval_proof_field(payload)
    if found:
        raise PolicyEffectValidationError(
            f"policy_change payload contains approval-proof field {found!r}"
        )

    domain = payload.get("domain")
    if not isinstance(domain, str) or not domain.strip():
        raise PolicyEffectValidationError("policy_change domain is required")
    normalized_domain = domain.strip().lower()
    defn = get_policy_effect_definition(normalized_domain)
    if defn is None:
        raise PolicyEffectValidationError(
            f"policy_change domain {domain!r} has no policy effect definition"
        )
    if not defn.supported:
        raise PolicyEffectValidationError(
            f"policy_change domain {domain!r} is reserved and cannot create an active Policy row"
        )

    mode = _normalize_mode(payload.get("enforcement_mode"))
    if mode is not None and mode not in defn.allowed_enforcement_modes:
        raise PolicyEffectValidationError(
            f"policy_change enforcement_mode must be one of {sorted(defn.allowed_enforcement_modes)}"
        )

    rule_json = _validate_rule_json(defn, payload.get("rule_json"))
    rule_effect = str(rule_json["effect"])
    if mode is not None and mode != rule_effect:
        raise PolicyEffectValidationError(
            "policy_change enforcement_mode must match rule_json.effect"
        )
    normalized_mode = mode or rule_effect

    applies_to = payload.get("applies_to_json")
    if applies_to is not None and not isinstance(applies_to, dict):
        raise PolicyEffectValidationError(
            "policy_change applies_to_json must be a JSON object or null"
        )

    return NormalizedPolicyChangePayload(
        definition=defn,
        domain=normalized_domain,
        enforcement_mode=normalized_mode,
        rule_json=rule_json,
        applies_to_json=_normalize_applies_to_json(applies_to),
    )
