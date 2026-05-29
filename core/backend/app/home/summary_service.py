"""Read-only aggregation for Home summary — no memory context assembly, execution, or job claims."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.memory.proposals import ProposalService
from app.models import ActivityRecord, Artifact, ExtractedEvidence, ExtractionJob, IntakeItem, Job, ModelProvider, Run, RuntimeAdapter, SourceConnection, Task
from app.proposals.read_model import compute_proposal_expired

from .schemas import (
    HomeActiveTaskItem,
    HomeActivitySummarySection,
    HomeArtifactSummaryItem,
    HomeIntakeSummarySection,
    HomeJobQueueStatusSection,
    HomeModelProviderStatusSection,
    HomePendingProposalItem,
    HomePendingProposalsSection,
    HomeRunStatsTodaySection,
    HomeRunSummaryItem,
    HomeRuntimeStatusSection,
    HomeSuggestedActionItem,
    HomeSummaryOut,
    HomeTaskSummarySection,
)

_ACTIVE_TASK_STATUSES = frozenset(
    {"inbox", "ready", "claimed", "in_progress", "needs_review", "blocked"}
)
_ACTIVE_RUN_STATUSES = frozenset({"queued", "running", "waiting_for_review"})


def _utc_day_bounds(now: datetime) -> tuple[datetime, datetime]:
    n = now.astimezone(UTC) if now.tzinfo else now.replace(tzinfo=UTC)
    start = n.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1)


def _clip(text: str | None, max_len: int = 500) -> str | None:
    if text is None:
        return None
    t = text.strip()
    if len(t) <= max_len:
        return t
    return t[: max_len - 3] + "..."


def _run_to_item(r: Run) -> HomeRunSummaryItem:
    return HomeRunSummaryItem(
        id=r.id,
        status=r.status,
        mode=r.mode,
        run_type=r.run_type,
        agent_id=r.agent_id,
        task_id=r.task_id,
        created_at=r.created_at,
        started_at=r.started_at,
        completed_at=r.ended_at,
        error_text=_clip(r.error_message),
    )


def _model_provider_section(db: Session, space_id: str) -> HomeModelProviderStatusSection:
    rows = db.query(ModelProvider).filter(ModelProvider.space_id == space_id).all()
    enabled = [r for r in rows if r.enabled]
    n_total = len(rows)
    n_enabled = len(enabled)
    missing = n_enabled == 0
    if missing:
        msg = "No enabled model providers configured for this space."
    else:
        msg = f"{n_enabled} enabled model provider(s) configured."
    return HomeModelProviderStatusSection(
        model_providers_count=n_total,
        enabled_model_providers_count=n_enabled,
        missing_model_provider_config=missing,
        message=msg,
    )


def _runtime_section(db: Session, space_id: str) -> HomeRuntimeStatusSection:
    rows = (
        db.query(RuntimeAdapter)
        .filter(
            RuntimeAdapter.space_id == space_id,
            RuntimeAdapter.enabled.is_(True),
        )
        .all()
    )
    types = sorted({r.adapter_type for r in rows})
    n_real = len(rows)
    if n_real == 0:
        msg = "No enabled runtime adapters configured for this space."
    else:
        msg = f"{n_real} enabled runtime adapter(s) configured."
    return HomeRuntimeStatusSection(
        real_adapters_configured_count=n_real,
        configured_adapter_types=types,
        message=msg,
    )


def _suggested_actions(
    *,
    pending_proposals: int,
    failed_today: int,
    needs_review_tasks: int,
    real_adapters: int,
    enabled_providers: int,
    raw_activities: int = 0,
    open_intake_items: int = 0,
    pending_extraction_jobs: int = 0,
    failed_extraction_jobs: int = 0,
    candidate_evidence: int = 0,
    due_connections: int = 0,
) -> list[HomeSuggestedActionItem]:
    actions: list[HomeSuggestedActionItem] = []
    if pending_proposals > 0:
        actions.append(
            HomeSuggestedActionItem(
                id="review-pending-proposals",
                label="Review pending proposals",
                reason=f"{pending_proposals} proposal(s) await review.",
                target_path="/proposals",
                priority="high",
            )
        )
    if failed_today > 0:
        actions.append(
            HomeSuggestedActionItem(
                id="inspect-failed-runs",
                label="Inspect failed runs",
                reason=f"{failed_today} run(s) failed today.",
                target_path="/runs?status=failed",
                priority="high",
            )
        )
    if raw_activities > 0:
        actions.append(
            HomeSuggestedActionItem(
                id="process-activity-inbox",
                label="Process Activity Inbox",
                reason=f"{raw_activities} raw activity record(s) need attention.",
                target_path="/activity",
                priority="normal",
            )
        )
    if needs_review_tasks > 0:
        actions.append(
            HomeSuggestedActionItem(
                id="review-tasks-needs-review",
                label="Review completed task outputs",
                reason=f"{needs_review_tasks} task(s) need review.",
                target_path="/tasks?status=needs_review",
                priority="normal",
            )
        )
    if failed_extraction_jobs > 0:
        actions.append(
            HomeSuggestedActionItem(
                id="review-failed-extractions",
                label="Review failed extractions",
                reason=f"{failed_extraction_jobs} extraction job(s) failed.",
                target_path="/intake",
                priority="normal",
            )
        )
    if due_connections > 0:
        actions.append(
            HomeSuggestedActionItem(
                id="check-due-connections",
                label="Scan due connections",
                reason=f"{due_connections} source connection(s) are due for a check.",
                target_path="/intake",
                priority="normal",
            )
        )
    if open_intake_items > 0 or candidate_evidence > 0 or pending_extraction_jobs > 0:
        reason_parts: list[str] = []
        if open_intake_items > 0:
            reason_parts.append(f"{open_intake_items} open item(s)")
        if candidate_evidence > 0:
            reason_parts.append(f"{candidate_evidence} evidence candidate(s)")
        if pending_extraction_jobs > 0:
            reason_parts.append(f"{pending_extraction_jobs} pending extraction(s)")
        actions.append(
            HomeSuggestedActionItem(
                id="review-intake",
                label="Review Intake",
                reason=", ".join(reason_parts) + " need attention.",
                target_path="/intake",
                priority="low",
            )
        )
    if enabled_providers == 0:
        actions.append(
            HomeSuggestedActionItem(
                id="configure-model-provider",
                label="Configure a model provider",
                reason="No enabled model providers are configured for this space.",
                target_path="/providers",
                priority="low",
            )
        )
    if real_adapters == 0:
        actions.append(
            HomeSuggestedActionItem(
                id="configure-runtime-adapter",
                label="Configure a runtime adapter",
                reason="No enabled runtime adapters are configured for this space.",
                target_path="/cli-tools",
                priority="low",
            )
        )
    prio_rank = {"high": 0, "normal": 1, "low": 2}
    actions.sort(key=lambda a: prio_rank[a.priority])
    return actions


def build_home_summary(
    db: Session,
    space_id: str,
    user_id: str,
    *,
    now: datetime | None = None,
    recent_runs_limit: int = 10,
    active_runs_limit: int = 20,
    pending_preview_limit: int = 10,
    recent_artifacts_limit: int = 10,
    active_tasks_limit: int = 20,
) -> HomeSummaryOut:
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    else:
        now = now.astimezone(UTC)
    day_start, day_end = _utc_day_bounds(now)
    week_ago = now - timedelta(days=7)

    recent_rows = (
        db.query(Run)
        .filter(Run.space_id == space_id)
        .order_by(Run.created_at.desc())
        .limit(recent_runs_limit)
        .all()
    )
    active_rows = (
        db.query(Run)
        .filter(Run.space_id == space_id, Run.status.in_(sorted(_ACTIVE_RUN_STATUSES)))
        .order_by(Run.created_at.desc())
        .limit(active_runs_limit)
        .all()
    )

    prop_svc = ProposalService(db)
    pending_count = prop_svc.count_reviewable_proposals(space_id, user_id)
    pending_models = prop_svc.list_reviewable_proposals(
        space_id, user_id, limit=pending_preview_limit, offset=0
    )
    pending_items: list[HomePendingProposalItem] = []
    for p in pending_models:
        pending_items.append(
            HomePendingProposalItem(
                id=p.id,
                title=p.title,
                proposal_type=p.proposal_type,
                status=p.status,
                risk_level=p.risk_level,
                urgency=p.urgency,
                review_deadline=p.review_deadline,
                expires_at=p.expires_at,
                expired=compute_proposal_expired(p, now=now),
                preview=bool(p.preview),
                created_by_run_id=p.created_by_run_id,
            )
        )

    art_rows = (
        db.query(
            Artifact.id,
            Artifact.title,
            Artifact.artifact_type,
            Artifact.preview,
            Artifact.run_id,
            Artifact.created_at,
        )
        .filter(Artifact.space_id == space_id)
        .order_by(Artifact.created_at.desc())
        .limit(recent_artifacts_limit)
        .all()
    )
    recent_artifacts = [
        HomeArtifactSummaryItem(
            id=row.id,
            title=row.title,
            artifact_type=row.artifact_type,
            preview=bool(row.preview),
            run_id=row.run_id,
            created_at=row.created_at,
        )
        for row in art_rows
    ]

    status_rows = (
        db.query(Task.status, func.count(Task.id))
        .filter(Task.space_id == space_id, Task.deleted_at.is_(None))
        .group_by(Task.status)
        .all()
    )
    by_status: dict[str, int] = {str(s): int(c) for s, c in status_rows}
    terminal = {"done", "cancelled"}
    total_open = sum(c for st, c in by_status.items() if st not in terminal)
    needs_review_count = by_status.get("needs_review", 0)
    blocked_count = by_status.get("blocked", 0)
    done_count = by_status.get("done", 0)
    task_summary = HomeTaskSummarySection(
        by_status=by_status,
        total_open=total_open,
        needs_review_count=needs_review_count,
        blocked_count=blocked_count,
        done_count=done_count,
    )

    active_task_rows = (
        db.query(Task)
        .filter(
            Task.space_id == space_id,
            Task.deleted_at.is_(None),
            Task.status.in_(sorted(_ACTIVE_TASK_STATUSES)),
        )
        .order_by(Task.updated_at.desc())
        .limit(active_tasks_limit)
        .all()
    )
    active_tasks = [
        HomeActiveTaskItem(
            id=t.id,
            title=t.title,
            status=t.status,
            priority=t.priority,
            risk_level=t.risk_level,
            task_type=t.task_type,
            assigned_user_id=t.assigned_user_id,
            assigned_agent_id=t.assigned_agent_id,
            due_at=t.due_at,
            updated_at=t.updated_at,
        )
        for t in active_task_rows
    ]

    recent_count = (
        db.query(func.count(ActivityRecord.id))
        .filter(ActivityRecord.space_id == space_id, ActivityRecord.created_at >= week_ago)
        .scalar()
        or 0
    )
    raw_count = (
        db.query(func.count(ActivityRecord.id))
        .filter(ActivityRecord.space_id == space_id, ActivityRecord.status == "raw")
        .scalar()
        or 0
    )
    today_count = (
        db.query(func.count(ActivityRecord.id))
        .filter(
            ActivityRecord.space_id == space_id,
            ActivityRecord.created_at >= day_start,
            ActivityRecord.created_at < day_end,
        )
        .scalar()
        or 0
    )
    activity_summary = HomeActivitySummarySection(
        recent_count=int(recent_count),
        raw_count=int(raw_count),
        today_count=int(today_count),
    )

    today_base = [Run.space_id == space_id, Run.created_at >= day_start, Run.created_at < day_end]
    created = db.query(func.count(Run.id)).filter(*today_base).scalar() or 0
    queued_today = (
        db.query(func.count(Run.id)).filter(*today_base, Run.status == "queued").scalar() or 0
    )
    running_today = (
        db.query(func.count(Run.id)).filter(*today_base, Run.status == "running").scalar() or 0
    )
    succeeded_today = (
        db.query(func.count(Run.id)).filter(*today_base, Run.status == "succeeded").scalar() or 0
    )
    failed_today = (
        db.query(func.count(Run.id)).filter(*today_base, Run.status == "failed").scalar() or 0
    )
    cancelled_today = (
        db.query(func.count(Run.id)).filter(*today_base, Run.status == "cancelled").scalar() or 0
    )
    dry_run_count = (
        db.query(func.count(Run.id)).filter(*today_base, Run.mode == "dry_run").scalar() or 0
    )
    run_stats_today = HomeRunStatsTodaySection(
        created=int(created),
        queued=int(queued_today),
        running=int(running_today),
        succeeded=int(succeeded_today),
        failed=int(failed_today),
        cancelled=int(cancelled_today),
        dry_run_count=int(dry_run_count),
    )

    jq_queued = (
        db.query(func.count(Job.id)).filter(Job.space_id == space_id, Job.status == "pending").scalar() or 0
    )
    jq_running = (
        db.query(func.count(Job.id))
        .filter(Job.space_id == space_id, Job.status.in_(("claimed", "running")))
        .scalar()
        or 0
    )
    jq_failed = (
        db.query(func.count(Job.id)).filter(Job.space_id == space_id, Job.status == "failed").scalar() or 0
    )
    retryable = (
        db.query(func.count(Job.id))
        .filter(
            Job.space_id == space_id,
            Job.status == "failed",
            Job.attempts < Job.max_attempts,
        )
        .scalar()
        or 0
    )
    err_row = (
        db.query(Job.error)
        .filter(Job.space_id == space_id, Job.status == "failed", Job.error.isnot(None))
        .order_by(Job.updated_at.desc())
        .limit(1)
        .scalar()
    )
    job_queue_status = HomeJobQueueStatusSection(
        queued=int(jq_queued),
        running=int(jq_running),
        failed=int(jq_failed),
        retryable=int(retryable),
        recent_error_preview=_clip(err_row, 240) if err_row else None,
    )

    # Intake summary
    open_intake = (
        db.query(func.count(IntakeItem.id))
        .filter(
            IntakeItem.space_id == space_id,
            IntakeItem.status.in_(("new", "triaged", "selected")),
            IntakeItem.deleted_at.is_(None),
        )
        .scalar()
        or 0
    )
    new_intake_today = (
        db.query(func.count(IntakeItem.id))
        .filter(
            IntakeItem.space_id == space_id,
            IntakeItem.created_at >= day_start,
            IntakeItem.created_at < day_end,
            IntakeItem.deleted_at.is_(None),
        )
        .scalar()
        or 0
    )
    pending_extract_jobs = (
        db.query(func.count(ExtractionJob.id))
        .filter(ExtractionJob.space_id == space_id, ExtractionJob.status == "pending")
        .scalar()
        or 0
    )
    failed_extract_jobs = (
        db.query(func.count(ExtractionJob.id))
        .filter(ExtractionJob.space_id == space_id, ExtractionJob.status == "failed")
        .scalar()
        or 0
    )
    candidate_ev = (
        db.query(func.count(ExtractedEvidence.id))
        .filter(
            ExtractedEvidence.space_id == space_id,
            ExtractedEvidence.status == "candidate",
            ExtractedEvidence.deleted_at.is_(None),
        )
        .scalar()
        or 0
    )
    active_ev = (
        db.query(func.count(ExtractedEvidence.id))
        .filter(
            ExtractedEvidence.space_id == space_id,
            ExtractedEvidence.status == "active",
            ExtractedEvidence.deleted_at.is_(None),
        )
        .scalar()
        or 0
    )
    due_conn = (
        db.query(func.count(SourceConnection.id))
        .filter(
            SourceConnection.space_id == space_id,
            SourceConnection.status == "active",
            SourceConnection.next_check_at.isnot(None),
            SourceConnection.next_check_at <= now,
            SourceConnection.deleted_at.is_(None),
        )
        .scalar()
        or 0
    )
    intake_summary = HomeIntakeSummarySection(
        open_items=int(open_intake),
        new_items_today=int(new_intake_today),
        pending_extraction_jobs=int(pending_extract_jobs),
        failed_extraction_jobs=int(failed_extract_jobs),
        candidate_evidence=int(candidate_ev),
        active_evidence=int(active_ev),
        due_connections=int(due_conn),
    )

    runtime_status = _runtime_section(db, space_id)
    model_provider_status = _model_provider_section(db, space_id)
    suggested = _suggested_actions(
        pending_proposals=pending_count,
        failed_today=int(failed_today),
        needs_review_tasks=needs_review_count,
        real_adapters=runtime_status.real_adapters_configured_count,
        enabled_providers=model_provider_status.enabled_model_providers_count,
        raw_activities=int(raw_count),
        open_intake_items=int(open_intake),
        pending_extraction_jobs=int(pending_extract_jobs),
        failed_extraction_jobs=int(failed_extract_jobs),
        candidate_evidence=int(candidate_ev),
        due_connections=int(due_conn),
    )

    return HomeSummaryOut(
        recent_runs=[_run_to_item(r) for r in recent_rows],
        active_runs=[_run_to_item(r) for r in active_rows],
        pending_proposals=HomePendingProposalsSection(count=pending_count, items=pending_items),
        recent_artifacts=recent_artifacts,
        task_summary=task_summary,
        active_tasks=active_tasks,
        activity_summary=activity_summary,
        run_stats_today=run_stats_today,
        job_queue_status=job_queue_status,
        runtime_status=runtime_status,
        model_provider_status=model_provider_status,
        suggested_actions=suggested,
        intake_summary=intake_summary,
    )
