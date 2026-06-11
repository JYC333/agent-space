"""Tests proving auth.policy uses canonical roles consistently.

Invariants:
  - viewer does not grant extra authority (normalizes to guest).
  - reviewer is recognized by auth.policy helpers.
  - Canonical order: guest < member < reviewer < admin < owner.
  - auth.policy and app.policy.roles agree on every canonical role.
"""
from __future__ import annotations

import pytest

from app.auth.policy import (
    can_manage_space,
    can_manage_space_resources,
    can_use_space,
    can_view_space,
)
from app.models import SpaceMembership, User
from app.policy.roles import has_role_at_least, normalize_role
from tests.support.ids import DEFAULT_USER_ID, PERSONAL_SPACE_ID


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_user_with_role(db, role: str) -> str:
    uid = f"role_test_{role}"
    if not db.query(User).filter(User.id == uid).first():
        db.add(User(id=uid, display_name=f"Test {role}", email=f"{uid}@test.invalid"))
    existing = db.query(SpaceMembership).filter(
        SpaceMembership.space_id == PERSONAL_SPACE_ID,
        SpaceMembership.user_id == uid,
    ).first()
    if existing:
        existing.role = role
    else:
        db.add(SpaceMembership(
            id=f"sm_{uid}",
            space_id=PERSONAL_SPACE_ID,
            user_id=uid,
            role=role,
            status="active",
        ))
    db.flush()
    return uid


# ---------------------------------------------------------------------------
# 1. viewer normalizes to guest — no extra authority
#
# NOTE: The SpaceMembership DB table enforces canonical roles via a CHECK
# constraint, so "viewer" can never be stored.  These tests cover the
# normalize_role / has_role_at_least functions only (pure, no DB needed).
# ---------------------------------------------------------------------------

class TestViewerNormalization:

    def test_viewer_normalizes_to_guest(self):
        assert normalize_role("viewer") == "guest"

    def test_viewer_not_above_guest(self):
        assert has_role_at_least("viewer", "member") is False

    def test_viewer_same_authority_as_guest(self):
        assert normalize_role("viewer") == normalize_role("guest")

    def test_viewer_cannot_use_space_by_normalization(self):
        """After normalization, viewer → guest, which is below member threshold."""
        normalized = normalize_role("viewer")
        assert has_role_at_least(normalized, "member") is False

    def test_viewer_cannot_manage_by_normalization(self):
        normalized = normalize_role("viewer")
        assert has_role_at_least(normalized, "admin") is False

    def test_guest_db_row_cannot_use_space(self, db):
        """A guest-role member can view but not use the space."""
        uid = _make_user_with_role(db, "guest")
        assert can_view_space(db, uid, PERSONAL_SPACE_ID) is True
        assert can_use_space(db, uid, PERSONAL_SPACE_ID) is False


# ---------------------------------------------------------------------------
# 2. reviewer is recognized consistently
# ---------------------------------------------------------------------------

class TestReviewerRecognized:

    def test_reviewer_can_view_space(self, db):
        uid = _make_user_with_role(db, "reviewer")
        assert can_view_space(db, uid, PERSONAL_SPACE_ID) is True

    def test_reviewer_can_use_space(self, db):
        uid = _make_user_with_role(db, "reviewer")
        assert can_use_space(db, uid, PERSONAL_SPACE_ID) is True

    def test_reviewer_cannot_manage_space_resources(self, db):
        uid = _make_user_with_role(db, "reviewer")
        assert can_manage_space_resources(db, uid, PERSONAL_SPACE_ID) is False

    def test_reviewer_cannot_manage_space(self, db):
        uid = _make_user_with_role(db, "reviewer")
        assert can_manage_space(db, uid, PERSONAL_SPACE_ID) is False

    def test_reviewer_outranks_member(self):
        assert has_role_at_least("reviewer", "member") is True

    def test_reviewer_does_not_outrank_admin(self):
        assert has_role_at_least("reviewer", "admin") is False


# ---------------------------------------------------------------------------
# 3. Canonical authority ladder: guest < member < reviewer < admin < owner
# ---------------------------------------------------------------------------

class TestCanonicalAuthorityLadder:

    @pytest.mark.parametrize("role,expected_view,expected_use,expected_manage_res,expected_manage", [
        ("guest",    True,  False, False, False),
        ("member",   True,  True,  False, False),
        ("reviewer", True,  True,  False, False),
        ("admin",    True,  True,  True,  False),
        ("owner",    True,  True,  True,  True),
    ])
    def test_auth_policy_per_role(self, db, role, expected_view, expected_use, expected_manage_res, expected_manage):
        uid = _make_user_with_role(db, role)
        assert can_view_space(db, uid, PERSONAL_SPACE_ID) is expected_view
        assert can_use_space(db, uid, PERSONAL_SPACE_ID) is expected_use
        assert can_manage_space_resources(db, uid, PERSONAL_SPACE_ID) is expected_manage_res
        assert can_manage_space(db, uid, PERSONAL_SPACE_ID) is expected_manage

    def test_roles_module_and_auth_policy_agree_on_admin_outranks_reviewer(self):
        assert has_role_at_least("admin", "reviewer") is True
        assert has_role_at_least("reviewer", "admin") is False

    def test_unknown_role_normalizes_to_guest(self):
        """Unknown role strings normalize to guest (least authority)."""
        assert normalize_role("unknown_role") == "guest"
        assert has_role_at_least("unknown_role", "member") is False
