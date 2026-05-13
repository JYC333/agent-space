"""Memory scope, read ACL, context redaction, access logs, and proposal acceptance."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func

from app.memory.context_builder import ContextBuilder
from app.memory.proposals import MemoryProposalService, build_memory_update_proposal
from app.memory.store import MemoryStore
from app.models import MemoryReadTrace, MemoryEntry
from app.schemas import MemoryCreate
from tests.conftest import USER, ensure_user, ensure_workspace

pytestmark = pytest.mark.canonical


@pytest.fixture
def family_space(db):
    """Household-style space with two members."""
    from app.models import Space

    sid = "family_space_acl"
    if not db.query(Space).filter(Space.id == sid).first():
        db.add(Space(id=sid, name="Family", type="household"))
        db.commit()
    ensure_user(db, "user_a", sid, email="a@t.invalid")
    ensure_user(db, "user_b", sid, email="b@t.invalid")
    return sid


def test_user_a_cannot_read_user_b_private_memory(db, family_space):
    store = MemoryStore(db)
    m = store.create(
        MemoryCreate(
            title="B secret",
            content="private body",
            type="semantic",
            scope="user",
            namespace="user.default",
            space_id=family_space,
            visibility="private",
            owner_user_id="user_b",
            subject_user_id="user_b",
        ),
        acting_user_id="user_b",
    )
    assert store.can_read_entry(
        m, family_space, "user_a", include_system_scope=(m.scope_type == "system")
    ) is False


def test_user_a_reads_user_b_space_shared_memory(db, family_space):
    store = MemoryStore(db)
    m = store.create(
        MemoryCreate(
            title="Team fact",
            content="we use pytest",
            type="semantic",
            scope="space",
            namespace="space.facts",
            space_id=family_space,
            visibility="space_shared",
            owner_user_id=None,
            subject_user_id=None,
        ),
        acting_user_id="user_b",
    )
    assert store.can_read_entry(m, family_space, "user_a") is True


def test_selected_users_denies_non_listed(db, family_space):
    store = MemoryStore(db)
    m = store.create(
        MemoryCreate(
            title="X",
            content="y",
            type="semantic",
            scope="user",
            namespace="n",
            space_id=family_space,
            visibility="selected_users",
            owner_user_id="user_a",
            selected_user_ids=["user_a"],
        ),
        acting_user_id="user_a",
    )
    assert store.can_read_entry(m, family_space, "user_b") is False


def test_selected_users_allows_listed(db, family_space):
    store = MemoryStore(db)
    m = store.create(
        MemoryCreate(
            title="X",
            content="y",
            type="semantic",
            scope="user",
            namespace="n",
            space_id=family_space,
            visibility="selected_users",
            owner_user_id="user_a",
            selected_user_ids=["user_a", "user_b"],
        ),
        acting_user_id="user_a",
    )
    assert store.can_read_entry(m, family_space, "user_b") is True


def test_restricted_owner_or_selected_only(db, family_space):
    store = MemoryStore(db)
    m = store.create(
        MemoryCreate(
            title="R",
            content="c",
            type="semantic",
            scope="user",
            namespace="n",
            space_id=family_space,
            visibility="restricted",
            owner_user_id="user_a",
            selected_user_ids=["user_b"],
        ),
        acting_user_id="user_a",
    )
    assert store.can_read_entry(m, family_space, "user_a") is True
    assert store.can_read_entry(m, family_space, "user_b") is True
    assert store.can_read_entry(m, family_space, USER) is False


def test_highly_restricted_space_shared_still_owner_only(db, family_space):
    from ulid import ULID

    m = MemoryEntry(
        id=str(ULID()),
        space_id=family_space,
        scope_type="user",
        memory_type="semantic",
        content="secret",
        status="active",
        namespace="n",
        title="H",
        visibility="space_shared",
        sensitivity_level="highly_restricted",
        owner_user_id="user_a",
    )
    db.add(m)
    db.commit()
    store = MemoryStore(db)
    assert store.can_read_entry(m, family_space, "user_a") is True
    assert store.can_read_entry(m, family_space, "user_b") is False


def test_highly_restricted_null_owner_excluded(db, family_space):
    store = MemoryStore(db)
    m = store.create(
        MemoryCreate(
            title="H2",
            content="x",
            type="semantic",
            scope="user",
            namespace="n",
            space_id=family_space,
            visibility="private",
            sensitivity_level="highly_restricted",
            owner_user_id="user_a",
        ),
        acting_user_id="user_a",
    )
    m.owner_user_id = None
    m.sensitivity_level = "highly_restricted"
    db.commit()
    db.refresh(m)
    assert store.can_read_entry(m, family_space, "user_b") is False


def test_workspace_shared_requires_workspace_id(db, family_space):
    ensure_workspace(db, "ws1", family_space, created_by_user_id="user_a")
    store = MemoryStore(db)
    m = store.create(
        MemoryCreate(
            title="W",
            content="z",
            type="project",
            scope="workspace",
            namespace="w.n",
            space_id=family_space,
            workspace_id="ws1",
            visibility="workspace_shared",
            owner_user_id="user_a",
        ),
        acting_user_id="user_a",
    )
    assert store.can_read_entry(m, family_space, "user_b", workspace_id="ws1") is True
    assert store.can_read_entry(m, family_space, "user_b", workspace_id=None) is False


def test_summary_only_redacts_content_for_non_owner(db, family_space):
    from app.memory.serialization import memory_entry_to_out

    store = MemoryStore(db)
    m = store.create(
        MemoryCreate(
            title="Summary title",
            content="FULL BODY",
            type="semantic",
            scope="user",
            namespace="n",
            space_id=family_space,
            visibility="summary_only",
            owner_user_id="user_a",
        ),
        acting_user_id="user_a",
    )
    out_owner = memory_entry_to_out(m, viewer_user_id="user_a", space_id=family_space)
    out_other = memory_entry_to_out(m, viewer_user_id="user_b", space_id=family_space)
    assert out_owner is not None and out_owner.content == "FULL BODY"
    assert out_other is not None and out_other.content is None


def test_system_scope_excluded_from_normal_list(db, family_space):
    store = MemoryStore(db)
    store.create(
        MemoryCreate(
            title="Sys",
            content="policy",
            type="semantic",
            scope="system",
            namespace="system.unit_test",
            space_id=family_space,
            visibility="space_shared",
            subject_user_id=None,
            owner_user_id=None,
        ),
        acting_user_id="user_a",
    )
    rows = store.list(family_space, "user_a", include_system_scope=False)
    assert all(r.scope_type != "system" for r in rows)


def test_context_builder_writes_access_logs(db, family_space):
    store = MemoryStore(db)
    store.create(
        MemoryCreate(
            title="Ctx",
            content="body",
            type="semantic",
            scope="user",
            namespace="user.default",
            space_id=family_space,
            visibility="private",
            owner_user_id="user_a",
            subject_user_id="user_a",
        ),
        acting_user_id="user_a",
    )
    before = db.query(func.count(MemoryReadTrace.id)).scalar() or 0
    pkg = ContextBuilder(db).build(
        space_id=family_space,
        user_id="user_a",
        context_reason="unit_test",
        agent_id=None,
        run_id=None,
    )
    after = db.query(func.count(MemoryReadTrace.id)).scalar() or 0
    assert len(pkg.user_memory) >= 1
    assert after > before
    last = db.query(MemoryReadTrace).order_by(MemoryReadTrace.accessed_at.desc()).first()
    assert last is not None
    assert last.access_type == "context_injection"


def test_fresh_db_has_memory_access_logs_table(db_engine):
    from sqlalchemy import inspect

    insp = inspect(db_engine)
    assert "memory_access_logs" in insp.get_table_names()


def test_proposal_acceptance_preserves_acl_fields(db, family_space):
    svc = MemoryProposalService(db)
    pid = str(uuid.uuid4())
    p = build_memory_update_proposal(
        pid,
        family_space,
        "user_a",
        workspace_id=None,
        proposed_title="T",
        proposed_content="C",
        rationale="r",
        memory_type="semantic",
        target_scope="user",
        target_namespace="user.default",
        target_visibility="selected_users",
        owner_user_id="user_a",
        subject_user_id="user_b",
        sensitivity_level="sensitive",
        selected_user_ids=["user_a", "user_b"],
    )
    db.add(p)
    db.commit()

    result = svc.accept(pid, space_id=family_space, user_id="user_a")
    assert result is not None
    _, mem = result
    assert mem.owner_user_id == "user_a"
    assert mem.subject_user_id == "user_b"
    assert mem.visibility == "selected_users"
    assert mem.sensitivity_level == "sensitive"
    assert mem.selected_user_ids == ["user_a", "user_b"]
