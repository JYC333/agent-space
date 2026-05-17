from __future__ import annotations

"""Structured policy decision tracing (logging only — no persistent audit table yet)."""

import json
import logging
from typing import Any

from .access import ActivePolicyDecision

TRACE_LOGGER = "app.policy.trace"
log = logging.getLogger(TRACE_LOGGER)


def record_policy_decision_trace(
    *,
    space_id: str,
    domain: str,
    decision: ActivePolicyDecision | str,
    enforcement_point: str,
    subject_type: str,
    subject_id: str | None = None,
    actor_user_id: str | None = None,
    policy_id: str | None = None,
    policy_key: str | None = None,
    outcome: str,
    metadata: dict[str, Any] | None = None,
    db: Any = None,
) -> None:
    """
    Emit a structured policy trace. Safe metadata only — never memory content.

    ``db`` is accepted for API symmetry with future persistent audit hooks.
    """
    _ = db
    decision_value = decision.value if isinstance(decision, ActivePolicyDecision) else str(decision)
    safe_meta = {k: v for k, v in (metadata or {}).items() if k not in ("content", "proposed_content")}
    payload = {
        "event": "policy_decision",
        "space_id": space_id,
        "domain": domain,
        "decision": decision_value,
        "enforcement_point": enforcement_point,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "actor_user_id": actor_user_id,
        "policy_id": policy_id,
        "policy_key": policy_key,
        "outcome": outcome,
        "metadata": safe_meta,
    }
    log.info("policy_decision_trace %s", json.dumps(payload, sort_keys=True, default=str))
