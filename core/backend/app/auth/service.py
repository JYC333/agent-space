from __future__ import annotations
from datetime import datetime, UTC
from typing import Optional

from sqlalchemy.orm import Session
from ulid import ULID

from ..models import AuthAccount, Space, SpaceMembership, User


def _new_id() -> str:
    return str(ULID())


class UserService:
    def __init__(self, db: Session):
        self.db = db

    def find_or_create_from_google(
        self,
        google_sub: str,
        email: str,
        display_name: str,
        avatar_url: Optional[str],
    ) -> User:
        acct = (
            self.db.query(AuthAccount)
            .filter(AuthAccount.provider == "google", AuthAccount.provider_user_id == google_sub)
            .first()
        )

        if acct:
            user = self.db.query(User).filter(User.id == acct.user_id).first()
            user.email = email
            user.display_name = display_name
            if avatar_url:
                user.avatar_url = avatar_url
            user.last_login_at = datetime.now(UTC)
            user.updated_at = datetime.now(UTC)
            self.db.commit()
            self.db.refresh(user)
            return user

        # New user — create User + AuthAccount + personal Space + Membership
        user = User(
            id=_new_id(),
            email=email,
            display_name=display_name,
            avatar_url=avatar_url,
            last_login_at=datetime.now(UTC),
        )
        self.db.add(user)
        self.db.flush()

        self.db.add(AuthAccount(
            id=_new_id(),
            user_id=user.id,
            provider="google",
            provider_user_id=google_sub,
            email=email,
        ))

        self._make_space(
            user_id=user.id,
            name=f"{display_name}'s Personal Space",
            space_type="personal",
        )

        self.db.commit()
        self.db.refresh(user)
        return user

    def create_space(self, user_id: str, name: str, space_type: str) -> Space:
        space = self._make_space(user_id, name, space_type)
        self.db.commit()
        self.db.refresh(space)
        return space

    def _make_space(self, user_id: str, name: str, space_type: str) -> Space:
        space = Space(
            id=_new_id(),
            name=name,
            type=space_type,
            created_by_user_id=user_id,
        )
        self.db.add(space)
        self.db.flush()
        self.db.add(SpaceMembership(
            id=_new_id(),
            space_id=space.id,
            user_id=user_id,
            role="owner",
            status="active",
        ))
        self.db.flush()
        from ..spaces.hooks import on_space_created

        on_space_created(self.db, space.id, seeded_by_user_id=user_id)
        return space

    def get_user_spaces(self, user_id: str) -> list[dict]:
        rows = (
            self.db.query(SpaceMembership, Space)
            .join(Space, SpaceMembership.space_id == Space.id)
            .filter(SpaceMembership.user_id == user_id, SpaceMembership.status == "active")
            .all()
        )
        return [
            {
                "id": s.id,
                "name": s.name,
                "type": s.type,
                "role": m.role,
                "created_at": s.created_at.isoformat(),
                "updated_at": s.updated_at.isoformat(),
            }
            for m, s in rows
        ]
