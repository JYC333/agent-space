"""Tests for the SpaceCreatedHookRegistry and its module-owned registration.

Covers the registry's dispatch mechanics (deterministic order, duplicate
detection, async rejection, failure propagation) and verifies that every module
that previously seeded per-space state during Space creation is now registered
exactly once — with no legacy direct seeder calls left in the spaces service.
"""

from __future__ import annotations

import importlib
import inspect

import pytest

from app.spaces import (
    DuplicateSpaceCreatedHookError,
    SpaceCreatedContext,
    SpaceCreatedHookRegistry,
)
from app.spaces.hooks import InvalidSpaceCreatedHookError
from app.modules.registry import Module, register_space_created_hooks


# The per-space initializers that existed before the registry refactor. Exact
# match guards against silent drift (an accidental drop or addition).
EXISTING_SPACE_CREATED_HOOKS = {
    "memory:system_memories",
    "execution_planes:default_planes",
    "knowledge:default_note_collections",
}


def _ctx() -> SpaceCreatedContext:
    # The dispatch-mechanics tests below never touch the DB, so a placeholder is
    # fine; hooks here only record that they ran.
    return SpaceCreatedContext(db=None, space_id="space-1", seeded_by_user_id="user-1")


# ---------------------------------------------------------------------------
# Dispatch mechanics
# ---------------------------------------------------------------------------

def test_duplicate_hook_name_fails_fast():
    registry = SpaceCreatedHookRegistry()
    registry.register("dup", lambda ctx: None)
    with pytest.raises(DuplicateSpaceCreatedHookError):
        registry.register("dup", lambda ctx: None)


def test_invalid_hook_registration_rejected():
    registry = SpaceCreatedHookRegistry()
    with pytest.raises(InvalidSpaceCreatedHookError):
        registry.register("", lambda ctx: None)
    with pytest.raises(InvalidSpaceCreatedHookError):
        registry.register("not-callable", object())  # type: ignore[arg-type]


def test_hooks_run_in_deterministic_order():
    registry = SpaceCreatedHookRegistry()
    calls: list[str] = []

    # Register out of order; execution sorts by (order, name).
    registry.register("c", lambda ctx: calls.append("c"), order=300)
    registry.register("a", lambda ctx: calls.append("a"), order=100)
    registry.register("b", lambda ctx: calls.append("b"), order=200)
    # Same order — broken by name.
    registry.register("a2", lambda ctx: calls.append("a2"), order=100)

    assert registry.registered_hooks() == ["a", "a2", "b", "c"]
    registry.run(_ctx())
    assert calls == ["a", "a2", "b", "c"]


def test_async_hook_is_rejected():
    # Hooks are synchronous: context.db is a thread-bound sync Session, so async
    # hooks are not supported. A hook returning an awaitable must fail loudly
    # rather than silently leaking an un-awaited coroutine.
    registry = SpaceCreatedHookRegistry()

    async def async_hook(ctx):  # pragma: no cover - body never awaited
        return None

    registry.register("async", async_hook)
    with pytest.raises(InvalidSpaceCreatedHookError, match="async hooks are not supported"):
        registry.run(_ctx())


def test_hook_exception_propagates():
    # Preserves the original direct-seeding failure semantics: a hook that raises
    # propagates unchanged so the caller's transaction is never committed.
    registry = SpaceCreatedHookRegistry()

    def boom(ctx):
        raise RuntimeError("hook exploded")

    registry.register("boom", boom)
    with pytest.raises(RuntimeError, match="hook exploded"):
        registry.run(_ctx())


def test_clear_resets_registry():
    registry = SpaceCreatedHookRegistry()
    registry.register("x", lambda ctx: None)
    registry.clear()
    assert registry.registered_hooks() == []


# ---------------------------------------------------------------------------
# Module-owned registration completeness
# ---------------------------------------------------------------------------

def test_module_registration_covers_all_existing_hooks():
    registry = SpaceCreatedHookRegistry()
    loaded = register_space_created_hooks(registry)

    registered = set(registry.registered_hooks())
    missing = EXISTING_SPACE_CREATED_HOOKS - registered
    assert not missing, f"existing space-created hooks no longer registered: {sorted(missing)}"
    # Exact match guards against silent drift.
    assert registered == EXISTING_SPACE_CREATED_HOOKS
    # memory + execution_planes + knowledge own the registration hooks.
    assert set(loaded) == {"memory", "execution_planes", "knowledge"}


def test_registered_hook_names_are_unique_and_ordered():
    registry = SpaceCreatedHookRegistry()
    register_space_created_hooks(registry)
    names = registry.registered_hooks()
    assert len(names) == len(set(names)), "hook names must be unique"
    # Deterministic execution order: memory → execution_planes → knowledge.
    assert names == [
        "memory:system_memories",
        "execution_planes:default_planes",
        "knowledge:default_note_collections",
    ]


def test_module_registration_is_idempotent_per_fresh_registry():
    first = SpaceCreatedHookRegistry()
    register_space_created_hooks(first)
    second = SpaceCreatedHookRegistry()
    register_space_created_hooks(second)
    assert first.registered_hooks() == second.registered_hooks()


def test_register_space_created_hooks_fails_fast_on_bad_import():
    bad = Module(
        "badmod", "Bad", "app.spaces", space_created_hooks="does_not_exist", always_on=True
    )
    with pytest.raises(ImportError):
        register_space_created_hooks(SpaceCreatedHookRegistry(), modules=[bad])


def test_register_space_created_hooks_fails_fast_on_missing_hook():
    # app.spaces.defaults exists but exposes no register_space_created_hooks.
    nohook = Module(
        "nohook", "NoHook", "app.spaces", space_created_hooks="defaults", always_on=True
    )
    with pytest.raises(RuntimeError, match="register_space_created_hooks"):
        register_space_created_hooks(SpaceCreatedHookRegistry(), modules=[nohook])


def test_register_space_created_hooks_skips_disabled_optional_module():
    disabled = Module(
        "optmod", "Opt", "app.spaces", space_created_hooks="does_not_exist", always_on=False
    )
    registry = SpaceCreatedHookRegistry()
    loaded = register_space_created_hooks(registry, enabled=None, modules=[disabled])
    assert loaded == []
    assert registry.registered_hooks() == []


# ---------------------------------------------------------------------------
# Boundary / facade guards
# ---------------------------------------------------------------------------

def test_registry_module_imports_no_product_modules():
    # The registry owns dispatch mechanics only — importing it must not pull in
    # product seeding modules at import time.
    import sys
    import importlib

    for mod in ("app.memory", "app.knowledge", "app.execution_planes"):
        sys.modules.pop(mod, None)
    importlib.reload(importlib.import_module("app.spaces.hooks"))

    product = {"app.memory", "app.knowledge", "app.execution_planes"}
    loaded_product = product & set(sys.modules)
    assert not loaded_product, (
        f"importing app.spaces.hooks pulled in product modules: {sorted(loaded_product)}"
    )


def test_spaces_facade_imports_cleanly():
    import importlib

    spaces = importlib.import_module("app.spaces")
    for name in (
        "SpaceCreatedContext",
        "SpaceCreatedHook",
        "SpaceCreatedHookRegistry",
        "DuplicateSpaceCreatedHookError",
    ):
        assert hasattr(spaces, name), f"spaces facade missing {name}"


def test_on_space_created_produces_same_default_records(db):
    # End-to-end through the real registry: a new space gets system-policy
    # memories, default execution planes, and default note collections — the
    # same side effects the legacy direct-seeding path produced.
    import uuid

    from app import models
    from app.spaces.hooks import on_space_created, reset_registry

    reset_registry()  # ensure the lazily built default registry is used

    space_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    db.add(models.User(id=user_id, email=f"{user_id}@example.com", display_name="U"))
    db.flush()
    db.add(models.Space(id=space_id, name="Hookspace", type="team", created_by_user_id=user_id))
    db.flush()

    on_space_created(db, space_id, seeded_by_user_id=user_id)

    memories = db.query(models.MemoryEntry).filter_by(space_id=space_id, scope_type="system").count()
    planes = db.query(models.ExecutionPlane).filter_by(space_id=space_id).count()
    collections = db.query(models.NoteCollection).filter_by(space_id=space_id).count()

    assert memories > 0, "system-policy memories were not seeded"
    assert planes == 8, f"expected 8 default execution planes, got {planes}"
    assert collections > 0, "default note collections were not seeded"


def test_hooks_invoke_seeders_without_committing(monkeypatch):
    # Atomicity: hooks run inside the caller's open transaction and must not
    # commit, so a later hook failure rolls earlier rows back too. Verify the
    # committing seeders are invoked with commit=False through the real hooks.
    import app.memory.seeder as memory_seeder
    import app.execution_planes.seeder as ep_seeder
    import app.knowledge.seeder as knowledge_seeder

    captured: dict[str, dict] = {}

    def fake_memories(db, space_id, *, commit=True):
        captured["memory"] = {"commit": commit}
        return 0

    def fake_planes(db, space_id, *, commit=True):
        captured["planes"] = {"commit": commit}
        return 0

    monkeypatch.setattr(memory_seeder, "seed_system_memories_for_space", fake_memories)
    monkeypatch.setattr(ep_seeder, "seed_default_execution_planes", fake_planes)
    # knowledge seeder already flushes (never commits) — stub it so this DB-free
    # test exercises only the commit wiring of the two committing seeders.
    monkeypatch.setattr(knowledge_seeder, "seed_default_note_collections", lambda db, space_id: 0)

    registry = SpaceCreatedHookRegistry()
    register_space_created_hooks(registry)
    registry.run(_ctx())

    assert captured["memory"]["commit"] is False
    assert captured["planes"]["commit"] is False


def test_spaces_service_dispatches_through_registry_not_direct_seeders():
    # The spaces hooks module must route through the registry, not call the old
    # direct seeders. Guard against a regression that reintroduces hardcoded
    # seeder imports/calls in the dispatch path.
    src = inspect.getsource(importlib.import_module("app.spaces.hooks"))
    assert "get_registry().run(" in src
    for legacy in (
        "seed_system_memories_for_space",
        "seed_default_execution_planes",
        "seed_default_note_collections",
    ):
        assert legacy not in src, f"legacy direct seeder call still present: {legacy}"
