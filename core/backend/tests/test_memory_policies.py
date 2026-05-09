"""
Tests for memory access policy functions (can_read, requires_proposal, validators).
"""
import pytest
from app.memory.policies import (
    can_read,
    requires_proposal,
    validate_memory_type,
    validate_scope,
    validate_status,
    PROPOSAL_REQUIRED_SCOPES,
    DIRECT_WRITE_SCOPES,
    SCOPE_HIERARCHY,
)


# ---------------------------------------------------------------------------
# can_read — cross-space boundary (hard wall)
# ---------------------------------------------------------------------------

def test_can_read_denies_cross_space():
    assert can_read(
        scope="user",
        requesting_user_id="u1",
        owner_user_id="u1",
        visibility="space_shared",
        space_id="space_a",
        requesting_space_id="space_b",
    ) is False


def test_can_read_allows_same_space():
    assert can_read(
        scope="user",
        requesting_user_id="u1",
        owner_user_id="u1",
        visibility="space_shared",
        space_id="personal",
        requesting_space_id="personal",
    ) is True


# ---------------------------------------------------------------------------
# can_read — visibility: private
# ---------------------------------------------------------------------------

def test_can_read_private_own_memory():
    assert can_read(
        scope="user",
        requesting_user_id="alice",
        owner_user_id="alice",
        visibility="private",
        space_id="personal",
        requesting_space_id="personal",
    ) is True


def test_can_read_private_other_user_denied():
    assert can_read(
        scope="user",
        requesting_user_id="bob",
        owner_user_id="alice",
        visibility="private",
        space_id="personal",
        requesting_space_id="personal",
    ) is False


# ---------------------------------------------------------------------------
# can_read — visibility: workspace_shared
# ---------------------------------------------------------------------------

def test_can_read_workspace_shared_same_workspace():
    assert can_read(
        scope="workspace",
        requesting_user_id="bob",
        owner_user_id="alice",
        visibility="workspace_shared",
        space_id="personal",
        requesting_space_id="personal",
        workspace_id="ws-1",
        requesting_workspace_id="ws-1",
    ) is True


def test_can_read_workspace_shared_different_workspace():
    assert can_read(
        scope="workspace",
        requesting_user_id="bob",
        owner_user_id="alice",
        visibility="workspace_shared",
        space_id="personal",
        requesting_space_id="personal",
        workspace_id="ws-1",
        requesting_workspace_id="ws-2",
    ) is False


def test_can_read_workspace_shared_no_workspace_falls_back_to_owner():
    # When workspace_id is absent, falls back to owner comparison
    assert can_read(
        scope="workspace",
        requesting_user_id="alice",
        owner_user_id="alice",
        visibility="workspace_shared",
        space_id="personal",
        requesting_space_id="personal",
    ) is True

    assert can_read(
        scope="workspace",
        requesting_user_id="bob",
        owner_user_id="alice",
        visibility="workspace_shared",
        space_id="personal",
        requesting_space_id="personal",
    ) is False


# ---------------------------------------------------------------------------
# can_read — visibility: space_shared
# ---------------------------------------------------------------------------

def test_can_read_space_shared_any_user_in_same_space():
    assert can_read(
        scope="space",
        requesting_user_id="carol",
        owner_user_id="alice",
        visibility="space_shared",
        space_id="personal",
        requesting_space_id="personal",
    ) is True


def test_can_read_unknown_visibility_is_denied():
    assert can_read(
        scope="user",
        requesting_user_id="u1",
        owner_user_id="u1",
        visibility="unknown_type",
        space_id="personal",
        requesting_space_id="personal",
    ) is False


# ---------------------------------------------------------------------------
# requires_proposal
# ---------------------------------------------------------------------------

def test_requires_proposal_for_protected_scopes():
    for scope in PROPOSAL_REQUIRED_SCOPES:
        assert requires_proposal(scope) is True


def test_does_not_require_proposal_for_agent_scope():
    for scope in DIRECT_WRITE_SCOPES:
        assert requires_proposal(scope) is False


# ---------------------------------------------------------------------------
# validate_memory_type
# ---------------------------------------------------------------------------

def test_validate_memory_type_valid():
    for t in ("preference", "semantic", "episodic", "procedural", "project"):
        assert validate_memory_type(t) is True


def test_validate_memory_type_invalid():
    assert validate_memory_type("random") is False
    assert validate_memory_type("") is False
    assert validate_memory_type("Preference") is False  # case-sensitive


# ---------------------------------------------------------------------------
# validate_scope
# ---------------------------------------------------------------------------

def test_validate_scope_valid():
    for s in SCOPE_HIERARCHY:
        assert validate_scope(s) is True


def test_validate_scope_invalid():
    assert validate_scope("global") is False
    assert validate_scope("") is False


# ---------------------------------------------------------------------------
# validate_status
# ---------------------------------------------------------------------------

def test_validate_status_valid():
    for s in ("active", "archived", "proposed", "rejected", "superseded"):
        assert validate_status(s) is True


def test_validate_status_invalid():
    assert validate_status("deleted") is False
    assert validate_status("") is False
