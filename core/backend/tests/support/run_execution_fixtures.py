"""Test-only helpers to materialize Run-linked Activity / Artifact / Proposal rows.

Used when read-surface tests need deterministic rows without going through
adapter execution. Execution-path coverage uses ``RunExecutionService`` with
the echo adapter instead.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session
from ulid import ULID

from app.models import (
    ActivityRecord,
    Artifact,
    MemoryEntry,
    Proposal,
    Run,
    TaskArtifact,
    TaskProposal,
    TaskRun,
)


_TERMINAL = frozenset({"succeeded", "failed", "degraded", "cancelled"})


def _new_id() -> str:
    return str(ULID())


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _load_run(db: Session, run_id: str, space_id: str) -> Run:
    run = db.query(Run).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    if run.space_id != space_id:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found in this space")
    return run


def _guard_executable(run: Run) -> None:
    if run.status in _TERMINAL:
        raise HTTPException(
            status_code=409,
            detail=f"Run '{run.id}' is already in terminal status '{run.status}'",
        )
    if run.status == "waiting_for_review":
        raise HTTPException(
            status_code=409,
            detail=f"Run '{run.id}' is waiting for review and cannot be executed",
        )
    if run.status not in ("queued", "running"):
        raise HTTPException(
            status_code=409,
            detail=f"Run '{run.id}' cannot transition from '{run.status}' to running",
        )


def materialize_run_outputs_for_tests(
    db: Session,
    run_id: str,
    *,
    space_id: str,
    simulate_failure: bool = False,
) -> None:
    """Transition ``run`` like a completed execution and insert Activity / Artifact / Proposal.

    Mirrors deterministic fixture behaviour without
    a dedicated runtime class or obsolete ``runtime`` override execution semantics.
    """
    run = _load_run(db, run_id, space_id)
    _guard_executable(run)

    mem_before = (
        db.query(func.count(MemoryEntry.id))
        .filter(MemoryEntry.space_id == space_id, MemoryEntry.status == "active")
        .scalar()
    )

    is_dry_run = run.mode == "dry_run"
    started_at = _utcnow()
    run.status = "running"
    run.started_at = run.started_at or started_at
    run.updated_at = started_at
    db.flush()

    try:
        activity_start = _record_activity(
            db,
            run=run,
            activity_type="test_fixture_execution",
            title="Fixture execution started",
            content=(
                "Fixture: dry_run preview body"
                if is_dry_run
                else "Fixture: live run body"
            ),
            execution_step="started",
        )
        artifact = _record_artifact(db, run=run, is_dry_run=is_dry_run)
        proposal = _record_proposal(db, run=run, is_dry_run=is_dry_run)
        _link_outputs_to_tasks(db, run=run, artifact=artifact, proposal=proposal)
        _record_activity(
            db,
            run=run,
            activity_type="test_fixture_execution",
            title=(
                "Fixture execution failed"
                if simulate_failure
                else "Fixture execution completed"
            ),
            content=(
                "Fixture: simulated failure"
                if simulate_failure
                else "Fixture: completion"
            ),
            execution_step="failed" if simulate_failure else "completed",
            artifact_id=artifact.id,
            proposal_id=proposal.id,
        )

        ended_at = _utcnow()
        output_summary = {
            "runtime": "test_fixture",
            "preview": is_dry_run,
            "ok": not simulate_failure,
            "summary": (
                "Fixture preview output summary"
                if is_dry_run
                else "Fixture live output summary"
            ),
        }
        if simulate_failure:
            run.status = "failed"
            run.error_message = "Fixture: simulated failure"
            run.error_json = {
                "runtime": "test_fixture",
                "reason": "simulated_failure",
                "preview": is_dry_run,
            }
        else:
            run.status = "succeeded"
            run.error_message = None
            run.error_json = None
        run.output_json = output_summary
        run.ended_at = ended_at
        run.updated_at = ended_at
        db.commit()
        db.refresh(run)

        mem_after = (
            db.query(func.count(MemoryEntry.id))
            .filter(MemoryEntry.space_id == space_id, MemoryEntry.status == "active")
            .scalar()
        )
        if mem_after != mem_before:
            raise RuntimeError(
                "Fixture invariant violated: active MemoryEntry count changed during "
                f"run {run_id}; memory must remain proposal-only."
            )
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise


def _record_activity(
    db: Session,
    *,
    run: Run,
    activity_type: str,
    title: str,
    content: str,
    execution_step: str,
    artifact_id: str | None = None,
    proposal_id: str | None = None,
) -> ActivityRecord:
    payload: dict = {
        "runtime": "test_fixture",
        "execution_step": execution_step,
        "preview": run.mode == "dry_run",
    }
    if artifact_id is not None:
        payload["artifact_id"] = artifact_id
    if proposal_id is not None:
        payload["proposal_id"] = proposal_id
    now = _utcnow()
    record = ActivityRecord(
        id=_new_id(),
        space_id=run.space_id,
        source_run_id=run.id,
        session_id=run.session_id,
        user_id=run.instructed_by_user_id,
        workspace_id=run.workspace_id,
        agent_id=run.agent_id,
        activity_type=activity_type,
        title=title,
        content=content,
        payload_json=payload,
        occurred_at=now,
        status="raw",
        updated_at=now,
    )
    db.add(record)
    db.flush()
    return record


def _record_artifact(db: Session, *, run: Run, is_dry_run: bool) -> Artifact:
    title = "Fixture preview report" if is_dry_run else "Fixture completion report"
    content_body = (
        "Fixture preview report for run "
        if is_dry_run
        else "Fixture completion report for run "
    ) + run.id
    artifact = Artifact(
        id=_new_id(),
        space_id=run.space_id,
        run_id=run.id,
        artifact_type="fixture_report",
        title=title,
        content=content_body,
        mime_type="text/plain",
        exportable=True,
        preview=is_dry_run,
    )
    db.add(artifact)
    db.flush()
    return artifact


def _record_proposal(db: Session, *, run: Run, is_dry_run: bool) -> Proposal:
    now = _utcnow()
    review_deadline = now + timedelta(hours=48)
    expires_at = now + (timedelta(hours=6) if is_dry_run else timedelta(days=14))
    urgency = "low" if is_dry_run else "normal"
    payload = {
        "proposed_content": "Fixture preview memory note" if is_dry_run else "Fixture memory note",
        "memory_type": "semantic",
        "target_scope": "agent",
        "target_namespace": f"agent.{run.agent_id}",
        "target_visibility": "private",
        "sensitivity_level": "normal",
        "source_run_id": run.id,
        "runtime": "test_fixture",
        "preview": is_dry_run,
    }
    proposal = Proposal(
        id=_new_id(),
        space_id=run.space_id,
        created_by_run_id=run.id,
        proposal_type="memory_update",
        status="pending",
        risk_level="low",
        urgency=urgency,
        preview=is_dry_run,
        title="Fixture preview proposal" if is_dry_run else "Fixture memory proposal",
        summary=(
            "Deterministic preview proposal from test fixture; not for apply."
            if is_dry_run
            else "Deterministic memory proposal from test fixture."
        ),
        payload_json=payload,
        rationale="Deterministic verification proposal (fixture)",
        workspace_id=run.workspace_id,
        created_by_user_id=run.instructed_by_user_id,
        created_by_agent_id=run.agent_id,
        review_deadline=review_deadline,
        expires_at=expires_at,
    )
    db.add(proposal)
    db.flush()
    return proposal


def _link_outputs_to_tasks(
    db: Session,
    *,
    run: Run,
    artifact: Artifact,
    proposal: Proposal,
) -> None:
    task_run_rows = (
        db.query(TaskRun)
        .filter(
            TaskRun.run_id == run.id,
            TaskRun.space_id == run.space_id,
        )
        .all()
    )
    for tr in task_run_rows:
        existing_ta = (
            db.query(TaskArtifact)
            .filter(
                TaskArtifact.task_id == tr.task_id,
                TaskArtifact.artifact_id == artifact.id,
            )
            .first()
        )
        if not existing_ta:
            db.add(
                TaskArtifact(
                    id=_new_id(),
                    space_id=run.space_id,
                    task_id=tr.task_id,
                    artifact_id=artifact.id,
                    role="report",
                )
            )
        existing_tp = (
            db.query(TaskProposal)
            .filter(
                TaskProposal.task_id == tr.task_id,
                TaskProposal.proposal_id == proposal.id,
            )
            .first()
        )
        if not existing_tp:
            db.add(
                TaskProposal(
                    id=_new_id(),
                    space_id=run.space_id,
                    task_id=tr.task_id,
                    proposal_id=proposal.id,
                    role="memory_update",
                )
            )
    if task_run_rows:
        db.flush()


def attach_pending_proposal_for_run(
    db: Session,
    run: Run,
    *,
    preview: bool = False,
) -> Proposal:
    """Insert a single pending memory proposal for read-surface tests (no Task linkage)."""
    now = _utcnow()
    p = Proposal(
        id=_new_id(),
        space_id=run.space_id,
        created_by_run_id=run.id,
        proposal_type="memory_update",
        status="pending",
        risk_level="low",
        urgency="normal",
        preview=preview,
        title="Fixture attached proposal",
        summary="Attached for task/run listing tests",
        payload_json={
            "proposed_content": "x",
            "memory_type": "semantic",
            "target_scope": "agent",
            "target_namespace": f"agent.{run.agent_id}",
            "preview": preview,
        },
        rationale="fixture",
        workspace_id=run.workspace_id,
        created_by_user_id=run.instructed_by_user_id,
        created_by_agent_id=run.agent_id,
        review_deadline=now + timedelta(hours=48),
        expires_at=now + timedelta(days=14),
    )
    db.add(p)
    db.flush()
    return p
