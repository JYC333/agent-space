"""Contract tests: space invitation email enforcement and new-user flow."""

from __future__ import annotations
import uuid

import hashlib
import secrets
from datetime import datetime, UTC, timedelta

from app.auth.session import SESSION_COOKIE, UserSessionService
from app.auth.service import UserService
from app.main import app as _app
from app.models import SpaceInvitation
from starlette.testclient import TestClient
from tests.support import factories


def _new_id() -> str:
    return str(uuid.uuid4())


def _authed_client(db, user_id: str) -> TestClient:
    _, raw = UserSessionService(db).create(user_id)
    return TestClient(_app, cookies={SESSION_COOKIE: raw}, raise_server_exceptions=True)


def _make_invitation(db, *, space_id: str, invited_email: str, invited_by_user_id: str) -> tuple[SpaceInvitation, str]:
    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    inv = SpaceInvitation(
        id=_new_id(),
        space_id=space_id,
        invited_email=invited_email,
        role="member",
        token_hash=token_hash,
        invited_by_user_id=invited_by_user_id,
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    db.add(inv)
    db.flush()
    return inv, raw_token


def test_accept_invitation_wrong_email_returns_403(db, client):
    """A user whose email differs from invited_email cannot accept the invitation."""
    space_id = _new_id()
    factories.create_test_space(db, space_id=space_id, name="Shared", space_type="household")
    owner = factories.create_test_user(db, space_id=space_id, email=f"owner-{space_id}@t.invalid")

    _, raw_token = _make_invitation(db, space_id=space_id, invited_email=f"alice-{space_id}@t.invalid",
                                    invited_by_user_id=owner.id)
    db.commit()

    # Bob (different email) tries to accept
    bob_space = _new_id()
    factories.create_test_space(db, space_id=bob_space, name="Bob personal", space_type="personal")
    bob = factories.create_test_user(db, space_id=bob_space, email=f"bob-{bob_space}@t.invalid")
    db.commit()

    r = _authed_client(db, bob.id).post(f"/api/v1/invitations/{raw_token}/accept")

    assert r.status_code == 403
    # Custom error handler returns {"error": ..., "message": ...} (not {"detail": ...})
    assert "different email" in r.json()["message"]


def test_accept_invitation_correct_email_succeeds(db, client):
    """A user whose email matches invited_email can accept the invitation."""
    space_id = _new_id()
    factories.create_test_space(db, space_id=space_id, name="Shared", space_type="household")
    owner = factories.create_test_user(db, space_id=space_id, email=f"owner-{space_id}@t.invalid")

    alice_email = f"alice-{space_id}@t.invalid"
    _, raw_token = _make_invitation(db, space_id=space_id, invited_email=alice_email,
                                    invited_by_user_id=owner.id)
    db.commit()

    alice_space = _new_id()
    factories.create_test_space(db, space_id=alice_space, name="Alice personal", space_type="personal")
    alice = factories.create_test_user(db, space_id=alice_space, email=alice_email)
    db.commit()

    r = _authed_client(db, alice.id).post(f"/api/v1/invitations/{raw_token}/accept")

    assert r.status_code == 200
    body = r.json()
    assert body["space_id"] == space_id
    assert body["role"] == "member"


def test_accept_invitation_email_check_is_case_insensitive(db, client):
    """Email comparison ignores case."""
    space_id = _new_id()
    factories.create_test_space(db, space_id=space_id, name="Shared", space_type="household")
    owner = factories.create_test_user(db, space_id=space_id, email=f"owner-{space_id}@t.invalid")

    _, raw_token = _make_invitation(db, space_id=space_id, invited_email=f"Alice-{space_id}@Example.COM",
                                    invited_by_user_id=owner.id)
    db.commit()

    alice_space = _new_id()
    factories.create_test_space(db, space_id=alice_space, name="Alice personal", space_type="personal")
    alice = factories.create_test_user(db, space_id=alice_space, email=f"alice-{space_id}@example.com")
    db.commit()

    r = _authed_client(db, alice.id).post(f"/api/v1/invitations/{raw_token}/accept")

    assert r.status_code == 200


def test_new_user_accepts_invitation_after_first_login(db, client):
    """A brand-new user (first Google login) can accept an invitation for their email.

    This is the 'unregistered user clicks invite link → registers → auto-accept' contract:
    find_or_create_from_google creates the user; accept must work immediately after.
    """
    space_id = _new_id()
    factories.create_test_space(db, space_id=space_id, name="Shared", space_type="household")
    owner = factories.create_test_user(db, space_id=space_id, email=f"owner-{space_id}@t.invalid")

    invited_email = f"newuser-{space_id}@t.invalid"
    _, raw_token = _make_invitation(db, space_id=space_id, invited_email=invited_email,
                                    invited_by_user_id=owner.id)
    db.commit()

    # Simulate first Google login — creates User + personal space + membership
    new_user = UserService(db).find_or_create_from_google(
        google_sub=f"google-{space_id}",
        email=invited_email,
        display_name="New User",
        avatar_url=None,
    )
    db.commit()

    r = _authed_client(db, new_user.id).post(f"/api/v1/invitations/{raw_token}/accept")

    assert r.status_code == 200
    body = r.json()
    assert body["space_id"] == space_id
    assert body["role"] == "member"


def test_new_user_wrong_email_cannot_accept(db, client):
    """A new user whose Google email differs from invited_email cannot auto-accept."""
    space_id = _new_id()
    factories.create_test_space(db, space_id=space_id, name="Shared", space_type="household")
    owner = factories.create_test_user(db, space_id=space_id, email=f"owner-{space_id}@t.invalid")

    _, raw_token = _make_invitation(db, space_id=space_id,
                                    invited_email=f"alice-{space_id}@t.invalid",
                                    invited_by_user_id=owner.id)
    db.commit()

    # A different user signs in via Google
    wrong_user = UserService(db).find_or_create_from_google(
        google_sub=f"google-wrong-{space_id}",
        email=f"bob-{space_id}@t.invalid",
        display_name="Bob",
        avatar_url=None,
    )
    db.commit()

    r = _authed_client(db, wrong_user.id).post(f"/api/v1/invitations/{raw_token}/accept")

    assert r.status_code == 403
    assert "different email" in r.json()["message"]
