"""Workflow tests for PersonalMemoryGrant runtime-only prompt injection."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from ulid import ULID

from app.models import (
    AgentVersion,
    Artifact,
    ContextSnapshot,
    MemoryEntry,
    PersonalMemoryGrant,
    Proposal,
    Run,
    SpaceMembership,
)
from app.runs.execution import RunExecutionService
from app.runtimes.base import RuntimeAdapterResult, RuntimeExecutionContext
from app.source_pointers.service import GrantDerivedSourcePointerError, create_source_pointer
from tests.support import factories


def _new_id() -> str:
    return str(ULID())


class _CapturingRuntimeAdapter:
    adapter_type = "echo"
    requires_credentials = False
    requires_file_access = False
    supports_sandboxed_execution = False

    def __init__(
        self,
        *,
        output_text: str = "",
        output_json: dict[str, Any] | None = None,
        echo_prompt_output: bool = False,
    ) -> None:
        self.seen_contexts: list[RuntimeExecutionContext] = []
        self.output_text = output_text
        self.output_json = output_json if output_json is not None else {"runtime_test": True}
        self.echo_prompt_output = echo_prompt_output

    def execute(self, ctx: RuntimeExecutionContext) -> RuntimeAdapterResult:
        self.seen_contexts.append(ctx)
        now = datetime.now(UTC)
        output_text = ctx.prompt if self.echo_prompt_output else self.output_text
        output_json = dict(self.output_json)
        if self.echo_prompt_output:
            output_json["echoed_prompt"] = ctx.prompt
        return RuntimeAdapterResult(
            success=True,
            stdout=output_text,
            stderr="",
            output_text=output_text,
            output_json=output_json,
            exit_code=0,
            started_at=now,
            completed_at=now,
            adapter_metadata={"adapter_type": self.adapter_type},
        )


def _personal_space(db):
    sid = _new_id()
    factories.create_test_space(db, space_id=sid, name="Personal", space_type="personal")
    user = factories.create_test_user(db, space_id=sid, display_name="Personal User")
    db.commit()
    return sid, user


def _team_space(db):
    sid = _new_id()
    factories.create_test_space(db, space_id=sid, name="Team", space_type="team")
    user = factories.create_test_user(db, space_id=sid, display_name="Team User")
    db.commit()
    return sid, user


def _add_member(db, *, space_id: str, user_id: str) -> None:
    db.add(SpaceMembership(
        id=_new_id(), space_id=space_id, user_id=user_id, role="member", status="active"
    ))


def _private_memory(db, *, space_id: str, owner_user_id: str, content: str) -> MemoryEntry:
    row = MemoryEntry(
        id=_new_id(),
        space_id=space_id,
        scope_type="user",
        memory_type="semantic",
        content=content,
        status="active",
        visibility="private",
        owner_user_id=owner_user_id,
        subject_user_id=owner_user_id,
        sensitivity_level="normal",
    )
    db.add(row)
    db.flush()
    return row


def _active_grant(
    db,
    *,
    granting_user_id: str,
    personal_space_id: str,
    target_space_id: str,
    target_run_id: str,
) -> PersonalMemoryGrant:
    grant = PersonalMemoryGrant(
        id=_new_id(),
        granting_user_id=granting_user_id,
        personal_space_id=personal_space_id,
        target_space_id=target_space_id,
        target_run_id=target_run_id,
        target_agent_id=None,
        grant_scope="run",
        access_mode="summary_only",
        status="active",
        memory_filter_json=None,
        read_expires_at=datetime.now(UTC) + timedelta(hours=1),
        egress_review_expires_at=datetime.now(UTC) + timedelta(hours=2),
    )
    db.add(grant)
    db.flush()
    return grant


def _prepare_roots(monkeypatch, tmp_path) -> None:
    from app.config import settings

    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "artifact_storage_root", str(artifact_root))
    monkeypatch.setattr(settings, "workspace_root", str(tmp_path / "workspaces"))
    monkeypatch.setattr(settings, "sandbox_root", str(tmp_path / "sandboxes"))


def _grant_run(db, *, prompt: str = "Use the available context") -> tuple[str, Any, str, Run, PersonalMemoryGrant, MemoryEntry]:
    personal_id, user = _personal_space(db)
    team_id, _team_user = _team_space(db)
    _add_member(db, space_id=team_id, user_id=user.id)
    private = _private_memory(
        db,
        space_id=personal_id,
        owner_user_id=user.id,
        content="RUNTIME_INJECTION_RAW_PRIVATE_SENTINEL",
    )
    run = factories.create_test_run(db, space_id=team_id, user_id=user.id, commit=False)
    run.prompt = prompt
    version = db.query(AgentVersion).filter(AgentVersion.id == run.agent_version_id).one()
    version.system_prompt = "stable agent system prompt"
    db.flush()
    grant = _active_grant(
        db,
        granting_user_id=user.id,
        personal_space_id=personal_id,
        target_space_id=team_id,
        target_run_id=run.id,
    )
    db.commit()
    return personal_id, user, team_id, run, grant, private


def _execute(db, monkeypatch, tmp_path, run: Run, adapter: _CapturingRuntimeAdapter):
    _prepare_roots(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "app.runs.execution.instantiate_runtime_adapter",
        lambda _adapter_type: adapter,
    )
    return RunExecutionService(db).execute_run(run.id, space_id=run.space_id)


def test_valid_grant_personal_context_block_is_passed_to_runtime_prompt_transiently(
    db, monkeypatch, tmp_path
):
    _, _, _, run, _, _ = _grant_run(db)
    adapter = _CapturingRuntimeAdapter()

    result = _execute(db, monkeypatch, tmp_path, run, adapter)

    assert result.success is True
    assert len(adapter.seen_contexts) == 1
    prompt = adapter.seen_contexts[0].prompt
    assert "[Personal context granted for this run - reasoning only]" in prompt
    assert "The user has 1 relevant personal memory entry available" in prompt
    assert "RUNTIME_INJECTION_RAW_PRIVATE_SENTINEL" not in prompt


def test_runtime_prompt_includes_reasoning_only_warning(db, monkeypatch, tmp_path):
    _, _, _, run, _, _ = _grant_run(db)
    adapter = _CapturingRuntimeAdapter()

    _execute(db, monkeypatch, tmp_path, run, adapter)

    prompt = adapter.seen_contexts[0].prompt
    assert "This personal context is granted for reasoning only." in prompt
    assert "Do not quote or persist it directly." in prompt
    assert "[End personal context]" in prompt


def test_persisted_context_snapshot_does_not_include_runtime_personal_context(
    db, monkeypatch, tmp_path
):
    _, _, _, run, _, private = _grant_run(db)
    adapter = _CapturingRuntimeAdapter()

    _execute(db, monkeypatch, tmp_path, run, adapter)

    db.expire_all()
    run_row = db.query(Run).filter(Run.id == run.id).one()
    snap = db.query(ContextSnapshot).filter(ContextSnapshot.id == run_row.context_snapshot_id).one()
    serialized_source_refs = str(snap.source_refs_json or [])
    serialized_trace = str(snap.retrieval_trace_json or [])
    summary = "The user has 1 relevant personal memory entry available"

    assert summary not in (snap.compiled_prefix_text or "")
    assert summary not in (snap.compiled_tail_text or "")
    assert summary not in serialized_source_refs
    assert summary not in serialized_trace
    assert private.id not in serialized_source_refs
    assert "RUNTIME_INJECTION_RAW_PRIVATE_SENTINEL" not in serialized_source_refs
    assert "RUNTIME_INJECTION_RAW_PRIVATE_SENTINEL" not in serialized_trace


def test_adapter_echoed_personal_context_block_is_redacted_from_persisted_run_output(
    db, monkeypatch, tmp_path
):
    _, _, _, run, _, _ = _grant_run(db)
    adapter = _CapturingRuntimeAdapter(echo_prompt_output=True)

    _execute(db, monkeypatch, tmp_path, run, adapter)

    db.expire_all()
    run_row = db.query(Run).filter(Run.id == run.id).one()
    raw = str(run_row.output_json or {})
    assert "The user has 1 relevant personal memory entry available" not in raw
    assert "Raw memory content is not included in this summary" not in raw
    assert "[REDACTED_PERSONAL_CONTEXT_BLOCK]" in raw


def test_run_persisted_prompt_fields_do_not_include_personal_context(
    db, monkeypatch, tmp_path
):
    _, _, _, run, _, _ = _grant_run(db, prompt="original persisted prompt")
    adapter = _CapturingRuntimeAdapter()

    _execute(db, monkeypatch, tmp_path, run, adapter)

    db.expire_all()
    run_row = db.query(Run).filter(Run.id == run.id).one()
    version = db.query(AgentVersion).filter(AgentVersion.id == run_row.agent_version_id).one()
    assert run_row.prompt == "original persisted prompt"
    assert "[Personal context granted for this run" not in (run_row.prompt or "")
    assert "The user has 1 relevant personal memory entry available" not in (run_row.prompt or "")
    assert version.system_prompt == "stable agent system prompt"
    assert "[Personal context granted for this run" not in (version.system_prompt or "")


def test_no_grant_runtime_prompt_has_no_personal_context_block(db, monkeypatch, tmp_path):
    _, user = _personal_space(db)
    team_id, _team_user = _team_space(db)
    _add_member(db, space_id=team_id, user_id=user.id)
    run = factories.create_test_run(db, space_id=team_id, user_id=user.id, commit=False)
    run.prompt = "regular prompt"
    db.commit()
    adapter = _CapturingRuntimeAdapter()

    _execute(db, monkeypatch, tmp_path, run, adapter)

    prompt = adapter.seen_contexts[0].prompt
    assert prompt == "regular prompt"
    assert "[Personal context granted for this run" not in prompt


def test_runtime_injection_does_not_enable_direct_shared_artifact_persistence(
    db, monkeypatch, tmp_path
):
    _, _, team_id, run, grant, _ = _grant_run(db)
    adapter = _CapturingRuntimeAdapter(
        output_text="model output derived from runtime personal context",
        output_json={
            "artifacts": [{
                "artifact_type": "report",
                "title": "Derived report",
                "content": "derived shared report",
            }]
        },
    )

    result = _execute(db, monkeypatch, tmp_path, run, adapter)

    assert result.success is True
    db.expire_all()
    run_row = db.query(Run).filter(Run.id == run.id).one()
    assert run_row.has_personal_grant_context is True
    provenance = (run_row.output_json or {}).get("output_provenance") or {}
    assert provenance == {
        "derived_from_personal_memory": True,
        "personal_memory_grant_ids": [grant.id],
        "raw_private_memory_included": False,
        "personal_summary_persisted": False,
    }
    errors = (run_row.output_json or {}).get("materialization_errors") or []
    assert any("artifacts[0]" in e and "egress" in e.lower() for e in errors)
    assert any("runtime_output_artifact" in e and "egress" in e.lower() for e in errors)
    assert db.query(Artifact).filter(Artifact.space_id == team_id).count() == 0


def test_runtime_injection_does_not_enable_direct_shared_memory_persistence(
    db, monkeypatch, tmp_path
):
    _, _, team_id, run, _, _ = _grant_run(db)
    adapter = _CapturingRuntimeAdapter(
        output_json={
            "proposed_changes": [{
                "proposal_type": "memory_update",
                "summary": "Grant-derived memory",
                "payload": {
                    "proposed_content": "derived from personal context",
                    "memory_type": "semantic",
                    "target_scope": "space",
                    "target_namespace": "space.knowledge",
                    "target_visibility": "space_shared",
                },
            }]
        },
    )

    result = _execute(db, monkeypatch, tmp_path, run, adapter)

    assert result.success is True
    db.expire_all()
    run_row = db.query(Run).filter(Run.id == run.id).one()
    errors = (run_row.output_json or {}).get("materialization_errors") or []
    assert any("proposed_changes[0]" in e and "egress" in e.lower() for e in errors)
    # Phase F2: only egress_review proposals may exist (no memory proposals)
    all_proposals = db.query(Proposal).filter(Proposal.space_id == team_id).all()
    memory_proposals = [p for p in all_proposals if p.proposal_type != "egress_review"]
    assert len(memory_proposals) == 0, (
        f"No memory proposals must be created in team space for grant-derived run: {[p.proposal_type for p in memory_proposals]}"
    )


def test_runtime_injection_does_not_enable_source_pointer_content_persistence(
    db, monkeypatch, tmp_path
):
    personal_id, user, team_id, run, _, private = _grant_run(db)
    adapter = _CapturingRuntimeAdapter()
    _execute(db, monkeypatch, tmp_path, run, adapter)

    db.expire_all()
    run_row = db.query(Run).filter(Run.id == run.id).one()
    metadata = dict((run_row.output_json or {}).get("output_provenance") or {})
    assert metadata.get("derived_from_personal_memory") is True

    with pytest.raises(GrantDerivedSourcePointerError):
        create_source_pointer(
            db,
            owner_space_id=team_id,
            source_space_id=personal_id,
            source_object_type="memory_entry",
            source_object_id=private.id,
            access_mode="read",
            granted_by_user_id=user.id,
            metadata_json=metadata,
        )
