from __future__ import annotations

import hashlib
import json
from typing import Protocol, runtime_checkable

from ...models import ActivityRecord
from ..proposal_payload import SOURCE_TRUST_VALUES, activity_provenance_entry
from .candidate import MemoryCandidate


def _resolved_trust_from_activity(record: ActivityRecord) -> str:
    raw = record.source_trust
    if isinstance(raw, str) and raw in SOURCE_TRUST_VALUES:
        return raw
    kind = (record.activity_type or "").lower().strip()
    if kind in ("user_capture", "chat_message", "user_input", "manual"):
        return "user_confirmed"
    if kind in ("run_event", "system_event", "workspace_event", "agent_run", "task_log"):
        return "internal_system"
    if kind in (
        "external_chat",
        "web_capture",
        "file_import",
        "external_source",
        "imported_chat",
    ):
        return "untrusted_external"
    if kind == "agent_inferred":
        return "agent_inferred"
    return "untrusted_external"


def _resolved_trust(record: ActivityRecord) -> str:
    """Never upgrades stored trust; unknown kinds default conservatively."""
    raw = record.source_trust
    if isinstance(raw, str) and raw in SOURCE_TRUST_VALUES:
        return raw
    sk = (record.source_kind or "").strip()
    if sk in (
        "user_capture",
        "chat_message",
    ):
        return "user_confirmed"
    if sk in ("run_event", "workspace_event", "system_event"):
        return "internal_system"
    if sk in ("external_chat", "web_capture", "file_import", "external_source"):
        return "untrusted_external"
    if sk:
        inferred = _resolved_trust_from_activity(record)
        return "untrusted_external" if inferred == "user_confirmed" else inferred
    return _resolved_trust_from_activity(record)


def _entity_refs_from_activity(record: ActivityRecord) -> list[dict]:
    raw = record.entity_refs_json
    if isinstance(raw, list):
        return [x for x in raw if isinstance(x, dict)]
    return []


def _lightweight_episodic_summary(record: ActivityRecord) -> str:
    t = (record.title or "").strip()
    if t:
        return t[:512]
    c = (record.content or "").strip()
    if len(c) > 200:
        return f"{c[:197]}…"
    return c or "activity"


def _lightweight_episodic_content(record: ActivityRecord) -> str:
    """Structured index JSON — must not embed full raw activity body."""
    body = {
        "event_time": record.occurred_at.isoformat() if record.occurred_at else None,
        "event_type": record.activity_type,
        "entity_refs": _entity_refs_from_activity(record),
        "summary": _lightweight_episodic_summary(record),
        "activity_id": record.id,
        "source_kind": record.source_kind,
        "source_run_id": record.source_run_id,
        "session_id": record.session_id,
    }
    return json.dumps(body, sort_keys=True, default=str)


def _candidate_dedupe_seed(
    *,
    space_id: str,
    activity_id: str,
    candidate_type: str,
    layer: str | None,
    kind: str | None,
    operation: str,
    summary: str,
    entity_refs: list,
    compiler_version: str,
) -> str:
    payload = {
        "space_id": space_id,
        "activity_ids": [activity_id],
        "candidate_type": candidate_type,
        "suggested_layer": layer,
        "suggested_kind": kind,
        "operation": operation,
        "summary": (summary or "")[:4000],
        "entity_refs": entity_refs,
        "compiler_version": compiler_version,
    }
    blob = json.dumps(payload, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()


@runtime_checkable
class MemoryCandidateClassifier(Protocol):
    def classify(self, record: ActivityRecord, *, compiler_version: str) -> list[MemoryCandidate]: ...


class DefaultRuleBasedMemoryCandidateClassifier:
    """Maps activity source signals to episodic / semantic / policy / case candidates."""

    def classify(self, record: ActivityRecord, *, compiler_version: str) -> list[MemoryCandidate]:
        if record.consolidation_status != "pending":
            return []

        trust = _resolved_trust(record)
        at = (record.activity_type or "").lower()

        if at == "consolidation.no_candidate":
            return []

        if at.startswith("policy.") or (record.payload_json or {}).get("policy_candidate"):
            dedupe = _candidate_dedupe_seed(
                space_id=record.space_id,
                activity_id=record.id,
                candidate_type="policy_candidate",
                layer=None,
                kind="policy",
                operation="policy_change",
                summary=_lightweight_episodic_summary(record),
                entity_refs=_entity_refs_from_activity(record),
                compiler_version=compiler_version,
            )
            return [
                MemoryCandidate(
                    candidate_type="policy_candidate",
                    space_id=record.space_id,
                    scope_type="space",
                    scope_id=record.space_id,
                    operation="policy_change",
                    suggested_layer=None,
                    suggested_kind="policy",
                    content=None,
                    summary=_lightweight_episodic_summary(record),
                    event_time=record.occurred_at,
                    event_type=record.activity_type,
                    subject_user_id=record.subject_user_id or record.user_id,
                    visibility="space_shared",
                    entity_refs=_entity_refs_from_activity(record),
                    provenance_entries=[
                        activity_provenance_entry(
                            activity_id=record.id,
                            source_trust=trust,
                            evidence={
                                "channel": "activity_consolidation",
                                "activity_type": record.activity_type,
                            },
                        )
                    ],
                    source_trust=trust,
                    risk_level="high",
                    requires_review=True,
                    rationale="Activity marked as policy candidate.",
                    dedupe_key=dedupe,
                    workspace_id=record.workspace_id,
                    source_activity_ids=[record.id],
                    policy_payload={
                        "operation": "create",
                        "domain": "memory",
                        "policy_key": f"activity_derived:{record.id[:8]}",
                        "policy_version": 1,
                        "rule_json": {"effect": "review", "from_activity": record.id},
                    },
                    memory_type="semantic",
                )
            ]

        if (record.payload_json or {}).get("consolidation", {}).get("lane") == "semantic":
            dedupe = _candidate_dedupe_seed(
                space_id=record.space_id,
                activity_id=record.id,
                candidate_type="semantic_memory",
                layer="semantic",
                kind="fact",
                operation="create",
                summary=_lightweight_episodic_summary(record),
                entity_refs=_entity_refs_from_activity(record),
                compiler_version=compiler_version,
            )
            return [
                MemoryCandidate(
                    candidate_type="semantic_memory",
                    space_id=record.space_id,
                    scope_type="user",
                    scope_id=record.user_id,
                    operation="create",
                    suggested_layer="semantic",
                    suggested_kind="fact",
                    content=_lightweight_episodic_content(record),
                    summary=_lightweight_episodic_summary(record),
                    event_time=record.occurred_at,
                    event_type=record.activity_type,
                    subject_user_id=record.subject_user_id or record.user_id,
                    visibility="space_shared",
                    entity_refs=_entity_refs_from_activity(record),
                    provenance_entries=[
                        activity_provenance_entry(
                            activity_id=record.id,
                            source_trust=trust,
                            evidence={"channel": "activity_consolidation"},
                        )
                    ],
                    source_trust=trust,
                    risk_level="medium",
                    requires_review=True,
                    rationale="Explicit semantic lane on activity payload.",
                    dedupe_key=dedupe,
                    workspace_id=record.workspace_id,
                    source_activity_ids=[record.id],
                    memory_type="semantic",
                )
            ]

        if at in ("task_log",) or "case" in at:
            ct = "case_memory"
            mem_type = "episodic"
            layer = "episodic"
            kind = "case"
        else:
            ct = "episodic_memory"
            mem_type = "episodic"
            layer = "episodic"
            kind = "event"

        dedupe = _candidate_dedupe_seed(
            space_id=record.space_id,
            activity_id=record.id,
            candidate_type=ct,
            layer=layer,
            kind=kind,
            operation="create",
            summary=_lightweight_episodic_summary(record),
            entity_refs=_entity_refs_from_activity(record),
            compiler_version=compiler_version,
        )
        return [
            MemoryCandidate(
                candidate_type=ct,
                space_id=record.space_id,
                scope_type="user",
                scope_id=record.user_id,
                operation="create",
                suggested_layer=layer,
                suggested_kind=kind,
                content=_lightweight_episodic_content(record),
                summary=_lightweight_episodic_summary(record),
                event_time=record.occurred_at,
                event_type=record.activity_type,
                subject_user_id=record.subject_user_id or record.user_id,
                visibility="space_shared",
                entity_refs=_entity_refs_from_activity(record),
                provenance_entries=[
                    activity_provenance_entry(
                        activity_id=record.id,
                        source_trust=trust,
                        evidence={"channel": "activity_consolidation"},
                    )
                ],
                source_trust=trust,
                risk_level="high" if trust == "untrusted_external" else "low",
                requires_review=trust in ("untrusted_external", "agent_inferred"),
                rationale=f"Rule-based classification ({ct}).",
                dedupe_key=dedupe,
                workspace_id=record.workspace_id,
                source_activity_ids=[record.id],
                memory_type=mem_type,
            )
        ]
