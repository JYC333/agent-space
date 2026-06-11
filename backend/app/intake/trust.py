"""Explicit trust vocabulary helpers for Intake/Evidence."""
from __future__ import annotations

EVIDENCE_TRUST_VALUES = frozenset({"trusted", "normal", "untrusted"})
SOURCE_CONNECTION_TRUST_VALUES = EVIDENCE_TRUST_VALUES
RUNTIME_TRUST_VALUES = frozenset({"high", "medium", "low", "unknown"})
ACTIVITY_SOURCE_TRUST_TO_EVIDENCE_TRUST = {
    "user_confirmed": "trusted",
    "internal_system": "normal",
    "trusted_external": "trusted",
    "untrusted_external": "untrusted",
    "agent_inferred": "untrusted",
}


def source_connection_trust_to_evidence_trust(value: str | None) -> str:
    """Map source-connection provenance trust into evidence trust.

    Source connections and evidence intentionally share the
    trusted/normal/untrusted vocabulary. Runtime trust values such as
    high/medium/low/unknown are a separate execution-plane vocabulary and must
    not be silently coerced into evidence trust.
    """
    trust = value or "normal"
    if trust not in SOURCE_CONNECTION_TRUST_VALUES:
        raise ValueError(f"Unsupported source connection trust level for evidence: {trust!r}")
    return trust


def evidence_trust_to_context_metadata(value: str | None) -> dict[str, str]:
    trust = value or "normal"
    if trust not in EVIDENCE_TRUST_VALUES:
        raise ValueError(f"Unsupported evidence trust level for context metadata: {trust!r}")
    return {"provenance_trust": trust}


def activity_source_trust_to_evidence_trust(value: str | None) -> str:
    trust = value or "internal_system"
    try:
        return ACTIVITY_SOURCE_TRUST_TO_EVIDENCE_TRUST[trust]
    except KeyError as exc:
        raise ValueError(f"Unsupported activity source_trust for evidence: {trust!r}") from exc
