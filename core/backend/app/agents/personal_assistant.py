from __future__ import annotations

"""Per-space system-managed default Assistant (the Chat identity).

Chat in this system is represented by a single **system-managed** default Assistant
Agent per space — never a naked DirectChat, never a hardcoded global default agent,
and never an ordinary user-created template instance.

The Assistant is an ordinary Agent backed by its own immutable ``AgentVersion``
(so the runtime path is unchanged — it loads ``Agent.current_version_id`` like any
other agent). What makes it special is bookkeeping only:

  - ``agent_kind == "system_assistant"`` marks it as the space's default Assistant,
  - it is system/space-owned (``owner_user_id`` may be NULL), not user-owned,
  - at most one *active* one exists per space (DB partial-unique index +
    resolve-before-create here),
  - it is minted from the internal ``personal_assistant`` seed spec, which is hidden
    from the public Template Library and from user create-from-template.

Per-run context selection is dynamic and handled by ContextBuilder/ContextRequest;
it never mints a new AgentVersion. Full chat execution is intentionally out of scope.
"""

from fastapi import HTTPException
from sqlalchemy.orm import Session as DBSession

from ..models import Agent, AgentTemplate, Space

PERSONAL_ASSISTANT_KEY = "personal_assistant"
SYSTEM_ASSISTANT_KIND = "system_assistant"

PERSONAL_ASSISTANT_NAME = "Personal Assistant"
SPACE_ASSISTANT_NAME = "Space Assistant"


def _assistant_name_for_space(db: DBSession, space_id: str) -> str:
    """Personal spaces get a "Personal Assistant"; shared spaces a "Space Assistant"."""
    space = db.query(Space).filter(Space.id == space_id).first()
    if space is not None and space.type != "personal":
        return SPACE_ASSISTANT_NAME
    return PERSONAL_ASSISTANT_NAME


def get_personal_assistant_template(db: DBSession) -> AgentTemplate | None:
    """Return the internal ``personal_assistant`` seed spec template, if seeded."""
    return (
        db.query(AgentTemplate)
        .filter(
            AgentTemplate.scope == "system",
            AgentTemplate.key == PERSONAL_ASSISTANT_KEY,
        )
        .first()
    )


def get_default_assistant(db: DBSession, *, space_id: str) -> Agent | None:
    """Return the space's active system-managed default Assistant, or None.

    Resolution is by ``agent_kind`` — the durable marker for the Chat identity —
    never by template provenance. Resolution never mints an Agent.
    """
    return (
        db.query(Agent)
        .filter(
            Agent.space_id == space_id,
            Agent.agent_kind == SYSTEM_ASSISTANT_KIND,
            Agent.status == "active",
        )
        .order_by(Agent.created_at.asc())
        .first()
    )


def get_or_create_default_assistant(
    db: DBSession, *, space_id: str, owner_user_id: str | None = None
) -> Agent:
    """Resolve the space's default Assistant, creating it on demand if absent.

    Idempotent: repeated calls return the same Agent (resolve-before-create plus a
    DB partial-unique index guarantee at most one active Assistant per space).
    Creation goes through the standard copy-on-create path (internal template
    version → new immutable AgentVersion), so the Assistant carries a real
    AgentVersion and the template's hard-safety policy. The resulting Agent is
    system-managed (``agent_kind="system_assistant"``, system/space-owned).

    The Assistant is always system-owned (``owner_user_id`` NULL) regardless of the
    caller — ``owner_user_id`` is accepted only for signature/back-compat and never
    makes the Assistant user-owned.

    Raises 404 if the internal ``personal_assistant`` seed spec has not been seeded.
    """
    existing = get_default_assistant(db, space_id=space_id)
    if existing is not None:
        return existing

    template = get_personal_assistant_template(db)
    if template is None:
        raise HTTPException(
            status_code=404,
            detail="personal_assistant system seed spec is not seeded",
        )

    # Local import avoids a module import cycle (template_service imports schemas
    # that pull in agent service helpers).
    from ..schemas import CreateAgentFromTemplate
    from .template_service import AgentTemplateService

    return AgentTemplateService(db).create_agent_from_template(
        template.id,
        space_id=space_id,
        owner_user_id=None,  # system-managed: never user-owned
        agent_kind=SYSTEM_ASSISTANT_KIND,
        overrides=CreateAgentFromTemplate(name=_assistant_name_for_space(db, space_id)),
    )


# ---------------------------------------------------------------------------
# Back-compat aliases (older callers/tests used the "personal assistant" names).
# ---------------------------------------------------------------------------

def resolve_default_personal_assistant(db: DBSession, *, space_id: str) -> Agent | None:
    return get_default_assistant(db, space_id=space_id)


def ensure_default_personal_assistant(
    db: DBSession, *, space_id: str, owner_user_id: str | None
) -> Agent:
    return get_or_create_default_assistant(db, space_id=space_id, owner_user_id=owner_user_id)
