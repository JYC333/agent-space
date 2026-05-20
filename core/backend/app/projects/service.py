"""Project service — CRUD, workspace linking, and summary counts."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import (
    ActivityRecord,
    Artifact,
    MemoryEntry,
    Project,
    ProjectWorkspace,
    Proposal,
    Run,
    Workspace,
)
from ..schemas import (
    ProjectCreate,
    ProjectSummaryOut,
    ProjectUpdate,
    ProjectWorkspaceLinkCreate,
)


def _now() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    from ulid import ULID
    return str(ULID())


def assert_project_in_space(
    db: Session,
    project_id: str | None,
    space_id: str,
) -> None:
    """Validate that project_id (when non-null) belongs to space_id and is not deleted.

    Call this in any service that accepts project_id as an optional input before
    persisting runs, activities, artifacts, proposals, or memory entries.
    Raises ValueError on any violation so the caller can surface a 400/422.
    project_id=None is always valid — the FK column is intentionally nullable.
    """
    if project_id is None:
        return
    row = (
        db.query(Project)
        .filter(
            Project.id == project_id,
            Project.space_id == space_id,
            Project.deleted_at.is_(None),
        )
        .first()
    )
    if row is None:
        raise ValueError(
            f"project_id '{project_id}' not found in space '{space_id}' or has been deleted"
        )


class ProjectService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Project CRUD
    # ------------------------------------------------------------------

    def create(
        self,
        space_id: str,
        data: ProjectCreate,
        *,
        created_by_user_id: str | None = None,
        commit: bool = True,
    ) -> Project:
        owner = data.owner_user_id or created_by_user_id
        duplicate = (
            self.db.query(Project)
            .filter(
                Project.space_id == space_id,
                Project.name == data.name.strip(),
                Project.status == "active",
                Project.deleted_at.is_(None),
            )
            .first()
        )
        if duplicate:
            raise ValueError(f"An active project named '{data.name.strip()}' already exists in this space")

        row = Project(
            id=_new_id(),
            space_id=space_id,
            owner_user_id=owner,
            name=data.name.strip(),
            description=data.description,
            status="active",
            current_focus=data.current_focus,
            settings_json=data.settings_json,
        )
        self.db.add(row)
        self.db.flush()
        if commit:
            self.db.commit()
            self.db.refresh(row)
        return row

    def list_projects(
        self,
        space_id: str,
        *,
        status: str = "active",
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[int, list[Project]]:
        q = self.db.query(Project).filter(
            Project.space_id == space_id,
            Project.deleted_at.is_(None),
        )
        if status:
            q = q.filter(Project.status == status)
        total = q.with_entities(func.count(Project.id)).scalar() or 0
        rows = q.order_by(Project.updated_at.desc()).offset(offset).limit(limit).all()
        return total, rows

    def get(self, project_id: str, space_id: str) -> Project | None:
        return (
            self.db.query(Project)
            .filter(
                Project.id == project_id,
                Project.space_id == space_id,
                Project.deleted_at.is_(None),
            )
            .first()
        )

    def update(
        self,
        project_id: str,
        space_id: str,
        data: ProjectUpdate,
        *,
        commit: bool = True,
    ) -> Project | None:
        row = self.get(project_id, space_id)
        if row is None:
            return None
        if data.name is not None:
            new_name = data.name.strip()
            if new_name != row.name:
                duplicate = (
                    self.db.query(Project)
                    .filter(
                        Project.space_id == space_id,
                        Project.name == new_name,
                        Project.status == "active",
                        Project.deleted_at.is_(None),
                        Project.id != project_id,
                    )
                    .first()
                )
                if duplicate:
                    raise ValueError(f"An active project named '{new_name}' already exists in this space")
            row.name = new_name
        if data.description is not None:
            row.description = data.description
        if data.current_focus is not None:
            row.current_focus = data.current_focus
        if data.settings_json is not None:
            row.settings_json = data.settings_json
        if data.status is not None:
            row.status = data.status
        self.db.flush()
        if commit:
            self.db.commit()
            self.db.refresh(row)
        return row

    def archive(
        self,
        project_id: str,
        space_id: str,
        *,
        commit: bool = True,
    ) -> Project | None:
        row = self.get(project_id, space_id)
        if row is None:
            return None
        row.status = "archived"
        row.archived_at = _now()
        self.db.flush()
        if commit:
            self.db.commit()
            self.db.refresh(row)
        return row

    # ------------------------------------------------------------------
    # Workspace linking
    # ------------------------------------------------------------------

    def link_workspace(
        self,
        project_id: str,
        space_id: str,
        data: ProjectWorkspaceLinkCreate,
        *,
        commit: bool = True,
    ) -> ProjectWorkspace:
        project = self.get(project_id, space_id)
        if project is None:
            raise ValueError("Project not found")

        workspace = (
            self.db.query(Workspace)
            .filter(
                Workspace.id == data.workspace_id,
                Workspace.space_id == space_id,
            )
            .first()
        )
        if workspace is None:
            raise ValueError("Workspace not found in this space")

        existing = (
            self.db.query(ProjectWorkspace)
            .filter(
                ProjectWorkspace.project_id == project_id,
                ProjectWorkspace.workspace_id == data.workspace_id,
                ProjectWorkspace.role == data.role,
            )
            .first()
        )
        if existing:
            raise ValueError(
                f"Workspace already linked to this project with role '{data.role}'"
            )

        link = ProjectWorkspace(
            id=_new_id(),
            project_id=project_id,
            workspace_id=data.workspace_id,
            role=data.role,
        )
        self.db.add(link)
        self.db.flush()
        if commit:
            self.db.commit()
            self.db.refresh(link)
        return link

    def unlink_workspace(
        self,
        project_id: str,
        workspace_id: str,
        space_id: str,
        *,
        role: str | None = None,
        commit: bool = True,
    ) -> bool:
        project = self.get(project_id, space_id)
        if project is None:
            return False
        q = self.db.query(ProjectWorkspace).filter(
            ProjectWorkspace.project_id == project_id,
            ProjectWorkspace.workspace_id == workspace_id,
        )
        if role is not None:
            q = q.filter(ProjectWorkspace.role == role)
        rows = q.all()
        if not rows:
            return False
        for row in rows:
            self.db.delete(row)
        self.db.flush()
        if commit:
            self.db.commit()
        return True

    def list_workspaces(
        self, project_id: str, space_id: str
    ) -> list[ProjectWorkspace]:
        project = self.get(project_id, space_id)
        if project is None:
            return []
        return (
            self.db.query(ProjectWorkspace)
            .filter(ProjectWorkspace.project_id == project_id)
            .order_by(ProjectWorkspace.created_at.asc())
            .all()
        )

    def list_projects_for_workspace(
        self, workspace_id: str, space_id: str
    ) -> list[ProjectWorkspace]:
        workspace = (
            self.db.query(Workspace)
            .filter(Workspace.id == workspace_id, Workspace.space_id == space_id)
            .first()
        )
        if workspace is None:
            return []
        return (
            self.db.query(ProjectWorkspace)
            .join(Project, ProjectWorkspace.project_id == Project.id)
            .filter(
                ProjectWorkspace.workspace_id == workspace_id,
                Project.space_id == space_id,
                Project.deleted_at.is_(None),
            )
            .order_by(ProjectWorkspace.created_at.asc())
            .all()
        )

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def get_summary(self, project_id: str, space_id: str) -> ProjectSummaryOut | None:
        project = self.get(project_id, space_id)
        if project is None:
            return None

        activity_count = (
            self.db.query(func.count(ActivityRecord.id))
            .filter(
                ActivityRecord.space_id == space_id,
                ActivityRecord.project_id == project_id,
            )
            .scalar() or 0
        )
        artifact_count = (
            self.db.query(func.count(Artifact.id))
            .filter(
                Artifact.space_id == space_id,
                Artifact.project_id == project_id,
            )
            .scalar() or 0
        )
        pending_proposal_count = (
            self.db.query(func.count(Proposal.id))
            .filter(
                Proposal.space_id == space_id,
                Proposal.project_id == project_id,
                Proposal.status == "pending",
            )
            .scalar() or 0
        )
        workspace_count = (
            self.db.query(func.count(ProjectWorkspace.id))
            .filter(ProjectWorkspace.project_id == project_id)
            .scalar() or 0
        )
        active_run_count = (
            self.db.query(func.count(Run.id))
            .filter(
                Run.space_id == space_id,
                Run.project_id == project_id,
                Run.status.in_(["queued", "running"]),
            )
            .scalar() or 0
        )
        memory_entry_count = (
            self.db.query(func.count(MemoryEntry.id))
            .filter(
                MemoryEntry.space_id == space_id,
                MemoryEntry.project_id == project_id,
                MemoryEntry.deleted_at.is_(None),
            )
            .scalar() or 0
        )

        return ProjectSummaryOut(
            project_id=project_id,
            activity_count=activity_count,
            artifact_count=artifact_count,
            pending_proposal_count=pending_proposal_count,
            workspace_count=workspace_count,
            active_run_count=active_run_count,
            memory_entry_count=memory_entry_count,
        )
