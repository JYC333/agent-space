"""Control plane service invariant tests.

Covers: ExecutionPlane, WorkspaceProfile, run execution metadata snapshot,
ExternalRunImportService, ReflectionService, ReflectionProposalBuilder,
and RuntimeToolBinding services.

Each test group protects a real product invariant, not just an import path.
"""

from __future__ import annotations
import uuid

import pytest

from app.models import (
    ExecutionPlane,
    Proposal,
    RunReflection,
    RuntimeToolBinding,
    Workspace,
    WorkspaceProfile,
)
from tests.support import factories
from tests.support.ids import DEFAULT_USER_ID, PERSONAL_SPACE_ID

pytest_plugins = ["tests.support.fixtures"]


def _new_id() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_execution_plane(db, *, space_id: str, name: str, plane_type: str = "local") -> ExecutionPlane:
    plane = ExecutionPlane(
        id=_new_id(),
        space_id=space_id,
        name=name,
        type=plane_type,
        provider="anthropic",
        execution_location="local",
        runtime_origin="open_source_external",
        trust_level="medium",
        observability_level="artifacts_only",
        data_exposure_level="local_only",
        credential_mode="user_local",
        config_json={},
        enabled=True,
    )
    db.add(plane)
    db.commit()
    db.refresh(plane)
    return plane


# ===========================================================================
# 1. ExecutionPlane service
# ===========================================================================

class TestExecutionPlaneService:
    def test_get_default_plane_known_adapter(self, db, test_space):
        """get_default_execution_plane returns the named plane for a known adapter_type."""
        from app.execution_planes.seeder import seed_default_execution_planes
        from app.execution_planes.service import ExecutionPlaneService

        seed_default_execution_planes(db, test_space.id)

        svc = ExecutionPlaneService(db)
        plane = svc.get_default_execution_plane(test_space.id, "claude_code")
        assert plane is not None
        assert plane.name == "local_claude_code_cli"
        assert plane.type == "local"

    def test_get_default_plane_unknown_adapter(self, db, test_space):
        """get_default_execution_plane returns None for unregistered adapter_type."""
        from app.execution_planes.service import ExecutionPlaneService

        svc = ExecutionPlaneService(db)
        assert svc.get_default_execution_plane(test_space.id, "nonexistent_tool") is None

    def test_get_default_plane_native(self, db, test_space):
        """capability maps to the native plane."""
        from app.execution_planes.seeder import seed_default_execution_planes
        from app.execution_planes.service import ExecutionPlaneService

        seed_default_execution_planes(db, test_space.id)
        svc = ExecutionPlaneService(db)

        plane = svc.get_default_execution_plane(test_space.id, "capability")
        assert plane is not None
        assert plane.name == "agent_space_native_local"
        assert plane.type == "native"

    def test_get_default_plane_disabled_not_returned(self, db, test_space):
        """get_default_execution_plane must not return disabled planes."""
        from app.execution_planes.seeder import seed_default_execution_planes
        from app.execution_planes.service import ExecutionPlaneService

        seed_default_execution_planes(db, test_space.id)

        svc = ExecutionPlaneService(db)
        # remote_codex and remote_claude are seeded as disabled — no adapter_type maps to them,
        # but verify that a manually disabled plane is not returned for a matching adapter.
        from app.models import ExecutionPlane as EP
        plane = svc.get_default_execution_plane(test_space.id, "claude_code")
        assert plane is not None  # enabled by default
        plane.enabled = False
        db.commit()
        assert svc.get_default_execution_plane(test_space.id, "claude_code") is None
        # Restore so later tests that seed and rely on this plane are not affected.
        plane.enabled = True
        db.commit()

    def test_externality_level_mapping(self, db, test_space):
        """externality_level_for_plane maps plane.type to the correct externality string."""
        from app.execution_planes.service import ExecutionPlaneService

        svc = ExecutionPlaneService(db)
        cases = [
            ("native", "native"),
            ("local", "local_external"),
            ("remote_vendor", "remote_external"),
            ("hybrid", "hybrid"),
            ("manual", "manual"),
        ]
        for plane_type, expected in cases:
            plane = ExecutionPlane(type=plane_type)
            assert svc.externality_level_for_plane(plane) == expected, (
                f"plane type '{plane_type}' should produce externality '{expected}'"
            )

    def test_list_planes_scoped_to_space(self, db, test_space):
        """list_execution_planes returns only planes for the given space_id."""
        from app.execution_planes.service import ExecutionPlaneService
        from app.execution_planes.seeder import seed_default_execution_planes

        seed_default_execution_planes(db, test_space.id)
        svc = ExecutionPlaneService(db)
        planes = svc.list_execution_planes(test_space.id)
        assert len(planes) >= 1
        assert all(p.space_id == test_space.id for p in planes)


# ===========================================================================
# 2. WorkspaceProfile service
# ===========================================================================

class TestWorkspaceProfileService:
    def test_get_or_create_makes_profile_on_first_call(self, db, test_space, test_user):
        """get_or_create creates a blank profile when none exists."""
        from app.workspace_profiles.service import WorkspaceProfileService

        ws = factories.create_test_workspace(db, space_id=test_space.id, commit=True)
        svc = WorkspaceProfileService(db)
        profile = svc.get_or_create_workspace_profile(ws.id, test_space.id)

        assert profile is not None
        assert profile.workspace_id == ws.id
        assert profile.space_id == test_space.id
        assert profile.cloud_allowed is False

    def test_get_or_create_is_idempotent(self, db, test_space, test_user):
        """Calling get_or_create twice returns the same profile, not a duplicate."""
        from app.workspace_profiles.service import WorkspaceProfileService

        ws = factories.create_test_workspace(db, space_id=test_space.id, commit=True)
        svc = WorkspaceProfileService(db)
        p1 = svc.get_or_create_workspace_profile(ws.id, test_space.id)
        p2 = svc.get_or_create_workspace_profile(ws.id, test_space.id)

        assert p1.id == p2.id
        count = db.query(WorkspaceProfile).filter(
            WorkspaceProfile.workspace_id == ws.id
        ).count()
        assert count == 1

    def test_update_workspace_profile(self, db, test_space):
        """update_workspace_profile persists the patch fields."""
        from app.workspace_profiles.service import WorkspaceProfileService

        ws = factories.create_test_workspace(db, space_id=test_space.id, commit=True)
        svc = WorkspaceProfileService(db)
        svc.get_or_create_workspace_profile(ws.id, test_space.id)

        updated = svc.update_workspace_profile(
            ws.id,
            test_space.id,
            {
                "test_commands_json": ["pytest -x"],
                "cloud_allowed": True,
                "current_focus": "workspace-profile integration",
            },
        )

        assert updated is not None
        assert updated.test_commands_json == ["pytest -x"]
        assert updated.cloud_allowed is True
        assert updated.current_focus == "workspace-profile integration"

    def test_update_returns_none_when_no_profile(self, db, test_space):
        """update_workspace_profile returns None if the profile was never created."""
        from app.workspace_profiles.service import WorkspaceProfileService

        ws = factories.create_test_workspace(db, space_id=test_space.id, commit=True)
        svc = WorkspaceProfileService(db)
        result = svc.update_workspace_profile(ws.id, test_space.id, {"cloud_allowed": True})
        assert result is None

    def test_get_validation_recipe_falls_back_to_task_type(self, db, test_space):
        """get_validation_recipe falls back to recipe search when profile has no pinned recipe."""
        from app.models import ValidationRecipe
        from app.workspace_profiles.service import WorkspaceProfileService

        ws = factories.create_test_workspace(db, space_id=test_space.id, commit=True)
        recipe = ValidationRecipe(
            id=_new_id(),
            space_id=test_space.id,
            workspace_id=ws.id,
            name="default-recipe",
            task_type="coding",
            risk_level="medium",
            commands_json=[],
            required_checks_json=[],
            requires_clean_git_state=False,
            enabled=True,
        )
        db.add(recipe)
        db.commit()

        svc = WorkspaceProfileService(db)
        # No profile yet — falls back to task_type search
        found = svc.get_validation_recipe_for_workspace(ws.id, test_space.id, task_type="coding")
        assert found is not None
        assert found.id == recipe.id

    def test_get_validation_recipe_returns_none_when_none_configured(self, db, test_space):
        from app.workspace_profiles.service import WorkspaceProfileService

        ws = factories.create_test_workspace(db, space_id=test_space.id, commit=True)
        svc = WorkspaceProfileService(db)
        result = svc.get_validation_recipe_for_workspace(ws.id, test_space.id, task_type="coding")
        assert result is None

    def test_get_or_create_rejects_workspace_from_other_space(self, db, test_space):
        """get_or_create must raise when workspace does not belong to the given space."""
        from app.models import Space, Workspace
        from app.workspace_profiles.service import WorkspaceProfileService

        other_space = Space(id=_new_id(), name="other-ws-space", type="personal")
        db.add(other_space)
        db.commit()
        foreign_ws = factories.create_test_workspace(db, space_id=other_space.id, commit=True)

        svc = WorkspaceProfileService(db)
        with pytest.raises(ValueError, match="not found in space"):
            svc.get_or_create_workspace_profile(foreign_ws.id, test_space.id)

    def test_update_rejects_validation_recipe_from_other_space(self, db, test_space):
        """update_workspace_profile must reject validation_recipe_id from another space."""
        from app.models import Space, ValidationRecipe
        from app.workspace_profiles.service import WorkspaceProfileService

        other_space = Space(id=_new_id(), name="recipe-space", type="personal")
        db.add(other_space)
        db.commit()
        foreign_recipe = ValidationRecipe(
            id=_new_id(),
            space_id=other_space.id,
            name="foreign-recipe",
            risk_level="low",
            commands_json=[],
            required_checks_json=[],
            requires_clean_git_state=False,
            enabled=True,
        )
        db.add(foreign_recipe)
        db.commit()

        ws = factories.create_test_workspace(db, space_id=test_space.id, commit=True)
        svc = WorkspaceProfileService(db)
        svc.get_or_create_workspace_profile(ws.id, test_space.id)

        with pytest.raises(ValueError, match="not found in space"):
            svc.update_workspace_profile(
                ws.id, test_space.id,
                {"validation_recipe_id": foreign_recipe.id},
            )

    def test_pinned_recipe_lookup_is_space_scoped(self, db, test_space):
        """get_validation_recipe_for_workspace must not return a recipe from another space."""
        from app.models import Space, ValidationRecipe, WorkspaceProfile
        from app.workspace_profiles.service import WorkspaceProfileService

        other_space = Space(id=_new_id(), name="pinned-recipe-space", type="personal")
        db.add(other_space)
        db.commit()
        foreign_recipe = ValidationRecipe(
            id=_new_id(),
            space_id=other_space.id,
            name="pinned-foreign",
            risk_level="low",
            commands_json=[],
            required_checks_json=[],
            requires_clean_git_state=False,
            enabled=True,
        )
        db.add(foreign_recipe)
        db.commit()

        ws = factories.create_test_workspace(db, space_id=test_space.id, commit=True)
        # Create profile manually with a cross-space recipe_id to simulate P0-4 scenario.
        profile = WorkspaceProfile(
            id=_new_id(),
            space_id=test_space.id,
            workspace_id=ws.id,
            cloud_allowed=False,
            validation_recipe_id=foreign_recipe.id,
        )
        db.add(profile)
        db.commit()

        svc = WorkspaceProfileService(db)
        result = svc.get_validation_recipe_for_workspace(ws.id, test_space.id)
        # The pinned recipe is from another space — must return None (falls through to task_type search)
        assert result is None


# ===========================================================================
# 3. Run creation — execution plane metadata snapshotting
# ===========================================================================

class TestRunCreationExecutionPlaneSnapshot:
    def test_run_snapshots_plane_metadata_from_adapter_type(self, db, test_space, test_user):
        """create_run populates observability/exposure/trust/externality from the resolved plane."""
        from app.execution_planes.seeder import seed_default_execution_planes
        from app.runs.run_service import RunService
        from app.schemas import RunCreate

        seed_default_execution_planes(db, test_space.id)

        agent = factories.create_test_agent(
            db, space_id=test_space.id, owner_user_id=test_user.id, commit=True
        )
        svc = RunService(db)
        run = svc.create_run(
            agent_id=agent.id,
            data=RunCreate(adapter_type="claude_code"),
            space_id=test_space.id,
            user_id=test_user.id,
        )

        assert run.execution_plane_id is not None
        assert run.observability_level == "artifacts_only"
        assert run.data_exposure_level == "local_only"
        assert run.trust_level == "medium"
        assert run.externality_level == "local_external"

    def test_run_with_no_plane_info_has_null_plane_fields(self, db, test_space, test_user):
        """create_run without any plane info leaves plane fields as None."""
        from app.runs.run_service import RunService
        from app.schemas import RunCreate

        agent = factories.create_test_agent(
            db, space_id=test_space.id, owner_user_id=test_user.id, commit=True
        )
        svc = RunService(db)
        run = svc.create_run(
            agent_id=agent.id,
            data=RunCreate(),
            space_id=test_space.id,
            user_id=test_user.id,
        )

        assert run.execution_plane_id is None
        assert run.observability_level is None
        assert run.externality_level is None

    def test_managed_run_always_gets_source_managed(self, db, test_space, test_user):
        """Managed runs created via RunService always have source='managed', not client-controlled."""
        from app.runs.run_service import RunService
        from app.schemas import RunCreate

        agent = factories.create_test_agent(
            db, space_id=test_space.id, owner_user_id=test_user.id, commit=True
        )
        svc = RunService(db)
        run = svc.create_run(
            agent_id=agent.id,
            data=RunCreate(),
            space_id=test_space.id,
            user_id=test_user.id,
        )
        assert run.source == "managed"

    def test_run_create_rejects_client_controlled_source_input(self):
        """RunCreate does not accept source from client input."""
        from pydantic import ValidationError
        from app.schemas import RunCreate

        with pytest.raises(ValidationError):
            RunCreate(source="remote_import")

    def test_run_with_explicit_execution_plane_id(self, db, test_space, test_user):
        """create_run accepts an explicit execution_plane_id and snapshots its metadata."""
        from app.runs.run_service import RunService
        from app.schemas import RunCreate

        plane = _make_execution_plane(
            db,
            space_id=test_space.id,
            name="explicit-plane",
            plane_type="remote_vendor",
        )
        plane.observability_level = "final_output_only"
        plane.data_exposure_level = "vendor_platform"
        plane.trust_level = "low"
        db.commit()

        agent = factories.create_test_agent(
            db, space_id=test_space.id, owner_user_id=test_user.id, commit=True
        )
        svc = RunService(db)
        run = svc.create_run(
            agent_id=agent.id,
            data=RunCreate(execution_plane_id=plane.id),
            space_id=test_space.id,
            user_id=test_user.id,
        )

        assert run.execution_plane_id == plane.id
        assert run.observability_level == "final_output_only"
        assert run.externality_level == "remote_external"


# ===========================================================================
# 4. ExternalRunImportService
# ===========================================================================

class TestExternalRunImportService:
    def _make_agent(self, db, space_id, user_id):
        return factories.create_test_agent(
            db, space_id=space_id, owner_user_id=user_id, commit=True
        )

    def test_import_creates_run_and_external_record(self, db, test_space, test_user):
        from app.models import ExternalRunRecord
        from app.runs.external_import import ExternalRunImport, ExternalRunImportService

        agent = self._make_agent(db, test_space.id, test_user.id)
        svc = ExternalRunImportService(db)
        result = svc.import_external_run(ExternalRunImport(
            space_id=test_space.id,
            agent_id=agent.id,
            agent_version_id=agent.current_version_id,
            vendor="anthropic",
            source="manual_import",
            raw_summary="Claude Code completed the task",
        ))

        assert result.run.id is not None
        assert result.run.source == "manual_import"
        assert result.run.externality_level == "manual"
        assert result.run.status == "succeeded"

        assert result.external_record.vendor == "anthropic"
        assert result.external_record.run_id == result.run.id
        assert result.external_record.raw_summary == "Claude Code completed the task"

        # Verify persisted
        persisted = db.query(ExternalRunRecord).filter(
            ExternalRunRecord.id == result.external_record.id
        ).first()
        assert persisted is not None

    def test_import_remote_sets_remote_external_externality(self, db, test_space, test_user):
        from app.runs.external_import import ExternalRunImport, ExternalRunImportService

        agent = self._make_agent(db, test_space.id, test_user.id)
        svc = ExternalRunImportService(db)
        result = svc.import_external_run(ExternalRunImport(
            space_id=test_space.id,
            agent_id=agent.id,
            agent_version_id=agent.current_version_id,
            vendor="openai",
            source="remote_import",
        ))

        assert result.run.externality_level == "remote_external"

    def test_import_with_artifacts(self, db, test_space, test_user):
        from app.runs.external_import import ExternalRunImport, ExternalRunImportService, ImportedArtifact

        agent = self._make_agent(db, test_space.id, test_user.id)
        svc = ExternalRunImportService(db)
        result = svc.import_external_run(ExternalRunImport(
            space_id=test_space.id,
            agent_id=agent.id,
            agent_version_id=agent.current_version_id,
            vendor="manual",
            source="manual_import",
            artifacts=[
                ImportedArtifact(
                    artifact_type="summary_text",
                    title="Run summary",
                    content="Fixed the bug in auth.py",
                ),
                ImportedArtifact(
                    artifact_type="code_patch",
                    title="auth.py patch",
                    content="--- a/auth.py\n+++ b/auth.py\n...",
                    mime_type="text/x-patch",
                ),
            ],
        ))

        assert len(result.artifacts) == 2
        assert result.artifacts[0].run_id == result.run.id
        assert result.artifacts[1].artifact_type == "code_patch"

    def test_import_rejects_invalid_vendor(self, db, test_space, test_user):
        from app.runs.external_import import ExternalRunImport, ExternalRunImportService

        agent = self._make_agent(db, test_space.id, test_user.id)
        svc = ExternalRunImportService(db)
        with pytest.raises(ValueError, match="Unknown vendor"):
            svc.import_external_run(ExternalRunImport(
                space_id=test_space.id,
                agent_id=agent.id,
                agent_version_id=agent.current_version_id,
                vendor="bad_vendor",
                source="manual_import",
            ))

    def test_import_rejects_workspace_from_other_space(self, db, test_space, test_user):
        """import_external_run must reject workspace_id that belongs to a different space."""
        from app.models import Space
        from app.runs.external_import import ExternalRunImport, ExternalRunImportService

        other_space = Space(id=_new_id(), name="import-ws-space", type="personal")
        db.add(other_space)
        db.commit()
        foreign_ws = factories.create_test_workspace(db, space_id=other_space.id, commit=True)

        agent = self._make_agent(db, test_space.id, test_user.id)
        svc = ExternalRunImportService(db)
        with pytest.raises(ValueError, match="not found in space"):
            svc.import_external_run(ExternalRunImport(
                space_id=test_space.id,
                agent_id=agent.id,
                agent_version_id=agent.current_version_id,
                vendor="manual",
                workspace_id=foreign_ws.id,
            ))

# ===========================================================================
# 5. ReflectionService
# ===========================================================================

class TestReflectionService:
    def _make_run(self, db, space_id, user_id):
        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user_id, commit=True)
        return factories.create_test_run(db, space_id=space_id, user_id=user_id, agent=agent, commit=True)

    def test_reflect_run_creates_reflection(self, db, test_space, test_user):
        from app.runs.reflection_service import ReflectionInput, ReflectionService

        run = self._make_run(db, test_space.id, test_user.id)
        svc = ReflectionService(db)
        reflection = svc.reflect_run(
            run.id,
            test_space.id,
            ReflectionInput(
                what_changed="Refactored auth module",
                what_worked="Tests pass",
                what_failed=None,
                memory_candidates=[{"title": "auth refactor pattern", "content": "Use middleware"}],
            ),
        )

        assert reflection.id is not None
        assert reflection.run_id == run.id
        assert reflection.space_id == test_space.id
        assert reflection.what_changed == "Refactored auth module"
        assert len(reflection.memory_candidates_json) == 1

    def test_reflect_run_with_empty_input_creates_zero_candidate_record(self, db, test_space, test_user):
        """An empty ReflectionInput is valid; produces a record with null candidate lists."""
        from app.runs.reflection_service import ReflectionService

        run = self._make_run(db, test_space.id, test_user.id)
        svc = ReflectionService(db)
        reflection = svc.reflect_run(run.id, test_space.id)

        assert reflection.id is not None
        assert reflection.memory_candidates_json is None
        assert reflection.follow_up_tasks_json is None

    def test_reflect_run_never_mutates_memory(self, db, test_space, test_user):
        """Calling reflect_run must not create any MemoryEntry rows."""
        from app.models import MemoryEntry
        from app.runs.reflection_service import ReflectionInput, ReflectionService

        before = db.query(MemoryEntry).filter(MemoryEntry.space_id == test_space.id).count()
        run = self._make_run(db, test_space.id, test_user.id)
        svc = ReflectionService(db)
        svc.reflect_run(
            run.id,
            test_space.id,
            ReflectionInput(memory_candidates=[{"title": "x", "content": "y"}]),
        )
        after = db.query(MemoryEntry).filter(MemoryEntry.space_id == test_space.id).count()
        assert after == before, "reflect_run must not create MemoryEntry rows"

    def test_list_reflections_for_run(self, db, test_space, test_user):
        from app.runs.reflection_service import ReflectionService

        run = self._make_run(db, test_space.id, test_user.id)
        svc = ReflectionService(db)
        svc.reflect_run(run.id, test_space.id)
        svc.reflect_run(run.id, test_space.id)

        reflections = svc.list_reflections_for_run(run.id, test_space.id)
        assert len(reflections) == 2
        assert all(r.run_id == run.id for r in reflections)

    def test_reflect_run_raises_for_unknown_run(self, db, test_space):
        from app.runs.reflection_service import ReflectionService

        svc = ReflectionService(db)
        with pytest.raises(ValueError, match="not found"):
            svc.reflect_run("nonexistent-run-id", test_space.id)


# ===========================================================================
# 6. ReflectionProposalBuilder
# ===========================================================================

class TestReflectionProposalBuilder:
    def _make_reflection(self, db, space_id, run, **kwargs):
        from app.models import RunReflection

        r = RunReflection(
            id=_new_id(),
            space_id=space_id,
            run_id=run.id,
            source="native",
            **kwargs,
        )
        db.add(r)
        db.commit()
        db.refresh(r)
        return r

    def _make_run(self, db, space_id, user_id):
        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user_id, commit=True)
        return factories.create_test_run(db, space_id=space_id, user_id=user_id, agent=agent, commit=True)

    def test_empty_reflection_creates_no_proposals(self, db, test_space, test_user):
        from app.runs.proposal_builder import ReflectionProposalBuilder

        run = self._make_run(db, test_space.id, test_user.id)
        refl = self._make_reflection(db, test_space.id, run)

        builder = ReflectionProposalBuilder(db)
        proposals = builder.create_learning_proposals_from_reflection(refl.id, test_space.id)
        assert proposals == []

    def test_memory_candidates_create_memory_update_proposals(self, db, test_space, test_user):
        from app.runs.proposal_builder import ReflectionProposalBuilder

        run = self._make_run(db, test_space.id, test_user.id)
        refl = self._make_reflection(
            db,
            test_space.id,
            run,
            memory_candidates_json=[
                {"title": "Pattern A", "content": "Use caching", "rationale": "It's faster"},
                {"title": "Pattern B", "content": "Avoid globals"},
            ],
        )

        builder = ReflectionProposalBuilder(db)
        proposals = builder.create_learning_proposals_from_reflection(refl.id, test_space.id)

        assert len(proposals) == 2
        assert all(p.proposal_type == "memory_update" for p in proposals)
        assert all(p.status == "pending" for p in proposals)
        assert all(p.space_id == test_space.id for p in proposals)
        assert all(p.payload_json["reflection_id"] == refl.id for p in proposals)

    def test_workspace_facts_creates_profile_update_proposal(self, db, test_space, test_user):
        from app.runs.proposal_builder import ReflectionProposalBuilder

        run = self._make_run(db, test_space.id, test_user.id)
        refl = self._make_reflection(
            db,
            test_space.id,
            run,
            workspace_facts_json={"tech_stack": ["Python", "FastAPI"]},
            reusable_rules_json=[{"rule": "Always run tests first"}],
        )

        builder = ReflectionProposalBuilder(db)
        proposals = builder.create_learning_proposals_from_reflection(refl.id, test_space.id)

        assert len(proposals) == 1
        assert proposals[0].proposal_type == "workspace_profile_update"

    def test_follow_up_tasks_create_follow_up_proposals(self, db, test_space, test_user):
        from app.runs.proposal_builder import ReflectionProposalBuilder

        run = self._make_run(db, test_space.id, test_user.id)
        refl = self._make_reflection(
            db,
            test_space.id,
            run,
            follow_up_tasks_json=[
                {"title": "Write migration tests", "description": "Cover edge cases"},
            ],
        )

        builder = ReflectionProposalBuilder(db)
        proposals = builder.create_learning_proposals_from_reflection(refl.id, test_space.id)

        assert len(proposals) == 1
        assert proposals[0].proposal_type == "follow_up_task"

    def test_proposals_reference_originating_run(self, db, test_space, test_user):
        """All created proposals must point back to the run that produced the reflection."""
        from app.runs.proposal_builder import ReflectionProposalBuilder

        run = self._make_run(db, test_space.id, test_user.id)
        refl = self._make_reflection(
            db,
            test_space.id,
            run,
            memory_candidates_json=[{"title": "x", "content": "y"}],
            follow_up_tasks_json=[{"title": "z"}],
        )

        builder = ReflectionProposalBuilder(db)
        proposals = builder.create_learning_proposals_from_reflection(refl.id, test_space.id)

        assert all(p.created_by_run_id == run.id for p in proposals)

    def test_unknown_reflection_raises(self, db, test_space):
        from app.runs.proposal_builder import ReflectionProposalBuilder

        builder = ReflectionProposalBuilder(db)
        with pytest.raises(ValueError, match="not found"):
            builder.create_learning_proposals_from_reflection("nonexistent", test_space.id)


# ===========================================================================
# 7. RuntimeToolBindingService
# ===========================================================================

class TestRuntimeToolBindingService:
    def _make_binding(
        self,
        db,
        *,
        space_id: str,
        runtime_adapter_type: str = "claude_code",
        workspace_id: str | None = None,
        agent_id: str | None = None,
        enabled: bool = True,
        external_type: str = "mcp_server",
        external_ref: str = "github.com/owner/mcp-server",
    ) -> RuntimeToolBinding:
        binding = RuntimeToolBinding(
            id=_new_id(),
            space_id=space_id,
            workspace_id=workspace_id,
            agent_id=agent_id,
            runtime_adapter_type=runtime_adapter_type,
            external_type=external_type,
            external_ref=external_ref,
            display_name="Test MCP Server",
            data_exposure_level="local_only",
            observability_level="artifacts_only",
            side_effect_level="none",
            approval_required=True,
            enabled=enabled,
        )
        db.add(binding)
        db.commit()
        db.refresh(binding)
        return binding

    def test_list_returns_empty_when_no_bindings(self, db, test_space):
        from app.runtime_tool_bindings.service import RuntimeToolBindingService

        svc = RuntimeToolBindingService(db)
        result = svc.list_runtime_tool_bindings(test_space.id)
        assert result == []

    def test_list_filters_by_space(self, db, test_space):
        from app.runtime_tool_bindings.service import RuntimeToolBindingService

        self._make_binding(db, space_id=test_space.id)

        svc = RuntimeToolBindingService(db)
        result = svc.list_runtime_tool_bindings(test_space.id)
        assert len(result) == 1
        assert result[0].space_id == test_space.id

    def test_list_excludes_disabled_by_default(self, db, test_space):
        from app.runtime_tool_bindings.service import RuntimeToolBindingService

        self._make_binding(
            db,
            space_id=test_space.id,
            runtime_adapter_type="claude_code",
            enabled=True,
        )
        self._make_binding(
            db,
            space_id=test_space.id,
            runtime_adapter_type="claude_code",
            enabled=False,
            external_ref="github.com/owner/disabled-mcp",
        )

        svc = RuntimeToolBindingService(db)
        # Scope by adapter so we don't see bindings from other tests in the same session
        result = svc.list_runtime_tool_bindings(
            test_space.id, runtime_adapter_type="claude_code", enabled_only=True
        )
        assert len(result) == 1
        assert result[0].enabled is True

    def test_list_include_disabled_flag(self, db, test_space):
        from app.runtime_tool_bindings.service import RuntimeToolBindingService

        self._make_binding(
            db,
            space_id=test_space.id,
            runtime_adapter_type="codex_cli",
            enabled=False,
        )

        svc = RuntimeToolBindingService(db)
        result = svc.list_runtime_tool_bindings(
            test_space.id, runtime_adapter_type="codex_cli", enabled_only=False
        )
        assert len(result) == 1

    def test_list_filters_by_runtime_adapter_type(self, db, test_space):
        from app.runtime_tool_bindings.service import RuntimeToolBindingService

        self._make_binding(
            db,
            space_id=test_space.id,
            runtime_adapter_type="claude_code",
        )
        self._make_binding(
            db,
            space_id=test_space.id,
            runtime_adapter_type="codex_cli",
            external_ref="github.com/owner/other-mcp",
        )

        svc = RuntimeToolBindingService(db)
        result = svc.list_runtime_tool_bindings(
            test_space.id, runtime_adapter_type="claude_code"
        )
        assert len(result) == 1
        assert result[0].runtime_adapter_type == "claude_code"

    def test_get_binding_by_id(self, db, test_space):
        from app.runtime_tool_bindings.service import RuntimeToolBindingService

        binding = self._make_binding(db, space_id=test_space.id)

        svc = RuntimeToolBindingService(db)
        found = svc.get_runtime_tool_binding(binding.id, test_space.id)
        assert found is not None
        assert found.id == binding.id

    def test_get_binding_returns_none_for_wrong_space(self, db, test_space):
        from app.runtime_tool_bindings.service import RuntimeToolBindingService

        binding = self._make_binding(db, space_id=test_space.id)

        svc = RuntimeToolBindingService(db)
        result = svc.get_runtime_tool_binding(binding.id, "nonexistent-space")
        assert result is None
