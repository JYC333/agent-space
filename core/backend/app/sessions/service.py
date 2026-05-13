from __future__ import annotations
"""
SessionService — manage chat sessions and messages.
"""

from datetime import datetime, UTC
from ulid import ULID
from sqlalchemy.orm import Session as DBSession

from ..models import Session, Message
from ..schemas import SessionCreate, MessageCreate
from ..config import settings


def _new_id() -> str:
    return str(ULID())


class SessionService:
    def __init__(self, db: DBSession):
        self.db = db

    def create_session(self, data: SessionCreate) -> Session:
        session = Session(
            id=_new_id(),
            space_id=data.space_id or settings.default_space_id,
            user_id=data.user_id or settings.default_user_id,
            workspace_id=data.workspace_id,
            title=data.title,
            status="active",
            metadata_json=data.metadata,
        )
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        return session

    def get_session(self, session_id: str) -> Session | None:
        return (
            self.db.query(Session)
            .filter(Session.id == session_id, Session.status == "active")
            .first()
        )

    def count_sessions(self, space_id: str, user_id: str) -> int:
        from sqlalchemy import func as _func
        return self.db.query(_func.count(Session.id)).filter(
            Session.space_id == space_id,
            Session.user_id == user_id,
            Session.status == "active",
        ).scalar() or 0

    def list_sessions(
        self,
        space_id: str,
        user_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Session]:
        return (
            self.db.query(Session)
            .filter(
                Session.space_id == space_id,
                Session.user_id == user_id,
                Session.status == "active",
            )
            .order_by(Session.updated_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

    def add_message(
        self,
        session_id: str,
        data: MessageCreate,
        space_id: str,
        user_id: str,
    ) -> Message | None:
        session = self.get_session(session_id)
        if not session:
            return None

        msg = Message(
            id=_new_id(),
            session_id=session_id,
            space_id=space_id,
            user_id=user_id,
            role=data.role,
            content=data.content,
            metadata_json=data.metadata,
        )
        self.db.add(msg)
        session.updated_at = datetime.now(UTC)
        self.db.commit()
        self.db.refresh(msg)
        return msg

    def get_messages(
        self,
        session_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Message]:
        return (
            self.db.query(Message)
            .filter(Message.session_id == session_id)
            .order_by(Message.created_at)
            .offset(offset)
            .limit(limit)
            .all()
        )
