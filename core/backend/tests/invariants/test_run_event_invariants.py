"""Invariant tests for RunEvent evidence spine.

Tests verify structural and cross-cutting invariants:
- RunEvent.run_id FK enforced (no orphaned events)
- UniqueConstraint on (space_id, run_id, event_index)
- event_type check constraint rejects unknown types
- status check constraint rejects unknown statuses
- data_exposure_level check constraint
- trust_level check constraint
- RunEvaluationService.evaluate() appends evaluation_created event (best-effort)
- _gather_events_evidence correctly derives patch/artifact signals
"""
from __future__ import annotations

import pytest
from sqlalchemy import CheckConstraint

from app.models import RunEvent
from app.runs.events import RUN_EVENT_TYPES, RunEventService
from app.runs.evaluation import RunEvaluationService, _gather_events_evidence
from tests.support import factories


SPACE = "space-revi-01"
USER = "user-revi-01"


def _setup(db):
    factories.create_test_space(db, space_id=SPACE)
    factories.create_test_user(db, space_id=SPACE, user_id=USER)


# ---------------------------------------------------------------------------
# ORM model constraints
# ---------------------------------------------------------------------------

class TestOrmConstraints:
    def test_run_event_type_definitions_do_not_drift(self):
        """Service enum, ORM constraint, and canonical migration must stay aligned."""
        import ast
        import re
        from pathlib import Path

        def _constraint_values(sqltext: str) -> set[str]:
            match = re.search(r"event_type\s+in\s*\((.*?)\)", sqltext, re.DOTALL)
            assert match is not None, sqltext
            return set(re.findall(r"'([^']+)'", match.group(1)))

        orm_constraint = next(
            c for c in RunEvent.__table__.constraints
            if isinstance(c, CheckConstraint) and c.name == "ck_run_events_event_type"
        )
        orm_values = _constraint_values(str(orm_constraint.sqltext))

        migration_path = (
            Path(__file__).parents[2]
            / "migrations"
            / "versions"
            / "0001_canonical_initial_schema.py"
        )
        migration_source = migration_path.read_text(encoding="utf-8")
        migration_tree = ast.parse(migration_source)
        migration_values: set[str] | None = None
        for node in ast.walk(migration_tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (
                isinstance(func, ast.Attribute)
                and func.attr == "CheckConstraint"
            ):
                continue
            has_name = any(
                kw.arg == "name"
                and isinstance(kw.value, ast.Constant)
                and kw.value.value == "ck_run_events_event_type"
                for kw in node.keywords
            )
            if has_name and node.args:
                sql = ast.literal_eval(node.args[0])
                migration_values = _constraint_values(sql)
                break

        assert migration_values is not None
        assert "policy_checked" in RUN_EVENT_TYPES
        assert set(RUN_EVENT_TYPES) == orm_values == migration_values

    def test_valid_event_can_be_created(self, db):
        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        db.commit()
        from datetime import UTC, datetime
        from ulid import ULID
        ev = RunEvent(
            id=str(ULID()),
            space_id=SPACE,
            run_id=run.id,
            event_index=0,
            event_type="context_compiled",
            status="succeeded",
            created_at=datetime.now(UTC),
        )
        db.add(ev)
        db.flush()
        assert ev.id is not None

    def test_unique_constraint_on_space_run_event_index(self, db):
        from sqlalchemy.exc import IntegrityError
        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        from datetime import UTC, datetime
        from ulid import ULID

        ev1 = RunEvent(
            id=str(ULID()), space_id=SPACE, run_id=run.id, event_index=0,
            event_type="context_compiled", status="succeeded", created_at=datetime.now(UTC),
        )
        db.add(ev1)
        db.flush()

        # Duplicate (space_id, run_id, event_index) must fail
        ev2 = RunEvent(
            id=str(ULID()), space_id=SPACE, run_id=run.id, event_index=0,
            event_type="runtime_selected", status="succeeded", created_at=datetime.now(UTC),
        )
        db.add(ev2)
        with pytest.raises(IntegrityError, match="UNIQUE constraint failed: run_events"):
            db.flush()
        db.rollback()


# ---------------------------------------------------------------------------
# _gather_events_evidence — signal derivation
# ---------------------------------------------------------------------------

class TestEventsEvidenceGathering:
    def test_no_events_returns_zero_count(self, db):
        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        ev = _gather_events_evidence(db, run)
        assert ev["count"] == 0
        assert ev["event_error_codes"] == []
        assert ev["patch_incomplete"] is False
        assert ev["artifact_ingestion_errors"] == 0

    def test_patch_incomplete_signal_from_event_error_code(self, db):
        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        svc = RunEventService(db)
        svc.append_event(
            run_id=run.id, space_id=SPACE,
            event_type="patch_collected", status="warning",
            error_code="code_patch_incomplete",
            metadata_json={"incomplete_patch": True, "proposal_created": True},
        )
        db.flush()

        ev = _gather_events_evidence(db, run)
        assert ev["patch_incomplete"] is True
        assert "code_patch_incomplete" in ev["event_error_codes"]

    def test_patch_collection_error_signal(self, db):
        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        svc = RunEventService(db)
        svc.append_event(
            run_id=run.id, space_id=SPACE,
            event_type="patch_collected", status="failed",
            error_code="code_patch_collection_error",
        )
        db.flush()

        ev = _gather_events_evidence(db, run)
        assert ev["patch_collection_error"] is True

    def test_artifact_ingestion_error_signal(self, db):
        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        svc = RunEventService(db)
        svc.append_event(
            run_id=run.id, space_id=SPACE,
            event_type="artifact_ingested", status="warning",
            error_code="produced_artifact_ingestion_error",
        )
        db.flush()

        ev = _gather_events_evidence(db, run)
        assert ev["artifact_ingestion_errors"] == 1

    def test_event_warnings_collected(self, db):
        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        svc = RunEventService(db)
        svc.append_event(
            run_id=run.id, space_id=SPACE,
            event_type="artifact_ingested", status="warning",
            error_code="produced_artifact_ingestion_error",
        )
        db.flush()

        ev = _gather_events_evidence(db, run)
        assert len(ev["event_warnings"]) == 1
        assert ev["event_warnings"][0]["event_type"] == "artifact_ingested"


# ---------------------------------------------------------------------------
# RunEvaluationService emits evaluation_created event
# ---------------------------------------------------------------------------

class TestEvaluationCreatedEvent:
    def test_evaluate_emits_evaluation_created_event(self, db):
        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        run.status = "succeeded"
        db.flush()

        svc = RunEvaluationService(db)
        evaluation = svc.evaluate(run.id, space_id=SPACE)
        db.flush()

        events = db.query(RunEvent).filter(
            RunEvent.run_id == run.id,
            RunEvent.event_type == "evaluation_created",
        ).all()
        assert len(events) >= 1
        ev = events[0]
        assert ev.status == "succeeded"
        assert ev.metadata_json is not None
        assert ev.metadata_json.get("run_evaluation_id") == evaluation.id
        assert ev.metadata_json.get("outcome_status") == evaluation.outcome_status

    def test_evaluate_twice_emits_two_evaluation_created_events(self, db):
        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        run.status = "succeeded"
        db.flush()

        svc = RunEvaluationService(db)
        svc.evaluate(run.id, space_id=SPACE)
        db.flush()
        svc.evaluate(run.id, space_id=SPACE)
        db.flush()

        events = db.query(RunEvent).filter(
            RunEvent.run_id == run.id,
            RunEvent.event_type == "evaluation_created",
        ).all()
        assert len(events) == 2


# ---------------------------------------------------------------------------
# RunEvent evidence in RunEvaluation
# ---------------------------------------------------------------------------

class TestRunEventEvidenceInEvaluation:
    def test_evidence_json_includes_events_key_when_events_exist(self, db):
        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        run.status = "succeeded"
        db.flush()

        svc_ev = RunEventService(db)
        svc_ev.append_event(run_id=run.id, space_id=SPACE, event_type="context_compiled", status="succeeded")
        db.flush()

        svc = RunEvaluationService(db)
        evaluation = svc.evaluate(run.id, space_id=SPACE)
        db.flush()

        assert evaluation.evidence_json is not None
        assert "events" in evaluation.evidence_json
        ev_key = evaluation.evidence_json["events"]
        assert ev_key["count"] >= 1

    def test_evidence_uses_run_event_error_codes_as_primary_source(self, db):
        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        run.status = "succeeded"
        db.flush()

        svc_ev = RunEventService(db)
        svc_ev.append_event(
            run_id=run.id, space_id=SPACE,
            event_type="patch_collected", status="warning",
            error_code="code_patch_incomplete",
            metadata_json={"incomplete_patch": True, "proposal_created": True},
        )
        db.flush()

        svc = RunEvaluationService(db)
        evaluation = svc.evaluate(run.id, space_id=SPACE)
        db.flush()

        # patch_incomplete signal from RunEvent should cause partial outcome
        assert evaluation.outcome_status == "partial"
        # materialization section should reflect the RunEvent signals
        mat = evaluation.evidence_json.get("materialization", {})
        assert "code_patch_incomplete" in mat.get("code_patch_warnings", [])


# ---------------------------------------------------------------------------
# RunEvent emission invariants from RunExecutionService
# ---------------------------------------------------------------------------

_EXEC_SPACE = "space-revi-exec-01"
_EXEC_USER = "user-revi-exec-01"
_PATCH_SPACE = "space-revi-patch-01"
_PATCH_USER = "user-revi-patch-01"
_SKIP_SPACE = "space-revi-skip-01"
_SKIP_USER = "user-revi-skip-01"
_MAT_SPACE = "space-revi-mat-01"
_MAT_USER = "user-revi-mat-01"


class TestExecutionEmitsAdapterCompletedOnException:
    """When adapter.execute() raises, adapter_completed failed event must be emitted."""

    def test_adapter_execute_exception_emits_adapter_completed_failed(
        self, db, tmp_path, monkeypatch
    ):
        from app.config import settings
        from app.models import RunEvent
        from app.runtimes.base import BaseRuntimeAdapter, RuntimeExecutionContext
        from app.runs.execution import RunExecutionService

        art_root = tmp_path / "artifacts"
        art_root.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(settings, "artifact_storage_root", str(art_root))
        monkeypatch.setattr(settings, "workspace_root", str(tmp_path / "workspaces"))
        monkeypatch.setattr(settings, "sandbox_root", str(tmp_path / "sandboxes"))

        factories.create_test_space(db, space_id=_EXEC_SPACE)
        factories.create_test_user(db, space_id=_EXEC_SPACE, user_id=_EXEC_USER)

        class ThrowingAdapter(BaseRuntimeAdapter):
            adapter_type = "echo"

            def execute(self, ctx: RuntimeExecutionContext):
                raise RuntimeError("adapter blew up")

        monkeypatch.setattr(
            "app.runs.execution.instantiate_runtime_adapter",
            lambda _adapter_type: ThrowingAdapter(),
        )

        agent = factories.create_test_agent(db, space_id=_EXEC_SPACE, owner_user_id=_EXEC_USER, commit=False)
        run = factories.create_test_run(db, space_id=_EXEC_SPACE, user_id=_EXEC_USER, agent=agent, commit=True)

        RunExecutionService(db).execute_run(run.id, space_id=_EXEC_SPACE)

        db.refresh(run)
        assert run.status == "failed"

        completed_events = (
            db.query(RunEvent)
            .filter(
                RunEvent.run_id == run.id,
                RunEvent.event_type == "adapter_completed",
                RunEvent.status == "failed",
            )
            .all()
        )
        assert len(completed_events) >= 1, (
            "adapter_completed failed event must be emitted when adapter.execute() raises"
        )
        ev = completed_events[0]
        assert ev.error_code == "adapter_runtime_error"


class TestPatchCollectedWarningOnIncompleteProposal:
    """patch_collected must emit status=warning + error_code=code_patch_incomplete
    when a proposal is created but the patch is incomplete."""

    def test_incomplete_patch_proposal_emits_patch_collected_warning(
        self, db, tmp_path, monkeypatch
    ):
        import subprocess
        from datetime import UTC, datetime
        from pathlib import Path

        from app.config import settings
        from app.models import AgentVersion, RunEvent
        from app.runtimes.base import BaseRuntimeAdapter, RuntimeAdapterResult, RuntimeExecutionContext
        from app.runs.code_patch_collector import WorktreeCollectionResult
        from app.runs.execution import RunExecutionService

        art_root = tmp_path / "artifacts"
        art_root.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(settings, "artifact_storage_root", str(art_root))
        ws_root = tmp_path / "workspaces"
        ws_root.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(settings, "workspace_root", str(ws_root))
        monkeypatch.setattr(settings, "sandbox_root", str(tmp_path / "sandboxes"))

        factories.create_test_space(db, space_id=_PATCH_SPACE)
        factories.create_test_user(db, space_id=_PATCH_SPACE, user_id=_PATCH_USER)

        # Initialise a real git workspace so worktree sandbox can be created.
        git_ws = tmp_path / "git_ws"
        git_ws.mkdir()
        subprocess.run(["git", "init", str(git_ws)], check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "t@t.invalid"],
            check=True, capture_output=True, cwd=str(git_ws),
        )
        subprocess.run(
            ["git", "config", "user.name", "T"],
            check=True, capture_output=True, cwd=str(git_ws),
        )
        (git_ws / "init.txt").write_text("init", encoding="utf-8")
        subprocess.run(["git", "add", "init.txt"], check=True, capture_output=True, cwd=str(git_ws))
        subprocess.run(
            ["git", "commit", "-m", "init"],
            check=True, capture_output=True, cwd=str(git_ws),
        )

        class WritingAdapter(BaseRuntimeAdapter):
            adapter_type = "claude_code"
            requires_file_access = True
            supports_sandboxed_execution = True

            def execute(self, ctx: RuntimeExecutionContext) -> RuntimeAdapterResult:
                if ctx.sandbox_cwd:
                    (Path(ctx.sandbox_cwd) / "init.txt").write_text("changed", encoding="utf-8")
                return RuntimeAdapterResult(
                    success=True, stdout="ok", output_text=None, exit_code=0,
                    started_at=datetime.now(UTC), completed_at=datetime.now(UTC),
                )

        monkeypatch.setattr(
            "app.runs.execution.instantiate_runtime_adapter",
            lambda _: WritingAdapter(),
        )

        workspace = factories.create_test_workspace(
            db, space_id=_PATCH_SPACE, root_path=str(git_ws), allow_external_root=True,
        )
        agent = factories.create_test_agent(db, space_id=_PATCH_SPACE, owner_user_id=_PATCH_USER)
        # Set risk_level=high so sandbox level resolves to worktree.
        version = db.query(AgentVersion).filter_by(id=agent.current_version_id).first()
        version.runtime_policy_json = {"risk_level": "high", "default_adapter_type": "claude_code"}
        db.flush()

        run = factories.create_test_run(db, space_id=_PATCH_SPACE, user_id=_PATCH_USER, agent=agent)
        run.workspace_id = workspace.id
        db.commit()

        def _fake_collect(_db, *, run=None, worktree_path=None, **kwargs):
            # Create the proposal when collection runs, matching the production
            # transaction order after runtime policy gates have completed.
            fake_proposal = factories.create_test_proposal(
                _db, space_id=_PATCH_SPACE, run_id=run.id,
                payload_json={"incomplete_patch": True, "proposed_content": "diff"},
            )
            return WorktreeCollectionResult(
                proposal_created=True,
                ops_count=2,
                skipped=[{"path": "img.png", "reason": "binary"}],
                incomplete_patch=True,
                proposal=fake_proposal,
            )

        monkeypatch.setattr(
            "app.runs.execution.collect_and_create_code_patch_proposal",
            _fake_collect,
        )

        RunExecutionService(db).execute_run(run.id, space_id=_PATCH_SPACE)
        db.flush()

        patch_events = (
            db.query(RunEvent)
            .filter(
                RunEvent.run_id == run.id,
                RunEvent.event_type == "patch_collected",
            )
            .all()
        )
        assert len(patch_events) >= 1, "patch_collected event must be emitted"
        ev = patch_events[0]
        assert ev.status == "warning", (
            f"Expected status=warning for incomplete patch, got {ev.status!r}"
        )
        assert ev.error_code == "code_patch_incomplete", (
            f"Expected error_code=code_patch_incomplete, got {ev.error_code!r}"
        )


# ---------------------------------------------------------------------------
# patch_collected status for skipped files without proposal
# ---------------------------------------------------------------------------

class TestPatchCollectedSkippedFilesWithoutProposal:
    """When skipped files exist but no proposal was created, patch_collected must emit warning."""

    def test_skipped_files_no_proposal_emits_patch_collected_warning(
        self, db, tmp_path, monkeypatch
    ):
        import subprocess
        from datetime import UTC, datetime
        from pathlib import Path

        from app.config import settings
        from app.models import AgentVersion, RunEvent
        from app.runtimes.base import BaseRuntimeAdapter, RuntimeAdapterResult, RuntimeExecutionContext
        from app.runs.code_patch_collector import WorktreeCollectionResult
        from app.runs.execution import RunExecutionService

        art_root = tmp_path / "artifacts"
        art_root.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(settings, "artifact_storage_root", str(art_root))
        ws_root = tmp_path / "workspaces"
        ws_root.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(settings, "workspace_root", str(ws_root))
        monkeypatch.setattr(settings, "sandbox_root", str(tmp_path / "sandboxes"))

        factories.create_test_space(db, space_id=_SKIP_SPACE)
        factories.create_test_user(db, space_id=_SKIP_SPACE, user_id=_SKIP_USER)

        git_ws = tmp_path / "git_ws_skip"
        git_ws.mkdir()
        subprocess.run(["git", "init", str(git_ws)], check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "t@t.invalid"],
            check=True, capture_output=True, cwd=str(git_ws),
        )
        subprocess.run(["git", "config", "user.name", "T"], check=True, capture_output=True, cwd=str(git_ws))
        (git_ws / "init.txt").write_text("init", encoding="utf-8")
        subprocess.run(["git", "add", "init.txt"], check=True, capture_output=True, cwd=str(git_ws))
        subprocess.run(["git", "commit", "-m", "init"], check=True, capture_output=True, cwd=str(git_ws))

        class WritingAdapter(BaseRuntimeAdapter):
            adapter_type = "claude_code"
            requires_file_access = True
            supports_sandboxed_execution = True

            def execute(self, ctx: RuntimeExecutionContext) -> RuntimeAdapterResult:
                if ctx.sandbox_cwd:
                    (Path(ctx.sandbox_cwd) / "init.txt").write_text("changed", encoding="utf-8")
                return RuntimeAdapterResult(
                    success=True, stdout="ok", output_text=None, exit_code=0,
                    started_at=datetime.now(UTC), completed_at=datetime.now(UTC),
                )

        monkeypatch.setattr(
            "app.runs.execution.instantiate_runtime_adapter",
            lambda _: WritingAdapter(),
        )

        workspace = factories.create_test_workspace(
            db, space_id=_SKIP_SPACE, root_path=str(git_ws), allow_external_root=True,
        )
        agent = factories.create_test_agent(db, space_id=_SKIP_SPACE, owner_user_id=_SKIP_USER)
        version = db.query(AgentVersion).filter_by(id=agent.current_version_id).first()
        version.runtime_policy_json = {"risk_level": "high", "default_adapter_type": "claude_code"}
        db.flush()

        run = factories.create_test_run(db, space_id=_SKIP_SPACE, user_id=_SKIP_USER, agent=agent)
        run.workspace_id = workspace.id
        db.commit()

        # Collector returns skipped files but NO proposal_created
        def _fake_collect(_db, *, run=None, worktree_path=None, **kwargs):
            return WorktreeCollectionResult(
                proposal_created=False,
                ops_count=0,
                skipped=[{"path": "img.png", "reason": "binary"}, {"path": "data.bin", "reason": "binary"}],
                incomplete_patch=False,
                proposal=None,
            )

        monkeypatch.setattr(
            "app.runs.execution.collect_and_create_code_patch_proposal",
            _fake_collect,
        )

        RunExecutionService(db).execute_run(run.id, space_id=_SKIP_SPACE)
        db.flush()

        patch_events = (
            db.query(RunEvent)
            .filter(
                RunEvent.run_id == run.id,
                RunEvent.event_type == "patch_collected",
            )
            .all()
        )
        assert len(patch_events) >= 1, "patch_collected event must be emitted"
        ev = patch_events[0]
        assert ev.status == "warning", (
            f"Expected status=warning for skipped files, got {ev.status!r}"
        )
        assert ev.error_code == "code_patch_skipped_files", (
            f"Expected error_code=code_patch_skipped_files, got {ev.error_code!r}"
        )
        assert (ev.metadata_json or {}).get("skipped_count", 0) > 0, (
            "metadata_json must include skipped_count > 0"
        )

    def test_skipped_files_evaluation_sees_partial_or_incomplete(self, db):
        """RunEvaluation must see code_patch_skipped_files and produce partial or incomplete."""
        from app.runs.evaluation import RunEvaluationService
        from app.runs.events import RunEventService

        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        run.status = "succeeded"
        db.flush()

        svc_ev = RunEventService(db)
        svc_ev.append_event(
            run_id=run.id, space_id=SPACE,
            event_type="patch_collected", status="warning",
            error_code="code_patch_skipped_files",
            metadata_json={"proposal_created": False, "skipped_count": 2,
                           "skipped_reasons": ["binary"]},
        )
        db.flush()

        evaluation = RunEvaluationService(db).evaluate(run.id, space_id=SPACE)
        db.flush()

        # A succeeded run with code_patch_skipped_files must be partial
        assert evaluation.outcome_status == "partial", (
            f"Expected partial outcome for skipped files signal, got {evaluation.outcome_status!r}"
        )
        # Evidence must not rely on materialization_errors string parsing
        mat = (evaluation.evidence_json or {}).get("materialization", {})
        assert "code_patch_skipped_files" in mat.get("code_patch_warnings", []), (
            "code_patch_skipped_files must appear in materialization.code_patch_warnings"
        )


# ---------------------------------------------------------------------------
# RunOutputMaterializer emits RunEvents for artifact/proposal outcomes
# ---------------------------------------------------------------------------

class TestMaterializerEmitsRunEvents:
    """RunOutputMaterializer success and failure paths must emit RunEvents."""

    def test_artifact_success_emits_artifact_ingested_event(self, db, tmp_path, monkeypatch):
        from app.config import settings
        from app.models import AgentVersion, RunEvent
        from app.runtimes.base import BaseRuntimeAdapter, RuntimeAdapterResult, RuntimeExecutionContext
        from app.runs.execution import RunExecutionService
        from datetime import UTC, datetime

        art_root = tmp_path / "artifacts_mat"
        art_root.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(settings, "artifact_storage_root", str(art_root))
        monkeypatch.setattr(settings, "workspace_root", str(tmp_path / "wss_mat"))
        monkeypatch.setattr(settings, "sandbox_root", str(tmp_path / "sbs_mat"))

        factories.create_test_space(db, space_id=_MAT_SPACE)
        factories.create_test_user(db, space_id=_MAT_SPACE, user_id=_MAT_USER)

        class ArtifactOutputAdapter(BaseRuntimeAdapter):
            adapter_type = "echo"

            def execute(self, ctx: RuntimeExecutionContext) -> RuntimeAdapterResult:
                return RuntimeAdapterResult(
                    success=True, stdout="", output_text=None, exit_code=0,
                    started_at=datetime.now(UTC), completed_at=datetime.now(UTC),
                    output_json={
                        "artifacts": [{"artifact_type": "report", "title": "My Report", "content": "data"}]
                    },
                )

        monkeypatch.setattr(
            "app.runs.execution.instantiate_runtime_adapter",
            lambda _: ArtifactOutputAdapter(),
        )

        agent = factories.create_test_agent(db, space_id=_MAT_SPACE, owner_user_id=_MAT_USER)
        run = factories.create_test_run(db, space_id=_MAT_SPACE, user_id=_MAT_USER, agent=agent, commit=True)

        RunExecutionService(db).execute_run(run.id, space_id=_MAT_SPACE)

        db.refresh(run)
        assert run.status == "succeeded"

        ingested = (
            db.query(RunEvent)
            .filter(
                RunEvent.run_id == run.id,
                RunEvent.event_type == "artifact_ingested",
                RunEvent.status == "succeeded",
            )
            .all()
        )
        assert any((e.metadata_json or {}).get("source") == "adapter_output" for e in ingested), (
            "artifact_ingested succeeded event with source=adapter_output must be emitted"
        )
        source_events = [e for e in ingested if (e.metadata_json or {}).get("source") == "adapter_output"]
        assert source_events[0].artifact_id is not None, "artifact_id must be set on artifact_ingested event"

    def test_artifact_failure_emits_artifact_ingested_warning(self, db, tmp_path, monkeypatch):
        """Invalid artifact spec (missing content) must emit artifact_ingested warning."""
        from app.config import settings
        from app.models import RunEvent
        from app.runtimes.base import BaseRuntimeAdapter, RuntimeAdapterResult, RuntimeExecutionContext
        from app.runs.execution import RunExecutionService
        from datetime import UTC, datetime

        # Need a new unique space to avoid UNIQUE conflicts from db.commit() in previous test
        _space = "space-revi-mat-02"
        _user = "user-revi-mat-02"
        factories.create_test_space(db, space_id=_space)
        factories.create_test_user(db, space_id=_space, user_id=_user)

        art_root = tmp_path / "artifacts_mat2"
        art_root.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(settings, "artifact_storage_root", str(art_root))
        monkeypatch.setattr(settings, "workspace_root", str(tmp_path / "wss_mat2"))
        monkeypatch.setattr(settings, "sandbox_root", str(tmp_path / "sbs_mat2"))

        class BadArtifactAdapter(BaseRuntimeAdapter):
            adapter_type = "echo"

            def execute(self, ctx: RuntimeExecutionContext) -> RuntimeAdapterResult:
                return RuntimeAdapterResult(
                    success=True, stdout="", output_text=None, exit_code=0,
                    started_at=datetime.now(UTC), completed_at=datetime.now(UTC),
                    output_json={
                        "artifacts": [{"artifact_type": "report", "title": "Bad"}]  # missing content
                    },
                )

        monkeypatch.setattr("app.runs.execution.instantiate_runtime_adapter", lambda _: BadArtifactAdapter())

        agent = factories.create_test_agent(db, space_id=_space, owner_user_id=_user)
        run = factories.create_test_run(db, space_id=_space, user_id=_user, agent=agent, commit=True)

        RunExecutionService(db).execute_run(run.id, space_id=_space)

        db.refresh(run)
        assert run.status == "succeeded"

        failed_ingested = (
            db.query(RunEvent)
            .filter(
                RunEvent.run_id == run.id,
                RunEvent.event_type == "artifact_ingested",
                RunEvent.error_code == "output_artifact_materialization_error",
            )
            .all()
        )
        assert len(failed_ingested) >= 1, (
            "artifact_ingested warning with error_code=output_artifact_materialization_error must be emitted"
        )

    def test_artifact_failure_seen_by_run_evaluation(self, db, tmp_path, monkeypatch):
        """RunEvaluation must classify a run with output_artifact_materialization_error as partial."""
        from app.runs.evaluation import RunEvaluationService
        from app.runs.events import RunEventService

        _space = "space-revi-mat-eval-01"
        _user = "user-revi-mat-eval-01"
        factories.create_test_space(db, space_id=_space)
        factories.create_test_user(db, space_id=_space, user_id=_user)
        run = factories.create_test_run(db, space_id=_space, user_id=_user)
        run.status = "succeeded"
        db.flush()

        svc_ev = RunEventService(db)
        svc_ev.append_event(
            run_id=run.id, space_id=_space,
            event_type="artifact_ingested", status="warning",
            error_code="output_artifact_materialization_error",
            metadata_json={"source": "adapter_output", "label": "artifacts[0]"},
        )
        db.flush()

        evaluation = RunEvaluationService(db).evaluate(run.id, space_id=_space)
        db.flush()

        assert evaluation.outcome_status == "partial", (
            f"Expected partial for output_artifact_materialization_error, got {evaluation.outcome_status!r}"
        )
        # Error code must appear in evidence
        ev_key = (evaluation.evidence_json or {}).get("events", {})
        assert "output_artifact_materialization_error" in ev_key.get("event_error_codes", [])

    def test_proposal_success_emits_proposal_created_event(self, db, tmp_path, monkeypatch):
        """Successful output_json proposed_change must emit proposal_created RunEvent."""
        from app.config import settings
        from app.models import Proposal, RunEvent
        from app.runtimes.base import BaseRuntimeAdapter, RuntimeAdapterResult, RuntimeExecutionContext
        from app.runs.execution import RunExecutionService
        from datetime import UTC, datetime

        _space = "space-revi-mat-03"
        _user = "user-revi-mat-03"
        factories.create_test_space(db, space_id=_space)
        factories.create_test_user(db, space_id=_space, user_id=_user)

        art_root = tmp_path / "artifacts_mat3"
        art_root.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(settings, "artifact_storage_root", str(art_root))
        monkeypatch.setattr(settings, "workspace_root", str(tmp_path / "wss_mat3"))
        monkeypatch.setattr(settings, "sandbox_root", str(tmp_path / "sbs_mat3"))

        ws = factories.create_test_workspace(db, space_id=_space)

        class ProposalOutputAdapter(BaseRuntimeAdapter):
            adapter_type = "echo"

            def execute(self, ctx: RuntimeExecutionContext) -> RuntimeAdapterResult:
                return RuntimeAdapterResult(
                    success=True, stdout="", output_text=None, exit_code=0,
                    started_at=datetime.now(UTC), completed_at=datetime.now(UTC),
                    output_json={
                        "proposed_changes": [{
                            "proposal_type": "memory_update",
                            "summary": "Test proposal",
                            "payload": {
                                "proposed_content": "some content",
                                "memory_type": "note",
                                "target_scope": "space",
                                "target_namespace": "general",
                            },
                        }]
                    },
                )

        monkeypatch.setattr("app.runs.execution.instantiate_runtime_adapter", lambda _: ProposalOutputAdapter())

        agent = factories.create_test_agent(db, space_id=_space, owner_user_id=_user)
        run = factories.create_test_run(db, space_id=_space, user_id=_user, agent=agent, commit=True)
        run.workspace_id = ws.id
        db.commit()

        RunExecutionService(db).execute_run(run.id, space_id=_space)

        db.refresh(run)
        assert run.status == "succeeded"

        proposal_events = (
            db.query(RunEvent)
            .filter(
                RunEvent.run_id == run.id,
                RunEvent.event_type == "proposal_created",
                RunEvent.status == "succeeded",
            )
            .all()
        )
        output_proposal_events = [
            e for e in proposal_events
            if (e.metadata_json or {}).get("source") == "adapter_output"
        ]
        assert len(output_proposal_events) >= 1, (
            "proposal_created succeeded event with source=adapter_output must be emitted"
        )
        assert output_proposal_events[0].proposal_id is not None
        assert (output_proposal_events[0].metadata_json or {}).get("proposal_type") == "memory_update"

        # The Proposal row must exist (memory_update spec → memory_create row type)
        props = db.query(Proposal).filter(Proposal.created_by_run_id == run.id).all()
        assert len(props) >= 1, f"At least one Proposal row must exist; got {props!r}"

    def test_proposal_failure_emits_proposal_created_warning(self, db, tmp_path, monkeypatch):
        """Invalid proposed_change spec must emit proposal_created warning."""
        from app.config import settings
        from app.models import RunEvent
        from app.runtimes.base import BaseRuntimeAdapter, RuntimeAdapterResult, RuntimeExecutionContext
        from app.runs.execution import RunExecutionService
        from datetime import UTC, datetime

        _space = "space-revi-mat-04"
        _user = "user-revi-mat-04"
        factories.create_test_space(db, space_id=_space)
        factories.create_test_user(db, space_id=_space, user_id=_user)

        art_root = tmp_path / "artifacts_mat4"
        art_root.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(settings, "artifact_storage_root", str(art_root))
        monkeypatch.setattr(settings, "workspace_root", str(tmp_path / "wss_mat4"))
        monkeypatch.setattr(settings, "sandbox_root", str(tmp_path / "sbs_mat4"))

        class BadProposalAdapter(BaseRuntimeAdapter):
            adapter_type = "echo"

            def execute(self, ctx: RuntimeExecutionContext) -> RuntimeAdapterResult:
                return RuntimeAdapterResult(
                    success=True, stdout="", output_text=None, exit_code=0,
                    started_at=datetime.now(UTC), completed_at=datetime.now(UTC),
                    output_json={
                        "proposed_changes": [{"proposal_type": "unsupported_type"}]
                    },
                )

        monkeypatch.setattr("app.runs.execution.instantiate_runtime_adapter", lambda _: BadProposalAdapter())

        agent = factories.create_test_agent(db, space_id=_space, owner_user_id=_user)
        run = factories.create_test_run(db, space_id=_space, user_id=_user, agent=agent, commit=True)

        RunExecutionService(db).execute_run(run.id, space_id=_space)

        db.refresh(run)
        assert run.status == "succeeded"

        failed_events = (
            db.query(RunEvent)
            .filter(
                RunEvent.run_id == run.id,
                RunEvent.event_type == "proposal_created",
                RunEvent.error_code == "output_proposal_materialization_error",
            )
            .all()
        )
        assert len(failed_events) >= 1, (
            "proposal_created warning with error_code=output_proposal_materialization_error must be emitted"
        )


# ---------------------------------------------------------------------------
# Runtime output artifact persistence emits RunEvents
# ---------------------------------------------------------------------------

class TestActivityMaterializerFailureEmitsRunEvent:
    """Invalid activity spec must emit artifact_ingested warning with kind=activity."""

    def test_invalid_activity_emits_artifact_ingested_warning(self, db, tmp_path, monkeypatch):
        from app.config import settings
        from app.models import RunEvent
        from app.runtimes.base import BaseRuntimeAdapter, RuntimeAdapterResult, RuntimeExecutionContext
        from app.runs.execution import RunExecutionService
        from datetime import UTC, datetime

        _space = "space-revi-act-01"
        _user = "user-revi-act-01"
        factories.create_test_space(db, space_id=_space)
        factories.create_test_user(db, space_id=_space, user_id=_user)

        art_root = tmp_path / "artifacts_act"
        art_root.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(settings, "artifact_storage_root", str(art_root))
        monkeypatch.setattr(settings, "workspace_root", str(tmp_path / "wss_act"))
        monkeypatch.setattr(settings, "sandbox_root", str(tmp_path / "sbs_act"))

        class BadActivityAdapter(BaseRuntimeAdapter):
            adapter_type = "echo"

            def execute(self, ctx: RuntimeExecutionContext) -> RuntimeAdapterResult:
                return RuntimeAdapterResult(
                    success=True, stdout="", output_text=None, exit_code=0,
                    started_at=datetime.now(UTC), completed_at=datetime.now(UTC),
                    output_json={
                        # source_kind="invalid_kind" will fail _activity_from_spec validation
                        "activities": [{"source_kind": "invalid_kind", "title": "bad activity"}],
                    },
                )

        monkeypatch.setattr("app.runs.execution.instantiate_runtime_adapter", lambda _: BadActivityAdapter())

        agent = factories.create_test_agent(db, space_id=_space, owner_user_id=_user)
        run = factories.create_test_run(db, space_id=_space, user_id=_user, agent=agent, commit=True)

        RunExecutionService(db).execute_run(run.id, space_id=_space)

        db.refresh(run)
        assert run.status == "succeeded", f"Run must still succeed; got {run.status!r}"

        activity_events = (
            db.query(RunEvent)
            .filter(
                RunEvent.run_id == run.id,
                RunEvent.event_type == "artifact_ingested",
                RunEvent.error_code == "output_activity_materialization_error",
            )
            .all()
        )
        assert len(activity_events) >= 1, (
            "artifact_ingested warning with error_code=output_activity_materialization_error must be emitted"
        )
        ev = activity_events[0]
        assert ev.status == "warning"
        assert (ev.metadata_json or {}).get("kind") == "activity"
        assert (ev.metadata_json or {}).get("source") == "adapter_output"

    def test_activity_failure_seen_by_run_evaluation(self, db):
        """RunEvaluation must classify a run with output_activity_materialization_error as partial."""
        from app.runs.evaluation import RunEvaluationService
        from app.runs.events import RunEventService

        _space = "space-revi-act-eval-01"
        _user = "user-revi-act-eval-01"
        factories.create_test_space(db, space_id=_space)
        factories.create_test_user(db, space_id=_space, user_id=_user)
        run = factories.create_test_run(db, space_id=_space, user_id=_user)
        run.status = "succeeded"
        db.flush()

        svc_ev = RunEventService(db)
        svc_ev.append_event(
            run_id=run.id, space_id=_space,
            event_type="artifact_ingested", status="warning",
            error_code="output_activity_materialization_error",
            metadata_json={"kind": "activity", "source": "adapter_output", "label": "activities[0]"},
        )
        db.flush()

        evaluation = RunEvaluationService(db).evaluate(run.id, space_id=_space)
        db.flush()

        assert evaluation.outcome_status == "partial", (
            f"Expected partial for output_activity_materialization_error, got {evaluation.outcome_status!r}"
        )
        mat = (evaluation.evidence_json or {}).get("materialization", {})
        assert "output_activity_materialization_error" in mat.get("codes", []), (
            "output_activity_materialization_error must appear in materialization.codes"
        )
        ev_key = (evaluation.evidence_json or {}).get("events", {})
        assert "output_activity_materialization_error" in ev_key.get("event_error_codes", []), (
            "output_activity_materialization_error must appear in events.event_error_codes"
        )


class TestRuntimeOutputArtifactEvents:
    """runtime_output artifact persistence must emit artifact_ingested RunEvents."""

    def test_runtime_output_artifact_success_emits_artifact_ingested(self, db, tmp_path, monkeypatch):
        from app.config import settings
        from app.models import Run, RunEvent
        from app.runtimes.base import BaseRuntimeAdapter, RuntimeAdapterResult, RuntimeExecutionContext
        from app.runs.artifact_persistence import ArtifactPersistenceService
        from app.runs.execution import RunExecutionService
        from datetime import UTC, datetime
        from sqlalchemy.orm import sessionmaker

        _space = "space-revi-rt-01"
        _user = "user-revi-rt-01"
        factories.create_test_space(db, space_id=_space)
        factories.create_test_user(db, space_id=_space, user_id=_user)

        art_root = tmp_path / "artifacts_rt"
        art_root.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(settings, "artifact_storage_root", str(art_root))
        monkeypatch.setattr(settings, "workspace_root", str(tmp_path / "wss_rt"))
        monkeypatch.setattr(settings, "sandbox_root", str(tmp_path / "sbs_rt"))

        class OutputTextAdapter(BaseRuntimeAdapter):
            adapter_type = "echo"

            def execute(self, ctx: RuntimeExecutionContext) -> RuntimeAdapterResult:
                return RuntimeAdapterResult(
                    success=True, stdout="", output_text="hello world", exit_code=0,
                    started_at=datetime.now(UTC), completed_at=datetime.now(UTC),
                )

        monkeypatch.setattr("app.runs.execution.instantiate_runtime_adapter", lambda _: OutputTextAdapter())

        agent = factories.create_test_agent(db, space_id=_space, owner_user_id=_user)
        run = factories.create_test_run(db, space_id=_space, user_id=_user, agent=agent, commit=True)

        # Policy audit durability is covered by dedicated policy tests. SQLite
        # cannot run its independent audit write while this business transaction
        # is intentionally kept open across artifact persistence and terminal state.
        monkeypatch.setattr(
            "app.policy.audit.DurablePolicyAuditWriter.write",
            lambda _writer, _envelope: "stub-policy-audit",
        )
        original_persist = ArtifactPersistenceService.persist_text_file
        visible_status_during_persist = []

        def _persist_and_observe_committed_run(self, **kwargs):
            FreshSession = sessionmaker(bind=db.get_bind())
            fresh = FreshSession()
            try:
                visible_status_during_persist.append(
                    fresh.query(Run).filter(Run.id == kwargs["run"].id).one().status
                )
            finally:
                fresh.close()
            return original_persist(self, **kwargs)

        monkeypatch.setattr(ArtifactPersistenceService, "persist_text_file", _persist_and_observe_committed_run)

        RunExecutionService(db).execute_run(run.id, space_id=_space)

        db.refresh(run)
        assert run.status == "succeeded"
        assert visible_status_during_persist
        assert visible_status_during_persist[0] != "succeeded", (
            "terminal run success must not commit before runtime_output artifact persistence"
        )

        rt_events = (
            db.query(RunEvent)
            .filter(
                RunEvent.run_id == run.id,
                RunEvent.event_type == "artifact_ingested",
                RunEvent.status == "succeeded",
            )
            .all()
        )
        runtime_output_events = [
            e for e in rt_events
            if (e.metadata_json or {}).get("source") == "runtime_output_text"
        ]
        assert len(runtime_output_events) >= 1, (
            "artifact_ingested succeeded event with source=runtime_output_text must be emitted"
        )
        assert runtime_output_events[0].artifact_id is not None

    def test_runtime_output_artifact_failure_emits_artifact_ingested_failed(self, db, tmp_path, monkeypatch):
        """When persist_text_file raises, artifact_ingested failed must be emitted and run still commits."""
        from app.config import settings
        from app.models import Run, RunEvent
        from app.runtimes.base import BaseRuntimeAdapter, RuntimeAdapterResult, RuntimeExecutionContext
        from app.runs.execution import RunExecutionService
        from datetime import UTC, datetime
        from sqlalchemy.orm import sessionmaker

        _space = "space-revi-rt-02"
        _user = "user-revi-rt-02"
        factories.create_test_space(db, space_id=_space)
        factories.create_test_user(db, space_id=_space, user_id=_user)

        art_root = tmp_path / "artifacts_rt2"
        art_root.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(settings, "artifact_storage_root", str(art_root))
        monkeypatch.setattr(settings, "workspace_root", str(tmp_path / "wss_rt2"))
        monkeypatch.setattr(settings, "sandbox_root", str(tmp_path / "sbs_rt2"))

        class OutputTextAdapter(BaseRuntimeAdapter):
            adapter_type = "echo"

            def execute(self, ctx: RuntimeExecutionContext) -> RuntimeAdapterResult:
                return RuntimeAdapterResult(
                    success=True, stdout="", output_text="output", exit_code=0,
                    started_at=datetime.now(UTC), completed_at=datetime.now(UTC),
                )

        monkeypatch.setattr("app.runs.execution.instantiate_runtime_adapter", lambda _: OutputTextAdapter())

        # Force persist_text_file to raise
        visible_status_during_persist = []

        def _failing_persist(*args, **kwargs):
            FreshSession = sessionmaker(bind=db.get_bind())
            fresh = FreshSession()
            try:
                visible_status_during_persist.append(
                    fresh.query(Run).filter(Run.id == kwargs["run"].id).one().status
                )
            finally:
                fresh.close()
            raise RuntimeError("disk full")

        monkeypatch.setattr(
            "app.runs.execution.ArtifactPersistenceService.persist_text_file",
            _failing_persist,
        )

        agent = factories.create_test_agent(db, space_id=_space, owner_user_id=_user)
        run = factories.create_test_run(db, space_id=_space, user_id=_user, agent=agent, commit=True)

        RunExecutionService(db).execute_run(run.id, space_id=_space)

        db.refresh(run)
        # Terminal run commit must not be poisoned
        assert run.status == "succeeded", f"Run terminal commit must not be poisoned; status={run.status!r}"
        assert visible_status_during_persist
        assert visible_status_during_persist[0] != "succeeded", (
            "terminal run success must not commit before failed runtime_output artifact persistence"
        )

        failed_rt_events = (
            db.query(RunEvent)
            .filter(
                RunEvent.run_id == run.id,
                RunEvent.event_type == "artifact_ingested",
                RunEvent.error_code == "runtime_output_artifact",
            )
            .all()
        )
        assert len(failed_rt_events) >= 1, (
            "artifact_ingested failed event with error_code=runtime_output_artifact must be emitted"
        )
