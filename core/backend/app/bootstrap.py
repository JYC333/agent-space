"""Fresh-instance bootstrap.

Brings a freshly migrated (empty) PostgreSQL database to a usable initial state.
This is the single, idempotent, service-layer bootstrap path — it is invoked once
from the application lifespan on startup and is safe to re-run: existing rows are
never modified or duplicated.

It ensures:
  - the default personal Space exists,
  - the default owner User exists,
  - an active owner SpaceMembership links the user to the space,
  - the default execution planes are seeded for the space.

Schema is owned by Alembic (see app.db.init_db). Bootstrap only inserts the
baseline rows the running app needs; it never creates or mutates schema.
"""
from __future__ import annotations

import logging
import uuid

from sqlalchemy.orm import Session

from .agents.template_seeder import seed_system_templates
from .evolution.services import EvolutionTargetRegistry
from .execution_planes.seeder import seed_default_execution_planes
from .models import Space, SpaceMembership, User
from .spaces.defaults import personal_space_id_for_owner

log = logging.getLogger(__name__)


def bootstrap_instance(
    db: Session,
    *,
    user_id: str,
    seed_execution_planes: bool = True,
) -> dict[str, bool]:
    """Idempotently ensure the default user + their personal space (+ planes).

    The default space is the owner's personal space, created with a generated
    UUID and located by owner membership — there is no fixed/magic space id.
    Returns a summary dict marking which rows were created on this call. Existing
    rows are left untouched, so calling this on every startup is safe.
    """
    created = {
        "space": False,
        "user": False,
        "membership": False,
        "execution_planes": False,
        "system_templates": False,
    }

    # System agent templates are global factories (no space/owner) — seed them
    # once, idempotently, independent of any space.
    created["system_templates"] = seed_system_templates(db) > 0
    EvolutionTargetRegistry(db).ensure_default_target_for_capture_memory_extraction()

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        db.add(User(id=user_id, email=None, display_name="Default User", status="active"))
        created["user"] = True

    # Ensure the referenced owner user exists before inserting the space.
    db.flush()

    # Find the owner's existing personal space, or mint a new one with a UUID.
    space_id = personal_space_id_for_owner(db, user_id)
    if space_id is None:
        space_id = str(uuid.uuid4())
        db.add(
            Space(
                id=space_id,
                name="Personal",
                type="personal",
                created_by_user_id=user_id,
            )
        )
        created["space"] = True

    # Ensure the space and user rows exist before inserting the membership row.
    db.flush()

    membership = (
        db.query(SpaceMembership)
        .filter(
            SpaceMembership.space_id == space_id,
            SpaceMembership.user_id == user_id,
        )
        .first()
    )
    if membership is None:
        db.add(
            SpaceMembership(
                space_id=space_id,
                user_id=user_id,
                role="owner",
                status="active",
            )
        )
        created["membership"] = True

    db.commit()

    if seed_execution_planes:
        # seed_default_execution_planes is idempotent and commits internally. It
        # returns how many plane rows it actually inserted, so the summary reports
        # execution_planes=True only when this call really created rows.
        inserted_planes = seed_default_execution_planes(db, space_id)
        created["execution_planes"] = inserted_planes > 0

    if any(created.values()):
        log.info("bootstrap_instance: ensured initial state %s", created)
    return created
