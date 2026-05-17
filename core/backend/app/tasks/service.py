from __future__ import annotations

from datetime import UTC, datetime
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session, joinedload
from ulid import ULID

from app.models import (
    Agent,
    Artifact,
    Board,
    Proposal,
    Run,
    Task,
    TaskArtifact,
    TaskProposal,
    TaskRun,
    Workspace,
)
from app.runs.run_service import RunService
from app.schemas import RunCreate, TaskCreate, TaskRunCreateBody, TaskUpdate

from .board_service import BoardService


def _new_id() -> str:
    return str(ULID())


def _can_read_task(task: Task, current_user_id: str) -> bool:
    """Visibility rule for tasks.

    space_shared: any space member can read (space-scoped API enforces space boundary).
    private / restricted: readable by created_by_user_id, assigned_user_id, or claimed_by_user_id.
    unknown: fail closed.
    """
    vis = (task.visibility or "space_shared").lower()
    if vis == "space_shared":
        return True
    if vis in ("private", "restricted"):
        return any(
            uid and uid == current_user_id
            for uid in (task.created_by_user_id, task.assigned_user_id, task.claimed_by_user_id)
        )
    return False


class TaskService:
    """Product-level Task board CRUD and Run linkage (not infrastructure Job rows).

    **Task ↔ Run source of truth:** rows in ``task_runs`` (``TaskRun``) are canonical.
    ``Run.task_id`` is an optional denormalized shortcut (primary task hint) for
    logging and read-model helpers; it must not be the only column used to enumerate
    runs for a task. ``list_task_runs`` always queries ``TaskRun``.
    """

    def __init__(self, db: Session):
        self.db = db
        self._boards = BoardService(db)

    def _validate_workspace(self, workspace_id: str, space_id: str) -> None:
        ws = self.db.query(Workspace).filter(Workspace.id == workspace_id).first()
        if not ws:
            raise HTTPException(status_code=400, detail=f"Workspace '{workspace_id}' not found")
        if ws.space_id != space_id:
            raise HTTPException(
                status_code=400,
                detail=f"Workspace '{workspace_id}' does not belong to this space",
            )

    def _validate_board_and_column(
        self,
        space_id: str,
        board_id: Optional[str],
        column_id: Optional[str],
    ) -> None:
        if column_id and not board_id:
            raise HTTPException(status_code=400, detail="column_id requires board_id")
        if board_id:
            b = (
                self.db.query(Board)
                .filter(Board.id == board_id, Board.space_id == space_id, Board.deleted_at.is_(None))
                .first()
            )
            if not b:
                raise HTTPException(status_code=400, detail="Board not found in this space")
            if column_id:
                self._boards.resolve_column(column_id, board_id, space_id)

    def create(self, data: TaskCreate, space_id: str, user_id: str) -> Task:
        if data.workspace_id:
            self._validate_workspace(data.workspace_id, space_id)
        self._validate_board_and_column(space_id, data.board_id, data.column_id)
        task = Task(
            id=_new_id(),
            space_id=space_id,
            workspace_id=data.workspace_id,
            board_id=data.board_id,
            column_id=data.column_id,
            parent_task_id=data.parent_task_id,
            title=data.title,
            description=data.description,
            task_type=data.task_type,
            status=data.status,
            priority=data.priority,
            risk_level=data.risk_level,
            created_by_user_id=user_id,
            assigned_user_id=data.assigned_user_id,
            assigned_agent_id=data.assigned_agent_id,
            source_activity_id=data.source_activity_id,
            source_run_id=data.source_run_id,
            source_proposal_id=data.source_proposal_id,
            source_artifact_id=data.source_artifact_id,
            acceptance_criteria_json=data.acceptance_criteria_json,
            definition_of_done=data.definition_of_done,
            required_outputs_json=data.required_outputs_json,
            due_at=data.due_at,
            start_after=data.start_after,
            max_runs=data.max_runs,
            max_cost=data.max_cost,
            max_duration_seconds=data.max_duration_seconds,
            policy_json=data.policy_json,
            metadata_json=data.metadata_json,
            tags=data.tags,
        )
        self.db.add(task)
        self.db.commit()
        self.db.refresh(task)
        return task

    def get(self, task_id: str, space_id: str, *, user_id: str | None = None) -> Task:
        task = (
            self.db.query(Task)
            .filter(Task.id == task_id, Task.space_id == space_id, Task.deleted_at.is_(None))
            .first()
        )
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        if user_id is not None and not _can_read_task(task, user_id):
            raise HTTPException(status_code=404, detail="Task not found")
        return task

    def list_tasks(
        self,
        space_id: str,
        *,
        board_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
        user_id: str | None = None,
    ) -> tuple[int, list[Task]]:
        q = self.db.query(Task).filter(Task.space_id == space_id, Task.deleted_at.is_(None))
        if board_id:
            q = q.filter(Task.board_id == board_id)
        rows = q.order_by(Task.updated_at.desc()).all()
        if user_id is not None:
            rows = [t for t in rows if _can_read_task(t, user_id)]
        total = len(rows)
        return total, rows[offset : offset + limit]

    def update(self, task_id: str, space_id: str, data: TaskUpdate) -> Task:
        task = self.get(task_id, space_id)
        payload = data.model_dump(exclude_unset=True)
        if "workspace_id" in payload and payload["workspace_id"]:
            self._validate_workspace(payload["workspace_id"], space_id)
        new_board = payload.get("board_id", task.board_id)
        new_column = payload.get("column_id", task.column_id)
        if "board_id" in payload or "column_id" in payload:
            self._validate_board_and_column(space_id, new_board, new_column)
        for key, value in payload.items():
            setattr(task, key, value)
        task.updated_at = datetime.now(UTC)
        self.db.commit()
        self.db.refresh(task)
        return task

    # ------------------------------------------------------------------
    # Run creation (queued only; no jobs, no runtime)
    # ------------------------------------------------------------------

    def create_queued_run_for_task(
        self,
        task_id: str,
        space_id: str,
        user_id: str,
        body: TaskRunCreateBody,
    ) -> tuple[TaskRun, Run]:
        """Create a queued Run plus a ``TaskRun`` row. Sets ``Run.task_id`` only as a denormalized primary-task shortcut; ``TaskRun`` is authoritative."""
        task = self.get(task_id, space_id)
        agent_id = body.agent_id or task.assigned_agent_id
        if not agent_id:
            raise HTTPException(
                status_code=400,
                detail="agent_id is required when the task has no assigned_agent_id",
            )
        if task.assigned_agent_id and agent_id != task.assigned_agent_id:
            policy = task.policy_json or {}
            if not policy.get("allow_assigned_agent_override"):
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "agent_id does not match task.assigned_agent_id; "
                        "set task.policy_json.allow_assigned_agent_override to true to override"
                    ),
                )
        if task.max_runs is not None:
            n_task_runs = (
                self.db.query(TaskRun)
                .filter(TaskRun.task_id == task.id, TaskRun.space_id == space_id)
                .count()
            )
            if n_task_runs >= task.max_runs:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Task max_runs ({task.max_runs}) reached; "
                        "cannot create another TaskRun for this task"
                    ),
                )
        agent = self.db.query(Agent).filter(Agent.id == agent_id, Agent.space_id == space_id).first()
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found in this space")

        ws_id = body.workspace_id if body.workspace_id is not None else task.workspace_id
        run_svc = RunService(self.db)
        run = run_svc.create_run(
            agent_id=agent_id,
            data=RunCreate(
                mode=body.mode,
                run_type=body.run_type,
                trigger_origin=body.trigger_origin,
                session_id=body.session_id,
                workspace_id=ws_id,
                prompt=body.prompt,
                instruction=body.instruction,
                parent_run_id=body.parent_run_id,
                instructed_by_agent_id=body.instructed_by_agent_id,
                adapter_type=body.adapter_type,
            ),
            space_id=space_id,
            user_id=user_id,
        )
        # Denormalized primary-task hint only; TaskRun row below is canonical.
        run.task_id = task.id
        if body.prompt is None and task.description:
            run.prompt = task.description
        elif body.prompt is None:
            run.prompt = task.title

        link = TaskRun(
            id=_new_id(),
            space_id=space_id,
            task_id=task.id,
            run_id=run.id,
            role="primary",
        )
        self.db.add(link)
        if body.set_task_in_progress:
            task.status = "in_progress"
            task.updated_at = datetime.now(UTC)
        self.db.commit()
        self.db.refresh(link)
        self.db.refresh(run)
        return link, run

    def list_task_runs(
        self,
        task_id: str,
        space_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[int, list[TaskRun], list[Run]]:
        """List runs for a task via ``task_runs`` only (never ``Run.task_id`` filter)."""
        self.get(task_id, space_id)
        q = self.db.query(TaskRun).filter(TaskRun.task_id == task_id, TaskRun.space_id == space_id)
        total = q.count()
        links = q.order_by(TaskRun.created_at.desc()).offset(offset).limit(limit).all()
        run_ids = [l.run_id for l in links]
        if not run_ids:
            return total, links, []
        runs_by_id = {
            r.id: r
            for r in self.db.query(Run).filter(Run.id.in_(run_ids), Run.space_id == space_id).all()
        }
        return total, links, [runs_by_id[l.run_id] for l in links if l.run_id in runs_by_id]

    def list_task_artifacts(
        self,
        task_id: str,
        space_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[int, list[TaskArtifact]]:
        self.get(task_id, space_id)
        q = (
            self.db.query(TaskArtifact)
            .options(joinedload(TaskArtifact.artifact))
            .filter(
                TaskArtifact.task_id == task_id,
                TaskArtifact.space_id == space_id,
            )
        )
        total = q.count()
        items = q.order_by(TaskArtifact.created_at.desc()).offset(offset).limit(limit).all()
        return total, items

    def list_task_proposals(
        self,
        task_id: str,
        space_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[int, list[TaskProposal]]:
        self.get(task_id, space_id)
        q = (
            self.db.query(TaskProposal)
            .options(joinedload(TaskProposal.proposal))
            .filter(
                TaskProposal.task_id == task_id,
                TaskProposal.space_id == space_id,
            )
        )
        total = q.count()
        items = q.order_by(TaskProposal.created_at.desc()).offset(offset).limit(limit).all()
        return total, items

    # ------------------------------------------------------------------
    # Manual link helpers (for future workers / background runners)
    # ------------------------------------------------------------------

    def link_task_to_run(
        self,
        *,
        space_id: str,
        task_id: str,
        run_id: str,
        role: str = "primary",
    ) -> TaskRun:
        """Insert canonical ``TaskRun``. If ``role`` is ``primary``, also set ``Run.task_id`` shortcut."""
        self.get(task_id, space_id)
        run = self.db.query(Run).filter(Run.id == run_id, Run.space_id == space_id).first()
        if not run:
            raise HTTPException(status_code=400, detail="Run not found in this space")
        link = TaskRun(
            id=_new_id(),
            space_id=space_id,
            task_id=task_id,
            run_id=run_id,
            role=role,
        )
        self.db.add(link)
        if role == "primary":
            run.task_id = task_id
        self.db.commit()
        self.db.refresh(link)
        if role == "primary":
            self.db.refresh(run)
        return link

    def link_task_to_artifact(
        self,
        *,
        space_id: str,
        task_id: str,
        artifact_id: str,
        role: str = "output",
    ) -> TaskArtifact:
        self.get(task_id, space_id)
        art = self.db.query(Artifact).filter(Artifact.id == artifact_id, Artifact.space_id == space_id).first()
        if not art:
            raise HTTPException(status_code=400, detail="Artifact not found in this space")
        row = TaskArtifact(
            id=_new_id(),
            space_id=space_id,
            task_id=task_id,
            artifact_id=artifact_id,
            role=role,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def link_task_to_proposal(
        self,
        *,
        space_id: str,
        task_id: str,
        proposal_id: str,
        role: str = "main_change",
    ) -> TaskProposal:
        self.get(task_id, space_id)
        prop = self.db.query(Proposal).filter(Proposal.id == proposal_id, Proposal.space_id == space_id).first()
        if not prop:
            raise HTTPException(status_code=400, detail="Proposal not found in this space")
        row = TaskProposal(
            id=_new_id(),
            space_id=space_id,
            task_id=task_id,
            proposal_id=proposal_id,
            role=role,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row
