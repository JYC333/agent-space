import pytest
from app.memory.proposals import MemoryProposalService
from app.memory.store import MemoryStore
from tests.conftest import SPACE, USER, ensure_user


def _create_proposal(db, **kwargs):
    svc = MemoryProposalService(db)
    return svc.create_proposal(
        space_id=kwargs.get("space_id", SPACE),
        user_id=kwargs.get("user_id", USER),
        target_scope=kwargs.get("target_scope", "user"),
        target_namespace=kwargs.get("target_namespace", "user.default.preferences"),
        memory_type=kwargs.get("memory_type", "preference"),
        proposed_title=kwargs.get("proposed_title", "Test proposal"),
        proposed_content=kwargs.get("proposed_content", "I prefer Python."),
        rationale="Extracted from test session.",
    )


def test_create_proposal(db):
    p = _create_proposal(db)
    assert p.id
    assert p.status == "pending"


def test_accept_proposal_creates_memory(db):
    p = _create_proposal(db)
    svc = MemoryProposalService(db)
    result = svc.accept(p.id, space_id=SPACE, user_id=USER)
    assert result is not None
    proposal, memory = result
    assert proposal.status == "accepted"
    assert proposal.decided_at is not None
    assert proposal.resulting_memory_id == memory.id

    # Memory should be in the store
    store = MemoryStore(db)
    mem = store.get(memory.id)
    assert mem is not None
    assert mem.status == "active"
    assert mem.title == p.proposed_title


def test_reject_proposal_does_not_create_memory(db):
    p = _create_proposal(db)
    svc = MemoryProposalService(db)
    proposal = svc.reject(p.id, space_id=SPACE, user_id=USER)
    assert proposal.status == "rejected"
    assert proposal.resulting_memory_id is None

    store = MemoryStore(db)
    all_mems = store.list(space_id=SPACE, user_id=USER)
    assert len(all_mems) == 0


def test_cannot_decide_already_decided_proposal(db):
    p = _create_proposal(db)
    svc = MemoryProposalService(db)
    svc.accept(p.id, space_id=SPACE, user_id=USER)
    # Second accept should return None (already decided)
    result = svc.accept(p.id, space_id=SPACE, user_id=USER)
    assert result is None


def test_list_pending_proposals(db):
    _create_proposal(db, proposed_title="P1")
    _create_proposal(db, proposed_title="P2")
    p3 = _create_proposal(db, proposed_title="P3")

    svc = MemoryProposalService(db)
    svc.reject(p3.id, space_id=SPACE, user_id=USER)

    pending = svc.list_proposals(space_id=SPACE, user_id=USER, status="pending")
    assert len(pending) == 2
    rejected = svc.list_proposals(space_id=SPACE, user_id=USER, status="rejected")
    assert len(rejected) == 1


def test_proposal_isolation_across_users(db):
    ensure_user(db, "user_a")
    ensure_user(db, "user_b")
    _create_proposal(db, user_id="user_a")
    _create_proposal(db, user_id="user_b")

    svc = MemoryProposalService(db)
    a = svc.list_proposals(space_id=SPACE, user_id="user_a")
    b = svc.list_proposals(space_id=SPACE, user_id="user_b")
    assert len(a) == 1 and a[0].created_by_user_id == "user_a"
    assert len(b) == 1 and b[0].created_by_user_id == "user_b"
