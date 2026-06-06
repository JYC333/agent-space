"""Invariant: memory_layer / memory_kind are persisted through the proposal-apply path.

These columns drive episodic-context filtering (ContextBuilder / MemoryRetriever) and
symbol-match retrieval. The read side has always referenced them; this invariant guards
the write side wired in apply_service -> MemoryCreate -> MemoryStore.create so the columns
are no longer always NULL.
"""

from __future__ import annotations

import pytest

from app.memory.proposals import ProposalService
from app.models import MemoryEntry
from app.schemas import MemoryCreate
from tests.support import factories


def _accepted_memory(db, space_id, user_id, *, payload_json):
    prop = factories.create_test_proposal(
        db,
        space_id=space_id,
        created_by_user_id=user_id,
        commit=True,
        payload_json=payload_json,
    )
    result = ProposalService(db).accept(prop.id, space_id=space_id, user_id=user_id)
    assert result is not None
    return (
        db.query(MemoryEntry)
        .filter(
            MemoryEntry.created_from_proposal_id == prop.id,
            MemoryEntry.status == "active",
        )
        .one()
    )


def test_memory_layer_and_kind_persisted_through_apply(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    mem = _accepted_memory(
        db, a, ua.id, payload_json={"target_layer": "episodic", "memory_kind": "fact"}
    )
    assert mem.memory_layer == "episodic"
    assert mem.memory_kind == "fact"


def test_memory_layer_defaults_to_null_when_absent(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    mem = _accepted_memory(db, a, ua.id, payload_json={})
    assert mem.memory_layer is None
    assert mem.memory_kind is None


def test_memory_create_rejects_invalid_layer():
    with pytest.raises(ValueError, match="invalid memory_layer"):
        MemoryCreate(title="t", content="c", type="semantic", memory_layer="bogus")
