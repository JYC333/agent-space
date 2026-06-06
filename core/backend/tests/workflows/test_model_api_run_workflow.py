"""End-to-end: a scheduled-style, no-tools API agent run through model_api.

Drives a real Run through RunExecutionService with the real model_api adapter and
the real shared invocation primitive. Only ``litellm.completion`` (the network call)
is mocked. Proves the full chain: provider config + agent + run → policy gates →
credential resolution → adapter → LLM call → output materialized as an Artifact.

Uses an Anthropic ModelProvider to also demonstrate ADR 0010: Anthropic is served
through the in-process encrypted API channel (key as a litellm parameter, never env),
which is a separate channel from the Claude Code CLI runtime.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.config import settings
from app.models import Artifact, MemoryEntry, Proposal, Run, RunStep
from app.runs.execution import RunExecutionService
from tests.support import factories


def _fake_litellm_response(text: str):
    choice = MagicMock()
    choice.message.content = text
    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = None
    return resp


def test_model_api_run_executes_and_materializes_artifact(
    db, test_user, test_space, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "artifact_storage_root", str(tmp_path / "artifacts"))
    monkeypatch.setattr(settings, "workspace_root", str(tmp_path / "workspaces"))
    monkeypatch.setattr(settings, "sandbox_root", str(tmp_path / "sandboxes"))

    space_id = test_space.id
    user = test_user

    # 1. User configures a ModelProvider (any vendor — here Anthropic) with an API key.
    provider = factories.create_test_model_provider(
        db,
        space_id=space_id,
        provider_type="anthropic",
        with_api_key=True,
        default_model="claude-3-5-sonnet-latest",
        enabled=True,
        commit=False,
    )

    # 2. Agent (its DEFAULT_RUNTIME_POLICY already allows model_api).
    agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user.id, commit=False)

    # 3. A queued model_api Run bound to that provider + a prompt (no tools).
    run = factories.create_test_run(db, space_id=space_id, user_id=user.id, agent=agent, commit=False)
    run.adapter_type = "model_api"
    run.model_provider_id = provider.id
    run.model_override_json = {"model": "claude-3-5-sonnet-latest", "source": "request"}
    run.prompt = "Summarize: the quick brown fox."
    db.commit()

    mem_before = db.query(MemoryEntry).filter(MemoryEntry.space_id == space_id).count()

    # 4. Execute — real pipeline, only the network call is mocked.
    with patch(
        "litellm.completion", return_value=_fake_litellm_response("A fox summary.")
    ) as mock_litellm:
        result = RunExecutionService(db).execute_run(run.id, space_id=space_id)

    # 5a. Run succeeded and the LLM text is the run output.
    assert result.success is True
    db.expire_all()
    run_row = db.query(Run).filter(Run.id == run.id).one()
    assert run_row.status == "succeeded"
    assert run_row.output_json["runtime_adapter_type"] == "model_api"
    assert run_row.output_json["output_text"] == "A fox summary."

    # 5b. litellm was called via the isolated in-process channel:
    #     anthropic model qualified, encrypted key passed as a parameter, no tools.
    kwargs = mock_litellm.call_args.kwargs
    assert kwargs["model"] == "anthropic/claude-3-5-sonnet-latest"
    assert kwargs["api_key"] == "sk-test-factory-key"
    assert "tools" not in kwargs
    roles = [m["role"] for m in kwargs["messages"]]
    assert roles == ["system", "user"]
    assert "the quick brown fox" in kwargs["messages"][1]["content"]

    # 5c. Output materialized as a durable Artifact bound to the run. The runtime
    #     output text is persisted to a file under artifact_storage_root (content=None).
    arts = db.query(Artifact).filter(Artifact.run_id == run.id).all()
    assert len(arts) >= 1
    for a in arts:
        assert a.space_id == space_id
    stored_texts = [
        (tmp_path / "artifacts" / a.storage_path).read_text(encoding="utf-8")
        for a in arts
        if a.storage_path
    ]
    assert any("A fox summary." in t for t in stored_texts)

    # 5d. Replay spine present; no silent memory writes or run proposals.
    step_types = {s.step_type for s in db.query(RunStep).filter(RunStep.run_id == run.id).all()}
    assert {"adapter_started", "completed"}.issubset(step_types)
    assert db.query(MemoryEntry).filter(MemoryEntry.space_id == space_id).count() == mem_before
    assert (
        db.query(Proposal).filter(Proposal.created_by_run_id == run.id).count() == 0
    )


def test_model_api_run_fails_cleanly_without_provider(
    db, test_user, test_space, tmp_path, monkeypatch
):
    """A model_api run with no resolved ModelProvider fails closed (no LLM call)."""
    monkeypatch.setattr(settings, "artifact_storage_root", str(tmp_path / "artifacts"))
    monkeypatch.setattr(settings, "workspace_root", str(tmp_path / "workspaces"))
    monkeypatch.setattr(settings, "sandbox_root", str(tmp_path / "sandboxes"))

    space_id = test_space.id
    agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=test_user.id, commit=False)
    run = factories.create_test_run(db, space_id=space_id, user_id=test_user.id, agent=agent, commit=False)
    run.adapter_type = "model_api"
    run.prompt = "anything"
    db.commit()

    with patch("litellm.completion") as mock_litellm:
        result = RunExecutionService(db).execute_run(run.id, space_id=space_id)

    assert result.success is False
    mock_litellm.assert_not_called()
    db.expire_all()
    assert db.query(Run).filter(Run.id == run.id).one().status == "failed"
