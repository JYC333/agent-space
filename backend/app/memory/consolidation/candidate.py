from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

CandidateType = Literal[
    "ignore",
    "episodic_memory",
    "semantic_memory",
    "policy_candidate",
    "case_memory",
    "archive_activity",
    "discard_activity",
]

ValidatorDecision = Literal[
    "reject",
    "preview_only",
    "create_review_proposal",
    "allow_auto_accept_if_policy_allows",
]


@dataclass(frozen=True)
class ValidationResult:
    decision: ValidatorDecision
    reason: str


@dataclass
class MemoryCandidate:
    """In-memory suggestion only — never persisted; must not write durable rows."""

    candidate_type: CandidateType
    space_id: str
    scope_type: str
    operation: Literal["create", "update", "archive", "policy_change"]
    suggested_layer: str | None = None
    suggested_kind: str | None = None
    content: str | None = None
    summary: str | None = None
    event_time: datetime | None = None
    event_type: str | None = None
    scope_id: str | None = None
    subject_user_id: str | None = None
    visibility: str = "space_shared"
    entity_refs: list[dict[str, Any]] = field(default_factory=list)
    relation_refs: list[dict[str, Any]] = field(default_factory=list)
    provenance_entries: list[dict[str, Any]] = field(default_factory=list)
    source_trust: str | None = None
    confidence: float = 1.0
    risk_level: str = "low"
    requires_review: bool = False
    rationale: str = ""
    dedupe_key: str = ""
    workspace_id: str | None = None
    source_activity_ids: list[str] = field(default_factory=list)
    target_memory_id: str | None = None
    policy_payload: dict[str, Any] | None = None
    memory_type: str = "episodic"
