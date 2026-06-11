from __future__ import annotations

"""Per-space Assistant preferences (a UI/context layer, never a policy layer).

``SpaceAssistantSettings`` holds user/space-configurable defaults for the space's
system-managed Assistant: response style, verbosity, default context toggles,
default project, proposal style, and soft model preferences.

These preferences influence default UI and context-selection behavior only. They
are deliberately kept off the immutable ``AgentVersion`` snapshot and are NEVER
merged into the assistant's hard policy (tool/runtime/output/memory/safety). So no
preference can grant a write scope, drop the proposal-only requirement, or expand
the output ceiling — those guarantees live solely on the AgentVersion.
"""

import uuid

from sqlalchemy.orm import Session as DBSession

from ..models import SpaceAssistantSettings
from .personal_assistant import get_default_assistant


def _new_id() -> str:
    return str(uuid.uuid4())


# Soft preference fields a caller may set. Anything outside this set (e.g. policy
# fields) is ignored — preferences can never reach hard policy.
_MUTABLE_FIELDS = (
    "response_style",
    "verbosity",
    "default_context_toggles_json",
    "default_project_id",
    "proposal_style",
    "model_preferences_json",
)


class AssistantSettingsService:
    def __init__(self, db: DBSession):
        self.db = db

    def get(self, space_id: str) -> SpaceAssistantSettings | None:
        return (
            self.db.query(SpaceAssistantSettings)
            .filter(SpaceAssistantSettings.space_id == space_id)
            .first()
        )

    def get_or_create(self, space_id: str) -> SpaceAssistantSettings:
        existing = self.get(space_id)
        if existing is not None:
            return existing
        assistant = get_default_assistant(self.db, space_id=space_id)
        row = SpaceAssistantSettings(
            id=_new_id(),
            space_id=space_id,
            assistant_agent_id=assistant.id if assistant else None,
            default_context_toggles_json={},
            model_preferences_json={},
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def update(self, space_id: str, updates: dict) -> SpaceAssistantSettings:
        """Apply soft-preference updates only. Hard policy is never touched here."""
        row = self.get_or_create(space_id)
        # Keep the assistant pointer fresh if one now exists.
        if row.assistant_agent_id is None:
            assistant = get_default_assistant(self.db, space_id=space_id)
            if assistant is not None:
                row.assistant_agent_id = assistant.id
        for field in _MUTABLE_FIELDS:
            if field in updates and updates[field] is not None:
                setattr(row, field, updates[field])
        self.db.commit()
        self.db.refresh(row)
        return row
