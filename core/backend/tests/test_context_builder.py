import pytest
from app.memory.store import MemoryStore
from app.memory.context_builder import ContextBuilder
from app.schemas import MemoryCreate
from tests.conftest import SPACE, USER


def _seed(db, scope, namespace, title, content, memory_type="semantic", importance=0.5):
    store = MemoryStore(db)
    store.create(MemoryCreate(
        title=title,
        content=content,
        type=memory_type,
        scope=scope,
        namespace=namespace,
        space_id=SPACE,
        owner_user_id=USER,
        importance=importance,
    ))


def test_context_builder_returns_package(db):
    _seed(db, "user", "user.default.preferences", "Prefers Python", "I prefer Python.", importance=0.8)
    _seed(db, "system", "system.policy", "System rule", "Always be concise.", importance=1.0)

    builder = ContextBuilder(db)
    pkg = builder.build(space_id=SPACE, user_id=USER)

    assert len(pkg.user_memory) >= 1
    assert len(pkg.system_policy) >= 1


def test_context_builder_requires_space_id(db):
    builder = ContextBuilder(db)
    try:
        builder.build(space_id="", user_id=USER)
        assert False, "Should have raised"
    except ValueError:
        pass


def test_context_builder_requires_user_id(db):
    builder = ContextBuilder(db)
    try:
        builder.build(space_id=SPACE, user_id="")
        assert False, "Should have raised"
    except ValueError:
        pass


def test_context_builder_does_not_include_unrelated_memories(db):
    _seed(db, "user", "user.default", "Alice pref", "Alice prefers Go.", importance=0.8)

    builder = ContextBuilder(db)
    # Build context for a different user — should get no memories
    pkg = builder.build(space_id=SPACE, user_id="other_user")

    assert len(pkg.user_memory) == 0


def test_context_builder_cross_space_isolation(db):
    store = MemoryStore(db)
    store.create(MemoryCreate(
        title="Space A memory",
        content="Private to space A.",
        type="semantic",
        scope="user",
        namespace="user.default",
        space_id="space_a",
        owner_user_id=USER,
        visibility="space_shared",
        importance=0.9,
    ))

    builder = ContextBuilder(db)
    # Context for space_b must not see space_a memory
    pkg = builder.build(space_id="space_b", user_id=USER)
    assert len(pkg.user_memory) == 0


def test_context_builder_workspace_isolation(db):
    # user_creator creates a workspace_shared memory in ws-a
    store = MemoryStore(db)
    store.create(MemoryCreate(
        title="WS-A project",
        content="Project A detail.",
        type="project",
        scope="workspace",
        namespace="workspace.ws-a.project",
        space_id=SPACE,
        owner_user_id="user_creator",
        workspace_id="ws-a",
        visibility="workspace_shared",
        importance=0.9,
    ))

    builder = ContextBuilder(db)
    # user_reader querying ws-a sees it
    pkg_a = builder.build(space_id=SPACE, user_id="user_reader", workspace_id="ws-a")
    # user_reader querying ws-b does NOT see it
    pkg_b = builder.build(space_id=SPACE, user_id="user_reader", workspace_id="ws-b")

    assert any(m.workspace_id == "ws-a" for m in pkg_a.workspace_memory)
    assert len(pkg_b.workspace_memory) == 0


def test_context_builder_query_search(db):
    _seed(db, "user", "user.default", "Favourite language", "My favourite language is Rust.", importance=0.7)
    _seed(db, "user", "user.default", "Team size", "My team has 5 people.", importance=0.4)

    builder = ContextBuilder(db)
    pkg = builder.build(space_id=SPACE, user_id=USER, query="Rust")

    titles = [m.title for m in pkg.user_memory]
    assert "Favourite language" in titles


def test_context_builder_episodic_memories(db):
    _seed(db, "user", "user.default.episodes", "Session 1 event", "User completed setup.",
          memory_type="episodic", importance=0.6)

    builder = ContextBuilder(db)
    pkg = builder.build(space_id=SPACE, user_id=USER)

    assert len(pkg.relevant_episodes) >= 1
