"""ActorService — stable actor identity foundation (M2).

This module provides get-or-create helpers for all actor kinds and ActorRef
factory functions.  It is intentionally small: no full identity provider,
no RBAC, no enterprise auth.

Rules enforced here at the service layer (not as DB-level CHECK constraints):
  - actor_type = user    → user_id required, agent_id null, space_id required
  - actor_type = agent   → agent_id required, user_id null, space_id required
  - actor_type in (system, service, job, automation, connector, integration)
                         → user_id null, agent_id null, space_id optional

Internal paths that need a non-human actor identity MUST call the appropriate
get_or_create_* helper instead of passing Settings.default_user_id.

Existing authorship fields (Run.instructed_by_user_id, Proposal.created_by_user_id, …)
are not migrated in bulk. New records use actor_ref. Do not remove these fields here.
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.orm import Session

from ..models import Actor, Agent, User
from ..schemas import ActorRef

log = logging.getLogger(__name__)

_SYSTEM_SERVICE_JOB_TYPES = frozenset(
    {"system", "service", "job", "automation", "connector", "integration"}
)


# ---------------------------------------------------------------------------
# get-or-create helpers
# ---------------------------------------------------------------------------


def get_or_create_user_actor(
    db: Session,
    user: User,
    space_id: str,
) -> Actor:
    """Return the active Actor row for this user+space, creating it if absent.

    Idempotent: successive calls with the same user and space return the same row.
    """
    existing = (
        db.query(Actor)
        .filter(
            Actor.actor_type == "user",
            Actor.user_id == user.id,
            Actor.space_id == space_id,
            Actor.status == "active",
        )
        .first()
    )
    if existing:
        return existing

    actor = Actor(
        actor_type="user",
        space_id=space_id,
        user_id=user.id,
        agent_id=None,
        service_name=None,
        display_name=user.display_name,
        status="active",
        metadata_json={},
    )
    db.add(actor)
    db.flush()
    log.debug("Created user actor %s for user=%s space=%s", actor.id, user.id, space_id)
    return actor


def get_or_create_agent_actor(
    db: Session,
    agent: Agent,
    space_id: str,
) -> Actor:
    """Return the active Actor row for this agent+space, creating it if absent."""
    existing = (
        db.query(Actor)
        .filter(
            Actor.actor_type == "agent",
            Actor.agent_id == agent.id,
            Actor.space_id == space_id,
            Actor.status == "active",
        )
        .first()
    )
    if existing:
        return existing

    actor = Actor(
        actor_type="agent",
        space_id=space_id,
        user_id=None,
        agent_id=agent.id,
        service_name=None,
        display_name=agent.name,
        status="active",
        metadata_json={},
    )
    db.add(actor)
    db.flush()
    log.debug("Created agent actor %s for agent=%s space=%s", actor.id, agent.id, space_id)
    return actor


def get_or_create_system_actor(
    db: Session,
    space_id: Optional[str] = None,
    service_name: str = "system",
) -> Actor:
    """Return the active system Actor, creating it if absent.

    System actors are deployment-level: space_id may be None.
    This helper must NOT use Settings.default_user_id as a fallback.
    """
    existing = (
        db.query(Actor)
        .filter(
            Actor.actor_type == "system",
            Actor.space_id == space_id,
            Actor.service_name == service_name,
            Actor.status == "active",
        )
        .first()
    )
    if existing:
        return existing

    actor = Actor(
        actor_type="system",
        space_id=space_id,
        user_id=None,
        agent_id=None,
        service_name=service_name,
        display_name=service_name,
        status="active",
        metadata_json={},
    )
    db.add(actor)
    db.flush()
    log.debug("Created system actor %s service=%s space=%s", actor.id, service_name, space_id)
    return actor


def get_or_create_service_actor(
    db: Session,
    service_name: str,
    space_id: Optional[str] = None,
) -> Actor:
    """Return the active service Actor for this service_name, creating if absent."""
    existing = (
        db.query(Actor)
        .filter(
            Actor.actor_type == "service",
            Actor.service_name == service_name,
            Actor.space_id == space_id,
            Actor.status == "active",
        )
        .first()
    )
    if existing:
        return existing

    actor = Actor(
        actor_type="service",
        space_id=space_id,
        user_id=None,
        agent_id=None,
        service_name=service_name,
        display_name=service_name,
        status="active",
        metadata_json={},
    )
    db.add(actor)
    db.flush()
    log.debug("Created service actor %s service=%s space=%s", actor.id, service_name, space_id)
    return actor


def get_or_create_job_actor(
    db: Session,
    service_name: str,
    space_id: Optional[str] = None,
) -> Actor:
    """Return the active job Actor for this service_name+space, creating if absent.

    Job actors represent background/queue workers.  They must not impersonate
    human users.  service_name identifies the job type (e.g. "memory_consolidation").
    """
    existing = (
        db.query(Actor)
        .filter(
            Actor.actor_type == "job",
            Actor.service_name == service_name,
            Actor.space_id == space_id,
            Actor.status == "active",
        )
        .first()
    )
    if existing:
        return existing

    actor = Actor(
        actor_type="job",
        space_id=space_id,
        user_id=None,
        agent_id=None,
        service_name=service_name,
        display_name=f"job:{service_name}",
        status="active",
        metadata_json={},
    )
    db.add(actor)
    db.flush()
    log.debug("Created job actor %s service=%s space=%s", actor.id, service_name, space_id)
    return actor


# ---------------------------------------------------------------------------
# ActorRef factory functions (no DB required)
# ---------------------------------------------------------------------------


def actor_ref_for_user(user: User, space_id: str) -> ActorRef:
    """Build an ActorRef for a human user.  No DB access required."""
    return ActorRef(
        actor_type="user",
        user_id=user.id,
        space_id=space_id,
        display_name=user.display_name,
    )


def actor_ref_for_agent(agent: Agent, space_id: str) -> ActorRef:
    """Build an ActorRef for an agent.  No DB access required."""
    return ActorRef(
        actor_type="agent",
        agent_id=agent.id,
        space_id=space_id,
        display_name=agent.name,
    )


def actor_ref_for_system(
    service_name: str = "system",
    space_id: Optional[str] = None,
) -> ActorRef:
    """Build an ActorRef for a system actor.  No DB access required.

    Must not use Settings.default_user_id.  System actors are always
    represented as actor_type=system with an explicit service_name.
    """
    return ActorRef(
        actor_type="system",
        space_id=space_id,
        service_name=service_name,
        display_name=service_name,
    )


def actor_ref_for_service(
    service_name: str,
    space_id: Optional[str] = None,
) -> ActorRef:
    """Build an ActorRef for a named service actor."""
    return ActorRef(
        actor_type="service",
        space_id=space_id,
        service_name=service_name,
        display_name=service_name,
    )


def actor_ref_for_job(
    service_name: str,
    space_id: Optional[str] = None,
) -> ActorRef:
    """Build an ActorRef for a background job actor."""
    return ActorRef(
        actor_type="job",
        space_id=space_id,
        service_name=service_name,
        display_name=f"job:{service_name}",
    )


# ---------------------------------------------------------------------------
# ActorRef resolver
# ---------------------------------------------------------------------------


def resolve_actor_ref(db: Session, actor_ref: ActorRef) -> Optional[Actor]:
    """Look up the persisted Actor row for an ActorRef.

    Returns None if actor_id is absent or no matching row exists.
    Does not create rows — use get_or_create_* for that.
    """
    if actor_ref.actor_id:
        return db.query(Actor).filter(Actor.id == actor_ref.actor_id).first()

    # Best-effort lookup without actor_id
    if actor_ref.actor_type == "user" and actor_ref.user_id:
        q = db.query(Actor).filter(
            Actor.actor_type == "user",
            Actor.user_id == actor_ref.user_id,
            Actor.status == "active",
        )
        if actor_ref.space_id:
            q = q.filter(Actor.space_id == actor_ref.space_id)
        return q.first()

    if actor_ref.actor_type == "agent" and actor_ref.agent_id:
        q = db.query(Actor).filter(
            Actor.actor_type == "agent",
            Actor.agent_id == actor_ref.agent_id,
            Actor.status == "active",
        )
        if actor_ref.space_id:
            q = q.filter(Actor.space_id == actor_ref.space_id)
        return q.first()

    if actor_ref.actor_type in _SYSTEM_SERVICE_JOB_TYPES and actor_ref.service_name:
        q = db.query(Actor).filter(
            Actor.actor_type == actor_ref.actor_type,
            Actor.service_name == actor_ref.service_name,
            Actor.status == "active",
        )
        if actor_ref.space_id:
            q = q.filter(Actor.space_id == actor_ref.space_id)
        return q.first()

    return None
