from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Float,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, synonym

from .db import Base


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(UTC)


def _uuid() -> str:
    return str(uuid.uuid4())


UUID_COL = String(36)
SPACE_COL = String(36)


# ---------------------------------------------------------------------------
# Space, users, membership, and auth support
# ---------------------------------------------------------------------------


class Space(Base):
    """Top-level permission and collaboration boundary.

    space_id currently serves four roles across the system:
      1. Ownership anchor  — every object (Memory, Run, Session, Task, …) belongs to one space.
      2. Access filter     — MemoryRetriever and MemoryStore enforce space_id as a hard filter.
      3. UI scope          — the frontend renders one active space at a time via SpaceContext.
      4. Execution boundary — ContextBuilder reads memory only from the run's space_id.

    Target model: keep Space as the permission/collaboration boundary while making view and
    execution semantics explicit over time (PersonalView, ExecutionContext — see
    docs/TARGET_VIEW_MODEL.md). A personal space has exactly one member: the owner.
    """

    __tablename__ = "spaces"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False, default="personal")
    # No DB FK: Space and User bootstrap each other in personal-mode setup.
    created_by_user_id: Mapped[Optional[str]] = mapped_column(UUID_COL, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

    users: Mapped[list["User"]] = relationship("User", back_populates="space")
    memberships: Mapped[list["SpaceMembership"]] = relationship("SpaceMembership", back_populates="space")
    agents: Mapped[list["Agent"]] = relationship("Agent", back_populates="space")
    workspaces: Mapped[list["Workspace"]] = relationship("Workspace", back_populates="space")
    execution_planes: Mapped[list["ExecutionPlane"]] = relationship(
        "ExecutionPlane", back_populates="space", foreign_keys="ExecutionPlane.space_id"
    )

    __table_args__ = (
        CheckConstraint("type in ('personal', 'household', 'team')", name="ck_spaces_type"),
    )


class User(Base):
    """Human identity. Space membership can also be represented in SpaceMembership."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    space_id: Mapped[Optional[str]] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=True, index=True)
    email: Mapped[Optional[str]] = mapped_column(String(256), nullable=True, unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(256), nullable=False)
    avatar_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="member")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)
    default_space_id: Mapped[Optional[str]] = mapped_column(SPACE_COL, nullable=True)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

    space: Mapped[Optional[Space]] = relationship("Space", back_populates="users", foreign_keys=[space_id])
    memberships: Mapped[list["SpaceMembership"]] = relationship("SpaceMembership", back_populates="user")


class SpaceMembership(Base):
    __tablename__ = "space_memberships"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(UUID_COL, ForeignKey("users.id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="member")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

    space: Mapped[Space] = relationship("Space", back_populates="memberships")
    user: Mapped[User] = relationship("User", back_populates="memberships")

    __table_args__ = (UniqueConstraint("space_id", "user_id", name="uq_space_memberships_space_user"),)


class AuthAccount(Base):
    """Auth provider link. No space_id because it belongs to global human identity."""

    __tablename__ = "auth_accounts"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(UUID_COL, ForeignKey("users.id"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_user_id: Mapped[str] = mapped_column(String(256), nullable=False)
    email: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)

    __table_args__ = (UniqueConstraint("provider", "provider_user_id", name="uq_auth_accounts_provider_user"),)


class UserSession(Base):
    """Server auth session. No space_id because it authenticates a global user."""

    __tablename__ = "user_sessions"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(UUID_COL, ForeignKey("users.id"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class SpaceInvitation(Base):
    __tablename__ = "space_invitations"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=False, index=True)
    invited_email: Mapped[str] = mapped_column(String(256), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="member")
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    invited_by_user_id: Mapped[str] = mapped_column(UUID_COL, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# ---------------------------------------------------------------------------
# Workspace
# ---------------------------------------------------------------------------


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    root_path: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    repo_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

    # Service-layer fields used today; WorkspaceManager/PathPolicy govern file access.
    # remain responsible for governing future file access.
    created_by_user_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("users.id"), nullable=True)
    slug: Mapped[Optional[str]] = mapped_column(String(256), nullable=True, index=True)
    workspace_type: Mapped[str] = mapped_column(String(32), nullable=False, default="project")
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="project")
    default_branch: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    visibility: Mapped[str] = mapped_column(String(32), nullable=False, default="private")
    protected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    system_managed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    registered_from: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    owner_space_id = synonym("space_id")

    space: Mapped[Space] = relationship("Space", back_populates="workspaces")
    profile: Mapped[Optional["WorkspaceProfile"]] = relationship(
        "WorkspaceProfile", back_populates="workspace", uselist=False, foreign_keys="WorkspaceProfile.workspace_id"
    )


# ---------------------------------------------------------------------------
# Project — goal/knowledge/context boundary
# ---------------------------------------------------------------------------


class Project(Base):
    """Goal-oriented knowledge and activity container.

    A Project organises activities, artifacts, proposals, runs, and linked
    workspaces around a long-lived objective. It is a stable ownership/context
    boundary — not a task manager or execution environment.

    Workspace is the file/execution/sandbox boundary.
    Project is the goal/knowledge boundary.
    A Project can link to many Workspaces; a Workspace can serve many Projects.
    """

    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=False, index=True)
    owner_user_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("users.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)
    current_focus: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    settings_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    space: Mapped["Space"] = relationship("Space")
    owner: Mapped[Optional["User"]] = relationship("User", foreign_keys=[owner_user_id])
    workspace_links: Mapped[list["ProjectWorkspace"]] = relationship(
        "ProjectWorkspace", back_populates="project", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "status in ('active', 'archived', 'deleted')",
            name="ck_projects_status",
        ),
    )


class ProjectWorkspace(Base):
    """M:N association between a Project and a Workspace.

    The ``role`` column captures how the Workspace serves the Project
    (e.g. primary code execution vs. docs vs. reference).
    Cross-space links are rejected at the service layer.
    """

    __tablename__ = "project_workspaces"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(UUID_COL, ForeignKey("projects.id"), nullable=False, index=True)
    workspace_id: Mapped[str] = mapped_column(UUID_COL, ForeignKey("workspaces.id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(64), nullable=False, default="reference")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

    project: Mapped["Project"] = relationship("Project", back_populates="workspace_links")
    workspace: Mapped["Workspace"] = relationship("Workspace")

    __table_args__ = (
        CheckConstraint(
            "role in ('primary_codebase', 'capability_library', 'docs', 'data', 'deployment', 'reference')",
            name="ck_project_workspaces_role",
        ),
        UniqueConstraint(
            "project_id", "workspace_id", "role",
            name="uq_project_workspaces_project_workspace_role",
        ),
    )


# ---------------------------------------------------------------------------
# Runtime configuration
# ---------------------------------------------------------------------------


class Credential(Base):
    __tablename__ = "credentials"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    credential_type: Mapped[str] = mapped_column(String(64), nullable=False)
    secret_ref: Mapped[str] = mapped_column(Text, nullable=False)
    scopes_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)



class ModelProvider(Base):
    __tablename__ = "model_providers"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    provider_type: Mapped[str] = mapped_column(String(64), nullable=False)
    base_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    default_model: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    credential_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("credentials.id"), nullable=True, index=True)
    capabilities_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    config_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

    credential: Mapped[Optional[Credential]] = relationship("Credential")



class ExecutionPlane(Base):
    """Where a run executes: native, local CLI, remote vendor, or manual import.

    Captures trust, observability, data-exposure, and credential semantics
    for each execution environment. Runtime adapters are attached to a plane.
    """

    __tablename__ = "execution_planes"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    execution_location: Mapped[str] = mapped_column(String(32), nullable=False)
    runtime_origin: Mapped[str] = mapped_column(String(64), nullable=False)
    trust_level: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    observability_level: Mapped[str] = mapped_column(String(64), nullable=False, default="black_box")
    data_exposure_level: Mapped[str] = mapped_column(String(64), nullable=False, default="unknown")
    credential_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    config_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

    space: Mapped["Space"] = relationship("Space", back_populates="execution_planes", foreign_keys=[space_id])

    __table_args__ = (
        CheckConstraint(
            "type in ('native', 'local', 'remote_vendor', 'hybrid', 'manual')",
            name="ck_execution_planes_type",
        ),
        CheckConstraint(
            "provider in ('agent_space', 'openai', 'anthropic', 'opencode', 'cursor', 'other')",
            name="ck_execution_planes_provider",
        ),
        CheckConstraint(
            "execution_location in ('local', 'remote', 'hybrid', 'manual')",
            name="ck_execution_planes_execution_location",
        ),
        CheckConstraint(
            "runtime_origin in ('native', 'external_vendor', 'open_source_external', 'manual')",
            name="ck_execution_planes_runtime_origin",
        ),
        CheckConstraint(
            "trust_level in ('high', 'medium', 'low', 'unknown')",
            name="ck_execution_planes_trust_level",
        ),
        CheckConstraint(
            "observability_level in ('full_trace', 'structured_events', 'artifacts_only', 'final_output_only', 'black_box')",
            name="ck_execution_planes_observability_level",
        ),
        CheckConstraint(
            "data_exposure_level in ('local_only', 'model_provider', 'vendor_platform', 'third_party_tools', 'unknown')",
            name="ck_execution_planes_data_exposure_level",
        ),
        CheckConstraint(
            "credential_mode in ('agent_space_vault', 'vendor_account', 'user_local', 'none', 'unknown')",
            name="ck_execution_planes_credential_mode",
        ),
        UniqueConstraint("space_id", "name", name="uq_execution_planes_space_name"),
    )


class RuntimeAdapter(Base):
    __tablename__ = "runtime_adapters"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    adapter_type: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    provider_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("model_providers.id"), nullable=True, index=True)
    credential_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("credentials.id"), nullable=True, index=True)
    config_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    health_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    execution_plane_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("execution_planes.id"), nullable=True, index=True)
    capability_support_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

    provider: Mapped[Optional[ModelProvider]] = relationship("ModelProvider")
    credential: Mapped[Optional[Credential]] = relationship("Credential")
    execution_plane: Mapped[Optional[ExecutionPlane]] = relationship("ExecutionPlane")

    # Field name aliases for CLI adapter config API (adapter_id, display_name, quota_status).
    adapter_id = synonym("adapter_type")
    display_name = synonym("name")
    quota_status = synonym("health_status")

    @property
    def executable_path(self) -> Optional[str]:
        return (self.config_json or {}).get("executable_path")

    @executable_path.setter
    def executable_path(self, value: Optional[str]) -> None:
        from sqlalchemy.orm.attributes import flag_modified

        d = dict(self.config_json or {})
        if value is None:
            d.pop("executable_path", None)
        else:
            d["executable_path"] = value
        self.config_json = d
        flag_modified(self, "config_json")

    @property
    def default_mode(self) -> str:
        return (self.config_json or {}).get("default_mode", "headless")

    @default_mode.setter
    def default_mode(self, value: Optional[str]) -> None:
        from sqlalchemy.orm.attributes import flag_modified

        d = dict(self.config_json or {})
        if value is None:
            d.pop("default_mode", None)
        else:
            d["default_mode"] = value
        self.config_json = d
        flag_modified(self, "config_json")

    @property
    def notes(self) -> Optional[str]:
        return (self.config_json or {}).get("notes")

    @notes.setter
    def notes(self, value: Optional[str]) -> None:
        from sqlalchemy.orm.attributes import flag_modified

        d = dict(self.config_json or {})
        if value is None:
            d.pop("notes", None)
        else:
            d["notes"] = value
        self.config_json = d
        flag_modified(self, "config_json")


# ---------------------------------------------------------------------------
# Agents and immutable versions
# ---------------------------------------------------------------------------


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=False, index=True)
    owner_user_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("users.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    role_instruction: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)
    # Nullable convenience pointer. DB FK is intentionally omitted to avoid an
    # Agent <-> AgentVersion DDL cycle in the clean initial baseline; the
    # canonical immutable execution FK is Run.agent_version_id.
    current_version_id: Mapped[Optional[str]] = mapped_column(UUID_COL, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

    # Denormalized fields slated to move fully onto AgentVersion over time.
    visibility: Mapped[str] = mapped_column(String(32), nullable=False, default="private")
    created_by_user_id = synonym("owner_user_id")

    space: Mapped[Space] = relationship("Space", back_populates="agents")
    versions: Mapped[list["AgentVersion"]] = relationship(
        "AgentVersion",
        back_populates="agent",
        foreign_keys="AgentVersion.agent_id",
        cascade="all, delete-orphan",
    )
    runs: Mapped[list["Run"]] = relationship("Run", back_populates="agent", foreign_keys="Run.agent_id")

    __table_args__ = (
        CheckConstraint("status in ('active', 'inactive', 'archived', 'disabled')", name="ck_agents_status"),
    )


class AgentVersion(Base):
    __tablename__ = "agent_versions"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    agent_id: Mapped[str] = mapped_column(UUID_COL, ForeignKey("agents.id"), nullable=False, index=True)
    space_id: Mapped[str] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=False, index=True)
    version_label: Mapped[str] = mapped_column(String(64), nullable=False)
    model_provider_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("model_providers.id"), nullable=True, index=True)
    model_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    runtime_adapter_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("runtime_adapters.id"), nullable=True, index=True)
    system_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    model_config_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    runtime_config_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    context_policy_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    memory_policy_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    capabilities_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    tool_permissions_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    runtime_policy_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    agent: Mapped[Agent] = relationship("Agent", back_populates="versions", foreign_keys=[agent_id])
    model_provider: Mapped[Optional[ModelProvider]] = relationship("ModelProvider")
    runtime_adapter: Mapped[Optional[RuntimeAdapter]] = relationship("RuntimeAdapter")

    version = synonym("version_label")

    __table_args__ = (UniqueConstraint("agent_id", "version_label", name="uq_agent_versions_agent_label"),)


# ---------------------------------------------------------------------------
# Sessions and messages
# ---------------------------------------------------------------------------


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=False, index=True)
    user_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("users.id"), nullable=True, index=True)
    agent_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("agents.id"), nullable=True, index=True)
    workspace_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("workspaces.id"), nullable=True, index=True)
    title: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

    messages: Mapped[list["Message"]] = relationship("Message", back_populates="session", order_by="Message.created_at")
    runs: Mapped[list["Run"]] = relationship("Run", back_populates="session")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=False, index=True)
    session_id: Mapped[str] = mapped_column(UUID_COL, ForeignKey("sessions.id"), nullable=False, index=True)
    user_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("users.id"), nullable=True, index=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)

    session: Mapped[Session] = relationship("Session", back_populates="messages")

    __table_args__ = (
        CheckConstraint("role in ('user', 'assistant', 'system', 'tool')", name="ck_messages_role"),
    )


# ---------------------------------------------------------------------------
# Source pointers and immutable snapshots
# ---------------------------------------------------------------------------


class SourcePointer(Base):
    """Cross-space provenance pointer (metadata only).

    Records that an object in owner_space is derived from or references an object in
    source_space. This table must never store raw source content, summaries, or snapshots.
    access_mode values (read, subscribe, federated) describe future intent only — they do
    not grant read access. All source object reads remain subject to source-space membership,
    visibility, and policy checks (memory.cross_space_read stays deny-by-default).

    See docs/TARGET_VIEW_MODEL.md and docs/FEDERATED_ACCESS_MODEL.md.
    """

    __tablename__ = "source_pointers"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    owner_space_id: Mapped[str] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=False, index=True)
    source_space_id: Mapped[str] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=False)
    source_object_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_object_id: Mapped[str] = mapped_column(UUID_COL, nullable=False)
    access_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    granted_by_user_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("users.id"), nullable=True, index=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)

    __table_args__ = (
        CheckConstraint(
            "access_mode in ('read', 'subscribe', 'federated')",
            name="ck_source_pointers_access_mode",
        ),
        Index(
            "ix_source_pointers_source",
            "source_space_id",
            "source_object_type",
            "source_object_id",
        ),
    )


class Policy(Base):
    __tablename__ = "policies"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    domain: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    policy_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

    policy_key: Mapped[Optional[str]] = mapped_column(String(256), nullable=True, index=True)
    policy_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=text("1"))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", server_default=text("'active'"), index=True)
    enforcement_mode: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    rule_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    applies_to_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    # Soft self-reference: no DB FK to avoid DDL cycle with policy versioning bootstrap.
    supersedes_policy_id: Mapped[Optional[str]] = mapped_column(UUID_COL, nullable=True, index=True)
    # Soft reference to proposals: policies is created before proposals in migration order.
    # Service layer enforces referential validity (no DB FK to avoid DDL ordering cycle).
    created_from_proposal_id: Mapped[Optional[str]] = mapped_column(UUID_COL, nullable=True, index=True)

    __table_args__ = (
        CheckConstraint(
            "status in ('draft', 'active', 'superseded', 'disabled')",
            name="ck_policies_status",
        ),
        CheckConstraint(
            "enforcement_mode is null or enforcement_mode in ('allow', 'deny', 'require_approval', 'allow_with_log')",
            name="ck_policies_enforcement_mode",
        ),
    )


class ContextSnapshot(Base):
    __tablename__ = "context_snapshots"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=False, index=True)
    source_refs_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    compiled_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    token_estimate: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    relevant_period_start: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    relevant_period_end: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)

    # Compiled context fields: inline text + optional artifact-storage refs + content hashes.
    # Offloading to artifact storage (replacing inline text with *_ref) is not yet implemented.
    compiled_prefix_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    compiled_tail_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    compiled_prefix_ref: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    compiled_tail_ref: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    prefix_hash: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    tail_hash: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    compiler_version: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    retrieval_trace_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    token_budget_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    policy_bundle_version: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    memory_digest_version: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    workspace_digest_version: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # Runtime-facing context bundle fields. These represent the rendered context
    # sent to an external runtime (Codex, Claude Code, OpenCode, etc.).
    # target_runtime_adapter_id and execution_plane_id are soft references (no FK
    # constraint) because context_snapshots is seeded before runtime_adapters and
    # execution_planes in the migration order.
    target_runtime_adapter_id: Mapped[Optional[str]] = mapped_column(UUID_COL, nullable=True)
    execution_plane_id: Mapped[Optional[str]] = mapped_column(UUID_COL, nullable=True)
    included_memory_refs_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    included_file_refs_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    included_doc_refs_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    redactions_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    data_exposure_level: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    rendered_context_uri: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    # Prefer rendered_context_uri for large rendered contexts. Use rendered_context_text
    # only for small inline contexts or fallback/debug — large payloads bloat the row.
    rendered_context_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "data_exposure_level is null or data_exposure_level in ('local_only', 'model_provider', 'vendor_platform', 'third_party_tools', 'unknown')",
            name="ck_context_snapshots_data_exposure_level",
        ),
    )


# ---------------------------------------------------------------------------
# ContextDigest — derived cache of approved Memory/Policy context
# ---------------------------------------------------------------------------


class ContextDigest(Base):
    """Versioned digest cache for approved Memory/Policy sources.

    Digest is derived cache — not Memory, not Policy, not a source of truth.
    Digest does not create Proposal. Digest can be deleted and regenerated.
    Digests summarise active approved Memory/Policy content only.
    """

    __tablename__ = "context_digests"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=False, index=True)

    # Scope: what this digest covers
    scope_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    scope_id: Mapped[Optional[str]] = mapped_column(UUID_COL, nullable=True, index=True)

    # Digest classification
    digest_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=text("1"))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)

    # Rendered digest text
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Source traceability
    source_memory_ids_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    source_policy_ids_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    source_relation_ids_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)

    # Hashes for cache invalidation
    source_hash: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    content_hash: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    # Dirty tracking
    dirty_since: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    dirty_reason_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    dirty_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))

    # Generation metadata
    generated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_from_run_id: Mapped[Optional[str]] = mapped_column(UUID_COL, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

    __table_args__ = (
        CheckConstraint(
            "digest_type in ('policy_bundle', 'workspace', 'agent')",
            name="ck_context_digests_digest_type",
        ),
        CheckConstraint(
            "status in ('active', 'dirty', 'superseded', 'disabled')",
            name="ck_context_digests_status",
        ),
    )


# ---------------------------------------------------------------------------
# Runs, activities, artifacts, and proposals
# ---------------------------------------------------------------------------


class Run(Base):
    """A single agent execution. space_id is the execution boundary — the run reads memory only
    from this space. instructed_by_user_id flows into ContextBuilder as user_id, controlling
    which private memories are included (owner must match). A run in a shared space cannot
    access personal-space private memories even when the same user instructed both
    (intentional — see docs/TARGET_VIEW_MODEL.md § ExecutionContext). Cross-space authorization
    requires PersonalMemoryGrant — see docs/PERSONAL_MEMORY_GRANT.md.
    """

    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=False, index=True)
    agent_id: Mapped[str] = mapped_column(UUID_COL, ForeignKey("agents.id"), nullable=False, index=True)
    agent_version_id: Mapped[str] = mapped_column(UUID_COL, ForeignKey("agent_versions.id"), nullable=False, index=True)
    context_snapshot_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("context_snapshots.id"), nullable=True, index=True)
    workspace_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("workspaces.id"), nullable=True, index=True)
    session_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("sessions.id"), nullable=True, index=True)
    parent_run_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("runs.id"), nullable=True, index=True)
    instructed_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    instructed_by_user_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("users.id"), nullable=True, index=True)
    instructed_by_agent_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("agents.id"), nullable=True, index=True)
    delegation_depth: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    run_type: Mapped[str] = mapped_column(String(32), nullable=False, default="agent", index=True)
    trigger_origin: Mapped[str] = mapped_column(String(32), nullable=False, default="manual", index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued", index=True)
    mode: Mapped[str] = mapped_column(String(32), nullable=False, default="live", index=True)
    prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    instruction: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    scheduled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)
    model_provider_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("model_providers.id"), nullable=True, index=True)
    runtime_adapter_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("runtime_adapters.id"), nullable=True, index=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    output_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    usage_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Optional primary-task hint (``Task.id``). Intentionally no DB FK: ``runs`` is
    # created before ``tasks`` in the canonical migration, and SQLite cannot add this
    # FK later without a batch table rebuild. **Canonical Task↔Run linkage is
    # ``task_runs`` (TaskRun);** task board reads must use TaskRun, not this column alone.
    task_id: Mapped[Optional[str]] = mapped_column(UUID_COL, nullable=True, index=True)
    # Soft reference to Project.id. No DB FK (SQLite ALTER TABLE cannot add FK to existing
    # table without full rebuild). Project scoping is enforced at the service layer.
    project_id: Mapped[Optional[str]] = mapped_column(UUID_COL, nullable=True, index=True)
    user_id = synonym("instructed_by_user_id")
    cli_adapter_config_id = synonym("runtime_adapter_id")
    adapter_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    capability_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    model_selection_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="agent_space_provider")
    model_override_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    permission_snapshot_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    # Policy-derived minimum sandbox class for future real runtimes (no sandbox created here).
    required_sandbox_level: Mapped[str] = mapped_column(
        String(32), nullable=False, default="none", server_default=text("'none'")
    )
    sandbox_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    runtime_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    usage_accuracy: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    estimated_input_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    estimated_output_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    estimated_cost: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    exit_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    visibility: Mapped[str] = mapped_column(
        String(32), nullable=False, default="space_shared", server_default=text("'space_shared'")
    )
    # Safe marker set when ContextSnapshotPopulator resolves a PersonalMemoryGrant.
    # personal_grant_context_json stores only non-sensitive grant metadata (grant_id, access_mode,
    # memory_count, etc.) — never raw memory text, generated summary, or memory IDs.
    has_personal_grant_context: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    personal_grant_context_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Execution plane fields: where the run executed and at what trust/observability/exposure level.
    # observability_level, data_exposure_level, and trust_level are snapshots copied from the
    # execution plane at run creation time; they do not auto-update when the plane changes.
    execution_plane_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("execution_planes.id"), nullable=True, index=True)
    source: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    observability_level: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    data_exposure_level: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    trust_level: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    externality_level: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    completed_at = synonym("ended_at")
    output = synonym("output_json")
    error = synonym("error_message")

    agent: Mapped[Agent] = relationship("Agent", back_populates="runs", foreign_keys=[agent_id])
    agent_version: Mapped[AgentVersion] = relationship("AgentVersion")
    context_snapshot: Mapped[Optional[ContextSnapshot]] = relationship("ContextSnapshot", foreign_keys=[context_snapshot_id])
    session: Mapped[Optional[Session]] = relationship("Session", back_populates="runs")
    parent_run: Mapped[Optional["Run"]] = relationship("Run", remote_side="Run.id", foreign_keys=[parent_run_id])
    artifacts: Mapped[list["Artifact"]] = relationship("Artifact", back_populates="run")
    proposals: Mapped[list["Proposal"]] = relationship("Proposal", back_populates="created_by_run")
    activities: Mapped[list["ActivityRecord"]] = relationship("ActivityRecord", back_populates="source_run")
    steps: Mapped[list["RunStep"]] = relationship("RunStep", back_populates="run", order_by="RunStep.step_index")
    execution_plane: Mapped[Optional[ExecutionPlane]] = relationship("ExecutionPlane", foreign_keys=[execution_plane_id])
    external_run_records: Mapped[list["ExternalRunRecord"]] = relationship("ExternalRunRecord", back_populates="run")
    run_reflections: Mapped[list["RunReflection"]] = relationship("RunReflection", back_populates="run")

    __table_args__ = (
        CheckConstraint(
            "status in ('queued', 'running', 'succeeded', 'degraded', 'failed', 'cancelled', 'waiting_for_review')",
            name="ck_runs_status",
        ),
        CheckConstraint("mode in ('live', 'dry_run')", name="ck_runs_mode"),
        CheckConstraint(
            "run_type in ('agent', 'system', 'workflow', 'validation', 'reflection', 'export')",
            name="ck_runs_run_type",
        ),
        CheckConstraint(
            "trigger_origin in ('manual', 'automation', 'job', 'parent_run', 'system')",
            name="ck_runs_trigger_origin",
        ),
        CheckConstraint(
            "required_sandbox_level in ('none', 'dry_run', 'worktree', 'one_shot_docker')",
            name="ck_runs_required_sandbox_level",
        ),
        CheckConstraint(
            "source is null or source in ('managed', 'ide_assist', 'manual_import', 'remote_import', 'scheduled', 'webhook')",
            name="ck_runs_source",
        ),
        CheckConstraint(
            "externality_level is null or externality_level in ('native', 'local_external', 'remote_external', 'hybrid', 'manual')",
            name="ck_runs_externality_level",
        ),
        CheckConstraint(
            "observability_level is null or observability_level in ('full_trace', 'structured_events', 'artifacts_only', 'final_output_only', 'black_box')",
            name="ck_runs_observability_level",
        ),
        CheckConstraint(
            "data_exposure_level is null or data_exposure_level in ('local_only', 'model_provider', 'vendor_platform', 'third_party_tools', 'unknown')",
            name="ck_runs_data_exposure_level",
        ),
        CheckConstraint(
            "trust_level is null or trust_level in ('high', 'medium', 'low', 'unknown')",
            name="ck_runs_trust_level",
        ),
    )


class ActivityRecord(Base):
    __tablename__ = "activity_records"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=False, index=True)
    source_run_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("runs.id"), nullable=True, index=True)
    session_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("sessions.id"), nullable=True, index=True)
    user_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("users.id"), nullable=True, index=True)
    workspace_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("workspaces.id"), nullable=True, index=True)
    agent_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("agents.id"), nullable=True, index=True)
    # Soft reference only: ``tasks`` is created after ``activity_records`` and also
    # references ``activity_records`` via ``tasks.source_activity_id``, so a FK from
    # here to ``tasks.id`` would create a DDL bootstrap cycle. Task output linkage
    # remains TaskRun / TaskArtifact / TaskProposal — never this column alone.
    source_task_id: Mapped[Optional[str]] = mapped_column(UUID_COL, nullable=True, index=True)
    # Soft reference to Project.id — no DB FK; enforced at service layer.
    project_id: Mapped[Optional[str]] = mapped_column(UUID_COL, nullable=True, index=True)
    source_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    activity_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    title: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="raw", index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

    source_kind: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    # Default: internal_system — a conservative default that does not over-elevate trust.
    # Callers that know the activity came directly from a user should set user_confirmed.
    source_trust: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    source_integrity_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    entity_refs_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    # subject_user_id: who the activity is *about* (distinct from user_id = who created it)
    subject_user_id: Mapped[Optional[str]] = mapped_column(UUID_COL, nullable=True, index=True)
    lifecycle_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="raw", server_default=text("'raw'"), index=True
    )
    consolidation_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending", server_default=text("'pending'"), index=True
    )
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    discarded_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    visibility: Mapped[str] = mapped_column(
        String(32), nullable=False, default="space_shared", server_default=text("'space_shared'")
    )
    owner_user_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("users.id"), nullable=True, index=True)

    # Field name aliases for activity API (source_type, source_session_id, metadata_json).
    source_type = synonym("activity_type")
    source_session_id = synonym("session_id")
    metadata_json = synonym("payload_json")

    source_run: Mapped[Optional[Run]] = relationship("Run", back_populates="activities")

    __table_args__ = (
        CheckConstraint(
            "status in ('raw', 'processed', 'proposals_generated', 'archived')",
            name="ck_activity_records_status",
        ),
        CheckConstraint(
            "lifecycle_status in ('raw', 'active', 'archived', 'discarded')",
            name="ck_activity_records_lifecycle_status",
        ),
        CheckConstraint(
            "consolidation_status in ('pending', 'skipped', 'proposals_generated', 'processed', 'failed')",
            name="ck_activity_records_consolidation_status",
        ),
        CheckConstraint(
            "source_kind is null or source_kind in ("
            "'user_capture', 'chat_message', 'external_chat', 'file_import', "
            "'web_capture', 'run_event', 'workspace_event', 'system_event', 'external_source')",
            name="ck_activity_records_source_kind",
        ),
        CheckConstraint(
            "source_trust is null or source_trust in ("
            "'user_confirmed', 'internal_system', 'trusted_external', "
            "'untrusted_external', 'agent_inferred')",
            name="ck_activity_records_source_trust",
        ),
    )


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=False, index=True)
    run_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("runs.id"), nullable=True, index=True)
    proposal_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("proposals.id"), nullable=True, index=True)
    artifact_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    storage_ref: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    storage_path: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    mime_type: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    exportable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("1"))
    export_formats_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    canonical_format: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    preview: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("0"))
    relevant_period_start: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    relevant_period_end: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    visibility: Mapped[str] = mapped_column(
        String(32), nullable=False, default="space_shared", server_default=text("'space_shared'")
    )
    owner_user_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("users.id"), nullable=True, index=True)
    # Source provenance: which runtime adapter and execution plane produced this artifact.
    source_runtime_adapter_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("runtime_adapters.id"), nullable=True, index=True)
    source_execution_plane_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("execution_planes.id"), nullable=True, index=True)
    trust_level: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    # Soft reference to Project.id — no DB FK; enforced at service layer.
    project_id: Mapped[Optional[str]] = mapped_column(UUID_COL, nullable=True, index=True)


    run: Mapped[Optional[Run]] = relationship("Run", back_populates="artifacts")

    __table_args__ = (
        CheckConstraint(
            "storage_path is null or storage_path not like '/%'",
            name="ck_artifacts_storage_path_relative",
        ),
        CheckConstraint(
            "trust_level is null or trust_level in ('high', 'medium', 'low', 'unknown')",
            name="ck_artifacts_trust_level",
        ),
    )


class Proposal(Base):
    __tablename__ = "proposals"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=False, index=True)
    created_by_run_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("runs.id"), nullable=True, index=True)
    proposal_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    risk_level: Mapped[str] = mapped_column(String(32), nullable=False, default="low", index=True)
    urgency: Mapped[str] = mapped_column(String(32), nullable=False, default="normal", index=True)
    # Dry-run preview marker. Preview proposals are distinguishable from
    # normal pending proposals; they must never be applied to active memory.
    preview: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("0"))
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    review_deadline: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("users.id"), nullable=True)

    # Extra proposal linkage fields used by services and review flows.
    workspace_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("workspaces.id"), nullable=True, index=True)
    rationale: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by_agent_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("agents.id"), nullable=True)
    created_by_user_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("users.id"), nullable=True)
    required_approver_role: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    visibility: Mapped[str] = mapped_column(
        String(32), nullable=False, default="space_shared", server_default=text("'space_shared'")
    )
    # Soft reference to Project.id — no DB FK; enforced at service layer.
    project_id: Mapped[Optional[str]] = mapped_column(UUID_COL, nullable=True, index=True)
    type = synonym("proposal_type")
    decided_at = synonym("reviewed_at")

    created_by_run: Mapped[Optional[Run]] = relationship("Run", back_populates="proposals")
    approvals: Mapped[list["ProposalApproval"]] = relationship("ProposalApproval", back_populates="proposal")

    user_id = synonym("created_by_user_id")

    # Memory follow-up: if Proposal grows, move memory_update payload accessors
    # (owner_user_id, subject_user_id, sensitivity_level, selected_user_ids, …)
    # out of this ORM class (e.g. app.memory.proposal_payload).

    @property
    def proposed_title(self) -> str:
        return self.title

    @property
    def proposed_content(self) -> str:
        return (self.payload_json or {}).get("proposed_content", "")

    @property
    def memory_type(self) -> str:
        return (self.payload_json or {}).get("memory_type", "")

    @property
    def target_scope(self) -> str:
        return (self.payload_json or {}).get("target_scope", "")

    @property
    def target_namespace(self) -> str:
        return (self.payload_json or {}).get("target_namespace", "")

    @property
    def source_session_id(self) -> Optional[str]:
        return (self.payload_json or {}).get("source_session_id")

    @property
    def source_task_id(self) -> Optional[str]:
        return (self.payload_json or {}).get("source_task_id")

    @property
    def source_run_id(self) -> Optional[str]:
        from .memory.proposal_payload import provenance_entries_from_payload

        p = self.payload_json or {}
        v = p.get("source_run_id")
        if v:
            return str(v)
        for e in provenance_entries_from_payload(p):
            if e.get("source_type") == "run_step":
                sid = e.get("source_id")
                return str(sid) if sid else None
        return None

    @property
    def source_activity_id(self) -> Optional[str]:
        from .memory.proposal_payload import first_activity_id, provenance_entries_from_payload

        p = self.payload_json or {}
        flat_key = p.get("source_activity_id")
        if flat_key:
            return str(flat_key)
        return first_activity_id(provenance_entries_from_payload(p))

    @property
    def owner_user_id(self) -> Optional[str]:
        """Memory proposal payload only; not a Proposal table column."""
        return (self.payload_json or {}).get("owner_user_id")

    @property
    def subject_user_id(self) -> Optional[str]:
        """Memory proposal payload: subject of the memory (distinct from proposer)."""
        return (self.payload_json or {}).get("subject_user_id")

    @property
    def sensitivity_level(self) -> Optional[str]:
        return (self.payload_json or {}).get("sensitivity_level")

    @property
    def selected_user_ids(self) -> Optional[list]:
        return (self.payload_json or {}).get("selected_user_ids")

    @property
    def resulting_memory_id(self) -> Optional[str]:
        return (self.payload_json or {}).get("resulting_memory_id")

    @resulting_memory_id.setter
    def resulting_memory_id(self, value: Optional[str]) -> None:
        from sqlalchemy.orm.attributes import flag_modified

        data = dict(self.payload_json or {})
        if value is None:
            data.pop("resulting_memory_id", None)
        else:
            data["resulting_memory_id"] = value
        self.payload_json = data
        flag_modified(self, "payload_json")

    __table_args__ = (
        CheckConstraint("urgency in ('low', 'normal', 'high', 'critical')", name="ck_proposals_urgency"),
        CheckConstraint("risk_level in ('low', 'medium', 'high', 'critical')", name="ck_proposals_risk_level"),
    )


class ProposalApproval(Base):
    """First-class approval row for proposal gates that cannot be represented by status alone.

    MVP supports egress_granting_user approvals. Rows store approval metadata only:
    no raw personal memory, generated summaries, memory IDs, or artifact/proposal payload content.
    """

    __tablename__ = "proposal_approvals"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    proposal_id: Mapped[str] = mapped_column(UUID_COL, ForeignKey("proposals.id"), nullable=False, index=True)
    approval_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    approver_user_id: Mapped[str] = mapped_column(UUID_COL, ForeignKey("users.id"), nullable=False, index=True)
    grant_id: Mapped[Optional[str]] = mapped_column(
        UUID_COL, ForeignKey("personal_memory_grants.id"), nullable=True, index=True
    )
    target_space_id: Mapped[Optional[str]] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    proposal: Mapped["Proposal"] = relationship("Proposal", back_populates="approvals")
    approver_user: Mapped["User"] = relationship("User", foreign_keys=[approver_user_id])
    grant: Mapped[Optional["PersonalMemoryGrant"]] = relationship("PersonalMemoryGrant", foreign_keys=[grant_id])
    target_space: Mapped[Optional["Space"]] = relationship("Space", foreign_keys=[target_space_id])

    __table_args__ = (
        CheckConstraint("approval_type in ('egress_granting_user')", name="ck_proposal_approvals_approval_type"),
        CheckConstraint("status in ('approved', 'revoked')", name="ck_proposal_approvals_status"),
        Index(
            "ix_proposal_approvals_unique_active",
            "proposal_id",
            "approval_type",
            "approver_user_id",
            "grant_id",
            unique=True,
            sqlite_where=text("status = 'approved'"),
        ),
        Index("ix_proposal_approvals_created_at", "created_at"),
    )


# ---------------------------------------------------------------------------
# Task board (product-level work items; not infrastructure jobs)
# ---------------------------------------------------------------------------


class Board(Base):
    """Space/workspace-level work surface for agent-native task tracking."""

    __tablename__ = "boards"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=False, index=True)
    workspace_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("workspaces.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    board_type: Mapped[str] = mapped_column(String(64), nullable=False, default="workspace")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    default_view: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    sort_order: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_by_user_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("users.id"), nullable=True)
    created_by_agent_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("agents.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    space: Mapped[Space] = relationship("Space", foreign_keys=[space_id])
    columns: Mapped[list["BoardColumn"]] = relationship(
        "BoardColumn",
        back_populates="board",
        foreign_keys="BoardColumn.board_id",
        order_by="BoardColumn.position",
    )


class BoardColumn(Base):
    __tablename__ = "board_columns"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=False, index=True)
    board_id: Mapped[str] = mapped_column(UUID_COL, ForeignKey("boards.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status_key: Mapped[str] = mapped_column(String(64), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    wip_limit: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    is_done_column: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_default_column: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    board: Mapped[Board] = relationship("Board", back_populates="columns", foreign_keys=[board_id])


class Task(Base):
    """Product-level work item; distinct from infrastructure Job rows."""

    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=False, index=True)
    workspace_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("workspaces.id"), nullable=True, index=True)
    board_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("boards.id"), nullable=True, index=True)
    column_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("board_columns.id"), nullable=True, index=True)
    parent_task_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("tasks.id"), nullable=True, index=True)

    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    task_type: Mapped[str] = mapped_column(String(64), nullable=False, default="general")
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="inbox")
    priority: Mapped[str] = mapped_column(String(32), nullable=False, default="normal")
    risk_level: Mapped[str] = mapped_column(String(32), nullable=False, default="low")
    visibility: Mapped[str] = mapped_column(
        String(32), nullable=False, default="space_shared", server_default=text("'space_shared'")
    )

    created_by_user_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("users.id"), nullable=True)
    created_by_agent_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("agents.id"), nullable=True)
    assigned_user_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("users.id"), nullable=True)
    assigned_agent_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("agents.id"), nullable=True)
    claimed_by_user_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("users.id"), nullable=True)
    claimed_by_agent_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("agents.id"), nullable=True)

    source_activity_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("activity_records.id"), nullable=True)
    source_run_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("runs.id"), nullable=True)
    source_proposal_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("proposals.id"), nullable=True)
    source_artifact_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("artifacts.id"), nullable=True)

    acceptance_criteria_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    definition_of_done: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    required_outputs_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)

    due_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    start_after: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    blocked_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    estimated_effort: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    actual_effort: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    max_runs: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    max_cost: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    max_duration_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    policy_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    tags: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    parent_task: Mapped[Optional["Task"]] = relationship(
        "Task",
        remote_side=[id],
        foreign_keys=[parent_task_id],
    )


class TaskRun(Base):
    __tablename__ = "task_runs"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=False, index=True)
    task_id: Mapped[str] = mapped_column(UUID_COL, ForeignKey("tasks.id"), nullable=False, index=True)
    run_id: Mapped[str] = mapped_column(UUID_COL, ForeignKey("runs.id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="primary")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)

    __table_args__ = (UniqueConstraint("task_id", "run_id", name="uq_task_runs_task_run"),)


class TaskArtifact(Base):
    __tablename__ = "task_artifacts"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=False, index=True)
    task_id: Mapped[str] = mapped_column(UUID_COL, ForeignKey("tasks.id"), nullable=False, index=True)
    artifact_id: Mapped[str] = mapped_column(UUID_COL, ForeignKey("artifacts.id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="output")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)

    artifact: Mapped["Artifact"] = relationship("Artifact", foreign_keys=[artifact_id])

    __table_args__ = (UniqueConstraint("task_id", "artifact_id", name="uq_task_artifacts_task_artifact"),)


class TaskProposal(Base):
    __tablename__ = "task_proposals"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=False, index=True)
    task_id: Mapped[str] = mapped_column(UUID_COL, ForeignKey("tasks.id"), nullable=False, index=True)
    proposal_id: Mapped[str] = mapped_column(UUID_COL, ForeignKey("proposals.id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="main_change")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)

    proposal: Mapped["Proposal"] = relationship("Proposal", foreign_keys=[proposal_id])

    __table_args__ = (UniqueConstraint("task_id", "proposal_id", name="uq_task_proposals_task_proposal"),)


class TaskDependency(Base):
    __tablename__ = "task_dependencies"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=False, index=True)
    task_id: Mapped[str] = mapped_column(UUID_COL, ForeignKey("tasks.id"), nullable=False, index=True)
    depends_on_task_id: Mapped[str] = mapped_column(UUID_COL, ForeignKey("tasks.id"), nullable=False, index=True)
    dependency_type: Mapped[str] = mapped_column(String(32), nullable=False, default="requires")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)

    __table_args__ = (
        UniqueConstraint("task_id", "depends_on_task_id", name="uq_task_dependencies_task_depends"),
    )


class TaskEvaluation(Base):
    __tablename__ = "task_evaluations"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=False, index=True)
    task_id: Mapped[str] = mapped_column(UUID_COL, ForeignKey("tasks.id"), nullable=False, index=True)
    run_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("runs.id"), nullable=True, index=True)
    evaluator_type: Mapped[str] = mapped_column(String(32), nullable=False)
    evaluator_user_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("users.id"), nullable=True)
    evaluator_agent_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("agents.id"), nullable=True)
    score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    checklist_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    known_issues_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    evidence_artifact_ids: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    recommendation: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)


# ---------------------------------------------------------------------------
# Infrastructure jobs and memory
# ---------------------------------------------------------------------------


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=False, index=True)
    job_type: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    result_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    scheduled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    claimed_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    claimed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

    # Extra job linkage fields used by the queue worker surface.
    user_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("users.id"), nullable=True, index=True)
    workspace_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("workspaces.id"), nullable=True, index=True)
    agent_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("agents.id"), nullable=True, index=True)
    payload = synonym("payload_json")
    result = synonym("result_json")

    events: Mapped[list["JobEvent"]] = relationship("JobEvent", back_populates="job", cascade="all, delete-orphan")


class JobEvent(Base):
    """Infrastructure queue event log. Not a product-level Automation object."""

    __tablename__ = "job_events"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    job_id: Mapped[str] = mapped_column(UUID_COL, ForeignKey("jobs.id"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)

    job: Mapped[Job] = relationship("Job", back_populates="events")


class MemoryEntry(Base):
    __tablename__ = "memory_entries"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=False, index=True)
    scope_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    scope_id: Mapped[Optional[str]] = mapped_column(UUID_COL, nullable=True, index=True)
    memory_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)
    source_proposal_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("proposals.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)
    valid_from: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_to: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # subject_user_id — who/what this memory is about (FK to users.id when it is a user).
    # owner_user_id — human who controls the memory for ACL; distinct from subject_user_id.
    subject_user_id: Mapped[Optional[str]] = mapped_column(
        UUID_COL, ForeignKey("users.id"), nullable=True, index=True
    )
    owner_user_id: Mapped[Optional[str]] = mapped_column(
        UUID_COL, ForeignKey("users.id"), nullable=True, index=True
    )
    sensitivity_level: Mapped[str] = mapped_column(
        String(32), nullable=False, default="normal", index=True
    )
    selected_user_ids: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    last_confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    workspace_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("workspaces.id"), nullable=True, index=True)
    # Soft reference to Project.id — no DB FK; enforced at service layer.
    project_id: Mapped[Optional[str]] = mapped_column(UUID_COL, nullable=True, index=True)
    agent_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("agents.id"), nullable=True, index=True)
    capability_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    namespace: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    title: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    visibility: Mapped[str] = mapped_column(String(32), nullable=False, default="private")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    importance: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    source_id: Mapped[Optional[str]] = mapped_column(UUID_COL, nullable=True)
    source_activity_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("activity_records.id"), nullable=True, index=True)
    source_artifact_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("artifacts.id"), nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    approved_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    access_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_accessed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    fitness_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    tags: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)

    memory_layer: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    memory_kind: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    event_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    event_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    summary_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    salience_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    last_retrieved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    reconsolidation_due: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # Soft self-references: root_memory_id / supersedes_memory_id point to the
    # lineage chain within a versioned semantic memory.  No DB FK to avoid DDL
    # bootstrap ordering issues on first creation.
    root_memory_id: Mapped[Optional[str]] = mapped_column(UUID_COL, nullable=True, index=True)
    supersedes_memory_id: Mapped[Optional[str]] = mapped_column(UUID_COL, nullable=True, index=True)
    source_trust: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    created_from_proposal_id: Mapped[Optional[str]] = mapped_column(
        UUID_COL, ForeignKey("proposals.id"), nullable=True, index=True
    )

    scope = synonym("scope_type")
    type = synonym("memory_type")

    __table_args__ = (
        CheckConstraint(
            "sensitivity_level in ('normal', 'sensitive', 'restricted', 'highly_restricted')",
            name="ck_memory_entries_sensitivity_level",
        ),
        CheckConstraint(
            "memory_layer is null or memory_layer in ('episodic', 'semantic')",
            name="ck_memory_entries_memory_layer",
        ),
        CheckConstraint(
            "source_trust is null or source_trust in ("
            "'user_confirmed', 'internal_system', 'trusted_external', "
            "'untrusted_external', 'agent_inferred')",
            name="ck_memory_entries_source_trust",
        ),
    )


class MemoryReadTrace(Base):
    __tablename__ = "memory_access_logs"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=False, index=True)
    memory_id: Mapped[str] = mapped_column(UUID_COL, ForeignKey("memory_entries.id"), nullable=False, index=True)
    user_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("users.id"), nullable=True, index=True)
    agent_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("agents.id"), nullable=True, index=True)
    run_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("runs.id"), nullable=True, index=True)
    access_type: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    accessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)


# ---------------------------------------------------------------------------
# Ontology / provenance tables
# ---------------------------------------------------------------------------


class EntityRef(Base):
    """Named domain entity referenced by memories, activities, or proposals."""

    __tablename__ = "entity_refs"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=False, index=True)
    entity_origin: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entity_id: Mapped[Optional[str]] = mapped_column(String(256), nullable=True, index=True)
    canonical_key: Mapped[Optional[str]] = mapped_column(String(512), nullable=True, index=True)
    display_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    aliases_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    scope_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    scope_id: Mapped[Optional[str]] = mapped_column(UUID_COL, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)


class MemoryRelation(Base):
    """Typed directed edge between two memory-system objects."""

    __tablename__ = "memory_relations"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_id: Mapped[str] = mapped_column(UUID_COL, nullable=False)
    target_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_id: Mapped[str] = mapped_column(UUID_COL, nullable=False)
    relation_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    evidence_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_from_proposal_id: Mapped[Optional[str]] = mapped_column(
        UUID_COL, ForeignKey("proposals.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)

    __table_args__ = (
        CheckConstraint(
            "relation_type in ('derived_from', 'supersedes', 'contradicts', 'related_to', "
            "'caused_by', 'supports', 'applies_to', 'mentions')",
            name="ck_memory_relations_relation_type",
        ),
    )


class Actor(Base):
    """Durable identity record for any principal that can act in the system.

    Covers human users, agents, system/service/job actors, and reserved future
    kinds (automation, connector, integration).  New audit/event/RunStep surfaces
    must reference an Actor rather than raw nullable user_id/agent_id pairs.

    Historical tables (Run, Proposal, ActivityRecord, …) keep their existing
    user_id/agent_id fields.  New records use actor_ref.  Do not migrate
    the old fields in bulk here.

    Constraints enforced by ActorService (not all expressible as simple DB checks
    with nullable columns in SQLite):
      - actor_type = user    → user_id required, agent_id must be null
      - actor_type = agent   → agent_id required, user_id must be null
      - actor_type in (system, service, job, automation, connector, integration)
                             → user_id and agent_id must both be null
    """

    __tablename__ = "actors"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    space_id: Mapped[Optional[str]] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=True, index=True)
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    user_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("users.id"), nullable=True, index=True)
    agent_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("agents.id"), nullable=True, index=True)
    service_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    display_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

    space: Mapped[Optional[Space]] = relationship("Space", foreign_keys=[space_id])
    user: Mapped[Optional[User]] = relationship("User", foreign_keys=[user_id])
    agent: Mapped[Optional[Agent]] = relationship("Agent", foreign_keys=[agent_id])

    __table_args__ = (
        CheckConstraint(
            "actor_type in ('user', 'agent', 'system', 'automation', 'connector', "
            "'integration', 'service', 'job')",
            name="ck_actors_actor_type",
        ),
        CheckConstraint(
            "status in ('active', 'disabled', 'archived')",
            name="ck_actors_status",
        ),
    )


class RunStep(Base):
    """Coarse execution step for replay and failure diagnosis (M3).

    Each RunStep captures one phase of a Run's lifecycle: creation, context
    preparation, adapter invocation, artifact/proposal production, completion,
    or failure.  All steps require actor identity — no nullable actor_id.

    Step writes are best-effort during rollout: a failed step write must not
    suppress the original run failure.  Secret/credential values must never
    appear in error_message or metadata_json.
    """

    __tablename__ = "run_steps"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=False, index=True)
    run_id: Mapped[str] = mapped_column(UUID_COL, ForeignKey("runs.id"), nullable=False, index=True)
    parent_step_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("run_steps.id"), nullable=True, index=True)
    actor_id: Mapped[str] = mapped_column(UUID_COL, ForeignKey("actors.id"), nullable=False, index=True)
    step_index: Mapped[int] = mapped_column(Integer, nullable=False)
    step_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    title: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    runtime_adapter_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("runtime_adapters.id"), nullable=True, index=True)
    workspace_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("workspaces.id"), nullable=True, index=True)
    session_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("sessions.id"), nullable=True, index=True)
    task_id: Mapped[Optional[str]] = mapped_column(UUID_COL, nullable=True, index=True)
    artifact_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("artifacts.id"), nullable=True, index=True)
    proposal_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("proposals.id"), nullable=True, index=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    input_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    output_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_type: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

    run: Mapped["Run"] = relationship("Run", back_populates="steps")
    actor: Mapped["Actor"] = relationship("Actor", foreign_keys=[actor_id])

    __table_args__ = (
        UniqueConstraint("run_id", "step_index", name="uq_run_steps_run_step_index"),
        CheckConstraint(
            "step_type in ("
            "'run_created', 'queued', 'context_prepared', 'runtime_selected', "
            "'adapter_started', 'adapter_completed', 'artifact_created', "
            "'proposal_created', 'failed', 'completed', "
            "'validation_started', 'validation_completed', 'cancelled')",
            name="ck_run_steps_step_type",
        ),
        CheckConstraint(
            "status in ('pending', 'running', 'succeeded', 'failed', 'skipped', 'cancelled')",
            name="ck_run_steps_status",
        ),
    )


class ProvenanceLink(Base):
    """Trace record linking a durable object (memory, policy) back to its evidence source."""

    __tablename__ = "provenance_links"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=False, index=True)
    target_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_id: Mapped[str] = mapped_column(UUID_COL, nullable=False)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_id: Mapped[str] = mapped_column(UUID_COL, nullable=False)
    source_trust: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    evidence_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)

    __table_args__ = (
        CheckConstraint(
            "source_type in ('activity', 'proposal', 'memory', 'artifact', "
            "'run_step', 'external_source', 'user_confirmation')",
            name="ck_provenance_links_source_type",
        ),
        CheckConstraint(
            "source_trust is null or source_trust in ("
            "'user_confirmed', 'internal_system', 'trusted_external', "
            "'untrusted_external', 'agent_inferred')",
            name="ck_provenance_links_source_trust",
        ),
    )


# ---------------------------------------------------------------------------
# Participation ledger (pointer-only, no content)
# ---------------------------------------------------------------------------


class ParticipationRecord(Base):
    """Cross-space participation ledger entry.

    Records that a user participated in a source object that belongs to a
    source_space, and links it back to the user's personal_space for
    PersonalView assembly (future). This table is a pointer ledger only:
    it must never contain raw content, payload, or summary fields.
    Population hooks are deferred — see docs/FUTURE_ROADMAP.md.
    """

    __tablename__ = "participation_records"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(UUID_COL, ForeignKey("users.id"), nullable=False, index=True)
    personal_space_id: Mapped[str] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=False, index=True)
    source_space_id: Mapped[str] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=False)
    source_object_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_object_id: Mapped[str] = mapped_column(UUID_COL, nullable=False)
    role: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)

    __table_args__ = (
        Index(
            "ix_participation_records_source",
            "source_space_id",
            "source_object_type",
            "source_object_id",
        ),
    )


# ---------------------------------------------------------------------------
# PersonalMemoryGrant
# ---------------------------------------------------------------------------


class PersonalMemoryGrant(Base):
    """Explicit user-authorized exception allowing one shared-space run to use a generated
    summary of selected personal-space private memories.

    Security invariants:
    - No grant → no cross-space personal memory read (enforced by MemoryRetriever space_id filter).
    - grant_scope must be 'run' (MVP); target_run_id is NOT NULL; target_agent_id is NULL.
    - access_mode must be 'summary_only' (MVP).
    - read_expires_at is required; grants deny access after expiry.
    - At most one active/consuming grant per (granting_user_id, target_run_id) — enforced by
      partial unique index in migration + service layer.
    - No raw memory content, generated summaries, or personal memory IDs stored here.
    """

    __tablename__ = "personal_memory_grants"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    granting_user_id: Mapped[str] = mapped_column(UUID_COL, ForeignKey("users.id"), nullable=False, index=True)
    personal_space_id: Mapped[str] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=False, index=True)
    target_space_id: Mapped[str] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=False, index=True)
    target_run_id: Mapped[str] = mapped_column(UUID_COL, ForeignKey("runs.id"), nullable=False, index=True)
    target_agent_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("agents.id"), nullable=True)
    grant_scope: Mapped[str] = mapped_column(String(32), nullable=False)
    access_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    memory_filter_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    read_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    egress_review_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    consume_started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_stage: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

    granting_user: Mapped["User"] = relationship("User", foreign_keys=[granting_user_id])
    personal_space: Mapped["Space"] = relationship("Space", foreign_keys=[personal_space_id])
    target_space: Mapped["Space"] = relationship("Space", foreign_keys=[target_space_id])
    target_run: Mapped["Run"] = relationship("Run", foreign_keys=[target_run_id])
    target_agent: Mapped[Optional["Agent"]] = relationship("Agent", foreign_keys=[target_agent_id])
    events: Mapped[list["PersonalMemoryGrantEvent"]] = relationship(
        "PersonalMemoryGrantEvent", back_populates="grant"
    )

    __table_args__ = (
        CheckConstraint("grant_scope in ('run')", name="ck_personal_memory_grants_grant_scope"),
        CheckConstraint("access_mode in ('summary_only')", name="ck_personal_memory_grants_access_mode"),
        CheckConstraint(
            "status in ('active', 'consuming', 'used', 'revoked', 'expired', 'failed')",
            name="ck_personal_memory_grants_status",
        ),
        # MVP invariant: agent-level grants deferred; target_agent_id must be NULL.
        CheckConstraint("target_agent_id is null", name="ck_personal_memory_grants_target_agent_id_null"),
    )


class PersonalMemoryGrantEvent(Base):
    """Audit trail entry for PersonalMemoryGrant lifecycle events.

    Metadata-only: metadata_json must not contain raw memory content, generated summaries,
    or personal MemoryEntry IDs. Safe fields: IDs, counts, boolean decisions, timestamps.
    """

    __tablename__ = "personal_memory_grant_events"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    grant_id: Mapped[str] = mapped_column(UUID_COL, ForeignKey("personal_memory_grants.id"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_user_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("users.id"), nullable=True, index=True)
    run_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("runs.id"), nullable=True, index=True)
    proposal_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("proposals.id"), nullable=True)
    source_space_id: Mapped[Optional[str]] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=True)
    target_space_id: Mapped[Optional[str]] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)

    grant: Mapped["PersonalMemoryGrant"] = relationship("PersonalMemoryGrant", back_populates="events")
    actor_user: Mapped[Optional["User"]] = relationship("User", foreign_keys=[actor_user_id])
    run: Mapped[Optional["Run"]] = relationship("Run", foreign_keys=[run_id])

    __table_args__ = (
        CheckConstraint(
            "event_type in ('created', 'previewed', 'consuming', 'used', 'revoked', 'expired', 'failed', 'denied', 'egress_proposal_created', 'egress_approved')",
            name="ck_personal_memory_grant_events_event_type",
        ),
        Index("ix_personal_memory_grant_events_created_at", "created_at"),
    )


# ---------------------------------------------------------------------------
# Execution control plane: validation, workspace profiles, external records
# ---------------------------------------------------------------------------


class ValidationRecipe(Base):
    """Reusable validation definition for workspace/task types.

    Validation is always controlled by agent-space even when coding execution is
    delegated to Codex, Claude Code, OpenCode, Cursor, or another runtime.
    """

    __tablename__ = "validation_recipes"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=False, index=True)
    workspace_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("workspaces.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    task_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    risk_level: Mapped[str] = mapped_column(String(32), nullable=False, default="low")
    commands_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    required_checks_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    artifact_expectations_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    timeout_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    requires_clean_git_state: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

    __table_args__ = (
        CheckConstraint(
            "risk_level in ('low', 'medium', 'high')",
            name="ck_validation_recipes_risk_level",
        ),
    )


class WorkspaceProfile(Base):
    """Structured operational knowledge for a workspace/repo.

    Stores durable agent-facing config: paths, commands, allowed runtimes,
    and data-exposure limits. Workspace.metadata_json is for ad-hoc annotations;
    WorkspaceProfile holds structured operational rules.
    """

    __tablename__ = "workspace_profiles"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=False, index=True)
    workspace_id: Mapped[str] = mapped_column(UUID_COL, ForeignKey("workspaces.id"), nullable=False, index=True)
    repo_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    tech_stack_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    important_paths_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    forbidden_paths_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    test_commands_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    build_commands_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    architecture_boundaries_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    current_focus: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    known_failures_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    validation_recipe_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("validation_recipes.id"), nullable=True)
    preferred_runtime_adapter_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("runtime_adapters.id"), nullable=True)
    cloud_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    max_data_exposure_level: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    min_observability_level: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

    workspace: Mapped["Workspace"] = relationship("Workspace", back_populates="profile", foreign_keys=[workspace_id])
    validation_recipe: Mapped[Optional[ValidationRecipe]] = relationship("ValidationRecipe")
    preferred_runtime_adapter: Mapped[Optional[RuntimeAdapter]] = relationship(
        "RuntimeAdapter", foreign_keys=[preferred_runtime_adapter_id]
    )

    __table_args__ = (
        UniqueConstraint("workspace_id", name="uq_workspace_profiles_workspace"),
        CheckConstraint(
            "max_data_exposure_level is null or max_data_exposure_level in ('local_only', 'model_provider', 'vendor_platform', 'third_party_tools', 'unknown')",
            name="ck_workspace_profiles_max_data_exposure_level",
        ),
        CheckConstraint(
            "min_observability_level is null or min_observability_level in ('full_trace', 'structured_events', 'artifacts_only', 'final_output_only', 'black_box')",
            name="ck_workspace_profiles_min_observability_level",
        ),
    )


class ExternalRunRecord(Base):
    """Evidence record for an externally executed or manually imported run.

    External output (Codex, Claude Code, Cursor, OpenCode, manual) is evidence,
    not internal truth. This table attaches external evidence to an internal Run.
    """

    __tablename__ = "external_run_records"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=False, index=True)
    run_id: Mapped[str] = mapped_column(UUID_COL, ForeignKey("runs.id"), nullable=False, index=True)
    vendor: Mapped[str] = mapped_column(String(64), nullable=False)
    vendor_run_id: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    runtime_adapter_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("runtime_adapters.id"), nullable=True, index=True)
    execution_plane_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("execution_planes.id"), nullable=True, index=True)
    external_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    observability_level: Mapped[str] = mapped_column(String(64), nullable=False, default="black_box")
    data_exposure_level: Mapped[str] = mapped_column(String(64), nullable=False, default="unknown")
    trace_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    raw_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    raw_output_uri: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    imported_diff_uri: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    imported_artifacts_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    imported_logs_uri: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="imported")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)

    run: Mapped["Run"] = relationship("Run", back_populates="external_run_records", foreign_keys=[run_id])
    runtime_adapter: Mapped[Optional[RuntimeAdapter]] = relationship("RuntimeAdapter", foreign_keys=[runtime_adapter_id])
    execution_plane: Mapped[Optional[ExecutionPlane]] = relationship("ExecutionPlane", foreign_keys=[execution_plane_id])

    __table_args__ = (
        CheckConstraint(
            "vendor in ('openai', 'anthropic', 'cursor', 'opencode', 'manual', 'other')",
            name="ck_external_run_records_vendor",
        ),
        CheckConstraint(
            "observability_level in ('full_trace', 'structured_events', 'artifacts_only', 'final_output_only', 'black_box')",
            name="ck_external_run_records_observability_level",
        ),
        CheckConstraint(
            "data_exposure_level in ('local_only', 'model_provider', 'vendor_platform', 'third_party_tools', 'unknown')",
            name="ck_external_run_records_data_exposure_level",
        ),
    )


class RunReflection(Base):
    """Self-learning record extracted from a run.

    Never directly mutates memory, policy, capability, workspace profile, or
    validation recipes. Only stores learning candidates that flow into proposals.
    Do not use TaskEvaluation for this — TaskEvaluation evaluates task success;
    RunReflection captures reusable learning from the run.
    """

    __tablename__ = "run_reflections"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=False, index=True)
    run_id: Mapped[str] = mapped_column(UUID_COL, ForeignKey("runs.id"), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="native")
    what_changed: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    what_worked: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    what_failed: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reusable_rules_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    reusable_commands_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    workspace_facts_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    memory_candidates_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    capability_candidates_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    policy_candidates_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    validation_candidates_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    follow_up_tasks_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)

    run: Mapped["Run"] = relationship("Run", back_populates="run_reflections", foreign_keys=[run_id])

    __table_args__ = (
        CheckConstraint(
            "source in ('native', 'external_import', 'manual', 'evaluator')",
            name="ck_run_reflections_source",
        ),
    )


class RuntimeToolBinding(Base):
    """Explicit binding allowing an external tool/plugin/skill/MCP server for a scope.

    This is NOT a plugin marketplace. It records only external capabilities that
    agent-space explicitly authorises for a space/workspace/agent/runtime combination.
    """

    __tablename__ = "runtime_tool_bindings"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=False, index=True)
    workspace_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("workspaces.id"), nullable=True, index=True)
    agent_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("agents.id"), nullable=True, index=True)
    # capability_id is a soft reference to capabilities (string ID from capability.yaml).
    capability_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    runtime_adapter_id: Mapped[str] = mapped_column(UUID_COL, ForeignKey("runtime_adapters.id"), nullable=False, index=True)
    execution_plane_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("execution_planes.id"), nullable=True, index=True)
    external_type: Mapped[str] = mapped_column(String(64), nullable=False)
    external_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    display_name: Mapped[str] = mapped_column(String(256), nullable=False)
    required_scopes_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    credential_ref: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    data_exposure_level: Mapped[str] = mapped_column(String(64), nullable=False, default="unknown")
    observability_level: Mapped[str] = mapped_column(String(64), nullable=False, default="black_box")
    side_effect_level: Mapped[str] = mapped_column(String(32), nullable=False, default="none")
    approval_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

    runtime_adapter: Mapped[RuntimeAdapter] = relationship("RuntimeAdapter", foreign_keys=[runtime_adapter_id])
    execution_plane: Mapped[Optional[ExecutionPlane]] = relationship("ExecutionPlane", foreign_keys=[execution_plane_id])

    __table_args__ = (
        CheckConstraint(
            "external_type in ('codex_plugin', 'claude_skill', 'claude_hook', 'mcp_server', 'app_integration', 'cli_tool')",
            name="ck_runtime_tool_bindings_external_type",
        ),
        CheckConstraint(
            "side_effect_level in ('none', 'local_files', 'external_read', 'external_write', 'sensitive')",
            name="ck_runtime_tool_bindings_side_effect_level",
        ),
        CheckConstraint(
            "data_exposure_level in ('local_only', 'model_provider', 'vendor_platform', 'third_party_tools', 'unknown')",
            name="ck_runtime_tool_bindings_data_exposure_level",
        ),
        CheckConstraint(
            "observability_level in ('full_trace', 'structured_events', 'artifacts_only', 'final_output_only', 'black_box')",
            name="ck_runtime_tool_bindings_observability_level",
        ),
    )
