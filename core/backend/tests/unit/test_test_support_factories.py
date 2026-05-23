"""Sanity checks for test support factories (not product invariants)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.models import Space, User
from app.runtimes.base import RuntimeExecutionContext
from tests.support.assertions import assert_memory_unchanged, assert_policy_requires_approval
from tests.support.fake_provider import DeterministicFakeProvider, FakeProviderConfig
from tests.support.fake_runtime import ConfigurableFakeRuntimeAdapter, FakeRuntimeConfig
from tests.support.ids import PERSONAL_SPACE_ID
from tests.support import factories


def test_create_test_space_user_roundtrip(db):
    s = factories.create_test_space(db, space_id="s_iso_1", name="N1", space_type="team")
    u = factories.create_test_user(db, space_id=s.id, user_id="u_iso_1")
    assert db.query(Space).filter(Space.id == s.id).one().name == "N1"
    assert db.query(User).filter(User.id == u.id).one().space_id == s.id


def test_create_test_agent_has_version(db):
    u = factories.create_test_user(db, space_id=PERSONAL_SPACE_ID, user_id="u_agent_seed")
    ag = factories.create_test_agent(db, space_id=PERSONAL_SPACE_ID, owner_user_id=u.id)
    assert ag.current_version_id is not None


def test_create_test_run_is_queued(db):
    u = factories.create_test_user(db, space_id=PERSONAL_SPACE_ID, user_id="u_run_seed")
    run = factories.create_test_run(db, space_id=PERSONAL_SPACE_ID, user_id=u.id, owner_user_id=u.id)
    assert run.status == "queued"
    assert run.space_id == PERSONAL_SPACE_ID


def test_fake_runtime_deterministic_success():
    fixed = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    cfg = FakeRuntimeConfig(
        output_text="ok",
        output_json={"k": 1},
        fixed_clock=fixed,
        produced_artifact_paths=["rel/out.txt"],
    )
    adapter = ConfigurableFakeRuntimeAdapter(cfg)
    ctx = RuntimeExecutionContext(
        run_id="r1",
        space_id=PERSONAL_SPACE_ID,
        prompt="hi",
        mode="live",
        sandbox_cwd=None,
        model_name=None,
        system_prompt=None,
        adapter_config={},
        simulate_failure=False,
    )
    r = adapter.execute(ctx)
    assert r.success is True
    assert r.output_text == "ok"
    assert r.output_json["k"] == 1
    assert r.produced_artifact_paths == ["rel/out.txt"]
    assert r.started_at == fixed and r.completed_at == fixed


def test_fake_runtime_simulate_failure():
    adapter = ConfigurableFakeRuntimeAdapter()
    ctx = RuntimeExecutionContext(
        run_id="r1",
        space_id=PERSONAL_SPACE_ID,
        prompt="x",
        mode="live",
        sandbox_cwd=None,
        model_name=None,
        system_prompt=None,
        adapter_config={},
        simulate_failure=True,
    )
    r = adapter.execute(ctx)
    assert r.success is False
    assert r.error_code == "simulated_failure"


@pytest.mark.asyncio
async def test_fake_provider_deterministic():
    p = DeterministicFakeProvider(
        FakeProviderConfig(content="c", model="openai/gpt-test", provider="openai")
    )
    from app.providers.models import ChatMessage, ChatRequest

    req = ChatRequest(model=None, messages=[ChatMessage(role="user", content="a")])
    out = await p.complete("k", None, req)
    assert out.content == "c"
    assert out.model == "openai/gpt-test"


@pytest.mark.asyncio
async def test_fake_provider_failure_raises():
    p = DeterministicFakeProvider(FakeProviderConfig(fail=True))
    from app.providers.models import ChatMessage, ChatRequest

    req = ChatRequest(model="m", messages=[ChatMessage(role="user", content="a")])
    with pytest.raises(RuntimeError, match="fake provider"):
        await p.complete("k", None, req)


def test_assert_memory_unchanged_fails_when_new_row(db):
    from app.models import MemoryEntry

    baseline = frozenset(r[0] for r in db.query(MemoryEntry.id).filter(MemoryEntry.space_id == PERSONAL_SPACE_ID).all())
    factories.create_test_memory_entry(db, space_id=PERSONAL_SPACE_ID, content="x")
    with pytest.raises(AssertionError, match="memory set changed"):
        assert_memory_unchanged(db, space_id=PERSONAL_SPACE_ID, baseline_ids=baseline)


def test_assert_policy_requires_approval_helper():
    assert_policy_requires_approval(
        {"action": "memory.create", "resource_id": "user"},
    )


def test_factory_commit_true_persists_and_refreshes(db):
    """Explicit ``commit=True`` finishes the transaction and refreshes the row."""
    s = factories.create_test_space(db, space_id="s_commit_1", name="C1", space_type="team", commit=True)
    u = factories.create_test_user(db, space_id=s.id, user_id="u_commit_1", commit=True)
    assert u.id == "u_commit_1"
    assert u.display_name == "u_commit_1"
