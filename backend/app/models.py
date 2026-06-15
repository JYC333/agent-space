from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

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
    created_by_user_id: Mapped[Optional[str]] = mapped_column(
        UUID_COL,
        ForeignKey(
            "users.id",
            name="fk_spaces_created_by_user_id_users",
            ondelete="SET NULL",
            use_alter=True,
        ),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

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
    """Human identity. Space access is represented only by SpaceMembership."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    email: Mapped[Optional[str]] = mapped_column(String(256), nullable=True, unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(256), nullable=False)
    avatar_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

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
    invited_by_user_id: Mapped[str] = mapped_column(
        UUID_COL,
        ForeignKey("users.id", name="fk_space_invitations_invited_by_user_id_users", use_alter=True),
        nullable=False,
    )
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
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    # When True, root_path may resolve to a directory outside settings.workspace_root.
    # Defaults to False: all unqualified absolute paths that escape workspace_root are rejected.
    allow_external_root: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

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
    settings_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
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
    scopes_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
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
    capabilities_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    config_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

    credential: Mapped[Optional[Credential]] = relationship("Credential")



class ModelProviderCredential(Base):
    """Credential-pool membership for a ModelProvider (Hermes H1).

    A provider may hold 1→N encrypted API-key Credentials. Pool membership,
    rotation health, and cooldown state are server-side records here — never
    client-side files. Rows are written by the providers/credentials authority;
    Python/alembic owns the schema.
    CLI login state is a separate credential class and is never pooled.
    """

    __tablename__ = "model_provider_credentials"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=False, index=True)
    provider_id: Mapped[str] = mapped_column(
        UUID_COL,
        ForeignKey("model_providers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    credential_id: Mapped[str] = mapped_column(UUID_COL, ForeignKey("credentials.id"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    healthy: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    cooldown_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_failure_class: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    request_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    failure_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

    __table_args__ = (
        UniqueConstraint("provider_id", "credential_id", name="uq_model_provider_credentials_provider_credential"),
        CheckConstraint(
            "last_failure_class in ('rate_limit', 'payment_required', 'unauthorized', "
            "'quota_exhausted', 'transient', 'permanent') or last_failure_class is null",
            name="ck_model_provider_credentials_failure_class",
        ),
    )



class ProviderTaskPolicy(Base):
    """Per-auxiliary-task provider chain (Hermes H2).

    Generalizes REFLECTOR_MODEL_PROVIDER_ID: each auxiliary task (reflector,
    condenser, title generation, …) may carry an ordered provider/model chain;
    invocation walks the chain and degrades gracefully to the space default
    provider. One policy per (space, task).
    """

    __tablename__ = "provider_task_policies"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=False, index=True)
    task: Mapped[str] = mapped_column(String(64), nullable=False)
    # Ordered list of {"provider_id": str, "model": str | None}.
    chain_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

    __table_args__ = (
        UniqueConstraint("space_id", "task", name="uq_provider_task_policies_space_task"),
    )



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
    config_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
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


# ---------------------------------------------------------------------------
# Agent templates — reusable factories (NOT runtime objects)
# ---------------------------------------------------------------------------


class AgentTemplate(Base):
    """A reusable factory for creating Agents.

    A template is NOT a runtime object: no Run, AgentVersion, or model-call path
    ever reads an AgentTemplate or AgentTemplateVersion to determine behavior.
    Creating an Agent from a template copies the selected AgentTemplateVersion into
    a fresh AgentVersion (copy-on-create). Template updates never mutate existing
    Agents. There is no inheritance, no runtime merging, no dynamic parent lookup.
    """

    __tablename__ = "agent_templates"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    scope: Mapped[str] = mapped_column(String(16), nullable=False, default="user", index=True)
    space_id: Mapped[Optional[str]] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=True, index=True)
    owner_user_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("users.id"), nullable=True, index=True)
    visibility: Mapped[str] = mapped_column(String(32), nullable=False, default="private")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft", index=True)
    current_version_id: Mapped[Optional[str]] = mapped_column(
        UUID_COL,
        ForeignKey(
            "agent_template_versions.id",
            name="fk_agent_templates_current_version_id_agent_template_versions",
            ondelete="SET NULL",
            use_alter=True,
        ),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

    versions: Mapped[list["AgentTemplateVersion"]] = relationship(
        "AgentTemplateVersion",
        back_populates="template",
        foreign_keys="AgentTemplateVersion.template_id",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        CheckConstraint("scope in ('system', 'space', 'user')", name="ck_agent_templates_scope"),
        CheckConstraint(
            "visibility in ('private', 'space_shared', 'system_public', 'system_internal')",
            name="ck_agent_templates_visibility",
        ),
        CheckConstraint(
            "status in ('draft', 'published', 'archived')",
            name="ck_agent_templates_status",
        ),
        # Scope ⇒ required ownership anchor. System templates need neither a
        # space nor an owner; space templates need a space; user templates need an owner.
        CheckConstraint(
            "(scope = 'system' AND space_id IS NULL AND owner_user_id IS NULL) "
            "OR (scope = 'space' AND space_id IS NOT NULL) "
            "OR (scope = 'user' AND owner_user_id IS NOT NULL)",
            name="ck_agent_templates_scope_ownership",
        ),
        # key is unique within its scope (partial unique indexes, one per scope).
        Index(
            "uq_agent_templates_system_key",
            "key",
            unique=True,
            postgresql_where=text("scope = 'system'"),
        ),
        Index(
            "uq_agent_templates_space_key",
            "space_id",
            "key",
            unique=True,
            postgresql_where=text("scope = 'space'"),
        ),
        Index(
            "uq_agent_templates_user_key",
            "owner_user_id",
            "key",
            unique=True,
            postgresql_where=text("scope = 'user'"),
        ),
    )


class AgentTemplateVersion(Base):
    """Immutable snapshot of template configuration.

    Published versions are treated as immutable by the service layer. A template's
    ``current_version_id`` points to one of its versions. These fields are copied
    verbatim into a new AgentVersion when an Agent is created from this template.
    """

    __tablename__ = "agent_template_versions"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    template_id: Mapped[str] = mapped_column(
        UUID_COL, ForeignKey("agent_templates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    system_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    model_config_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    context_policy_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    memory_policy_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    tool_policy_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    runtime_policy_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    output_policy_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    schedule_defaults_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    output_schema_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_by_user_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("users.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    template: Mapped[AgentTemplate] = relationship(
        "AgentTemplate", back_populates="versions", foreign_keys=[template_id]
    )

    __table_args__ = (
        UniqueConstraint("template_id", "version", name="uq_agent_template_versions_template_version"),
    )


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
    # Agent kind distinguishes the system-managed default Assistant (the Chat
    # identity, one active per space) from ordinary template-instantiated agents.
    # Runtime never reads this — it only gates seeding/resolution and UI labelling.
    agent_kind: Mapped[str] = mapped_column(
        String(32), nullable=False, default="standard",
        server_default=text("'standard'"), index=True,
    )
    # Provenance only — records which template/version this Agent was created from.
    # NEVER read to assemble runtime config; runtime always loads from AgentVersion.
    source_template_id: Mapped[Optional[str]] = mapped_column(
        UUID_COL,
        ForeignKey(
            "agent_templates.id",
            name="fk_agents_source_template_id_agent_templates",
            ondelete="SET NULL",
            use_alter=True,
        ),
        nullable=True,
        index=True,
    )
    source_template_version_id: Mapped[Optional[str]] = mapped_column(
        UUID_COL,
        ForeignKey(
            "agent_template_versions.id",
            name="fk_agents_source_template_version_id_agent_template_versions",
            ondelete="SET NULL",
            use_alter=True,
        ),
        nullable=True,
        index=True,
    )
    # Nullable convenience pointer; Run.agent_version_id remains the canonical immutable execution FK.
    current_version_id: Mapped[Optional[str]] = mapped_column(
        UUID_COL,
        ForeignKey(
            "agent_versions.id",
            name="fk_agents_current_version_id_agent_versions",
            ondelete="SET NULL",
            use_alter=True,
        ),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

    # Denormalized fields slated to move fully onto AgentVersion over time.
    visibility: Mapped[str] = mapped_column(String(32), nullable=False, default="private")
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
        CheckConstraint("agent_kind in ('standard', 'system_assistant')", name="ck_agents_agent_kind"),
        # At most one active system-managed default Assistant per space.
        Index(
            "uq_agents_system_assistant_per_space",
            "space_id",
            unique=True,
            postgresql_where=text("agent_kind = 'system_assistant' AND status = 'active'"),
        ),
    )


class AgentVersion(Base):
    __tablename__ = "agent_versions"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    agent_id: Mapped[str] = mapped_column(UUID_COL, ForeignKey("agents.id"), nullable=False, index=True)
    space_id: Mapped[str] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=False, index=True)
    version_label: Mapped[str] = mapped_column(String(64), nullable=False)
    model_provider_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("model_providers.id"), nullable=True, index=True)
    model_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    system_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    model_config_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    runtime_config_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    context_policy_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    memory_policy_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    capabilities_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    tool_permissions_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    runtime_policy_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # Clean-model runtime snapshot fields (copied from AgentTemplateVersion on create-from-template).
    tool_policy_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    output_policy_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    schedule_config_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    output_schema_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    # Provenance for versions created by accepted agent_config_update proposals.
    source_proposal_id: Mapped[Optional[str]] = mapped_column(
        UUID_COL,
        ForeignKey(
            "proposals.id",
            name="fk_agent_versions_source_proposal_id_proposals",
            ondelete="SET NULL",
            use_alter=True,
        ),
        nullable=True,
        index=True,
    )
    source_activity_id: Mapped[Optional[str]] = mapped_column(
        UUID_COL,
        ForeignKey(
            "activity_records.id",
            name="fk_agent_versions_source_activity_id_activity_records",
            ondelete="SET NULL",
            use_alter=True,
        ),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    agent: Mapped[Agent] = relationship("Agent", back_populates="versions", foreign_keys=[agent_id])
    model_provider: Mapped[Optional[ModelProvider]] = relationship("ModelProvider")

    __table_args__ = (UniqueConstraint("agent_id", "version_label", name="uq_agent_versions_agent_label"),)


class SpaceAssistantSettings(Base):
    """User/space-configurable preferences for a space's default Assistant.

    This is a *preferences* layer kept deliberately separate from AgentVersion:
    it influences default UI/context behavior only and can NEVER loosen the
    assistant's hard policy (tool/runtime/output/safety) — those live on the
    immutable AgentVersion snapshot and are never merged with these fields.
    """

    __tablename__ = "space_assistant_settings"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(
        SPACE_COL, ForeignKey("spaces.id"), nullable=False, unique=True, index=True
    )
    assistant_agent_id: Mapped[Optional[str]] = mapped_column(
        UUID_COL,
        ForeignKey(
            "agents.id",
            name="fk_space_assistant_settings_assistant_agent_id_agents",
            ondelete="SET NULL",
            use_alter=True,
        ),
        nullable=True,
        index=True,
    )
    response_style: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    verbosity: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    default_context_toggles_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # Soft reference to projects.id (no hard FK — a deleted project simply leaves a
    # dangling default that the UI resolves leniently). See SOFT_REFERENCE_ALLOWLIST.
    default_project_id: Mapped[Optional[str]] = mapped_column(UUID_COL, nullable=True)
    proposal_style: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    model_preferences_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

    __table_args__ = (
        CheckConstraint(
            "response_style is null or response_style in ('neutral', 'friendly', 'direct', 'formal')",
            name="ck_space_assistant_settings_response_style",
        ),
        CheckConstraint(
            "verbosity is null or verbosity in ('concise', 'balanced', 'detailed')",
            name="ck_space_assistant_settings_verbosity",
        ),
        CheckConstraint(
            "proposal_style is null or proposal_style in ('proactive', 'balanced', 'conservative')",
            name="ck_space_assistant_settings_proposal_style",
        ),
    )


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
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
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
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)

    session: Mapped[Session] = relationship("Session", back_populates="messages")

    __table_args__ = (
        CheckConstraint("role in ('user', 'assistant', 'system', 'tool')", name="ck_messages_role"),
    )


class SessionSummary(Base):
    """Derived condensed summary of a chat session.

    Invariants:
    - Never a MemoryEntry. SessionCondenser must not create Proposal or MemoryEntry rows.
    - Derived context only: can be regenerated, superseded, or discarded.
    - Multiple versions per session are kept; only one has status="active".
    - version is monotonically increasing per session (unique per session).
    """

    __tablename__ = "session_summaries"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=False, index=True)
    session_id: Mapped[str] = mapped_column(UUID_COL, ForeignKey("sessions.id"), nullable=False, index=True)
    user_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("users.id"), nullable=True, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)
    summary_text: Mapped[str] = mapped_column(Text, nullable=False)
    source_message_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_first_message_id: Mapped[Optional[str]] = mapped_column(
        UUID_COL,
        ForeignKey("messages.id", name="fk_session_summaries_source_first_message_id_messages", ondelete="SET NULL"),
        nullable=True,
    )
    source_last_message_id: Mapped[Optional[str]] = mapped_column(
        UUID_COL,
        ForeignKey("messages.id", name="fk_session_summaries_source_last_message_id_messages", ondelete="SET NULL"),
        nullable=True,
    )
    summary_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    token_estimate_before: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    token_estimate_after: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    condenser_version: Mapped[str] = mapped_column(String(64), nullable=False, default="pattern.v1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)

    __table_args__ = (
        CheckConstraint("status in ('active', 'superseded')", name="ck_session_summaries_status"),
        UniqueConstraint("session_id", "version", name="uq_session_summaries_session_version"),
        Index("ix_session_summaries_session_status", "session_id", "status"),
        Index("ix_session_summaries_space_session_status", "space_id", "session_id", "status"),
        Index(
            "ix_session_summaries_one_active_per_session",
            "session_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
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
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
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
    policy_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

    policy_key: Mapped[Optional[str]] = mapped_column(String(256), nullable=True, index=True)
    policy_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=text("1"))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", server_default=text("'active'"), index=True)
    enforcement_mode: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    rule_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    applies_to_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    supersedes_policy_id: Mapped[Optional[str]] = mapped_column(
        UUID_COL,
        ForeignKey(
            "policies.id",
            name="fk_policies_supersedes_policy_id_policies",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )
    created_from_proposal_id: Mapped[Optional[str]] = mapped_column(
        UUID_COL,
        ForeignKey(
            "proposals.id",
            name="fk_policies_created_from_proposal_id_proposals",
            ondelete="SET NULL",
            use_alter=True,
        ),
        nullable=True,
        index=True,
    )

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
    source_refs_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
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
    retrieval_trace_json: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    token_budget_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    policy_bundle_version: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    memory_digest_version: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    workspace_digest_version: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # Runtime-facing context bundle fields. These represent the rendered context
    # sent to an external runtime (Codex, Claude Code, OpenCode, etc.).
    execution_plane_id: Mapped[Optional[str]] = mapped_column(
        UUID_COL,
        ForeignKey(
            "execution_planes.id",
            name="fk_context_snapshots_execution_plane_id_execution_planes",
            ondelete="SET NULL",
            use_alter=True,
        ),
        nullable=True,
    )
    included_memory_refs_json: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    included_evidence_refs_json: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    included_file_refs_json: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    included_doc_refs_json: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    redactions_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    data_exposure_level: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    rendered_context_uri: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    # Prefer rendered_context_uri for large rendered contexts. Use rendered_context_text
    # only for small inline contexts or fallback/debug — large payloads bloat the row.
    rendered_context_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Chat-path context fields — link this snapshot to the agent, session, and run that
    # requested it.  All three carry deferred FKs (ALTER TABLE) to avoid circular table
    # creation ordering: context_snapshots is created before agents/sessions/runs.
    # run_id specifically avoids a circular FK loop: runs.context_snapshot_id already
    # points here; we add the reverse direction via use_alter=True.
    agent_id: Mapped[Optional[str]] = mapped_column(
        UUID_COL,
        ForeignKey(
            "agents.id",
            name="fk_context_snapshots_agent_id_agents",
            ondelete="SET NULL",
            use_alter=True,
        ),
        nullable=True,
        index=True,
    )
    session_id: Mapped[Optional[str]] = mapped_column(
        UUID_COL,
        ForeignKey(
            "sessions.id",
            name="fk_context_snapshots_session_id_sessions",
            ondelete="SET NULL",
            use_alter=True,
        ),
        nullable=True,
        index=True,
    )
    run_id: Mapped[Optional[str]] = mapped_column(
        UUID_COL,
        ForeignKey(
            "runs.id",
            name="fk_context_snapshots_run_id_runs",
            ondelete="SET NULL",
            use_alter=True,
        ),
        nullable=True,
        index=True,
    )
    # Serialised ContextRequest that produced this snapshot (for audit/debug).
    request_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "data_exposure_level is null or data_exposure_level in ('local_only', 'model_provider', 'vendor_platform', 'third_party_tools', 'unknown')",
            name="ck_context_snapshots_data_exposure_level",
        ),
    )

    items: Mapped[list["ContextSnapshotItem"]] = relationship(
        "ContextSnapshotItem",
        back_populates="context_snapshot",
        cascade="all, delete-orphan",
        order_by="ContextSnapshotItem.created_at",
    )


# ---------------------------------------------------------------------------
# ContextSnapshotItem — per-item audit record for a ContextSnapshot
# ---------------------------------------------------------------------------


class ContextSnapshotItem(Base):
    """Audit record of a single item included in a ContextSnapshot.

    Created by ChatContextBuilder.persist_snapshot() to record what was actually
    selected for a model call.  item_id is a nullable reference to the originating
    row (memory_id, knowledge_item_id, etc.) with no FK constraint since item_type
    varies across many source tables (polymorphic association).
    """

    __tablename__ = "context_snapshot_items"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    context_snapshot_id: Mapped[str] = mapped_column(
        UUID_COL, ForeignKey("context_snapshots.id"), nullable=False, index=True
    )
    item_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    item_id: Mapped[Optional[str]] = mapped_column(UUID_COL, nullable=True)
    title: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    excerpt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    token_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)

    context_snapshot: Mapped["ContextSnapshot"] = relationship(
        "ContextSnapshot", back_populates="items"
    )

    __table_args__ = (
        CheckConstraint(
            "item_type in ('memory', 'knowledge_item', 'source', 'activity_record', 'task', "
            "'idea', 'project', 'workspace', 'run', 'proposal', 'artifact', 'manual_context')",
            name="ck_context_snapshot_items_item_type",
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
    source_memory_ids_json: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    source_policy_ids_json: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    source_relation_ids_json: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)

    # Hashes for cache invalidation
    source_hash: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    content_hash: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    # Dirty tracking
    dirty_since: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    dirty_reason_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
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


class WorkingDir(Base):
    """Persistent, system-managed runtime working directory (non-git).

    Registry for the persistent working-directory scopes in the CLI sandbox
    scope ladder: ``session`` (lives for a chat session) and ``project`` (lives
    with a non-coding project). Run-scope (``ephemeral``) dirs have no row — they
    are a per-run filesystem dir under ``$SANDBOX_ROOT/ephemeral`` captured by the
    run row + events; repo-scope uses ``Workspace`` (git) + a per-run worktree.

    Provisioned ahead of its implementing stage; see the "CLI sandbox scope
    ladder" stage in ``.agent/architecture/TS_MIGRATION_ROADMAP.md``.
    """

    __tablename__ = "working_dirs"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=False, index=True)
    scope: Mapped[str] = mapped_column(String(16), nullable=False)
    session_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("sessions.id"), nullable=True, index=True)
    project_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("projects.id"), nullable=True, index=True)
    # Path relative to $SANDBOX_ROOT (portable across host/container roots).
    rel_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active", index=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    cleaned_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("scope in ('session', 'project')", name="ck_working_dirs_scope"),
        CheckConstraint("status in ('active', 'cleaning', 'cleaned')", name="ck_working_dirs_status"),
        CheckConstraint(
            "(scope = 'session' AND session_id IS NOT NULL AND project_id IS NULL) "
            "OR (scope = 'project' AND project_id IS NOT NULL AND session_id IS NULL)",
            name="ck_working_dirs_owner",
        ),
        # One working dir per owner (partial unique — only the relevant FK is set).
        Index(
            "ix_working_dirs_session_uniq", "session_id",
            unique=True, postgresql_where=text("session_id IS NOT NULL"),
        ),
        Index(
            "ix_working_dirs_project_uniq", "project_id",
            unique=True, postgresql_where=text("project_id IS NOT NULL"),
        ),
    )


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
    # Set for session/project working-dir scopes; NULL for run-scope ephemeral and
    # repo-scope worktree. See the "CLI sandbox scope ladder" stage in the roadmap.
    working_dir_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("working_dirs.id"), nullable=True, index=True)
    parent_run_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("runs.id"), nullable=True, index=True)
    instructed_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    instructed_by_user_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("users.id"), nullable=True, index=True)
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
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    output_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    usage_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    # Optional primary-task hint; canonical Task<->Run linkage is TaskRun.
    task_id: Mapped[Optional[str]] = mapped_column(
        UUID_COL,
        ForeignKey("tasks.id", name="fk_runs_task_id_tasks", ondelete="SET NULL", use_alter=True),
        nullable=True,
        index=True,
    )
    project_id: Mapped[Optional[str]] = mapped_column(
        UUID_COL,
        ForeignKey("projects.id", name="fk_runs_project_id_projects", ondelete="SET NULL", use_alter=True),
        nullable=True,
        index=True,
    )
    adapter_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    capability_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    model_selection_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="cli_default", server_default=text("'cli_default'"))
    model_override_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    permission_snapshot_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
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
    personal_grant_context_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    # Execution plane fields: where the run executed and at what trust/observability/exposure level.
    # observability_level, data_exposure_level, and trust_level are snapshots copied from the
    # execution plane at run creation time; they do not auto-update when the plane changes.
    execution_plane_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("execution_planes.id"), nullable=True, index=True)
    source: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    observability_level: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    data_exposure_level: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    trust_level: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    externality_level: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    agent: Mapped[Agent] = relationship("Agent", back_populates="runs", foreign_keys=[agent_id])
    agent_version: Mapped[AgentVersion] = relationship("AgentVersion")
    context_snapshot: Mapped[Optional[ContextSnapshot]] = relationship("ContextSnapshot", foreign_keys=[context_snapshot_id])
    session: Mapped[Optional[Session]] = relationship("Session", back_populates="runs")
    parent_run: Mapped[Optional["Run"]] = relationship("Run", remote_side="Run.id", foreign_keys=[parent_run_id])
    artifacts: Mapped[list["Artifact"]] = relationship("Artifact", back_populates="run")
    proposals: Mapped[list["Proposal"]] = relationship("Proposal", back_populates="created_by_run")
    activities: Mapped[list["ActivityRecord"]] = relationship("ActivityRecord", back_populates="source_run")
    steps: Mapped[list["RunStep"]] = relationship("RunStep", back_populates="run", order_by="RunStep.step_index")
    events: Mapped[list["RunEvent"]] = relationship("RunEvent", back_populates="run", order_by="RunEvent.event_index")
    execution_plane: Mapped[Optional[ExecutionPlane]] = relationship("ExecutionPlane", foreign_keys=[execution_plane_id])
    external_run_records: Mapped[list["ExternalRunRecord"]] = relationship("ExternalRunRecord", back_populates="run")
    run_reflections: Mapped[list["RunReflection"]] = relationship("RunReflection", back_populates="run")
    evaluations: Mapped[list["RunEvaluation"]] = relationship(
        "RunEvaluation", back_populates="run", order_by="RunEvaluation.evaluated_at"
    )
    finalizations: Mapped[list["RunFinalization"]] = relationship(
        "RunFinalization", back_populates="run", order_by="RunFinalization.finalized_at"
    )

    __table_args__ = (
        CheckConstraint(
            "status in ('queued', 'running', 'succeeded', 'degraded', 'failed', 'cancelled', 'waiting_for_review')",
            name="ck_runs_status",
        ),
        CheckConstraint("mode in ('live', 'dry_run')", name="ck_runs_mode"),
        CheckConstraint(
            "run_type in ('agent', 'system', 'workflow', 'validation', 'reflection', 'export', 'evolution')",
            name="ck_runs_run_type",
        ),
        CheckConstraint(
            "trigger_origin in ('manual', 'automation', 'job', 'system')",
            name="ck_runs_trigger_origin",
        ),
        CheckConstraint(
            "required_sandbox_level in ('none', 'dry_run', 'ephemeral', 'worktree', 'one_shot_docker')",
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
    # Optional provenance hint; task output linkage remains TaskRun / TaskArtifact / TaskProposal.
    source_task_id: Mapped[Optional[str]] = mapped_column(
        UUID_COL,
        ForeignKey(
            "tasks.id",
            name="fk_activity_records_source_task_id_tasks",
            ondelete="SET NULL",
            use_alter=True,
        ),
        nullable=True,
        index=True,
    )
    project_id: Mapped[Optional[str]] = mapped_column(
        UUID_COL,
        ForeignKey(
            "projects.id",
            name="fk_activity_records_project_id_projects",
            ondelete="SET NULL",
            use_alter=True,
        ),
        nullable=True,
        index=True,
    )
    source_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    activity_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    title: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    payload_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="raw", index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

    source_kind: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    # Default: internal_system — a conservative default that does not over-elevate trust.
    # Callers that know the activity came directly from a user should set user_confirmed.
    source_trust: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    source_integrity_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    entity_refs_json: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    # subject_user_id: who the activity is *about* (distinct from user_id = who created it)
    subject_user_id: Mapped[Optional[str]] = mapped_column(
        UUID_COL,
        ForeignKey("users.id", name="fk_activity_records_subject_user_id_users", ondelete="SET NULL"),
        nullable=True,
        index=True,
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

    source_run: Mapped[Optional[Run]] = relationship("Run", back_populates="activities")

    __table_args__ = (
        CheckConstraint(
            "status in ('raw', 'processed', 'proposals_generated', 'archived')",
            name="ck_activity_records_status",
        ),
        CheckConstraint(
            "consolidation_status in ('pending', 'skipped', 'proposals_generated', 'processed', 'failed')",
            name="ck_activity_records_consolidation_status",
        ),
        CheckConstraint(
            "source_kind is null or source_kind in ("
            "'user_capture', 'chat_message', 'external_chat', 'file_import', "
            "'web_capture', 'run_event', 'workspace_event', 'system_event', "
            "'external_source', 'intake')",
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
    exportable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    export_formats_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    canonical_format: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    preview: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    relevant_period_start: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    relevant_period_end: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    visibility: Mapped[str] = mapped_column(
        String(32), nullable=False, default="space_shared", server_default=text("'space_shared'")
    )
    owner_user_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("users.id"), nullable=True, index=True)
    # Source provenance: which execution plane produced this artifact.
    source_execution_plane_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("execution_planes.id"), nullable=True, index=True)
    trust_level: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    project_id: Mapped[Optional[str]] = mapped_column(
        UUID_COL,
        ForeignKey("projects.id", name="fk_artifacts_project_id_projects", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )


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
    preview: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    payload_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
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
    project_id: Mapped[Optional[str]] = mapped_column(
        UUID_COL,
        ForeignKey("projects.id", name="fk_proposals_project_id_projects", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_by_run: Mapped[Optional[Run]] = relationship("Run", back_populates="proposals")
    approvals: Mapped[list["ProposalApproval"]] = relationship("ProposalApproval", back_populates="proposal")

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
        from .memory import provenance_entries_from_payload

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
        from .memory import first_activity_id, provenance_entries_from_payload

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
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
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
            postgresql_where=text("status = 'approved'"),
        ),
        Index("ix_proposal_approvals_created_at", "created_at"),
    )


# ---------------------------------------------------------------------------
# Evolution substrate — targets, signals, and scoped capability artifacts
# ---------------------------------------------------------------------------


class CapabilityVersion(Base):
    """Proposal-approved capability artifact version.

    Core capability manifests remain file-defined defaults. Rows here represent
    scoped forks or imported/manual/evolved artifacts and point at artifact
    storage rather than embedding large prompt bodies.
    """

    __tablename__ = "capability_versions"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    capability_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    scope_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    scope_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    parent_version_id: Mapped[Optional[str]] = mapped_column(
        UUID_COL,
        ForeignKey("capability_versions.id", name="fk_capability_versions_parent_version_id"),
        nullable=True,
        index=True,
    )
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="evolution", index=True)
    artifact_uri: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    content_ref: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    content_hash: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft", index=True)
    proposal_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("proposals.id"), nullable=True, index=True)
    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

    parent_version: Mapped[Optional["CapabilityVersion"]] = relationship("CapabilityVersion", remote_side="CapabilityVersion.id")

    __table_args__ = (
        Index(
            "ix_capability_versions_key_scope_status",
            "capability_key",
            "scope_type",
            "scope_id",
            "status",
        ),
    )


class CapabilityOverlay(Base):
    """Scoped capability overlay layered over a core/default capability version."""

    __tablename__ = "capability_overlays"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    capability_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    scope_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    scope_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    base_version_id: Mapped[Optional[str]] = mapped_column(
        UUID_COL,
        ForeignKey("capability_versions.id", name="fk_capability_overlays_base_version_id"),
        nullable=True,
        index=True,
    )
    overlay_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    patch_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft", index=True)
    proposal_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("proposals.id"), nullable=True, index=True)
    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

    base_version: Mapped[Optional[CapabilityVersion]] = relationship("CapabilityVersion")

    __table_args__ = (
        Index(
            "ix_capability_overlays_key_scope_status",
            "capability_key",
            "scope_type",
            "scope_id",
            "status",
        ),
    )


class EvolutionTarget(Base):
    """Product/system object that can receive evolution signals and proposals."""

    __tablename__ = "evolution_targets"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    space_id: Mapped[Optional[str]] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=True, index=True)
    target_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    target_ref_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    target_ref_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    capability_key: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    current_version_id: Mapped[Optional[str]] = mapped_column(
        UUID_COL,
        ForeignKey("capability_versions.id", name="fk_evolution_targets_current_version_id"),
        nullable=True,
        index=True,
    )
    risk_level: Mapped[str] = mapped_column(String(32), nullable=False, default="medium", index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    engine_policy_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

    current_version: Mapped[Optional[CapabilityVersion]] = relationship("CapabilityVersion")
    signals: Mapped[list["EvolutionSignal"]] = relationship("EvolutionSignal", back_populates="target")

    __table_args__ = (
        Index(
            "ix_evolution_targets_space_type_ref_status",
            "space_id",
            "target_type",
            "target_ref_id",
            "status",
        ),
    )


class EvolutionSignal(Base):
    """Queryable evidence that an evolution target may need improvement."""

    __tablename__ = "evolution_signals"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    space_id: Mapped[Optional[str]] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=True, index=True)
    target_id: Mapped[str] = mapped_column(UUID_COL, ForeignKey("evolution_targets.id"), nullable=False, index=True)
    signal_type: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    severity: Mapped[str] = mapped_column(String(32), nullable=False, default="medium", index=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    payload_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)

    target: Mapped[EvolutionTarget] = relationship("EvolutionTarget", back_populates="signals")

    __table_args__ = (
        Index(
            "ix_evolution_signals_space_target_type_created",
            "space_id",
            "target_id",
            "signal_type",
            "created_at",
        ),
    )


# ---------------------------------------------------------------------------
# Knowledge — human-browsable relational long-term content
# ---------------------------------------------------------------------------


class KnowledgeItem(Base):
    """Versioned, proposal-approved Knowledge content.

    Knowledge is intentionally separate from Memory: these rows are not runtime
    context entries and must not be injected into ContextBuilder automatically.
    """

    __tablename__ = "knowledge_items"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=False, index=True)
    project_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("projects.id"), nullable=True, index=True)
    workspace_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("workspaces.id"), nullable=True, index=True)
    root_item_id: Mapped[Optional[str]] = mapped_column(
        UUID_COL,
        ForeignKey("knowledge_items.id", name="fk_knowledge_items_root_item_id_knowledge_items", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    supersedes_item_id: Mapped[Optional[str]] = mapped_column(
        UUID_COL,
        ForeignKey(
            "knowledge_items.id",
            name="fk_knowledge_items_supersedes_item_id_knowledge_items",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )
    item_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    slug: Mapped[Optional[str]] = mapped_column(String(512), nullable=True, index=True)
    aliases_json: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    content_format: Mapped[str] = mapped_column(String(32), nullable=False, default="markdown")
    content_schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    plain_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    excerpt: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)
    visibility: Mapped[str] = mapped_column(String(32), nullable=False, default="space_shared", index=True)
    verification_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unverified")
    reflection_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unreviewed")
    tags_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    source_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    owner_user_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("users.id"), nullable=True, index=True)
    created_by_user_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("users.id"), nullable=True)
    created_by_agent_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("agents.id"), nullable=True)
    created_by_run_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("runs.id"), nullable=True)
    source_activity_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("activity_records.id"), nullable=True)
    source_artifact_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("artifacts.id"), nullable=True)
    created_from_proposal_id: Mapped[Optional[str]] = mapped_column(
        UUID_COL, ForeignKey("proposals.id"), nullable=True, index=True
    )
    approved_by_user_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("users.id"), nullable=True)
    redirect_to_item_id: Mapped[Optional[str]] = mapped_column(
        UUID_COL,
        ForeignKey(
            "knowledge_items.id",
            name="fk_knowledge_items_redirect_to_item_id_knowledge_items",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    deprecated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "item_type in ('concept', 'claim', 'lesson', 'procedure', 'decision', "
            "'question', 'answer', 'summary')",
            name="ck_knowledge_items_item_type",
        ),
        CheckConstraint(
            "content_format in ('markdown', 'plain', 'prosemirror_json')",
            name="ck_knowledge_items_content_format",
        ),
        CheckConstraint(
            "status in ('draft', 'active', 'superseded', 'archived')",
            name="ck_knowledge_items_status",
        ),
        CheckConstraint(
            "visibility in ('private', 'space_shared', 'workspace_shared', 'restricted')",
            name="ck_knowledge_items_visibility",
        ),
        CheckConstraint(
            "verification_status in ('unverified', 'needs_review', 'verified')",
            name="ck_knowledge_items_verification_status",
        ),
        CheckConstraint(
            "reflection_status in ('unreviewed', 'reviewed', 'distilled')",
            name="ck_knowledge_items_reflection_status",
        ),
        CheckConstraint("confidence is null or (confidence >= 0 and confidence <= 1)", name="ck_knowledge_items_confidence"),
        # Slug is for readable URLs only; it is intentionally NOT globally unique
        # because version history keeps multiple rows per logical item sharing a
        # slug. Stable page identity is root_item_id / id, not slug.
        Index("ix_knowledge_items_space_slug", "space_id", "slug"),
    )


class KnowledgeItemRelation(Base):
    """Semantic wiki graph relation between two same-space KnowledgeItem rows.

    This is the item-to-item layer. Evidence/provenance links from an item to a
    Source live on KnowledgeItemSource, not here. A question item and its answer
    item (both first-class KnowledgeItem types) are linked with a generic
    ``related_to`` relation; there is no dedicated ``answers`` relation type.
    """

    __tablename__ = "knowledge_item_relations"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=False, index=True)
    from_item_id: Mapped[str] = mapped_column(UUID_COL, ForeignKey("knowledge_items.id"), nullable=False, index=True)
    to_item_id: Mapped[str] = mapped_column(UUID_COL, ForeignKey("knowledge_items.id"), nullable=False, index=True)
    relation_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    evidence_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_proposal_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("proposals.id"), nullable=True)
    created_by_user_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("users.id"), nullable=True)
    created_by_agent_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("agents.id"), nullable=True)
    # Reserved for a future durable assessment table; no target table exists yet.
    created_from_assessment_id: Mapped[Optional[str]] = mapped_column(UUID_COL, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

    __table_args__ = (
        CheckConstraint(
            "relation_type in ('related_to', 'explains', 'depends_on', 'prerequisite_of', "
            "'part_of', 'example_of', 'applies_to', 'supports', 'contradicts', "
            "'derived_from', 'summarizes', 'updates')",
            name="ck_knowledge_item_relations_relation_type",
        ),
        CheckConstraint(
            "status in ('candidate', 'active', 'rejected', 'archived')",
            name="ck_knowledge_item_relations_status",
        ),
        CheckConstraint(
            "confidence is null or (confidence >= 0 and confidence <= 1)",
            name="ck_knowledge_item_relations_confidence",
        ),
        Index(
            "ix_knowledge_item_relations_unique_active",
            "space_id",
            "from_item_id",
            "to_item_id",
            "relation_type",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )


class Source(Base):
    """First-class provenance / evidence object backing wiki KnowledgeItems.

    Source is NOT a semantic wiki item and must never appear in the main
    KnowledgeItem list. It represents raw material / evidence (a webpage, paper,
    chat capture, processed ActivityRecord, ...). A Source may point back to an
    existing ActivityRecord via ``source_activity_id`` (the raw capture layer) or
    to any other origin through ``content_ref`` / ``metadata_json``.
    """

    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    uri: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    content_ref: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    raw_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="raw", index=True)
    source_activity_id: Mapped[Optional[str]] = mapped_column(
        UUID_COL, ForeignKey("activity_records.id"), nullable=True, index=True
    )
    created_by_user_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("users.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

    __table_args__ = (
        CheckConstraint(
            "source_type in ('activity_record', 'chat_capture', 'webpage', 'article', "
            "'paper', 'pdf', 'file', 'email', 'manual_reference', 'external_note')",
            name="ck_sources_source_type",
        ),
        CheckConstraint(
            "status in ('raw', 'processing', 'processed', 'archived', 'error')",
            name="ck_sources_status",
        ),
    )


class KnowledgeItemSource(Base):
    """Evidence/provenance link between a KnowledgeItem and a Source.

    This join table records *why* a Source backs an item (derived_from,
    supported_by, cites, summarizes, mentions). It is strictly for item->source
    evidence; semantic item->item relations live on KnowledgeItemRelation.
    """

    __tablename__ = "knowledge_item_sources"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=False, index=True)
    knowledge_item_id: Mapped[str] = mapped_column(
        UUID_COL, ForeignKey("knowledge_items.id"), nullable=False, index=True
    )
    source_id: Mapped[str] = mapped_column(UUID_COL, ForeignKey("sources.id"), nullable=False, index=True)
    relation_type: Mapped[str] = mapped_column(String(32), nullable=False, default="derived_from", index=True)
    locator: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    quote: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_by_user_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)

    __table_args__ = (
        CheckConstraint(
            "relation_type in ('derived_from', 'supported_by', 'cites', 'summarizes', 'mentions')",
            name="ck_knowledge_item_sources_relation_type",
        ),
        CheckConstraint(
            "confidence is null or (confidence >= 0 and confidence <= 1)",
            name="ck_knowledge_item_sources_confidence",
        ),
        Index(
            "ix_knowledge_item_sources_unique",
            "knowledge_item_id",
            "source_id",
            "relation_type",
            unique=True,
        ),
    )


class Note(Base):
    """Working knowledge: freely-editable notes (direct CRUD, no proposal gate).

    Notes are the *working* layer of the Knowledge domain. Unlike KnowledgeItem
    (canonical wiki content, proposal-gated and versioned) a note evolves freely
    and is edited directly by its owner — meeting notes, design notes, research
    and thinking notes. Promotion of a note into canonical wiki knowledge happens
    later through the normal KnowledgeItem proposal flow; the relationship is then
    recorded on the generic EntityLink layer (e.g. ``source_for`` / ``derived_from``).

    Content is stored as ``content_json`` (ProseMirror JSON once a rich editor is
    wired) plus the derived ``plain_text`` / ``excerpt`` projections used for list
    previews and future search. The current editor ships markdown/plain text.
    """

    __tablename__ = "notes"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    content_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    content_format: Mapped[str] = mapped_column(String(32), nullable=False, default="markdown")
    content_schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    plain_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    excerpt: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)
    primary_project_id: Mapped[Optional[str]] = mapped_column(
        UUID_COL, ForeignKey("projects.id"), nullable=True, index=True
    )
    created_from_activity_id: Mapped[Optional[str]] = mapped_column(
        UUID_COL, ForeignKey("activity_records.id"), nullable=True
    )
    created_by_user_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("users.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

    __table_args__ = (
        CheckConstraint(
            "content_format in ('markdown', 'plain', 'prosemirror_json')",
            name="ck_notes_content_format",
        ),
        CheckConstraint(
            "status in ('active', 'archived', 'deleted')",
            name="ck_notes_status",
        ),
    )


class NoteCollection(Base):
    """Space-scoped, user-configurable folders for Notes.

    PARA is seeded as an initial folder template, but collection rows are the
    source of truth for the Notes tree. ``system_role`` is internal behavior:
    only Inbox and Archive receive special protection.
    """

    __tablename__ = "note_collections"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=False, index=True)
    parent_id: Mapped[Optional[str]] = mapped_column(
        UUID_COL,
        ForeignKey("note_collections.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    system_role: Mapped[str] = mapped_column(String(32), nullable=False, default="normal", index=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_hidden: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

    __table_args__ = (
        CheckConstraint("system_role in ('normal', 'inbox', 'archive')", name="ck_note_collections_system_role"),
        CheckConstraint("parent_id is null or parent_id <> id", name="ck_note_collections_not_self_parent"),
        Index(
            "ix_note_collections_one_inbox_per_space",
            "space_id",
            unique=True,
            postgresql_where=text("system_role = 'inbox'"),
        ),
        Index(
            "ix_note_collections_one_archive_per_space",
            "space_id",
            unique=True,
            postgresql_where=text("system_role = 'archive'"),
        ),
        Index("ix_note_collections_parent_sort", "space_id", "parent_id", "sort_order"),
    )


class NoteCollectionItem(Base):
    """Membership of a Note in a collection."""

    __tablename__ = "note_collection_items"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    collection_id: Mapped[str] = mapped_column(
        UUID_COL, ForeignKey("note_collections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    note_id: Mapped[str] = mapped_column(UUID_COL, ForeignKey("notes.id", ondelete="CASCADE"), nullable=False, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)

    __table_args__ = (
        UniqueConstraint("collection_id", "note_id", name="uq_note_collection_items_collection_note"),
    )


class EntityLink(Base):
    """Generic directional relation between two same-space domain objects.

    The cross-object link layer for the Knowledge domain: it connects a note to
    another note, a wiki KnowledgeItem, a Source, a Project, a Workspace, an
    ActivityRecord, a Run, or a Proposal without hardcoding a join table per pair.
    ``source_id`` / ``target_id`` are polymorphic (resolved via ``source_type`` /
    ``target_type``) and are therefore intentionally not foreign keys.

    EntityLink complements — and does not replace — the type-specific tables:
      * KnowledgeItemRelation — governed wiki item <-> item semantic graph.
      * KnowledgeItemSource   — wiki item <-> Source evidence links.
      * ProvenanceLink        — provenance into memory/policy/knowledge targets.
    It is the user-facing working relation layer (direct CRUD), primarily for notes.
    """

    __tablename__ = "entity_links"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    source_id: Mapped[str] = mapped_column(UUID_COL, nullable=False, index=True)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    target_id: Mapped[str] = mapped_column(UUID_COL, nullable=False, index=True)
    link_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="accepted", index=True)
    created_by_user_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)

    __table_args__ = (
        CheckConstraint(
            "source_type in ('note', 'knowledge_item', 'source', 'project', "
            "'workspace', 'activity', 'run', 'proposal')",
            name="ck_entity_links_source_type",
        ),
        CheckConstraint(
            "target_type in ('note', 'knowledge_item', 'source', 'project', "
            "'workspace', 'activity', 'run', 'proposal')",
            name="ck_entity_links_target_type",
        ),
        CheckConstraint(
            "link_type in ('references', 'related_to', 'belongs_to', "
            "'captured_from', 'source_for', 'derived_from')",
            name="ck_entity_links_link_type",
        ),
        CheckConstraint(
            "status in ('suggested', 'accepted', 'rejected')",
            name="ck_entity_links_status",
        ),
        CheckConstraint(
            "confidence is null or (confidence >= 0 and confidence <= 1)",
            name="ck_entity_links_confidence",
        ),
        Index(
            "ix_entity_links_unique_accepted",
            "space_id",
            "source_type",
            "source_id",
            "target_type",
            "target_id",
            "link_type",
            unique=True,
            postgresql_where=text("status = 'accepted'"),
        ),
    )


# ---------------------------------------------------------------------------
# Cards (knowledge review / spaced-repetition foundation)
# ---------------------------------------------------------------------------


class Card(Base):
    """Shared card content derived from knowledge objects.

    Card content is space-scoped; review scheduling and history are user-specific
    (CardReviewState / CardReview). source_type / source_id are polymorphic
    back-references to the originating object and are intentionally not FKs
    (allowlisted in the DDL semantics test).
    """

    __tablename__ = "cards"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=False, index=True)
    card_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    front: Mapped[str] = mapped_column(Text, nullable=False)
    back: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    source_id: Mapped[Optional[str]] = mapped_column(UUID_COL, nullable=True, index=True)  # polymorphic, no FK
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)
    created_by_user_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    review_states: Mapped[list["CardReviewState"]] = relationship(
        "CardReviewState", back_populates="card", cascade="all, delete-orphan"
    )
    reviews: Mapped[list["CardReview"]] = relationship(
        "CardReview", back_populates="card", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("card_type in ('basic', 'cloze')", name="ck_cards_card_type"),
        CheckConstraint(
            "status in ('draft', 'active', 'suspended', 'archived')",
            name="ck_cards_status",
        ),
        CheckConstraint(
            "source_type is null or source_type in "
            "('note', 'knowledge_item', 'source', 'activity', 'run', 'proposal')",
            name="ck_cards_source_type",
        ),
        Index("ix_cards_source", "source_type", "source_id"),
    )


class CardReviewState(Base):
    """Per-user FSRS scheduling state for a card. One row per (card, user) pair.

    FSRS fields (stability, difficulty, elapsed_days, scheduled_days, state) are
    populated by the review scheduler once implemented. The row can exist before
    the first review is processed — all scheduling fields are nullable.
    """

    __tablename__ = "card_review_states"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    card_id: Mapped[str] = mapped_column(UUID_COL, ForeignKey("cards.id"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(UUID_COL, ForeignKey("users.id"), nullable=False)
    due_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    stability: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    difficulty: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    elapsed_days: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    scheduled_days: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    reps: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lapses: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    state: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    last_reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

    card: Mapped["Card"] = relationship("Card", back_populates="review_states")

    __table_args__ = (
        CheckConstraint(
            "state is null or state in ('new', 'learning', 'review', 'relearning')",
            name="ck_card_review_states_state",
        ),
        UniqueConstraint("card_id", "user_id", name="uq_card_review_states_card_user"),
        Index("ix_card_review_states_user_due", "user_id", "due_at"),
    )


class CardReview(Base):
    """Append-only review history entry recorded each time a user rates a card.

    Ratings follow the FSRS scale: again | hard | good | easy.
    review_state_snapshot_json captures the CardReviewState at review time for
    scheduler replay/audit. duration_ms is the display time before the user rated.
    """

    __tablename__ = "card_reviews"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    card_id: Mapped[str] = mapped_column(UUID_COL, ForeignKey("cards.id"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(UUID_COL, ForeignKey("users.id"), nullable=False)
    rating: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    review_state_snapshot_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)

    card: Mapped["Card"] = relationship("Card", back_populates="reviews")

    __table_args__ = (
        CheckConstraint(
            "rating in ('again', 'hard', 'good', 'easy')",
            name="ck_card_reviews_rating",
        ),
        Index("ix_card_reviews_user_reviewed_at", "user_id", "reviewed_at"),
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
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
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
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
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

    acceptance_criteria_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    definition_of_done: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    required_outputs_json: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)

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

    policy_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    tags: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)

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
    run_evaluation_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("run_evaluations.id"), nullable=True, index=True)
    evaluator_type: Mapped[str] = mapped_column(String(32), nullable=False)
    evaluator_user_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("users.id"), nullable=True)
    evaluator_agent_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("agents.id"), nullable=True)
    score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    checklist_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    known_issues_json: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    evidence_artifact_ids: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
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
    payload_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    result_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    # Durable queue scheduling time. NOT NULL with a server default so a row can
    # always be ordered by the claim query even if a writer omits it; enqueue()
    # still sets it explicitly. Claim semantics require scheduled_at <= now().
    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now, server_default=text("now()")
    )
    claimed_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    claimed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

    # Extra job linkage fields used by the queue worker surface.
    user_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("users.id"), nullable=True, index=True)
    workspace_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("workspaces.id"), nullable=True, index=True)
    agent_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("agents.id"), nullable=True, index=True)
    events: Mapped[list["JobEvent"]] = relationship("JobEvent", back_populates="job", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint(
            "status in ('pending', 'claimed', 'running', 'completed', 'failed', 'cancelled')",
            name="ck_jobs_status",
        ),
        CheckConstraint("attempts >= 0", name="ck_jobs_attempts_nonneg"),
        CheckConstraint("max_attempts > 0", name="ck_jobs_max_attempts_positive"),
        # Pending-claim index: matches the SELECT ... FOR UPDATE SKIP LOCKED claim
        # query (WHERE status='pending' AND scheduled_at <= now ORDER BY priority
        # DESC, scheduled_at ASC). Partial on pending so the index stays small.
        Index(
            "ix_jobs_claim_pending",
            text("priority DESC"),
            "scheduled_at",
            postgresql_where=text("status = 'pending'"),
        ),
        # Filtered-worker variant: workers that claim a subset of job_types.
        Index(
            "ix_jobs_type_claim_pending",
            "job_type",
            text("priority DESC"),
            "scheduled_at",
            postgresql_where=text("status = 'pending'"),
        ),
    )


class JobEvent(Base):
    """Infrastructure queue event log. Not a product-level Automation object."""

    __tablename__ = "job_events"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    job_id: Mapped[str] = mapped_column(UUID_COL, ForeignKey("jobs.id"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
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
    selected_user_ids: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    last_confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    workspace_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("workspaces.id"), nullable=True, index=True)
    project_id: Mapped[Optional[str]] = mapped_column(
        UUID_COL,
        ForeignKey("projects.id", name="fk_memory_entries_project_id_projects", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
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
    tags: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)

    memory_layer: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    memory_kind: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    event_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    event_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    last_retrieved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    root_memory_id: Mapped[Optional[str]] = mapped_column(
        UUID_COL,
        ForeignKey("memory_entries.id", name="fk_memory_entries_root_memory_id_memory_entries", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    supersedes_memory_id: Mapped[Optional[str]] = mapped_column(
        UUID_COL,
        ForeignKey(
            "memory_entries.id",
            name="fk_memory_entries_supersedes_memory_id_memory_entries",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )
    source_trust: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    created_from_proposal_id: Mapped[Optional[str]] = mapped_column(
        UUID_COL, ForeignKey("proposals.id"), nullable=True, index=True
    )

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
# Provenance / relation tables
# ---------------------------------------------------------------------------


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
    evidence_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
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

    Constraints enforced by ActorService (service-layer rules, not DB-level constraints):
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
    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
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
    workspace_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("workspaces.id"), nullable=True, index=True)
    session_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("sessions.id"), nullable=True, index=True)
    task_id: Mapped[Optional[str]] = mapped_column(
        UUID_COL,
        ForeignKey("tasks.id", name="fk_run_steps_task_id_tasks", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    artifact_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("artifacts.id"), nullable=True, index=True)
    proposal_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("proposals.id"), nullable=True, index=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    input_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    output_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_type: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
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


class RunEvent(Base):
    """Structured append-only harness evidence record for a Run.

    RunEvent is finer-grained than RunStep but coarser than raw adapter logs.
    It captures each significant phase of a run as a structured record (context
    compilation, runtime selection, sandbox creation, adapter invocation/completion,
    artifact ingestion, patch collection, validation, proposal creation, evaluation).

    Append-only: rows are never updated or deleted. event_index is MAX()+1 scoped
    to (space_id, run_id) — the same documented distributed-writer risk as RunStep.

    RunEvent is evidence; it references Artifact, Proposal, RunStep, etc. but does
    not replace them. Never stores raw credentials, stdout/stderr, full rendered
    context, full patch bodies, or raw private memory text.
    """

    __tablename__ = "run_events"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=False, index=True)
    run_id: Mapped[str] = mapped_column(UUID_COL, ForeignKey("runs.id"), nullable=False, index=True)
    step_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("run_steps.id"), nullable=True, index=True)
    actor_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("actors.id"), nullable=True, index=True)
    event_index: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_code: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    workspace_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("workspaces.id"), nullable=True, index=True)
    artifact_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("artifacts.id"), nullable=True, index=True)
    proposal_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("proposals.id"), nullable=True, index=True)
    data_exposure_level: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    trust_level: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, index=True)

    run: Mapped["Run"] = relationship("Run", back_populates="events")

    __table_args__ = (
        UniqueConstraint("space_id", "run_id", "event_index", name="uq_run_events_space_run_event_index"),
        CheckConstraint(
            "event_type in ("
            "'context_compiled', 'runtime_selected', 'credential_granted', "
            "'sandbox_created', 'policy_checked', 'adapter_invoked', 'adapter_completed', "
            "'artifact_ingested', 'patch_collected', 'validation_started', "
            "'validation_completed', 'proposal_created', 'evaluation_created', "
            "'run_finalized')",
            name="ck_run_events_event_type",
        ),
        CheckConstraint(
            "status in ('pending', 'running', 'succeeded', 'failed', 'skipped', 'warning', 'cancelled')",
            name="ck_run_events_status",
        ),
        CheckConstraint(
            "data_exposure_level is null or data_exposure_level in "
            "('local_only', 'model_provider', 'vendor_platform', 'third_party_tools', 'unknown')",
            name="ck_run_events_data_exposure_level",
        ),
        CheckConstraint(
            "trust_level is null or trust_level in ('high', 'medium', 'low', 'unknown')",
            name="ck_run_events_trust_level",
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
    evidence_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)

    __table_args__ = (
        CheckConstraint(
            "source_type in ('activity', 'proposal', 'memory', 'artifact', "
            "'run_step', 'external_source', 'user_confirmation', "
            "'intake_item', 'source_snapshot', 'extracted_evidence', 'run_event')",
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
    memory_filter_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
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
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
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
    commands_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    required_checks_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    artifact_expectations_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
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
    tech_stack_json: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    important_paths_json: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    forbidden_paths_json: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    test_commands_json: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    build_commands_json: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    architecture_boundaries_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    current_focus: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    known_failures_json: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    validation_recipe_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("validation_recipes.id"), nullable=True)
    cloud_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    max_data_exposure_level: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    min_observability_level: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

    workspace: Mapped["Workspace"] = relationship("Workspace", back_populates="profile", foreign_keys=[workspace_id])
    validation_recipe: Mapped[Optional[ValidationRecipe]] = relationship("ValidationRecipe")

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
    runtime_adapter_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    execution_plane_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("execution_planes.id"), nullable=True, index=True)
    external_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    observability_level: Mapped[str] = mapped_column(String(64), nullable=False, default="black_box")
    data_exposure_level: Mapped[str] = mapped_column(String(64), nullable=False, default="unknown")
    trace_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    raw_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    raw_output_uri: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    imported_diff_uri: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    imported_artifacts_json: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    imported_logs_uri: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="imported")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)

    run: Mapped["Run"] = relationship("Run", back_populates="external_run_records", foreign_keys=[run_id])
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
    reusable_rules_json: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    reusable_commands_json: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    workspace_facts_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    memory_candidates_json: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    capability_candidates_json: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    policy_candidates_json: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    validation_candidates_json: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    follow_up_tasks_json: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)

    run: Mapped["Run"] = relationship("Run", back_populates="run_reflections", foreign_keys=[run_id])

    __table_args__ = (
        CheckConstraint(
            "source in ('native', 'external_import', 'manual', 'evaluator')",
            name="ck_run_reflections_source",
        ),
    )


class RunEvaluation(Base):
    """Deterministic harness-level evaluation of a completed Run.

    Append-only: each call to RunEvaluationService.evaluate() creates a new row.
    Existing evaluations are never deleted or overwritten. GET latest returns the
    most recent evaluation for a run. This preserves classifier-version history
    and auditability.

    Uses only evidence observable at the harness boundary: Run status/error/output,
    ordered RunSteps, ContextSnapshot metadata, Artifacts, Proposals, ValidationRecipe,
    and linked Task/TaskRun. Never uses LLM-as-judge. Never auto-applies proposals.
    """

    __tablename__ = "run_evaluations"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=False, index=True)
    run_id: Mapped[str] = mapped_column(UUID_COL, ForeignKey("runs.id"), nullable=False, index=True)
    evaluator_type: Mapped[str] = mapped_column(String(64), nullable=False, default="deterministic_harness")
    evaluator_version: Mapped[str] = mapped_column(String(64), nullable=False, default="harness_eval.v1", index=True)
    outcome_status: Mapped[str] = mapped_column(String(32), nullable=False)
    failure_layer: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    failure_reason_code: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    trajectory_status: Mapped[str] = mapped_column(String(32), nullable=False)
    evidence_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    rule_trace_json: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, index=True)

    run: Mapped["Run"] = relationship("Run", foreign_keys=[run_id], back_populates="evaluations")

    __table_args__ = (
        CheckConstraint(
            "outcome_status in ('passed', 'failed', 'partial', 'unknown')",
            name="ck_run_evaluations_outcome_status",
        ),
        CheckConstraint(
            "failure_layer is null or failure_layer in ("
            "'context', 'sandbox', 'runtime', 'tool', 'validation', "
            "'policy', 'task_spec', 'orchestration', 'evaluator', 'unknown')",
            name="ck_run_evaluations_failure_layer",
        ),
        CheckConstraint(
            "trajectory_status in ('acceptable', 'incomplete', 'unsafe', 'insufficient_evidence')",
            name="ck_run_evaluations_trajectory_status",
        ),
    )


class RunFinalization(Base):
    """Canonical post-run finalization record.

    Created by PostRunFinalizationService after a Run reaches a terminal state.
    Idempotent per (run_id, finalizer_version): repeated finalization calls return
    the existing completed or failed record without creating duplicate RunEvaluation,
    TaskEvaluation, or run_finalized RunEvent rows.

    Append-only: rows are never updated after creation.
    """

    __tablename__ = "run_finalizations"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=False, index=True)
    run_id: Mapped[str] = mapped_column(UUID_COL, ForeignKey("runs.id"), nullable=False, index=True)
    finalizer_version: Mapped[str] = mapped_column(String(64), nullable=False, default="post_run_finalization.v1")
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    run_evaluation_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("run_evaluations.id"), nullable=True, index=True)
    task_evaluation_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("task_evaluations.id"), nullable=True, index=True)
    outcome_status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    failure_layer: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    failure_reason_code: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    trajectory_status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    skipped_reasons_json: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    error_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    finalized_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)

    run: Mapped["Run"] = relationship("Run", foreign_keys=[run_id], back_populates="finalizations")

    __table_args__ = (
        UniqueConstraint("run_id", "finalizer_version", name="uq_run_finalizations_run_version"),
        CheckConstraint(
            "status in ('completed', 'failed')",
            name="ck_run_finalizations_status",
        ),
        CheckConstraint(
            "outcome_status is null or outcome_status in ('passed', 'failed', 'partial', 'unknown')",
            name="ck_run_finalizations_outcome_status",
        ),
        CheckConstraint(
            "failure_layer is null or failure_layer in ("
            "'context', 'sandbox', 'runtime', 'tool', 'validation', "
            "'policy', 'task_spec', 'orchestration', 'evaluator', 'unknown')",
            name="ck_run_finalizations_failure_layer",
        ),
        CheckConstraint(
            "trajectory_status is null or trajectory_status in "
            "('acceptable', 'incomplete', 'unsafe', 'insufficient_evidence')",
            name="ck_run_finalizations_trajectory_status",
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
    runtime_adapter_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    execution_plane_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("execution_planes.id"), nullable=True, index=True)
    external_type: Mapped[str] = mapped_column(String(64), nullable=False)
    external_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    display_name: Mapped[str] = mapped_column(String(256), nullable=False)
    required_scopes_json: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    credential_ref: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    data_exposure_level: Mapped[str] = mapped_column(String(64), nullable=False, default="unknown")
    observability_level: Mapped[str] = mapped_column(String(64), nullable=False, default="black_box")
    side_effect_level: Mapped[str] = mapped_column(String(32), nullable=False, default="none")
    approval_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

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


class RunExecutionLock(Base):
    """Durable per-run execution lock.

    Inserted when a worker begins executing a Run, deleted when execution
    completes (success, failure, cancellation, or exception).  The PK on
    run_id guarantees that at most one worker can hold the lock for a given
    Run at any time — a second INSERT raises IntegrityError and the caller
    aborts without executing the Run again.

    This is defence-in-depth for the heartbeat / reclaim path: if a job is
    reclaimed as stuck while the original worker is still in adapter.execute(),
    the second worker's lock-acquire fails immediately rather than producing a
    second code_patch proposal for the same run.
    """

    __tablename__ = "run_execution_locks"

    run_id: Mapped[str] = mapped_column(
        UUID_COL, ForeignKey("runs.id"), primary_key=True,
    )
    locked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now,
    )
    worker_id: Mapped[str] = mapped_column(String(64), nullable=False)
    job_id: Mapped[Optional[str]] = mapped_column(
        UUID_COL,
        ForeignKey("jobs.id", name="fk_run_execution_locks_job_id_jobs", ondelete="SET NULL"),
        nullable=True,
    )


class CliCredentialEvent(Base):
    """Durable audit record for CLI credential usage during agent run execution.

    Records metadata only — never stores raw secrets, API keys, tokens,
    HOME paths, credential source paths, or session file contents.

    Populated by CredentialBroker.record_usage() wired through CliRuntimeAdapter.
    """

    __tablename__ = "cli_credential_events"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=False, index=True)
    run_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("runs.id"), nullable=True, index=True)
    runtime_adapter_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    credential_profile_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    # Source of the credential: "profile" | "container_default" | "none".
    # "container_default" is retained only for historical audit rows.
    credential_source: Mapped[str] = mapped_column(String(32), nullable=False, default="none")
    trigger_origin: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    fallback_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    fallback_reason: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    broker_error: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # "ok" | "failed" | "not_needed" | "pending"
    cleanup_status: Mapped[str] = mapped_column(String(32), nullable=False, default="not_needed")
    # "grant" | "grant_denied" | "grant_failed" | "automation_denied" | "cleanup_failed"
    action: Mapped[str] = mapped_column(String(64), nullable=False, default="grant")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)

    __table_args__ = (
        CheckConstraint(
            "credential_source in ('profile', 'container_default', 'none')",
            name="ck_cli_credential_events_credential_source",
        ),
    )


class PolicyDecisionRecord(Base):
    """Append-only durable evidence of sensitive policy decisions.

    Records who requested what action, what the decision was, and why.
    Never stores raw memory content, personal_context_block, credentials,
    prompts, patch body, stdout, stderr, or other sensitive payloads.
    Metadata is sanitized via sanitize_policy_metadata() before persistence.
    """

    __tablename__ = "policy_decision_records"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    space_id: Mapped[Optional[str]] = mapped_column(SPACE_COL, nullable=True, index=True)
    actor_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    actor_id: Mapped[Optional[str]] = mapped_column(UUID_COL, nullable=True, index=True)
    actor_ref_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    action: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    resource_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    resource_id: Mapped[Optional[str]] = mapped_column(String(256), nullable=True, index=True)
    decision: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    risk_level: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    required_approver_role: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    approval_capability: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    policy_rule_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    policy_source: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    policy_id: Mapped[Optional[str]] = mapped_column(UUID_COL, nullable=True)
    audit_code: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    run_id: Mapped[Optional[str]] = mapped_column(UUID_COL, nullable=True, index=True)
    proposal_id: Mapped[Optional[str]] = mapped_column(UUID_COL, nullable=True, index=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now, index=True
    )

    __table_args__ = (
        Index("ix_policy_decision_records_space_created", "space_id", "created_at"),
        Index("ix_policy_decision_records_space_action_created", "space_id", "action", "created_at"),
        Index("ix_policy_decision_records_run_created", "run_id", "created_at"),
        Index("ix_policy_decision_records_proposal_created", "proposal_id", "created_at"),
        Index("ix_policy_decision_records_audit_created", "audit_code", "created_at"),
        CheckConstraint(
            "decision in ('allow', 'deny', 'require_approval')",
            name="ck_policy_decision_records_decision",
        ),
        CheckConstraint(
            "risk_level in ('low', 'medium', 'high', 'critical')",
            name="ck_policy_decision_records_risk_level",
        ),
    )


# ---------------------------------------------------------------------------
# Automation
# ---------------------------------------------------------------------------


class Automation(Base):
    """A user-defined automation rule that can trigger agent runs.

    Automation creation and updates require PolicyGateway.enforce()
    (automation.create / automation.update). Manual fire requires
    automation.fire policy check. All automation-triggered runs carry
    trigger_origin="automation".

    Automation must not directly write Memory, Policy, Workspace files,
    Capability, or Credentials. It may produce Runs which in turn create
    proposals and artifacts via existing gates.

    preflight_snapshot_json stores runtime preflight and policy preflight
    snapshots at creation time. Manual fire reruns both before queuing a new Run.
    """

    __tablename__ = "automations"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=False, index=True)
    owner_user_id: Mapped[str] = mapped_column(UUID_COL, ForeignKey("users.id"), nullable=False, index=True)
    agent_id: Mapped[str] = mapped_column(UUID_COL, ForeignKey("agents.id"), nullable=False, index=True)
    workspace_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("workspaces.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    trigger_type: Mapped[str] = mapped_column(String(64), nullable=False, default="manual")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)
    preflight_snapshot_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    config_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    # Schedule trigger bookkeeping. cron expression + timezone live in config_json
    # ({"cron": "...", "timezone": "..."}). next_run_at is the next due UTC instant
    # (indexed for the scheduler scan); last_fired_at records the last fire.
    next_run_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    last_fired_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

    automation_runs: Mapped[list["AutomationRun"]] = relationship(
        "AutomationRun", back_populates="automation", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "trigger_type in ('manual', 'schedule')",
            name="ck_automations_trigger_type",
        ),
        CheckConstraint(
            "status in ('active', 'paused', 'archived')",
            name="ck_automations_status",
        ),
    )


class AutomationRun(Base):
    """Link record connecting an Automation to the Run it triggered.

    Created by AutomationService.fire() alongside the Run row.
    """

    __tablename__ = "automation_runs"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    automation_id: Mapped[str] = mapped_column(UUID_COL, ForeignKey("automations.id"), nullable=False, index=True)
    run_id: Mapped[str] = mapped_column(UUID_COL, ForeignKey("runs.id"), nullable=False, index=True)
    triggered_by_user_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("users.id"), nullable=True, index=True)
    trigger_type: Mapped[str] = mapped_column(String(64), nullable=False, default="manual")
    preflight_snapshot_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)

    automation: Mapped["Automation"] = relationship("Automation", back_populates="automation_runs")

    __table_args__ = (
        Index("ix_automation_runs_automation_created", "automation_id", "created_at"),
    )


class AutomationCredentialGrant(Base):
    """One-time pre-authorization for an automation's unattended credential use.

    Created when a scheduled Automation is created (the owner/admin act of creating
    the automation is the explicit approval). While an active grant exists, the
    ``runtime.use_credential`` policy gate ALLOWs same-space credential use for runs
    fired by this automation (trigger_origin="automation") instead of the default
    REQUIRE_APPROVAL. Cross-space credential use remains hard-denied regardless.

    Revoked when the automation is archived. The grant authorizes the automation's
    same-space credential use only; it never widens space boundaries.
    """

    __tablename__ = "automation_credential_grants"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=False, index=True)
    automation_id: Mapped[str] = mapped_column(
        UUID_COL, ForeignKey("automations.id"), nullable=False, index=True
    )
    granted_by_user_id: Mapped[str] = mapped_column(UUID_COL, ForeignKey("users.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by_user_id: Mapped[Optional[str]] = mapped_column(
        UUID_COL, ForeignKey("users.id"), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "status in ('active', 'revoked')",
            name="ck_automation_credential_grants_status",
        ),
        Index(
            "ix_automation_credential_grants_lookup",
            "space_id", "automation_id", "status",
        ),
    )


# ---------------------------------------------------------------------------
# Intake and Evidence
# ---------------------------------------------------------------------------


class SourceConnector(Base):
    """Catalog entry describing a supported external or internal intake connector."""

    __tablename__ = "source_connectors"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    connector_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(256), nullable=False)
    connector_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    ingestion_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)
    capabilities_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    config_schema_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

    __table_args__ = (
        CheckConstraint(
            "connector_type in ('external_feed', 'external_url', 'internal_activity', 'internal_artifact', 'internal_run', 'file', 'document')",
            name="ck_source_connectors_connector_type",
        ),
        CheckConstraint(
            "ingestion_mode in ('pull', 'manual', 'internal')",
            name="ck_source_connectors_ingestion_mode",
        ),
        CheckConstraint(
            "status in ('active', 'disabled')",
            name="ck_source_connectors_status",
        ),
    )


class SourceConnection(Base):
    """A configured, space-scoped source connection.

    Connections bind a connector to endpoint/config/credential/consent policy.
    Intake items and extraction jobs reference this object instead of encoding
    connector-specific subscription semantics directly on the item rows.
    """

    __tablename__ = "source_connections"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=False, index=True)
    connector_id: Mapped[str] = mapped_column(UUID_COL, ForeignKey("source_connectors.id"), nullable=False, index=True)
    owner_user_id: Mapped[str] = mapped_column(UUID_COL, ForeignKey("users.id"), nullable=False, index=True)
    credential_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("credentials.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    endpoint_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)
    fetch_frequency: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")
    capture_policy: Mapped[str] = mapped_column(String(64), nullable=False, default="metadata_only")
    trust_level: Mapped[str] = mapped_column(String(32), nullable=False, default="normal")
    topic_hints_json: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    consent_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    policy_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    config_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    last_checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    next_check_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

    __table_args__ = (
        CheckConstraint(
            "status in ('active', 'paused', 'archived')",
            name="ck_source_connections_status",
        ),
        CheckConstraint(
            "fetch_frequency in ('manual', 'hourly', 'daily', 'weekly')",
            name="ck_source_connections_fetch_frequency",
        ),
        CheckConstraint(
            "capture_policy in ('metadata_only', 'excerpt_only', 'auto_extract_relevant', 'auto_extract_all_text', 'archive_all_snapshots')",
            name="ck_source_connections_capture_policy",
        ),
        CheckConstraint(
            "trust_level in ('trusted', 'normal', 'untrusted')",
            name="ck_source_connections_trust_level",
        ),
        Index("ix_source_connections_space_status", "space_id", "status"),
        Index("ix_source_connections_due", "status", "next_check_at"),
        Index(
            "uq_source_connections_active_endpoint",
            "space_id", "connector_id", "endpoint_url",
            unique=True,
            postgresql_where=text("endpoint_url IS NOT NULL AND deleted_at IS NULL AND status != 'archived'"),
        ),
    )


class IntakeItem(Base):
    """A raw external or internal item that has entered a space's intake pool.

    IntakeItem is candidate material. Raw content and extracted text live in
    artifacts/snapshots/evidence rows. Intake does not directly mutate Memory,
    Knowledge, policy, tasks, files, or capabilities.
    """

    __tablename__ = "intake_items"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=False, index=True)
    connection_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("source_connections.id"), nullable=True, index=True)
    item_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_object_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    source_object_id: Mapped[Optional[str]] = mapped_column(UUID_COL, nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(1024), nullable=False)
    source_uri: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    canonical_uri: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_domain: Mapped[Optional[str]] = mapped_column(String(256), nullable=True, index=True)
    source_external_id: Mapped[Optional[str]] = mapped_column(String(512), nullable=True, index=True)
    author: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    occurred_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    content_hash: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    excerpt: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="new", index=True)
    read_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unread")
    content_state: Mapped[str] = mapped_column(String(64), nullable=False, default="metadata_only")
    retention_policy: Mapped[str] = mapped_column(String(32), nullable=False, default="metadata_only")
    relevance_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    novelty_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    raw_artifact_id: Mapped[Optional[str]] = mapped_column(
        UUID_COL,
        ForeignKey("artifacts.id", name="fk_intake_items_raw_artifact_id_artifacts", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    extracted_artifact_id: Mapped[Optional[str]] = mapped_column(
        UUID_COL,
        ForeignKey("artifacts.id", name="fk_intake_items_extracted_artifact_id_artifacts", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    summary_artifact_id: Mapped[Optional[str]] = mapped_column(
        UUID_COL,
        ForeignKey("artifacts.id", name="fk_intake_items_summary_artifact_id_artifacts", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    search_index_ref: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    embedding_index_ref: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

    __table_args__ = (
        CheckConstraint(
            "status in ('new', 'triaged', 'selected', 'ignored', 'archived')",
            name="ck_intake_items_status",
        ),
        CheckConstraint(
            "read_status in ('unread', 'skimmed', 'read', 'discussed')",
            name="ck_intake_items_read_status",
        ),
        CheckConstraint(
            "item_type in ('external_url', 'feed_entry', 'activity_record', 'artifact', 'run_event', 'file', 'document', 'log')",
            name="ck_intake_items_item_type",
        ),
        CheckConstraint(
            "content_state in ('metadata_only', 'excerpt_saved', 'content_queued', 'content_saved', 'snapshot_queued', 'snapshot_saved', 'extraction_failed', 'content_unavailable')",
            name="ck_intake_items_content_state",
        ),
        CheckConstraint(
            "retention_policy in ('metadata_only', 'summary_only', 'full_text', 'full_snapshot', 'archived')",
            name="ck_intake_items_retention_policy",
        ),
        Index("ix_intake_items_space_status", "space_id", "status"),
        Index("ix_intake_items_space_connection", "space_id", "connection_id"),
        Index("ix_intake_items_space_domain", "space_id", "source_domain"),
        Index("ix_intake_items_canonical_uri", "space_id", "canonical_uri"),
        Index("ix_intake_items_source_object", "space_id", "source_object_type", "source_object_id"),
        Index(
            "uq_intake_items_active_canonical_uri",
            "space_id", "canonical_uri",
            unique=True,
            postgresql_where=text("canonical_uri IS NOT NULL AND deleted_at IS NULL"),
        ),
        Index(
            "uq_intake_items_active_source_uri",
            "space_id", "source_uri",
            unique=True,
            postgresql_where=text("source_uri IS NOT NULL AND deleted_at IS NULL"),
        ),
    )


class SourceSnapshot(Base):
    """Immutable metadata for source snapshots captured into Artifact storage."""

    __tablename__ = "source_snapshots"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=False, index=True)
    intake_item_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("intake_items.id"), nullable=True, index=True)
    connection_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("source_connections.id"), nullable=True, index=True)
    snapshot_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    artifact_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("artifacts.id"), nullable=True, index=True)
    content_hash: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    source_uri: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    capture_method: Mapped[str] = mapped_column(String(64), nullable=False, default="manual")
    trust_level: Mapped[str] = mapped_column(String(32), nullable=False, default="normal")
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)

    __table_args__ = (
        CheckConstraint(
            "snapshot_type in ('metadata', 'raw', 'extracted', 'summary')",
            name="ck_source_snapshots_snapshot_type",
        ),
        CheckConstraint(
            "capture_method in ('manual', 'connection_scan', 'full_text', 'snapshot', 'internal')",
            name="ck_source_snapshots_capture_method",
        ),
        CheckConstraint(
            "trust_level in ('trusted', 'normal', 'untrusted')",
            name="ck_source_snapshots_trust_level",
        ),
        Index("ix_source_snapshots_space_item", "space_id", "intake_item_id"),
    )


class ExtractionJob(Base):
    """Durable audit record for intake scan/extraction work."""

    __tablename__ = "extraction_jobs"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=False, index=True)
    connection_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("source_connections.id"), nullable=True, index=True)
    intake_item_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("intake_items.id"), nullable=True, index=True)
    source_snapshot_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("source_snapshots.id"), nullable=True, index=True)
    source_object_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    source_object_id: Mapped[Optional[str]] = mapped_column(UUID_COL, nullable=True, index=True)
    job_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    items_seen: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    items_created: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    items_updated: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    error_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # Sanitized short error description — never raw HTTP response body.
    error_message: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)

    __table_args__ = (
        CheckConstraint(
            "job_type in ('connection_scan', 'manual_url', 'extract_text', 'snapshot', 'normalize_activity', 'normalize_artifact', 'normalize_run_event')",
            name="ck_extraction_jobs_job_type",
        ),
        CheckConstraint(
            "status in ('pending', 'running', 'succeeded', 'failed', 'skipped')",
            name="ck_extraction_jobs_status",
        ),
        Index("ix_extraction_jobs_space_status", "space_id", "status"),
        Index("ix_extraction_jobs_space_created", "space_id", "created_at"),
        Index("ix_extraction_jobs_source_object", "space_id", "source_object_type", "source_object_id"),
    )


class ExtractedEvidence(Base):
    """A citable evidence unit derived from intake, activity, artifacts, or runs."""

    __tablename__ = "extracted_evidence"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=False, index=True)
    intake_item_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("intake_items.id"), nullable=True, index=True)
    extraction_job_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("extraction_jobs.id"), nullable=True, index=True)
    source_snapshot_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("source_snapshots.id"), nullable=True, index=True)
    source_object_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    source_object_id: Mapped[Optional[str]] = mapped_column(UUID_COL, nullable=True, index=True)
    evidence_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(1024), nullable=False)
    content_excerpt: Mapped[Optional[str]] = mapped_column(String(4096), nullable=True)
    content_hash: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    artifact_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("artifacts.id"), nullable=True, index=True)
    source_uri: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_title: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    source_author: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    occurred_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    trust_level: Mapped[str] = mapped_column(String(32), nullable=False, default="normal", index=True)
    extraction_method: Mapped[str] = mapped_column(String(64), nullable=False, default="manual")
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="candidate", index=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_by_user_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("users.id"), nullable=True, index=True)
    created_by_agent_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("agents.id"), nullable=True, index=True)
    created_by_run_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("runs.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

    __table_args__ = (
        CheckConstraint(
            "evidence_type in ('document', 'excerpt', 'event', 'log', 'artifact', 'claim', 'summary')",
            name="ck_extracted_evidence_evidence_type",
        ),
        CheckConstraint(
            "trust_level in ('trusted', 'normal', 'untrusted')",
            name="ck_extracted_evidence_trust_level",
        ),
        CheckConstraint(
            "status in ('candidate', 'active', 'rejected', 'archived')",
            name="ck_extracted_evidence_status",
        ),
        Index("ix_extracted_evidence_source_object", "space_id", "source_object_type", "source_object_id"),
        Index("ix_extracted_evidence_space_status", "space_id", "status"),
    )


class EvidenceLink(Base):
    """Multi-target evidence link used for provenance and context eligibility."""

    __tablename__ = "evidence_links"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=False, index=True)
    evidence_id: Mapped[str] = mapped_column(UUID_COL, ForeignKey("extracted_evidence.id"), nullable=False, index=True)
    target_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    target_id: Mapped[Optional[str]] = mapped_column(UUID_COL, nullable=True, index=True)
    link_type: Mapped[str] = mapped_column(String(64), nullable=False, default="context_candidate", index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="candidate", index=True)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    created_by_user_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("users.id"), nullable=True, index=True)
    created_by_agent_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("agents.id"), nullable=True, index=True)
    created_by_run_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("runs.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

    __table_args__ = (
        CheckConstraint(
            "target_type in ('space', 'workspace', 'project', 'user', 'agent', 'run', 'proposal', 'artifact', 'knowledge', 'memory', 'task')",
            name="ck_evidence_links_target_type",
        ),
        CheckConstraint(
            "link_type in ('supports', 'contradicts', 'derived_from', 'mentions', 'context_candidate', 'used_in_context', 'provenance')",
            name="ck_evidence_links_link_type",
        ),
        CheckConstraint(
            "status in ('candidate', 'active', 'rejected', 'archived')",
            name="ck_evidence_links_status",
        ),
        Index("ix_evidence_links_target", "space_id", "target_type", "target_id"),
        Index("ix_evidence_links_evidence_target", "evidence_id", "target_type", "target_id"),
    )


class WorkspaceIntakeProfile(Base):
    """Workspace-specific intake observation, routing, and context policy."""

    __tablename__ = "workspace_intake_profiles"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=False, index=True)
    workspace_id: Mapped[str] = mapped_column(UUID_COL, ForeignKey("workspaces.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)
    observation_policy: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")
    routing_policy_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    filters_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    extraction_policy_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    context_policy_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_by_user_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("users.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

    __table_args__ = (
        CheckConstraint(
            "status in ('active', 'paused', 'archived')",
            name="ck_workspace_intake_profiles_status",
        ),
        CheckConstraint(
            "observation_policy in ('disabled', 'manual', 'auto_select', 'auto_extract')",
            name="ck_workspace_intake_profiles_observation_policy",
        ),
        UniqueConstraint("space_id", "workspace_id", name="uq_workspace_intake_profiles_workspace"),
    )


class WorkspaceSourceBinding(Base):
    """Workspace-scoped filter over a space-level source connection."""

    __tablename__ = "workspace_source_bindings"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=False, index=True)
    workspace_id: Mapped[str] = mapped_column(UUID_COL, ForeignKey("workspaces.id"), nullable=False, index=True)
    project_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("projects.id"), nullable=True, index=True)
    source_connection_id: Mapped[str] = mapped_column(UUID_COL, ForeignKey("source_connections.id"), nullable=False, index=True)
    binding_key: Mapped[str] = mapped_column(String(128), nullable=False, default="default", server_default=text("'default'"))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    filters_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    routing_policy_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    extraction_policy_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_by_user_id: Mapped[Optional[str]] = mapped_column(UUID_COL, ForeignKey("users.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

    __table_args__ = (
        CheckConstraint(
            "status in ('active', 'paused', 'archived')",
            name="ck_workspace_source_bindings_status",
        ),
        Index("ix_workspace_source_bindings_workspace_status", "workspace_id", "status"),
        UniqueConstraint(
            "space_id",
            "workspace_id",
            "source_connection_id",
            "binding_key",
            name="uq_workspace_source_bindings_connection",
        ),
    )


# ---------------------------------------------------------------------------
# Daily Capture Report — built-in optional feature
# ---------------------------------------------------------------------------


class DailyCaptureReportSetting(Base):
    """Per-user/per-space settings for the Daily Capture Report feature.

    Constraints:
    - unique(space_id, user_id): one setting per user per space.
    - enabled controls scheduled execution; manual runs are always allowed.
    - local_time is HH:MM in the user's configured timezone.
    - Thresholds are 0..1; max counts are bounded at the service layer.
    - Memory proposals are off by default; experience proposals are on by default.
    """

    __tablename__ = "daily_capture_report_settings"

    id: Mapped[str] = mapped_column(UUID_COL, primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(SPACE_COL, ForeignKey("spaces.id"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(UUID_COL, ForeignKey("users.id"), nullable=False, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    local_time: Mapped[str] = mapped_column(String(5), nullable=False, default="08:00")
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    include_source_types_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=lambda: ["user_capture"])
    create_experience_proposals: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    create_memory_proposals: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    experience_confidence_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.75)
    memory_confidence_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.85)
    max_experience_proposals_per_day: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    max_memory_proposals_per_day: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    last_report_date: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    next_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

    __table_args__ = (
        CheckConstraint(
            "experience_confidence_threshold >= 0.0 and experience_confidence_threshold <= 1.0",
            name="ck_daily_capture_report_settings_experience_threshold",
        ),
        CheckConstraint(
            "memory_confidence_threshold >= 0.0 and memory_confidence_threshold <= 1.0",
            name="ck_daily_capture_report_settings_memory_threshold",
        ),
        CheckConstraint(
            "max_experience_proposals_per_day >= 0 and max_experience_proposals_per_day <= 20",
            name="ck_daily_capture_report_settings_max_experience",
        ),
        CheckConstraint(
            "max_memory_proposals_per_day >= 0 and max_memory_proposals_per_day <= 10",
            name="ck_daily_capture_report_settings_max_memory",
        ),
        UniqueConstraint("space_id", "user_id", name="uq_daily_capture_report_settings_space_user"),
    )
