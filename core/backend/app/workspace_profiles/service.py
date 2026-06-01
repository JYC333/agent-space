from __future__ import annotations
import uuid
"""WorkspaceProfile service — structured operational knowledge for workspaces.

WorkspaceProfile stores durable agent-facing config (test commands, forbidden
paths, runtime preferences, data-exposure limits). workspace.metadata_json
remains for ad-hoc annotations and is not replaced by this service.
"""

import logging
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from ..models import WorkspaceProfile, ValidationRecipe, Workspace

log = logging.getLogger(__name__)


def _new_id() -> str:
    return str(uuid.uuid4())

_JSON_LIST_FIELDS = frozenset({
    "tech_stack_json",
    "important_paths_json",
    "forbidden_paths_json",
    "test_commands_json",
    "build_commands_json",
    "known_failures_json",
})

# Fields that may appear in an update patch; anything else is silently ignored
# at the API layer (Pydantic schema) but we raise here if reached for safety.
_PATCHABLE_FIELDS = frozenset({
    "repo_type",
    "tech_stack_json",
    "important_paths_json",
    "forbidden_paths_json",
    "test_commands_json",
    "build_commands_json",
    "architecture_boundaries_json",
    "current_focus",
    "known_failures_json",
    "validation_recipe_id",
    "preferred_runtime_adapter_id",
    "cloud_allowed",
    "max_data_exposure_level",
    "min_observability_level",
})


def _check_workspace_in_space(db: Session, workspace_id: str, space_id: str) -> None:
    ws = db.query(Workspace).filter(
        Workspace.id == workspace_id,
        Workspace.owner_space_id == space_id,
    ).first()
    if not ws:
        raise ValueError(
            f"Workspace '{workspace_id}' not found in space '{space_id}'"
        )


class WorkspaceProfileService:
    def __init__(self, db: Session):
        self.db = db

    def get_or_create_workspace_profile(
        self,
        workspace_id: str,
        space_id: str,
    ) -> WorkspaceProfile:
        """Return the profile for this workspace, creating a blank one if absent.

        Raises ValueError if the workspace does not belong to space_id.
        A workspace has at most one profile (unique constraint on workspace_id).
        """
        _check_workspace_in_space(self.db, workspace_id, space_id)

        profile = (
            self.db.query(WorkspaceProfile)
            .filter(
                WorkspaceProfile.workspace_id == workspace_id,
                WorkspaceProfile.space_id == space_id,
            )
            .first()
        )
        if profile:
            return profile

        profile = WorkspaceProfile(
            id=_new_id(),
            space_id=space_id,
            workspace_id=workspace_id,
            cloud_allowed=False,
        )
        self.db.add(profile)
        self.db.commit()
        self.db.refresh(profile)
        return profile

    def get_workspace_profile(
        self,
        workspace_id: str,
        space_id: str,
    ) -> WorkspaceProfile | None:
        return (
            self.db.query(WorkspaceProfile)
            .filter(
                WorkspaceProfile.workspace_id == workspace_id,
                WorkspaceProfile.space_id == space_id,
            )
            .first()
        )

    def update_workspace_profile(
        self,
        workspace_id: str,
        space_id: str,
        patch: dict,
    ) -> WorkspaceProfile | None:
        """Apply a partial update to the profile. Returns None if no profile exists.

        FK fields (preferred_runtime_adapter_id, validation_recipe_id) are validated
        against space_id before being written. Unrecognised patch fields are rejected.
        """
        profile = self.get_workspace_profile(workspace_id, space_id)
        if not profile:
            return None

        unknown = set(patch) - _PATCHABLE_FIELDS
        if unknown:
            raise ValueError(f"Unknown patch fields: {sorted(unknown)}")

        # Validate FK fields belong to the same space before applying.
        if "preferred_runtime_adapter_id" in patch and patch["preferred_runtime_adapter_id"]:
            from ..models import RuntimeAdapter
            adapter = self.db.query(RuntimeAdapter).filter(
                RuntimeAdapter.id == patch["preferred_runtime_adapter_id"],
                RuntimeAdapter.space_id == space_id,
            ).first()
            if not adapter:
                raise ValueError(
                    f"RuntimeAdapter '{patch['preferred_runtime_adapter_id']}' "
                    f"not found in space '{space_id}'"
                )

        if "validation_recipe_id" in patch and patch["validation_recipe_id"]:
            recipe = self.db.query(ValidationRecipe).filter(
                ValidationRecipe.id == patch["validation_recipe_id"],
                ValidationRecipe.space_id == space_id,
            ).first()
            if not recipe:
                raise ValueError(
                    f"ValidationRecipe '{patch['validation_recipe_id']}' "
                    f"not found in space '{space_id}'"
                )

        for field, value in patch.items():
            setattr(profile, field, value)
            if field in _JSON_LIST_FIELDS:
                flag_modified(profile, field)
        self.db.commit()
        self.db.refresh(profile)
        return profile

    def get_validation_recipe_for_workspace(
        self,
        workspace_id: str,
        space_id: str,
        task_type: str | None = None,
    ) -> ValidationRecipe | None:
        """Return the ValidationRecipe for this workspace.

        Priority:
        1. The recipe pinned on the workspace profile (must be in the same space).
        2. Best matching recipe by task_type in this space/workspace.
        3. None if nothing is configured.
        """
        profile = self.get_workspace_profile(workspace_id, space_id)
        if profile and profile.validation_recipe_id:
            # Always scope the pinned recipe lookup by space_id to prevent cross-space leakage.
            recipe = self.db.query(ValidationRecipe).filter(
                ValidationRecipe.id == profile.validation_recipe_id,
                ValidationRecipe.space_id == space_id,
            ).first()
            if recipe:
                return recipe
            # FK points to a recipe not in this space — fall through to task_type search.
            log.warning(
                "WorkspaceProfile %s has validation_recipe_id %s that is not in space %s; "
                "falling back to task_type search",
                profile.id,
                profile.validation_recipe_id,
                space_id,
            )

        q = (
            self.db.query(ValidationRecipe)
            .filter(
                ValidationRecipe.space_id == space_id,
                ValidationRecipe.workspace_id == workspace_id,
                ValidationRecipe.enabled == True,  # noqa: E712
            )
        )
        if task_type:
            q = q.filter(ValidationRecipe.task_type == task_type)
        return q.order_by(ValidationRecipe.created_at.desc()).first()
