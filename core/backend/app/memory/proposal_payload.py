from __future__ import annotations
"""
Typed payload helpers for memory and policy proposals.

Canonical provenance is ``provenance_entries``: a list of objects
``{source_type, source_id, source_trust?, evidence_json?}``.

Legacy keys ``source_activity_id`` / ``source_evidence`` (and related) are
normalized into entries when *reading* payloads; new proposals should only
persist ``provenance_entries`` (plus non-provenance operational fields such as
``source_run_id`` is mirrored into entries at build time and may remain as a
denormalized hint for queries until fully derived).
"""

from dataclasses import dataclass
from typing import Any, Iterable, Optional

# DB check constraints mirror (provenance_links / proposals consumption)
PROVENANCE_SOURCE_TYPES: frozenset[str] = frozenset(
    {
        "activity",
        "proposal",
        "memory",
        "artifact",
        "run_step",
        "external_source",
        "user_confirmation",
    }
)

SOURCE_TRUST_VALUES: frozenset[str] = frozenset(
    {
        "user_confirmed",
        "internal_system",
        "trusted_external",
        "untrusted_external",
        "agent_inferred",
    }
)

_TRUST_RANK: dict[str, int] = {
    "user_confirmed": 50,
    "trusted_external": 40,
    "internal_system": 35,
    "untrusted_external": 20,
    "agent_inferred": 10,
}


@dataclass
class ProvenanceEntry:
    source_type: str
    source_id: str
    source_trust: Optional[str] = None
    evidence_json: Optional[dict[str, Any]] = None

    def to_row_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "source_type": self.source_type,
            "source_id": self.source_id,
        }
        if self.source_trust is not None:
            d["source_trust"] = self.source_trust
        if self.evidence_json is not None:
            d["evidence_json"] = dict(self.evidence_json)
        return d


@dataclass
class MemoryProposalPayload:
    """Structured payload for memory write proposals stored in Proposal.payload_json."""

    operation: str  # "create" | "update" | "archive"

    # Required for memory_update and memory_archive; absent for memory_create.
    target_memory_id: Optional[str] = None

    target_layer: Optional[str] = None
    memory_kind: Optional[str] = None

    # Scope / namespace carried on the proposal for read-model display.
    target_scope: Optional[str] = None
    target_namespace: Optional[str] = None

    # Content and type — used by create and update operations.
    content: Optional[str] = None
    memory_type: Optional[str] = None
    title: Optional[str] = None

    # Visibility / access control
    visibility: Optional[str] = None

    # User ownership
    subject_user_id: Optional[str] = None
    owner_user_id: Optional[str] = None

    # Fine-grained access control
    sensitivity_level: Optional[str] = None
    selected_user_ids: Optional[list[str]] = None

    entity_refs: Optional[list[dict]] = None
    relation_refs: Optional[list[dict]] = None

    provenance_entries: Optional[list[dict[str, Any]]] = None

    # Source monitoring result — written at accept time for high-risk / audit
    source_monitoring_result: Optional[dict] = None

    risk_level: Optional[str] = None

    def to_payload_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dict suitable for Proposal.payload_json."""
        d: dict[str, Any] = {"operation": self.operation}
        for fname in (
            "target_memory_id",
            "target_layer",
            "memory_kind",
            "target_scope",
            "target_namespace",
            "content",
            "memory_type",
            "title",
            "visibility",
            "subject_user_id",
            "owner_user_id",
            "sensitivity_level",
            "selected_user_ids",
            "entity_refs",
            "relation_refs",
            "provenance_entries",
            "source_monitoring_result",
            "risk_level",
        ):
            v = getattr(self, fname)
            if v is not None:
                d[fname] = v
        return d


@dataclass
class PolicyProposalPayload:
    """Structured payload for policy_change proposals stored in Proposal.payload_json."""

    operation: str  # "create" | "update" | "supersede"

    target_policy_id: Optional[str] = None
    policy_key: Optional[str] = None
    policy_version: Optional[int] = None
    domain: Optional[str] = None
    enforcement_mode: Optional[str] = None
    priority: Optional[int] = None
    rule_json: Optional[dict] = None
    applies_to_json: Optional[dict] = None
    supersedes_policy_id: Optional[str] = None
    provenance_entries: Optional[list[dict[str, Any]]] = None
    source_monitoring_result: Optional[dict] = None
    risk_level: Optional[str] = None

    def to_payload_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"operation": self.operation}
        for fname in (
            "target_policy_id",
            "policy_key",
            "policy_version",
            "domain",
            "enforcement_mode",
            "priority",
            "rule_json",
            "applies_to_json",
            "supersedes_policy_id",
            "provenance_entries",
            "source_monitoring_result",
            "risk_level",
        ):
            v = getattr(self, fname)
            if v is not None:
                d[fname] = v
        return d


def _as_str_id(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _normalize_one(raw: dict[str, Any]) -> dict[str, Any] | None:
    st = _as_str_id(raw.get("source_type"))
    sid = _as_str_id(raw.get("source_id"))
    if not st or not sid:
        return None
    if st not in PROVENANCE_SOURCE_TYPES:
        return None
    out: dict[str, Any] = {"source_type": st, "source_id": sid}
    trust = raw.get("source_trust")
    if trust is not None:
        ts = str(trust).strip()
        if ts in SOURCE_TRUST_VALUES:
            out["source_trust"] = ts
    ev = raw.get("evidence_json")
    if isinstance(ev, dict):
        out["evidence_json"] = dict(ev)
    return out


def provenance_entries_from_payload(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Return normalized provenance entries merged from canonical and old payload-format keys."""
    p = dict(payload or {})
    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str | None]] = set()

    def _add(e: dict[str, Any] | None) -> None:
        if not e:
            return
        key = (e["source_type"], e["source_id"], e.get("source_trust"))
        if key in seen:
            return
        seen.add(key)
        merged.append(e)

    raw_list = p.get("provenance_entries")
    if isinstance(raw_list, list):
        for item in raw_list:
            if isinstance(item, dict):
                _add(_normalize_one(item))

    act = _as_str_id(p.get("source_activity_id"))
    if act:
        ev: dict[str, Any] = {}
        if p.get("source_evidence") is not None:
            ev["note"] = str(p.get("source_evidence"))
        _add(
            _normalize_one(
                {
                    "source_type": "activity",
                    "source_id": act,
                    "source_trust": p.get("activity_source_trust"),
                    "evidence_json": ev or None,
                }
            )
        )

    rid = _as_str_id(p.get("source_run_id"))
    if rid:
        _add(
            _normalize_one(
                {
                    "source_type": "run_step",
                    "source_id": rid,
                    "source_trust": "internal_system",
                    "evidence_json": {"from_payload": "source_run_id"},
                }
            )
        )

    for mem_key in ("source_memory_id", "derived_from_memory_id"):
        mid = _as_str_id(p.get(mem_key))
        if mid:
            _add(
                _normalize_one(
                    {
                        "source_type": "memory",
                        "source_id": mid,
                        "source_trust": p.get("memory_source_trust"),
                    }
                )
            )

    return merged


def dominant_source_trust(entries: Iterable[dict[str, Any]]) -> str | None:
    """Pick the strongest declared trust among entries (for MemoryEntry.source_trust)."""
    best: str | None = None
    best_rank = -1
    for e in entries:
        t = e.get("source_trust")
        if not isinstance(t, str) or t not in SOURCE_TRUST_VALUES:
            continue
        r = _TRUST_RANK.get(t, 0)
        if r > best_rank:
            best_rank = r
            best = t
    return best


def first_activity_id(entries: Iterable[dict[str, Any]]) -> str | None:
    for e in entries:
        if e.get("source_type") == "activity":
            sid = _as_str_id(e.get("source_id"))
            if sid:
                return sid
    return None


def user_confirmation_entry(*, user_id: str, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    ev = dict(evidence or {})
    ev.setdefault("channel", "explicit_user_action")
    return {
        "source_type": "user_confirmation",
        "source_id": user_id,
        "source_trust": "user_confirmed",
        "evidence_json": ev,
    }


def activity_provenance_entry(
    *,
    activity_id: str,
    source_trust: str | None,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    # Callers SHOULD pass trust resolved from Activity kind (see ActivityService /
    # MEMORY_FOUNDATION_INVARIANTS.md). If trust is missing/invalid, default to
    # untrusted_external — not internal_system — so unknown callers cannot silently
    # elevate to system-trusted semantic/policy paths.
    trust = source_trust if source_trust in SOURCE_TRUST_VALUES else "untrusted_external"
    return {
        "source_type": "activity",
        "source_id": activity_id,
        "source_trust": trust,
        "evidence_json": dict(evidence),
    }


def proposal_provenance_entry(*, proposal_id: str, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "source_type": "proposal",
        "source_id": proposal_id,
        "source_trust": "internal_system",
        "evidence_json": dict(evidence or {}),
    }


def merge_distinct_provenance_entries(
    *lists: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Stable de-duplication by (source_type, source_id, source_trust)."""
    seen: set[tuple[str, str, str | None]] = set()
    out: list[dict[str, Any]] = []
    for lst in lists:
        for e in lst:
            st = e.get("source_type")
            sid = e.get("source_id")
            if not isinstance(st, str) or not isinstance(sid, str):
                continue
            tr = e.get("source_trust") if isinstance(e.get("source_trust"), str) else None
            key = (st, sid, tr)
            if key in seen:
                continue
            seen.add(key)
            out.append(e)
    return out


def strip_legacy_provenance_keys(payload: dict[str, Any]) -> dict[str, Any]:
    """Remove old provenance-only keys after normalization into provenance_entries."""
    p = dict(payload)
    for k in (
        "source_activity_id",
        "source_evidence",
        "activity_source_trust",
        "memory_source_trust",
        "derived_from_memory_id",
        "source_memory_id",
    ):
        p.pop(k, None)
    return p


def ensure_provenance_entries_list(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Return a fresh list of normalized entries; mutates ``payload`` in-place to attach it."""
    entries = provenance_entries_from_payload(payload)
    payload["provenance_entries"] = list(entries)
    return entries
