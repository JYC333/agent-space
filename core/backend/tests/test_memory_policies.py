"""
Tests for memory policy helpers and centralized read_auth rules.
"""

from types import SimpleNamespace

from app.memory.policies import (
    DIRECT_WRITE_SCOPES,
    PROPOSAL_REQUIRED_SCOPES,
    SCOPE_HIERARCHY,
    requires_proposal,
    validate_memory_type,
    validate_scope,
    validate_status,
)
from app.memory.read_auth import can_read_memory


def _mem(
    *,
    space_id: str = "s1",
    scope_type: str = "user",
    visibility: str = "private",
    owner_user_id: str | None = "u1",
    subject_user_id: str | None = None,
    sensitivity_level: str = "normal",
    selected_user_ids: list | None = None,
    workspace_id: str | None = None,
    deleted_at=None,
):
    return SimpleNamespace(
        space_id=space_id,
        deleted_at=deleted_at,
        scope_type=scope_type,
        visibility=visibility,
        owner_user_id=owner_user_id,
        subject_user_id=subject_user_id,
        sensitivity_level=sensitivity_level,
        selected_user_ids=selected_user_ids,
        workspace_id=workspace_id,
    )


def test_can_read_memory_denies_cross_space():
    m = _mem(space_id="space_a", visibility="space_shared", owner_user_id=None)
    assert can_read_memory(m, user_id="u1", space_id="space_b") is False


def test_can_read_memory_space_shared_same_space():
    m = _mem(space_id="s1", visibility="space_shared", owner_user_id=None)
    assert can_read_memory(m, user_id="u2", space_id="s1") is True


def test_can_read_memory_private_owner_only():
    m = _mem(visibility="private", owner_user_id="u1")
    assert can_read_memory(m, user_id="u1", space_id="s1") is True
    assert can_read_memory(m, user_id="u2", space_id="s1") is False


def test_can_read_memory_private_null_owner_denied():
    m = _mem(visibility="private", owner_user_id=None)
    assert can_read_memory(m, user_id="u1", space_id="s1") is False


def test_can_read_memory_workspace_shared_requires_workspace():
    m = _mem(visibility="workspace_shared", owner_user_id=None, workspace_id="w1")
    assert can_read_memory(m, user_id="u2", space_id="s1", workspace_id="w1") is True
    assert can_read_memory(m, user_id="u2", space_id="s1", workspace_id=None) is False
    assert can_read_memory(m, user_id="u2", space_id="s1", workspace_id="w2") is False


def test_can_read_memory_system_excluded_by_default():
    m = _mem(scope_type="system", visibility="space_shared", owner_user_id=None)
    assert can_read_memory(m, user_id="u1", space_id="s1", include_system_scope=False) is False
    assert can_read_memory(m, user_id="u1", space_id="s1", include_system_scope=True) is True


def test_can_read_memory_public_template_excluded_by_default():
    m = _mem(visibility="public_template", owner_user_id=None)
    assert can_read_memory(m, user_id="u1", space_id="s1", include_public_templates=False) is False
    assert can_read_memory(m, user_id="u1", space_id="s1", include_public_templates=True) is True


def test_can_read_memory_selected_users():
    m = _mem(
        visibility="selected_users",
        owner_user_id="owner1",
        selected_user_ids=["u9"],
    )
    assert can_read_memory(m, user_id="owner1", space_id="s1") is True
    assert can_read_memory(m, user_id="u9", space_id="s1") is True
    assert can_read_memory(m, user_id="u8", space_id="s1") is False


def test_can_read_memory_restricted_selected():
    m = _mem(
        visibility="restricted",
        owner_user_id="o1",
        selected_user_ids=["guest"],
    )
    assert can_read_memory(m, user_id="o1", space_id="s1") is True
    assert can_read_memory(m, user_id="guest", space_id="s1") is True
    assert can_read_memory(m, user_id="stranger", space_id="s1") is False


def test_can_read_memory_highly_restricted_owner_only_even_if_space_shared():
    m = _mem(
        visibility="space_shared",
        owner_user_id="o1",
        sensitivity_level="highly_restricted",
    )
    assert can_read_memory(m, user_id="o1", space_id="s1") is True
    assert can_read_memory(m, user_id="u2", space_id="s1") is False


def test_can_read_memory_highly_restricted_null_owner_denied():
    m = _mem(
        visibility="space_shared",
        owner_user_id=None,
        sensitivity_level="highly_restricted",
    )
    assert can_read_memory(m, user_id="u1", space_id="s1") is False


def test_requires_proposal():
    assert requires_proposal("user") is True
    assert requires_proposal("agent") is False


def test_validate_memory_type():
    assert validate_memory_type("semantic") is True
    assert validate_memory_type("invalid") is False


def test_validate_scope():
    assert validate_scope("workspace") is True
    assert validate_scope("bogus") is False


def test_validate_status():
    assert validate_status("active") is True
    assert validate_status("bogus") is False


def test_constants():
    assert "user" in PROPOSAL_REQUIRED_SCOPES
    assert "agent" in DIRECT_WRITE_SCOPES
    assert "system" in SCOPE_HIERARCHY
