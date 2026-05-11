"""
System-core workspace registration.

On backend startup (when ENABLE_SYSTEM_EVOLUTION=true), validates the
agent-space worktree is a git repo, finds/creates the owner's personal space,
and registers the workspace with:
  - workspace_type = system_core
  - protected = true
  - system_managed = true
  - registered_from = "auto"

The worktree path is derived from AGENT_SPACE_HOME: AGENT_SPACE_HOME/workspaces/<space_id>/agent-space

This module is ONLY invoked at startup — not through any API endpoint.
"""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from sqlalchemy.orm import Session
from ulid import ULID

from ..config import settings, paths
from ..models import Space, SpaceMembership, User, Workspace

log = logging.getLogger(__name__)

# Well-known ID for the system-core workspace (stable across restarts)
SYSTEM_CORE_WORKSPACE_ID = "system-core-workspace"


def _new_id() -> str:
    return str(ULID())


def _validate_git_repo(path: Path) -> bool:
    """Return True if path is a valid git repository."""
    if not path.is_dir():
        return False
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            cwd=path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def _ensure_personal_space(db: Session, user: User) -> Space:
    """Find or create a personal space for the user."""
    # Look for existing personal space where user is owner/member
    membership = (
        db.query(SpaceMembership)
        .filter(
            SpaceMembership.user_id == user.id,
            SpaceMembership.role == "owner",
            SpaceMembership.status == "active",
        )
        .first()
    )
    if membership:
        space = db.query(Space).filter(Space.id == membership.space_id).first()
        if space and space.type == "personal":
            return space

    # Create a new personal space
    space = Space(
        id=_new_id(),
        name=f"{user.display_name}'s Personal Space",
        type="personal",
        created_by_user_id=user.id,
    )
    db.add(space)
    db.flush()
    db.add(SpaceMembership(
        id=_new_id(),
        space_id=space.id,
        user_id=user.id,
        role="owner",
        status="active",
    ))
    log.info("Created personal space '%s' for user %s", space.name, user.email)
    return space


def _call_deployer_init_worktree(repo_path: str) -> bool:
    """Ask deployer to clone the canonical repo into the worktree dir."""
    from ..deployment.client import DeployerClient
    from ..config import settings

    log.info("calling deployer init for worktree at %s", repo_path)
    client = DeployerClient(settings.deployer_socket_path)
    if not client.available:
        log.warning("deployer socket not available at %s", settings.deployer_socket_path)
        return False

    log.info("submitting init_agent_space_worktree job with WORKSPACE_DIR=%s", repo_path)
    result = client.submit_job(
        {
            "job_id": "init-worktree-bootstrap",
            "job_type": "init_agent_space_worktree",
        },
        args={"WORKSPACE_DIR": repo_path},
    )
    log.info("deployer result: %s", result)
    if result.get("status") == "succeeded":
        log.info("deployer initialized worktree at %s", repo_path)
        return True
    log.warning("deployer init failed: %s", result.get("error", "unknown"))
    return False


def register_system_core_workspace(db: Session) -> Workspace | None:
    """
    Register the agent-space worktree as a system_core workspace in the owner's
    personal space. Idempotent — safe to call on every startup.

    Returns the Workspace record, or None if system evolution is disabled
    or validation fails. Errors are logged, never raised — startup must not
    be blocked by system evolution misconfiguration.
    """
    if not settings.enable_system_evolution:
        return None

    if not settings.system_core_owner_email:
        log.warning(
            "ENABLE_SYSTEM_EVOLUTION=true but SYSTEM_CORE_OWNER_EMAIL is not set — skipping"
        )
        return None

    # Find the owner user by email
    user = db.query(User).filter(User.email == settings.system_core_owner_email).first()
    if not user:
        log.warning(
            "SYSTEM_CORE_OWNER_EMAIL '%s' — no user found with that email; "
            "complete Google OAuth login first — skipping system core registration",
            settings.system_core_owner_email,
        )
        return None

    # Get or create owner's personal space
    space = _ensure_personal_space(db, user)

    # Compute worktree path for this space
    repo_path = paths.system_core_workspace_dir_for_space(space.id).resolve()

    # Ask deployer to clone the canonical repo if not already initialized
    if not _validate_git_repo(repo_path):
        log.info("system_core worktree not found at %s — asking deployer to init", repo_path)
        ok = _call_deployer_init_worktree(str(repo_path))
        if not ok:
            log.warning(
                "system_core workspace '%s' could not be initialized — skipping registration",
                repo_path,
            )
            return None

    if not _validate_git_repo(repo_path):
        log.warning(
            "system_core workspace '%s' is not a valid git repository after init — skipping",
            repo_path,
        )
        return None

    # Check if already registered
    existing = db.query(Workspace).filter(
        Workspace.owner_space_id == space.id,
        Workspace.id == SYSTEM_CORE_WORKSPACE_ID,
    ).first()
    if existing:
        log.info(
            "system_core workspace already registered at %s",
            existing.root_path,
        )
        existing.root_path = str(repo_path)
        db.commit()
        return existing

    # Register the workspace
    ws = Workspace(
        id=SYSTEM_CORE_WORKSPACE_ID,
        owner_space_id=space.id,
        created_by_user_id=user.id,
        name="Agent Space",
        description="Agent-space self-evolution workspace — managed by agent-space",
        workspace_type="system_core",
        kind="repo",
        root_path=str(repo_path),
        visibility="private",
        protected=True,
        system_managed=True,
        registered_from="auto",
        status="active",
    )
    db.add(ws)
    db.commit()
    db.refresh(ws)
    log.info(
        "Registered system_core workspace at %s in space %s",
        repo_path,
        space.id,
    )
    return ws