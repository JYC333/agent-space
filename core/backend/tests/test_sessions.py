import pytest
from app.sessions.service import SessionService
from app.schemas import SessionCreate, MessageCreate
from tests.conftest import SPACE, USER, ensure_user


def test_create_session(db):
    svc = SessionService(db)
    session = svc.create_session(SessionCreate(title="Test session"))
    assert session.id
    assert session.status == "active"
    assert session.title == "Test session"


def test_list_sessions(db):
    svc = SessionService(db)
    svc.create_session(SessionCreate(title="S1"))
    svc.create_session(SessionCreate(title="S2"))
    sessions = svc.list_sessions(space_id=SPACE, user_id=USER)
    assert len(sessions) == 2


def test_add_and_list_messages(db):
    svc = SessionService(db)
    session = svc.create_session(SessionCreate(title="Chat"))
    svc.add_message(session.id, MessageCreate(role="user", content="Hello"), space_id=SPACE, user_id=USER)
    svc.add_message(session.id, MessageCreate(role="assistant", content="Hi"), space_id=SPACE, user_id=USER)
    msgs = svc.get_messages(session.id)
    assert len(msgs) == 2
    assert msgs[0].role == "user"
    assert msgs[1].role == "assistant"


def test_add_message_to_nonexistent_session(db):
    svc = SessionService(db)
    result = svc.add_message("does-not-exist", MessageCreate(role="user", content="X"),
                             space_id=SPACE, user_id=USER)
    assert result is None


def test_session_isolation_across_users(db):
    ensure_user(db, "user_a")
    ensure_user(db, "user_b")
    svc = SessionService(db)
    svc.create_session(SessionCreate(title="A session", user_id="user_a", space_id=SPACE))
    svc.create_session(SessionCreate(title="B session", user_id="user_b", space_id=SPACE))
    a = svc.list_sessions(space_id=SPACE, user_id="user_a")
    b = svc.list_sessions(space_id=SPACE, user_id="user_b")
    assert len(a) == 1 and a[0].user_id == "user_a"
    assert len(b) == 1 and b[0].user_id == "user_b"
