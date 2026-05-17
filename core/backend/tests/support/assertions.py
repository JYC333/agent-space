"""Observable-state assertions for DB-backed tests (no hidden setup)."""

from __future__ import annotations

from typing import Any, TypeVar

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import ActivityRecord, Artifact, MemoryEntry, Proposal
from app.policy.engine import PolicyEngine
from app.workspace.path_policy import PathPolicy, PathPolicyError

T = TypeVar("T")


def assert_no_cross_space_leakage(
    db: Session,
    row: Any,
    *,
    space_id: str,
    msg: str | None = None,
) -> None:
    """Assert an ORM instance's ``space_id`` matches the expected tenant."""
    rid = getattr(row, "space_id", None)
    assert rid == space_id, msg or f"expected space_id={space_id!r}, got {rid!r} on {type(row).__name__}"


def assert_memory_unchanged(
    db: Session,
    *,
    space_id: str,
    baseline_ids: frozenset[str],
    status: str = "active",
) -> None:
    """Assert the set of MemoryEntry ids (optionally filtered by status) is unchanged."""
    q = db.query(MemoryEntry.id).filter(MemoryEntry.space_id == space_id)
    if status is not None:
        q = q.filter(MemoryEntry.status == status)
    current = frozenset(r[0] for r in q.all())
    assert current == baseline_ids, (
        f"memory set changed in space {space_id!r}: "
        f"added={sorted(current - baseline_ids)} removed={sorted(baseline_ids - current)}"
    )


def assert_proposal_created(
    db: Session,
    *,
    proposal_id: str,
    space_id: str,
    msg: str | None = None,
) -> Proposal:
    row = db.query(Proposal).filter(Proposal.id == proposal_id).first()
    assert row is not None, msg or f"proposal {proposal_id!r} not found"
    assert row.space_id == space_id, msg or f"proposal space mismatch: {row.space_id!r} != {space_id!r}"
    return row


def assert_proposal_not_applied(
    db: Session,
    *,
    proposal_id: str,
    space_id: str,
) -> None:
    """Pending proposal must not have produced active memory in this space."""
    prop = assert_proposal_created(db, proposal_id=proposal_id, space_id=space_id)
    assert prop.status == "pending", f"expected pending proposal, got {prop.status!r}"
    rid = (prop.payload_json or {}).get("resulting_memory_id")
    assert not rid, f"proposal payload unexpectedly contains resulting_memory_id={rid!r}"
    linked = (
        db.query(func.count(MemoryEntry.id))
        .filter(
            MemoryEntry.space_id == space_id,
            MemoryEntry.source_proposal_id == proposal_id,
            MemoryEntry.status == "active",
        )
        .scalar()
    )
    assert linked == 0, f"expected no active MemoryEntry for proposal {proposal_id!r}, found {linked}"


def assert_activity_recorded(
    db: Session,
    *,
    space_id: str,
    run_id: str | None = None,
    activity_type: str | None = None,
    min_count: int = 1,
) -> list[ActivityRecord]:
    q = db.query(ActivityRecord).filter(ActivityRecord.space_id == space_id)
    if run_id is not None:
        q = q.filter(ActivityRecord.source_run_id == run_id)
    if activity_type is not None:
        q = q.filter(ActivityRecord.activity_type == activity_type)
    rows = q.all()
    assert len(rows) >= min_count, (
        f"expected at least {min_count} activity row(s) "
        f"(space_id={space_id!r}, run_id={run_id!r}, activity_type={activity_type!r}), got {len(rows)}"
    )
    return rows


def assert_artifact_created(
    db: Session,
    *,
    artifact_id: str,
    space_id: str,
    run_id: str | None = None,
) -> Artifact:
    row = db.query(Artifact).filter(Artifact.id == artifact_id).first()
    assert row is not None, f"artifact {artifact_id!r} not found"
    assert row.space_id == space_id, f"artifact space mismatch: {row.space_id!r} != {space_id!r}"
    if run_id is not None:
        assert row.run_id == run_id, f"expected run_id={run_id!r}, got {row.run_id!r}"
    return row


def assert_path_access_denied(
    policy: PathPolicy,
    path: str,
    *,
    allowed_root: str,
    msg: str | None = None,
) -> None:
    try:
        policy.validate(path, allowed_root=allowed_root)
    except PathPolicyError:
        return
    raise AssertionError(msg or f"expected PathPolicyError for path={path!r} root={allowed_root!r}")


def assert_policy_requires_approval(
    context: dict[str, Any],
    *,
    msg: str | None = None,
) -> None:
    d = PolicyEngine().check(context)
    assert d.requires_approval, msg or f"expected REQUIRE_APPROVAL, got {d.decision} ({d.reason})"


def assert_run_has_audit_trail(
    db: Session,
    *,
    space_id: str,
    run_id: str,
    min_activities: int = 1,
) -> None:
    n = (
        db.query(func.count(ActivityRecord.id))
        .filter(
            ActivityRecord.space_id == space_id,
            ActivityRecord.source_run_id == run_id,
        )
        .scalar()
    )
    assert n is not None and n >= min_activities, (
        f"expected at least {min_activities} ActivityRecord(s) for run {run_id!r} in space {space_id!r}, got {n!r}"
    )


# ---------------------------------------------------------------------------
# PersonalMemoryGrant egress_review proposal payload safety assertions
# ---------------------------------------------------------------------------

_FORBIDDEN_CONTENT_KEYS = frozenset({
    "content",
    "body",
    "raw_content",
    "payload",
    "summary",
    "generated_summary",
    "personal_context_block",
    "memory_text",
    "personal_memory_text",
    "artifact_payload",
    "output_text",
    "adapter_output",
    "source_snapshot",
    "memory_ids",
    "personal_memory_ids",
})


def assert_no_personal_content_fields(payload_json: dict[str, Any], *, msg: str | None = None) -> None:
    """Assert an egress_review proposal payload contains no forbidden content keys.

    Also verifies the serialized payload doesn't contain raw content sentinel strings
    if provided via known_raw_text.
    """
    if not isinstance(payload_json, dict):
        raise AssertionError(msg or f"payload_json must be a dict, got {type(payload_json).__name__}")
    found = [k for k in _FORBIDDEN_CONTENT_KEYS if k in payload_json]
    assert not found, (
        msg or f"egress_review proposal payload contains forbidden content keys: {found!r}"
    )


def assert_egress_review_proposal_is_content_free(
    proposal: Proposal,
    *,
    known_raw_text: str | None = None,
    known_summary_text: str | None = None,
    msg: str | None = None,
) -> None:
    """Assert an egress_review proposal's payload is free of personal content."""
    payload = proposal.payload_json or {}
    assert_no_personal_content_fields(payload, msg=msg)

    payload_str = str(payload)
    if known_raw_text:
        assert known_raw_text not in payload_str, (
            msg or f"egress_review payload contains raw personal memory text: {known_raw_text!r}"
        )
    if known_summary_text:
        assert known_summary_text not in payload_str, (
            msg or f"egress_review payload contains generated summary text: {known_summary_text!r}"
        )
    assert "personal_context_block" not in payload_str, (
        msg or "egress_review payload must not contain personal_context_block"
    )
    assert proposal.proposal_type == "egress_review", (
        msg or f"expected proposal_type='egress_review', got {proposal.proposal_type!r}"
    )
    assert proposal.risk_level == "high", (
        msg or f"egress_review proposal must have risk_level='high', got {proposal.risk_level!r}"
    )
    assert payload.get("raw_private_memory_included") is False
    assert payload.get("personal_summary_persisted") is False
    assert payload.get("derived_from_personal_memory") is True
    assert payload.get("egress_guard_required") is True
    assert payload.get("requires_approval_type") == "egress_granting_user"
