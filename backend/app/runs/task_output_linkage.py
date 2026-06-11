"""Canonical TaskRun-based linkage for run outputs."""

from __future__ import annotations
import uuid

from sqlalchemy.orm import Session

from ..models import Artifact, Proposal, Run, TaskArtifact, TaskProposal, TaskRun


def _new_id() -> str:
    return str(uuid.uuid4())


def link_run_outputs_to_tasks(
    db: Session,
    *,
    run: Run,
    artifact: Artifact | None = None,
    proposal: Proposal | None = None,
    proposal_role: str = "memory_update",
) -> None:
    """Attach produced artifact / proposal to every task linked via ``TaskRun``."""

    task_run_rows = (
        db.query(TaskRun)
        .filter(
            TaskRun.run_id == run.id,
            TaskRun.space_id == run.space_id,
        )
        .all()
    )
    for tr in task_run_rows:
        if artifact is not None:
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
        if proposal is not None:
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
                        role=proposal_role,
                    )
                )
    if task_run_rows:
        db.flush()
