"""PersonalMemoryGrant resolver.

Implements:
- Grant lookup and validation for a specific run
- Atomic active → consuming → used/failed state transitions
- Personal memory eligibility filtering (cross-space read, controlled path)
- Summary-only context block generation (deterministic, no LLM)
- Safe audit event writing

Security invariants:
- Only grants matching run_id, granting_user_id, target_space_id, grant_scope='run',
  access_mode='summary_only', and non-expired read_expires_at are eligible.
- Revoked/used/failed/expired grants are rejected at query time.
- Highly restricted and restricted memories are never included.
- After raw memory read, failure must transition grant to 'failed'; it must not
  return to 'active'.
- Callers must not persist the returned personal_context_block to shared
  ContextSnapshot text fields, source_refs, or any shared artifact.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Optional

from sqlalchemy import update
from sqlalchemy.orm import Session

from ..models import MemoryEntry, PersonalMemoryGrant, PersonalMemoryGrantEvent, Run

log = logging.getLogger(__name__)

# Sensitivity levels that may be included in grant-derived summaries.
# restricted and highly_restricted are always excluded.
_ALLOWED_SENSITIVITY_LEVELS = frozenset({"normal", "sensitive"})

_DEFAULT_MAX_ITEMS = 10
_MAX_MAX_ITEMS = 20


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _new_id() -> str:
    from ulid import ULID
    return str(ULID())


def _write_event(
    db: Session,
    *,
    grant_id: str,
    event_type: str,
    actor_user_id: str | None = None,
    run_id: str | None = None,
    source_space_id: str | None = None,
    target_space_id: str | None = None,
    metadata_json: dict | None = None,
) -> None:
    from .validation import validate_grant_event_metadata
    if metadata_json is not None:
        validate_grant_event_metadata(metadata_json)
    event = PersonalMemoryGrantEvent(
        id=_new_id(),
        grant_id=grant_id,
        event_type=event_type,
        actor_user_id=actor_user_id,
        run_id=run_id,
        source_space_id=source_space_id,
        target_space_id=target_space_id,
        metadata_json=metadata_json,
    )
    db.add(event)
    db.flush()


# ---------------------------------------------------------------------------
# Grant lookup
# ---------------------------------------------------------------------------


def find_active_grant_for_run(
    db: Session,
    *,
    run_id: str,
    granting_user_id: str,
    target_space_id: str,
    now: datetime,
) -> Optional[PersonalMemoryGrant]:
    """Return an eligible active grant for this (run, user, space) triple, or None."""
    return (
        db.query(PersonalMemoryGrant)
        .filter(
            PersonalMemoryGrant.target_run_id == run_id,
            PersonalMemoryGrant.granting_user_id == granting_user_id,
            PersonalMemoryGrant.target_space_id == target_space_id,
            PersonalMemoryGrant.status == "active",
            PersonalMemoryGrant.grant_scope == "run",
            PersonalMemoryGrant.access_mode == "summary_only",
            PersonalMemoryGrant.target_agent_id.is_(None),
            PersonalMemoryGrant.read_expires_at > now,
        )
        .first()
    )


# ---------------------------------------------------------------------------
# Atomic state transitions
# ---------------------------------------------------------------------------


def begin_consuming_grant(
    db: Session,
    *,
    grant_id: str,
    now: datetime,
) -> bool:
    """Atomically transition grant from active → consuming.

    Uses a conditional UPDATE so that at most one concurrent caller succeeds.
    Returns True if this caller claimed the grant; False if another did first.
    """
    stmt = (
        update(PersonalMemoryGrant)
        .where(
            PersonalMemoryGrant.id == grant_id,
            PersonalMemoryGrant.status == "active",
            PersonalMemoryGrant.read_expires_at > now,
        )
        .values(status="consuming", consume_started_at=now)
        .execution_options(synchronize_session="fetch")
    )
    result = db.execute(stmt)
    db.flush()
    return result.rowcount == 1


def mark_grant_used(
    db: Session,
    *,
    grant_id: str,
    run_id: str,
    memory_count: int,
    source_space_id: str | None = None,
    target_space_id: str | None = None,
) -> None:
    """Transition grant from consuming → used and write a 'used' audit event."""
    now = datetime.now(UTC)
    stmt = (
        update(PersonalMemoryGrant)
        .where(
            PersonalMemoryGrant.id == grant_id,
            PersonalMemoryGrant.status == "consuming",
        )
        .values(status="used", used_at=now)
        .execution_options(synchronize_session="fetch")
    )
    db.execute(stmt)
    db.flush()

    _write_event(
        db,
        grant_id=grant_id,
        event_type="used",
        run_id=run_id,
        source_space_id=source_space_id,
        target_space_id=target_space_id,
        metadata_json={
            "memory_count": memory_count,
            "access_mode": "summary_only",
            "raw_memory_included": False,
            "personal_summary_persisted": False,
        },
    )


def mark_grant_failed(
    db: Session,
    *,
    grant_id: str,
    run_id: str,
    failure_stage: str,
    source_space_id: str | None = None,
    target_space_id: str | None = None,
) -> None:
    """Transition grant to failed regardless of current consuming state.

    After raw memory read, grant must not return to 'active' on failure.
    """
    now = datetime.now(UTC)
    stmt = (
        update(PersonalMemoryGrant)
        .where(PersonalMemoryGrant.id == grant_id)
        .values(status="failed", failed_at=now, failure_stage=failure_stage)
        .execution_options(synchronize_session="fetch")
    )
    db.execute(stmt)
    db.flush()

    _write_event(
        db,
        grant_id=grant_id,
        event_type="failed",
        run_id=run_id,
        source_space_id=source_space_id,
        target_space_id=target_space_id,
        metadata_json={
            "failure_stage": failure_stage,
            "raw_memory_included": False,
        },
    )


# ---------------------------------------------------------------------------
# Personal memory retrieval
# ---------------------------------------------------------------------------


def retrieve_eligible_memories(
    db: Session,
    *,
    personal_space_id: str,
    granting_user_id: str,
    memory_filter: dict | None,
) -> list[MemoryEntry]:
    """Retrieve personal-space private memories eligible for summary generation.

    Hard filters applied (all must pass):
    - space_id == personal_space_id  (cross-space read; only allowed via grant)
    - owner_user_id == granting_user_id
    - visibility == 'private'
    - sensitivity_level in ('normal', 'sensitive')  — restricted/highly_restricted excluded
    - status == 'active'
    - deleted_at IS NULL

    Optional memory_filter_json filters:
    - memory_layers: list of allowed memory_layer values
    - memory_kinds: list of allowed memory_kind values
    - namespaces: list of allowed namespace values
    - max_items: max rows returned (default 10, max 20)
    """
    mf = memory_filter or {}
    raw_max = mf.get("max_items", _DEFAULT_MAX_ITEMS)
    try:
        max_items = min(int(raw_max), _MAX_MAX_ITEMS)
    except (TypeError, ValueError):
        max_items = _DEFAULT_MAX_ITEMS

    q = (
        db.query(MemoryEntry)
        .filter(
            MemoryEntry.space_id == personal_space_id,
            MemoryEntry.owner_user_id == granting_user_id,
            MemoryEntry.visibility == "private",
            MemoryEntry.sensitivity_level.in_(list(_ALLOWED_SENSITIVITY_LEVELS)),
            MemoryEntry.status == "active",
            MemoryEntry.deleted_at.is_(None),
        )
    )

    memory_layers = mf.get("memory_layers")
    if memory_layers:
        q = q.filter(MemoryEntry.memory_layer.in_(memory_layers))

    memory_kinds = mf.get("memory_kinds")
    if memory_kinds:
        q = q.filter(MemoryEntry.memory_kind.in_(memory_kinds))

    namespaces = mf.get("namespaces")
    if namespaces:
        q = q.filter(MemoryEntry.namespace.in_(namespaces))

    q = q.order_by(MemoryEntry.updated_at.desc(), MemoryEntry.created_at.desc())
    q = q.limit(max_items)

    return q.all()


# ---------------------------------------------------------------------------
# Summary generation
# ---------------------------------------------------------------------------


def generate_personal_summary(memories: list[MemoryEntry]) -> str:
    """Generate a structured summary of personal memories for ephemeral context.

    MVP implementation: deterministic, extractive, no LLM.
    Does not include raw memory text, memory IDs, or full content.
    The summary is safe for ephemeral use only — it must not be persisted
    to shared ContextSnapshot fields.
    """
    if not memories:
        return "No personal memory entries are available for this context."

    count = len(memories)

    kinds: set[str] = set()
    for m in memories:
        if m.memory_kind:
            kinds.add(m.memory_kind)

    timestamps = [
        m.updated_at or m.created_at
        for m in memories
        if (m.updated_at or m.created_at) is not None
    ]
    most_recent = max(timestamps) if timestamps else None

    noun = "entry" if count == 1 else "entries"
    parts = [
        f"The user has {count} relevant personal memory {noun} available for this context."
    ]
    if kinds:
        parts.append(f"Categories: {', '.join(sorted(kinds))}.")
    if most_recent:
        parts.append(f"Most recently updated: {most_recent.strftime('%Y-%m-%d')}.")
    parts.append(
        "Raw memory content is not included in this summary; "
        "only aggregate metadata is provided."
    )
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Resolution result
# ---------------------------------------------------------------------------


@dataclass
class PersonalGrantResolutionResult:
    """Result of a grant resolution attempt for a single run context build."""

    grant: Optional[PersonalMemoryGrant]
    personal_context_block: str
    memory_count: int
    grant_metadata: Optional[dict]

    @property
    def has_personal_context(self) -> bool:
        return bool(self.personal_context_block)


_NO_GRANT_RESULT = PersonalGrantResolutionResult(
    grant=None,
    personal_context_block="",
    memory_count=0,
    grant_metadata=None,
)


# ---------------------------------------------------------------------------
# Top-level orchestration
# ---------------------------------------------------------------------------


def resolve_personal_memory_context_for_run(
    db: Session,
    *,
    run: Run,
) -> PersonalGrantResolutionResult:
    """Orchestrate grant resolution for one run context build.

    This is the entry point called by ContextSnapshotPopulator.

    Safety contract:
    - If no valid grant, returns _NO_GRANT_RESULT (no cross-space read).
    - The returned personal_context_block is ephemeral.  Callers MUST NOT
      persist it to ContextSnapshot.compiled_prefix_text,
      compiled_tail_text, source_refs_json, or any shared artifact.
    - Only safe grant metadata (grant_id, memory_count, access_mode, …)
      may be added to shared ContextSnapshot source_refs.
    - Failure after cross-space read → grant transitions to 'failed';
      it is never restored to 'active'.
    """
    granting_user_id = run.instructed_by_user_id
    if not granting_user_id:
        return _NO_GRANT_RESULT

    now = datetime.now(UTC)

    # Step 1: find eligible active grant
    grant = find_active_grant_for_run(
        db,
        run_id=run.id,
        granting_user_id=granting_user_id,
        target_space_id=run.space_id,
        now=now,
    )
    if grant is None:
        return _NO_GRANT_RESULT

    # Step 2: atomic active → consuming claim
    claimed = begin_consuming_grant(db, grant_id=grant.id, now=now)
    if not claimed:
        log.info(
            "Run %s: grant %s already consumed by concurrent caller — proceeding without grant",
            run.id,
            grant.id,
        )
        return _NO_GRANT_RESULT

    # Refresh to pick up updated status/consume_started_at
    db.refresh(grant)

    _write_event(
        db,
        grant_id=grant.id,
        event_type="consuming",
        run_id=run.id,
        source_space_id=grant.personal_space_id,
        target_space_id=grant.target_space_id,
        metadata_json={
            "access_mode": grant.access_mode,
            "raw_memory_included": False,
        },
    )

    # Step 3: cross-space personal memory retrieval
    memories: list[MemoryEntry] = []
    try:
        memories = retrieve_eligible_memories(
            db,
            personal_space_id=grant.personal_space_id,
            granting_user_id=grant.granting_user_id,
            memory_filter=grant.memory_filter_json,
        )
    except Exception:
        log.exception(
            "Run %s: memory retrieval failed for grant %s", run.id, grant.id
        )
        mark_grant_failed(
            db,
            grant_id=grant.id,
            run_id=run.id,
            failure_stage="memory_retrieval",
            source_space_id=grant.personal_space_id,
            target_space_id=grant.target_space_id,
        )
        return _NO_GRANT_RESULT

    # Step 4: summary generation (after cross-space read — never restore to active on failure)
    try:
        summary = generate_personal_summary(memories)
    except Exception:
        log.exception(
            "Run %s: summary generation failed for grant %s", run.id, grant.id
        )
        mark_grant_failed(
            db,
            grant_id=grant.id,
            run_id=run.id,
            failure_stage="summary_generation",
            source_space_id=grant.personal_space_id,
            target_space_id=grant.target_space_id,
        )
        return _NO_GRANT_RESULT

    # Step 5: consuming → used
    memory_count = len(memories)
    mark_grant_used(
        db,
        grant_id=grant.id,
        run_id=run.id,
        memory_count=memory_count,
        source_space_id=grant.personal_space_id,
        target_space_id=grant.target_space_id,
    )
    db.refresh(grant)

    grant_metadata = {
        "grant_id": grant.id,
        "granting_user_id": grant.granting_user_id,
        "personal_space_id": grant.personal_space_id,
        "target_space_id": grant.target_space_id,
        "access_mode": grant.access_mode,
        "memory_count": memory_count,
        "raw_memory_included": False,
        "personal_summary_persisted": False,
    }

    return PersonalGrantResolutionResult(
        grant=grant,
        personal_context_block=summary,
        memory_count=memory_count,
        grant_metadata=grant_metadata,
    )
