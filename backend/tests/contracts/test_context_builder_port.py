"""Contract: ``ContextBuilderPort`` is a faithful seam over ``ContextBuilder``.

These tests protect the migration seam introduced for the TS-first migration
(see ``.agent/architecture/TS_MIGRATION_STRATEGY.md``). They assert that:

- the concrete ``ContextBuilder`` structurally satisfies ``ContextBuilderPort``,
  so callers may type against the port without behavior change; and
- a lightweight fake can stand in for the port without a database, which is the
  whole point of extracting it.

No DB is required — the port is a pure structural contract.
"""

from __future__ import annotations

import pytest

from app.memory import ContextBuilderPort
from app.memory.context_builder import ContextBuilder
from app.schemas import ContextPackage
from tests.support.fake_context_builder import FakeContextBuilder


def test_concrete_context_builder_satisfies_port():
    """The authority implementation must conform to the published seam."""
    assert issubclass(ContextBuilder, ContextBuilderPort)


def test_port_is_reexported_from_facade():
    """Callers import the seam from the module facade, not an internal path."""
    from app.memory import ContextBuilderPort as FromFacade
    from app.memory.ports import ContextBuilderPort as FromModule

    assert FromFacade is FromModule


def test_fake_satisfies_port_and_builds_package():
    fake = FakeContextBuilder()
    assert isinstance(fake, ContextBuilderPort)

    pkg = fake.build(space_id="space-1", user_id="user-1", query="hello")
    assert isinstance(pkg, ContextPackage)
    assert fake.calls[-1]["space_id"] == "space-1"
    assert fake.calls[-1]["user_id"] == "user-1"
    assert fake.calls[-1]["query"] == "hello"


def test_fake_returns_scripted_package():
    scripted = ContextPackage(attachments=[{"kind": "file", "path": "a.txt"}])
    fake = FakeContextBuilder(package=scripted)
    assert fake.build(space_id="s", user_id="u") is scripted


def test_fake_enforces_space_boundary():
    """Both the real builder and the fake refuse to build without a space/user."""
    fake = FakeContextBuilder()
    with pytest.raises(ValueError):
        fake.build(space_id="", user_id="u")
    with pytest.raises(ValueError):
        fake.build(space_id="s", user_id="")
