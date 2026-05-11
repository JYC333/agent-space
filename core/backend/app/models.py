from __future__ import annotations
from datetime import datetime, UTC
from typing import Optional
from sqlalchemy import (
    String, Text, Float, Integer, Boolean,
    DateTime, ForeignKey, JSON, func, UniqueConstraint
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .db import Base


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# Spaces, Users, Memberships
# ---------------------------------------------------------------------------

class Space(Base):
    __tablename__ = "spaces"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    # personal | household | team
    type: Mapped[str] = mapped_column(String(32), nullable=False, default="personal")
    created_by_user_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now, onupdate=_now)

    memberships: Mapped[list["SpaceMembership"]] = relationship("SpaceMembership", back_populates="space")
    workspaces: Mapped[list["Workspace"]] = relationship("Workspace", back_populates="space", foreign_keys="Workspace.owner_space_id")


class SpaceMembership(Base):
    __tablename__ = "space_memberships"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    space_id: Mapped[str] = mapped_column(String(64), ForeignKey("spaces.id"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # owner | admin | member | guest
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="member")
    # active | invited | suspended
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now, onupdate=_now)

    space: Mapped["Space"] = relationship("Space", back_populates="memberships")


class User(Base):
    """
    Human identity. Created on first Google OAuth login.
    A user can belong to multiple spaces via SpaceMembership.
    """
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str] = mapped_column(String(256), nullable=False, unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(256), nullable=False)
    avatar_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now, onupdate=_now)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # String (no FK) — avoids circular dependency with Space
    default_space_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    auth_accounts: Mapped[list["AuthAccount"]] = relationship("AuthAccount", back_populates="user")
    sessions: Mapped[list["UserSession"]] = relationship("UserSession", back_populates="user")


class AuthAccount(Base):
    """
    Links a User to a third-party auth provider.
    Do NOT rely solely on email — use provider_user_id as the stable identity.
    """
    __tablename__ = "auth_accounts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)          # "google"
    provider_user_id: Mapped[str] = mapped_column(String(256), nullable=False)  # Google sub
    email: Mapped[str] = mapped_column(String(256), nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)

    user: Mapped["User"] = relationship("User", back_populates="auth_accounts")

    __table_args__ = (UniqueConstraint("provider", "provider_user_id"),)


class UserSession(Base):
    """Server-side session. Token is stored hashed; raw token goes in an HttpOnly cookie."""
    __tablename__ = "user_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    user: Mapped["User"] = relationship("User", back_populates="sessions")


class SpaceInvitation(Base):
    """
    Pending invitation to join a space.
    Token is shared as a URL param (raw); stored hashed.
    """
    __tablename__ = "space_invitations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    space_id: Mapped[str] = mapped_column(String(64), ForeignKey("spaces.id"), nullable=False, index=True)
    invited_email: Mapped[str] = mapped_column(String(256), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="member")  # owner|admin|member|viewer
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    # pending | accepted | revoked | expired
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    invited_by_user_id: Mapped[str] = mapped_column(String(64), nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)
    accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class Workspace(Base):
    """
    A project or knowledge area owned by a Space. All workspace-scoped data
    (memories, tasks, sessions, agent runs) carries workspace_id referencing this table.

    root_path — optional local filesystem path (managed by WorkspaceManager + PathPolicy).
    Sharing with other Spaces is deferred to WorkspaceSpaceAccess.

    workspace_type values:
      project | repo | knowledge_base | personal | team  (default: project)
      system_core — registered automatically on startup when ENABLE_SYSTEM_EVOLUTION=true; governed by
        system_core policy (no direct writes, git worktree sandbox, code_patch proposals,
        explicit approval required, test-then-prod deploy).
    """
    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_space_id: Mapped[str] = mapped_column(String(64), ForeignKey("spaces.id"), nullable=False, index=True)
    created_by_user_id: Mapped[str] = mapped_column(String(64), nullable=False)

    name: Mapped[str] = mapped_column(String(256), nullable=False)
    slug: Mapped[Optional[str]] = mapped_column(String(256), nullable=True, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # project | repo | knowledge_base | personal | team | system_core
    workspace_type: Mapped[str] = mapped_column(String(32), nullable=False, default="project")
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="project")
    repo_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Root path on disk (absolute or relative to WORKSPACE_ROOT)
    root_path: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    default_branch: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    # private | space_shared
    visibility: Mapped[str] = mapped_column(String(32), nullable=False, default="private")
    # active | archived
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)

    # Protection flags for system-managed workspaces
    protected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    system_managed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # env | manual — how the workspace was registered
    registered_from: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now, onupdate=_now)

    space: Mapped["Space"] = relationship("Space", back_populates="workspaces", foreign_keys=[owner_space_id])
    memberships: Mapped[list["WorkspaceMembership"]] = relationship("WorkspaceMembership", back_populates="workspace")


class WorkspaceMembership(Base):
    __tablename__ = "workspace_memberships"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), ForeignKey("workspaces.id"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # owner | editor | viewer | agent_operator
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="viewer")

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now, onupdate=_now)

    workspace: Mapped["Workspace"] = relationship("Workspace", back_populates="memberships")


class WorkspaceSpaceAccess(Base):
    """
    Future cross-space workspace sharing. Schema defined now; inactive for MVP.
    A Space granted access here can run agents against this workspace, but does
    NOT inherit the owner Space's agents, memory, activity, or runtime history.
    """
    __tablename__ = "workspace_space_access"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), ForeignKey("workspaces.id"), nullable=False, index=True)
    space_id: Mapped[str] = mapped_column(String(64), ForeignKey("spaces.id"), nullable=False, index=True)
    # viewer | runner | contributor | maintainer | owner
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="viewer")
    created_by_user_id: Mapped[str] = mapped_column(String(64), nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)

    __table_args__ = (UniqueConstraint("workspace_id", "space_id"),)


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------

class Agent(Base):
    """
    A configurable runtime actor scoped to a Space.
    Agents are not owned by Workspaces — Session is the bridge between Agent and Workspace.
    Cross-space reuse should use Agent Template / Copy, not shared Agent objects.
    """
    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    # No FK — space_id is a scoping key, not a strict FK (consistent with Memory, Task, etc.)
    space_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # No FK — system agents use "system" as the creator
    created_by_user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # private | space_shared
    visibility: Mapped[str] = mapped_column(String(32), nullable=False, default="private")

    # Injected as system context on every run
    role_instruction: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # {"model": "claude-sonnet-4-6", "max_tokens": 8192}
    model_config_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    # {"readable_scopes": [...], "writable_scopes": ["agent"], "readable_types": [...]}
    memory_policy_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    # list of capability_ids this agent may invoke, e.g. ["memory.reflect", "agent.echo"]
    capabilities_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    # Permitted tools and adapter types, e.g. {"allowed_tools": [...], "allowed_adapter_types": [...]}
    tool_policy_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    # {"risk_level": "medium", "can_delegate": true, "max_delegation_depth": 3, "max_run_time_seconds": 300}
    runtime_policy_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    # active | disabled | archived
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now, onupdate=_now)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    runs: Mapped[list["AgentRun"]] = relationship(
        "AgentRun",
        foreign_keys="AgentRun.agent_id",
        back_populates="agent",
    )


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------

class Memory(Base):
    __tablename__ = "memories"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    space_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    owner_user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    workspace_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)

    # Direct entity links (complement the scope enum for precise FK-style queries)
    agent_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    capability_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)

    # Scope: system | space | user | workspace | agent | capability
    scope: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    # e.g. user.default.preferences, workspace.project-a.context
    namespace: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    # preference | semantic | episodic | procedural | project
    type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)

    title: Mapped[str] = mapped_column(String(512), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # active | archived | proposed | rejected | superseded
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)
    # private | space_shared | workspace_shared | restricted | public_template
    visibility: Mapped[str] = mapped_column(String(32), nullable=False, default="private")

    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    importance: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)

    # Provenance — one of these will be set depending on what produced the memory
    source_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    source_activity_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    source_artifact_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)

    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    approved_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now, onupdate=_now)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    access_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_accessed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    fitness_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    tags: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)


# ---------------------------------------------------------------------------
# Memory Proposals
# ---------------------------------------------------------------------------

class MemoryProposal(Base):
    __tablename__ = "memory_proposals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    space_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    workspace_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    source_session_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    source_task_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    source_run_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    source_activity_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)

    target_scope: Mapped[str] = mapped_column(String(32), nullable=False)
    target_namespace: Mapped[str] = mapped_column(String(255), nullable=False)
    target_visibility: Mapped[str] = mapped_column(String(32), nullable=False, default="private")
    memory_type: Mapped[str] = mapped_column(String(32), nullable=False)

    proposed_title: Mapped[str] = mapped_column(String(512), nullable=False)
    proposed_content: Mapped[str] = mapped_column(Text, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    # Direct supporting quotes or context excerpts from the source
    source_evidence: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # low | medium | high | critical
    risk_level: Mapped[str] = mapped_column(String(32), nullable=False, default="low")

    # pending | accepted | rejected | needs_changes
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)

    # Reviewer notes, requested changes, follow-up context
    review_metadata: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    approved_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    resulting_memory_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    space_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    workspace_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    title: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now, onupdate=_now)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    messages: Mapped[list["Message"]] = relationship("Message", back_populates="session", order_by="Message.created_at")
    summaries: Mapped[list["SessionSummary"]] = relationship("SessionSummary", back_populates="session")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("sessions.id"), nullable=False, index=True)
    space_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)

    # user | assistant | system | tool
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)

    session: Mapped["Session"] = relationship("Session", back_populates="messages")


class SessionSummary(Base):
    __tablename__ = "session_summaries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("sessions.id"), nullable=False, index=True)
    space_id: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)

    summary: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)

    session: Mapped["Session"] = relationship("Session", back_populates="summaries")


# ---------------------------------------------------------------------------
# Capabilities
# ---------------------------------------------------------------------------

class Capability(Base):
    __tablename__ = "capabilities"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    entrypoint: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    manifest_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    status: Mapped[str] = mapped_column(String(32), nullable=False, default="enabled", index=True)
    created_by_user_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_by_agent_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    source_proposal_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now, onupdate=_now)


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------

class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    space_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    workspace_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    session_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)

    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    capability_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    # pending | running | completed | failed | cancelled
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    result: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now, onupdate=_now)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    runs: Mapped[list["AgentRun"]] = relationship("AgentRun", back_populates="task")


# ---------------------------------------------------------------------------
# CLI Adapter Configs
# ---------------------------------------------------------------------------

class CLIAdapterConfig(Base):
    """
    Per-space configuration for a CLI agent tool (Claude Code, Codex CLI, etc.).

    Stores tool preferences, quota status, and usage notes. A space can have
    multiple configs for the same adapter_id (e.g. different executable paths).
    """
    __tablename__ = "cli_adapter_configs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    space_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    # claude_code | codex_cli | opencode | gemini_cli | custom | echo
    adapter_id: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(256), nullable=False)

    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    executable_path: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    # interactive | headless
    default_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="headless")

    # enough | medium | low | exhausted | unknown
    quota_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now, onupdate=_now)

    runs: Mapped[list["AgentRun"]] = relationship(
        "AgentRun",
        foreign_keys="AgentRun.cli_adapter_config_id",
        back_populates="cli_adapter_config",
    )


# ---------------------------------------------------------------------------
# Agent Runs
# ---------------------------------------------------------------------------

class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("tasks.id"), nullable=True, index=True)
    space_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    # Which configured agent was used (optional — runs can be ad-hoc without an agent config)
    agent_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("agents.id"), nullable=True, index=True)

    # Which CLI tool config was used for this run
    cli_adapter_config_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("cli_adapter_configs.id"), nullable=True, index=True
    )

    # Who initiated this run
    instructed_by_user_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    # If initiated by another agent run (multi-agent delegation)
    instructed_by_agent_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    # The parent run that spawned this run (for delegation chain tracking)
    parent_run_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("agent_runs.id"), nullable=True, index=True)
    # How deep in the delegation chain (0 = user-initiated, 1 = one level of delegation, ...)
    delegation_depth: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Kept for backward compat — prefer instructed_by_user_id
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)

    workspace_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    permission_snapshot_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    adapter_type: Mapped[str] = mapped_column(String(64), nullable=False)
    capability_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    # cli_default | cli_model_override | agent_space_provider
    model_selection_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="cli_default")
    # Used when model_selection_mode = cli_model_override; {"provider_id": ..., "model_name": ...}
    model_override_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    context_snapshot: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # pending | running | completed | failed
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    output: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    exit_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Sandbox metadata (set when the run executes in an isolated environment)
    sandbox_level: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    sandbox_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    executor_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    # Approximate usage — accuracy may be precise | estimated | unknown
    runtime_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    usage_accuracy: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    estimated_input_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    estimated_output_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    estimated_cost: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)

    task: Mapped[Optional["Task"]] = relationship("Task", back_populates="runs")
    agent: Mapped[Optional["Agent"]] = relationship(
        "Agent",
        foreign_keys=[agent_id],
        back_populates="runs",
    )
    cli_adapter_config: Mapped[Optional["CLIAdapterConfig"]] = relationship(
        "CLIAdapterConfig",
        foreign_keys=[cli_adapter_config_id],
        back_populates="runs",
    )
    parent_run: Mapped[Optional["AgentRun"]] = relationship(
        "AgentRun",
        remote_side="AgentRun.id",
        foreign_keys=[parent_run_id],
    )
    tool_calls: Mapped[list["ToolCall"]] = relationship("ToolCall", back_populates="run")
    artifacts: Mapped[list["Artifact"]] = relationship("Artifact", back_populates="run")


class ToolCall(Base):
    __tablename__ = "tool_calls"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("agent_runs.id"), nullable=False, index=True)
    space_id: Mapped[str] = mapped_column(String(64), nullable=False)

    workspace_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    initiated_by_user_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    agent_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="completed")
    policy_decision_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)

    tool_name: Mapped[str] = mapped_column(String(256), nullable=False)
    input_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    output_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    run: Mapped["AgentRun"] = relationship("AgentRun", back_populates="tool_calls")


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("agent_runs.id"), nullable=True, index=True)
    space_id: Mapped[str] = mapped_column(String(64), nullable=False)

    proposal_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    task_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("tasks.id"), nullable=True, index=True)

    name: Mapped[str] = mapped_column(String(512), nullable=False)
    artifact_type: Mapped[str] = mapped_column(String(64), nullable=False)
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    path: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)

    run: Mapped["AgentRun"] = relationship("AgentRun", back_populates="artifacts")


# ---------------------------------------------------------------------------
# Usage Events
# ---------------------------------------------------------------------------

class UsageEvent(Base):
    """
    Approximate usage record per agent run. Accuracy levels reflect the data
    source: precise (provider API), estimated (CLI output parsing), unknown.

    In the multi-CLI MVP, most runs use monthly subscriptions so precise
    token counts are unavailable. Track runtime and run counts instead.
    """
    __tablename__ = "usage_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("agent_runs.id"), nullable=False, index=True)
    space_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    agent_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    workspace_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    cli_adapter_config_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("cli_adapter_configs.id"), nullable=True, index=True
    )

    # run_completed | run_failed | run_timeout
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)

    # precise | estimated | unknown
    accuracy: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")

    input_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    estimated_cost: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    runtime_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    raw_usage_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)


# ---------------------------------------------------------------------------
# Approvals
# ---------------------------------------------------------------------------

class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    space_id: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)

    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)

    # pending | approved | rejected
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    decided_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


# ---------------------------------------------------------------------------
# Generalized Proposals
# ---------------------------------------------------------------------------

class Proposal(Base):
    """
    Generalized proposal for any agent-generated change requiring human approval.
    MemoryProposal stays for backward compat but future proposals use this table.
    Types: memory_update | code_patch | capability_install | capability_update |
           schema_migration | policy_change | report | classification | other
    """
    __tablename__ = "proposals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    space_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    workspace_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    rationale: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    payload_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # low | medium | high | critical
    risk_level: Mapped[str] = mapped_column(String(32), nullable=False, default="low")
    # pending | accepted | rejected | superseded | expired
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)

    created_by_agent_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    created_by_run_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    created_by_user_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    required_approver_role: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    approval_events: Mapped[list["ApprovalEvent"]] = relationship("ApprovalEvent", back_populates="proposal")
    artifacts: Mapped[list["ProposalArtifact"]] = relationship("ProposalArtifact", back_populates="proposal")


class ApprovalEvent(Base):
    """Per-decision events on a Proposal (one proposal may have multiple review cycles)."""
    __tablename__ = "approval_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    proposal_id: Mapped[str] = mapped_column(String(36), ForeignKey("proposals.id"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)

    # accepted | rejected | requested_changes
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)

    proposal: Mapped["Proposal"] = relationship("Proposal", back_populates="approval_events")


class ProposalArtifact(Base):
    """Artifacts attached to a generalized Proposal (diff, patch, report, etc.)."""
    __tablename__ = "proposal_artifacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    proposal_id: Mapped[str] = mapped_column(String(36), ForeignKey("proposals.id"), nullable=False, index=True)
    space_id: Mapped[str] = mapped_column(String(64), nullable=False)

    # diff | patch | report | log | context | validation | file | export
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    path: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)

    proposal: Mapped["Proposal"] = relationship("Proposal", back_populates="artifacts")


# ---------------------------------------------------------------------------
# Memory Access Logs
# ---------------------------------------------------------------------------

class MemoryAccessLog(Base):
    """Audit log for every memory read. Feeds the memory evolver fitness function."""
    __tablename__ = "memory_access_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    space_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    workspace_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    agent_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    memory_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)

    # read | propose | write | accept | reject
    access_type: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    policy_decision_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)


# ---------------------------------------------------------------------------
# Activity Records
# ---------------------------------------------------------------------------

class ActivityRecord(Base):
    """
    Entry point for all incoming data. Raw material that may produce proposals
    but must never become active memory directly.

    source_type values:
      user_input | imported_chat | web_capture | file_import |
      agent_run  | task_log      | manual
    """
    __tablename__ = "activity_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    space_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    user_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    workspace_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    agent_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)

    # What produced this record
    source_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    title: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # Links back to the system entity that generated the activity
    source_run_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    source_task_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    source_session_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    source_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # raw | processed | proposals_generated | archived
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="raw", index=True)

    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now, onupdate=_now)


# ---------------------------------------------------------------------------
# Context Snapshots
# ---------------------------------------------------------------------------

class ContextSnapshot(Base):
    """
    Frozen context package captured at the start of an agent run.
    Stored for audit and reproducibility — memory updates during a run
    must never mutate the snapshot.
    """
    __tablename__ = "context_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("agent_runs.id"), nullable=False, unique=True, index=True
    )
    space_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    # Full ContextPackage serialised as JSON
    context_package: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    # IDs of every Memory record included in this snapshot
    memory_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    # The compiled instruction file content (CLAUDE.md / AGENTS.md / etc.)
    compiled_content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # claude | codex | cursor | generic
    target_format: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    # Size accounting
    total_chars: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    budget_chars: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Security scan outcomes
    secrets_found: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    injection_risk: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # JSON list of scan finding labels e.g. ["api_key", "injection:ignore_previous"]
    scan_findings: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)

    run: Mapped["AgentRun"] = relationship("AgentRun")


# ---------------------------------------------------------------------------
# Context Attachments
# ---------------------------------------------------------------------------

class ContextAttachment(Base):
    """
    Structured context attachment for an agent run or session.

    attachment_type values:
      file | file_range | folder_tree | git_diff | staged_diff | recent_commits |
      url  | memory_entry | activity_record | wiki_page | proposal | run_artifact
    """
    __tablename__ = "context_attachments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    space_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    run_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    session_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)

    attachment_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    # Human-readable label shown in UI
    label: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    # Flexible reference — structure depends on attachment_type:
    #   file:           {"path": "src/models.py"}
    #   file_range:     {"path": "src/models.py", "start": 10, "end": 50}
    #   folder_tree:    {"path": "src/"}
    #   git_diff:       {"base": "main", "head": "HEAD"}
    #   staged_diff:    {}
    #   recent_commits: {"count": 5}
    #   url:            {"url": "https://..."}
    #   memory_entry:   {"memory_id": "..."}
    #   activity_record:{"activity_id": "..."}
    #   wiki_page:      {"page_id": "..."}
    #   proposal:       {"proposal_id": "..."}
    #   run_artifact:   {"artifact_id": "..."}
    ref_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    # Resolved at context-build time; None means not yet resolved
    resolved_content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Security outcome
    approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)


# ---------------------------------------------------------------------------
# Observability
# ---------------------------------------------------------------------------

class RunMetrics(Base):
    """Performance and cost metrics per agent run."""
    __tablename__ = "run_metrics"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    agent_run_id: Mapped[str] = mapped_column(String(36), ForeignKey("agent_runs.id"), nullable=False, unique=True, index=True)

    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    token_input: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    token_output: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    cost_estimate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    tool_call_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    memory_count_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # completed | failed | timed_out
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="completed")

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)

    run: Mapped["AgentRun"] = relationship("AgentRun")


class UserFeedback(Base):
    """User-provided feedback on runs or proposals. Training signal for evolver."""
    __tablename__ = "user_feedback"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    space_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    agent_run_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("agent_runs.id"), nullable=True, index=True)
    proposal_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("proposals.id"), nullable=True, index=True)

    # 1-5
    rating: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    feedback_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # accepted | rejected | corrected | useful | not_useful
    feedback_type: Mapped[str] = mapped_column(String(32), nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)


class FailureEvent(Base):
    """Structured failure records. Used by evolver to detect underperforming agents/capabilities."""
    __tablename__ = "failure_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    agent_run_id: Mapped[str] = mapped_column(String(36), ForeignKey("agent_runs.id"), nullable=False, index=True)

    # timeout | adapter_error | policy_denied | tool_error | delegation_limit | unknown
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    details_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)


class ValidationResult(Base):
    """Test/command validation results for capability tests and coding agent runs."""
    __tablename__ = "validation_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    agent_run_id: Mapped[str] = mapped_column(String(36), ForeignKey("agent_runs.id"), nullable=False, index=True)
    workspace_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    command: Mapped[str] = mapped_column(Text, nullable=False)
    # passed | failed | skipped | error
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    stdout: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    stderr: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)


# ---------------------------------------------------------------------------
# Capability Lifecycle
# ---------------------------------------------------------------------------

class CapabilityVersion(Base):
    """Versioned snapshot of a capability manifest. Supports capability evolution."""
    __tablename__ = "capability_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    capability_id: Mapped[str] = mapped_column(String(128), ForeignKey("capabilities.id"), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(32), nullable=False)

    manifest_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    source_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    # draft | proposed | testing | enabled | disabled | deprecated | rejected | archived
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")

    created_by_agent_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    source_proposal_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now, onupdate=_now)

    capability: Mapped["Capability"] = relationship("Capability")
    tests: Mapped[list["CapabilityTest"]] = relationship("CapabilityTest", back_populates="version")


class CapabilityTest(Base):
    """Test run result for a specific capability version."""
    __tablename__ = "capability_tests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    capability_version_id: Mapped[str] = mapped_column(String(36), ForeignKey("capability_versions.id"), nullable=False, index=True)

    command: Mapped[str] = mapped_column(Text, nullable=False)
    # passed | failed | skipped | error
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    output: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)

    version: Mapped["CapabilityVersion"] = relationship("CapabilityVersion", back_populates="tests")


# ---------------------------------------------------------------------------
# Credentials (governance skeleton — encryption deferred)
# ---------------------------------------------------------------------------

class Credential(Base):
    """
    External service credential reference. Agents never receive raw secrets.
    The ToolRunner uses credentials internally; agents only see tool results.
    Encryption at rest is deferred — encrypted_secret_ref is a placeholder.
    """
    __tablename__ = "credentials"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    space_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    owner_user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    workspace_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    provider: Mapped[str] = mapped_column(String(128), nullable=False)
    scopes_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    encrypted_secret_ref: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # active | revoked | expired
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now, onupdate=_now)

    access_logs: Mapped[list["CredentialAccessLog"]] = relationship("CredentialAccessLog", back_populates="credential")


class CredentialAccessLog(Base):
    """Audit log for every credential use."""
    __tablename__ = "credential_access_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    credential_id: Mapped[str] = mapped_column(String(36), ForeignKey("credentials.id"), nullable=False, index=True)
    space_id: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    agent_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    tool_call_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)

    # read | use | revoke
    action: Mapped[str] = mapped_column(String(32), nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)

    credential: Mapped["Credential"] = relationship("Credential", back_populates="access_logs")


# ---------------------------------------------------------------------------
# CLI Credential Events (audit log for CLI login state usage)
# ---------------------------------------------------------------------------

class CliCredentialEvent(Base):
    """
    Audit log for every time a CLI credential profile is granted to a sandbox run.

    Separate from CredentialAccessLog (which tracks API secrets). This table
    tracks usage of CLI login state (e.g. ~/.claude) by agent runs.
    """
    __tablename__ = "cli_credential_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("agent_runs.id"), nullable=False, index=True)
    space_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    # e.g. "claude-code", "codex", "opencode"
    runtime: Mapped[str] = mapped_column(String(64), nullable=False)
    # profile id from cli-credentials.yaml, e.g. "claude-code/default"
    profile_id: Mapped[str] = mapped_column(String(128), nullable=False)

    # worktree | docker
    executor_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    # low | medium | high | critical
    risk_level: Mapped[str] = mapped_column(String(32), nullable=False)

    readonly: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # credential.grant | credential.denied | credential.skipped (no profile configured)
    action: Mapped[str] = mapped_column(String(32), nullable=False, default="credential.grant")
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)


# ---------------------------------------------------------------------------
# API Keys (auth skeleton — middleware deferred)
# ---------------------------------------------------------------------------

class ApiKey(Base):
    """
    API key for service-level authentication.
    Key value is stored hashed. Middleware wiring deferred.
    """
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    space_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    owner_user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    name: Mapped[str] = mapped_column(String(256), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    # full | read_only | agent_only
    scope: Mapped[str] = mapped_column(String(32), nullable=False, default="full")
    # active | revoked
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")

    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now, onupdate=_now)


# ---------------------------------------------------------------------------
# Provider Config (space-scoped LLM provider credentials via litellm)
# ---------------------------------------------------------------------------

class ProviderConfig(Base):
    """
    Space-scoped LLM provider configuration with encrypted API key storage.
    Used for direct chat/completion tasks via litellm — separate from runtime CLI credentials.
    """
    __tablename__ = "provider_configs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    space_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    # Base64-encoded encrypted API key and nonce (binary can't be stored in SQLite as UTF-8 cleanly)
    encrypted_key: Mapped[str] = mapped_column(Text, nullable=False)
    key_nonce: Mapped[str] = mapped_column(String(24), nullable=False)  # base64 of 12-byte nonce
    models: Mapped[list] = mapped_column(JSON, nullable=False)
    api_base: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now, onupdate=_now)


# ---------------------------------------------------------------------------
# Durable Job Queue
# ---------------------------------------------------------------------------

class Job(Base):
    """
    Persistent queue entry for any long-running backend operation.
    Workers claim rows atomically, execute the registered handler, and write results back.
    Designed so the storage backend can be replaced (Redis, etc.) without changing callers.
    """
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)

    # Scoping — mirrors AgentRun for consistent filtering
    space_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    workspace_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    agent_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)

    # Dispatch key — maps to a registered handler function
    job_type: Mapped[str] = mapped_column(String(128), nullable=False, index=True)

    # pending | claimed | running | completed | failed | cancelled
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)

    # Higher value = processed first
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Handler input / output
    payload: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    result: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Retry tracking
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)

    # Worker locking — set when a worker claims this row
    claimed_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    claimed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Scheduling — job stays pending until scheduled_at has passed
    scheduled_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)

    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now, onupdate=_now)

    events: Mapped[list["JobEvent"]] = relationship("JobEvent", back_populates="job", cascade="all, delete-orphan")


class JobEvent(Base):
    """Append-only log of runtime status changes, log lines, and artifacts for a Job."""
    __tablename__ = "job_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_id: Mapped[str] = mapped_column(String(36), ForeignKey("jobs.id"), nullable=False, index=True)

    # log | status_change | artifact | error
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)

    job: Mapped["Job"] = relationship("Job", back_populates="events")


# ---------------------------------------------------------------------------
# Deployment Jobs
# ---------------------------------------------------------------------------

class DeploymentJob(Base):
    """
    Records deployment actions (rebuild/restart) requested through the backend
    and executed by the host-level deployer via Unix socket.

    Every job should be linked to an approved proposal. Admin maintenance jobs
    (no proposal) are permitted but must be flagged via proposal_id=None.
    """
    __tablename__ = "deployment_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    proposal_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    space_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    requested_by_user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    approved_by_user_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # rebuild_agent_space | restart_agent_space | health_check
    job_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target: Mapped[str] = mapped_column(String(64), nullable=False, default="local")

    # pending | queued | running | succeeded | failed | cancelled
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)

    request_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    result_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    logs_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


# ---------------------------------------------------------------------------
# Workspace Console Sessions
# ---------------------------------------------------------------------------

class WorkspaceSession(Base):
    """
    Runtime session connecting a Space's agent to a Workspace.
    Belongs to the Space that started it; even if Workspace is shared,
    session/runtime data remains space-scoped.
    """
    __tablename__ = "workspace_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    space_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    workspace_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    agent_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("agents.id"), nullable=True, index=True)
    created_by_user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    # Runtime adapter: mock | claude_code | codex | opencode | anthropic_api | custom
    runtime_adapter: Mapped[str] = mapped_column(String(64), nullable=False, default="mock")
    model: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)

    # pending | running | completed | failed | stopped
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    sandbox_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Normalized RuntimeEvent list [{type, ...fields}]
    events_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now, onupdate=_now)
