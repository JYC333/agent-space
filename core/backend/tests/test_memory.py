import pytest
from app.memory.store import MemoryStore
from app.schemas import MemoryCreate, MemoryUpdate
from tests.conftest import SPACE, USER, ensure_space, ensure_user, ensure_workspace


def _make(db, **kwargs) -> object:
    store = MemoryStore(db)
    subject_user_id = kwargs.get("subject_user_id", kwargs.get("owner_user_id", USER))
    data = MemoryCreate(
        title=kwargs.get("title", "Test memory"),
        content=kwargs.get("content", "Some content"),
        type=kwargs.get("type", "semantic"),
        scope=kwargs.get("scope", "user"),
        namespace=kwargs.get("namespace", "user.default"),
        space_id=kwargs.get("space_id", SPACE),
        subject_user_id=subject_user_id,
        owner_user_id=kwargs.get("owner_user_id"),
        workspace_id=kwargs.get("workspace_id"),
        visibility=kwargs.get("visibility", "private"),
        importance=kwargs.get("importance", 0.5),
    )
    acting = kwargs.get("acting_user_id", subject_user_id)
    return store.create(data, acting_user_id=acting)


def test_create_memory(db):
    store = MemoryStore(db)
    mem = _make(db)
    assert mem.id
    assert mem.status == "active"
    assert mem.version == 1
    assert mem.space_id == SPACE


def test_get_memory(db):
    mem = _make(db)
    store = MemoryStore(db)
    fetched = store.get(mem.id)
    assert fetched is not None
    assert fetched.id == mem.id


def test_update_memory(db):
    mem = _make(db)
    store = MemoryStore(db)
    updated = store.update(mem.id, MemoryUpdate(title="Updated title"))
    assert updated.title == "Updated title"
    assert updated.version == 2


def test_delete_memory(db):
    mem = _make(db)
    store = MemoryStore(db)
    assert store.delete(mem.id) is True
    assert store.get(mem.id) is None


def test_list_memories(db):
    _make(db, title="A")
    _make(db, title="B")
    store = MemoryStore(db)
    results = store.list(space_id=SPACE, user_id=USER)
    assert len(results) == 2


def test_user_scoped_memories_do_not_leak_across_users(db):
    ensure_user(db, "user_1")
    ensure_user(db, "user_2")
    _make(db, title="User1 memory", subject_user_id="user_1")
    _make(db, title="User2 memory", subject_user_id="user_2")

    store = MemoryStore(db)
    user1_mems = store.list(space_id=SPACE, user_id="user_1")
    user2_mems = store.list(space_id=SPACE, user_id="user_2")

    assert all(m.subject_user_id == "user_1" for m in user1_mems)
    assert all(m.subject_user_id == "user_2" for m in user2_mems)
    assert len(user1_mems) == 1
    assert len(user2_mems) == 1


def test_cross_space_memory_does_not_leak(db):
    ensure_space(db, "space_a")
    ensure_space(db, "space_b")
    _make(db, title="Space A memory", space_id="space_a", subject_user_id=USER, visibility="space_shared")

    store = MemoryStore(db)
    # Same user, different space — must not see it
    results = store.list(space_id="space_b", user_id=USER)
    assert len(results) == 0


def test_workspace_memories_require_workspace_id(db):
    ensure_user(db, "user_a")
    ensure_user(db, "user_b")
    ensure_workspace(db, "ws-a", SPACE, created_by_user_id="user_a")
    ensure_workspace(db, "ws-b", SPACE, created_by_user_id="user_b")
    # user_a creates a workspace_shared memory in ws-a
    _make(db, scope="workspace", workspace_id="ws-a", visibility="workspace_shared",
          subject_user_id="user_a")

    store = MemoryStore(db)
    # user_b querying with ws-a context can see it (workspace_shared within that workspace)
    ws_a_mems = store.list(space_id=SPACE, user_id="user_b", workspace_id="ws-a", scope="workspace")
    # user_b querying with ws-b context cannot see it (different workspace)
    ws_b_mems = store.list(space_id=SPACE, user_id="user_b", workspace_id="ws-b", scope="workspace")

    assert len(ws_a_mems) == 1
    assert ws_a_mems[0].workspace_id == "ws-a"
    assert len(ws_b_mems) == 0


def test_search_memories(db):
    _make(db, title="Python backend preference", content="I prefer Python for backend work")
    _make(db, title="Unrelated memory", content="Something else entirely")

    store = MemoryStore(db)
    results = store.search(query="Python", space_id=SPACE, user_id=USER)
    assert len(results) >= 1
    assert any("Python" in m.title or "Python" in m.content for m in results)


def test_deleted_memory_not_listed(db):
    mem = _make(db)
    store = MemoryStore(db)
    store.delete(mem.id)
    results = store.list(space_id=SPACE, user_id=USER)
    assert all(m.id != mem.id for m in results)
