"""Unit tests for ``AppPaths.validate()`` sensitive-directory hardening.

``validate()`` runs identically for host (direct local) runs and inside the
Docker backend container where ``AGENT_SPACE_HOME=/aspace`` is a bind mount.
These tests build both shapes under ``tmp_path`` (we cannot create a real
``/aspace`` mount in CI) and assert the same fail-fast behavior:

- a correctly locked-down (mode 700) tree validates,
- a world-accessible sensitive directory is rejected,
- a non-writable required directory is rejected.
"""
from __future__ import annotations

import os
import stat

import pytest

from app.config import AppPaths


SENSITIVE = ("config", "secrets", "db", "runtime")


def _make_tree(root) -> AppPaths:
    """Create a locked-down (mode 700) data tree rooted at ``root``."""
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(root, 0o700)
    paths = AppPaths(home=root)
    for name in SENSITIVE:
        d = root / name
        d.mkdir(mode=0o700, exist_ok=True)
        os.chmod(d, 0o700)
    return paths


def test_host_style_tree_with_700_perms_validates(tmp_path):
    """A host data root with mode-700 sensitive dirs passes validation."""
    paths = _make_tree(tmp_path / "aspace" / "dev")
    paths.validate()  # must not raise


def test_docker_style_aspace_tree_validates(tmp_path):
    """A container-style /aspace bind-mount tree (mode 700) passes validation."""
    # Mirror the container layout: AGENT_SPACE_HOME points at the mount root.
    paths = _make_tree(tmp_path / "aspace")
    paths.validate()  # must not raise


@pytest.mark.parametrize("sensitive_name", SENSITIVE + ("",))
def test_world_accessible_sensitive_dir_is_rejected(tmp_path, sensitive_name):
    """Any world-accessible sensitive dir (incl. home itself) fails fast."""
    home = tmp_path / "aspace" / "dev"
    paths = _make_tree(home)
    target = home if sensitive_name == "" else home / sensitive_name
    os.chmod(target, 0o707)  # add world rwx bits
    with pytest.raises(RuntimeError, match="world-accessible"):
        paths.validate()


@pytest.mark.skipif(os.geteuid() == 0, reason="root bypasses write-permission checks")
def test_non_writable_required_dir_is_rejected(tmp_path):
    """A required sensitive dir that the process cannot write to fails fast."""
    home = tmp_path / "aspace" / "dev"
    paths = _make_tree(home)
    # Read+execute only (no write), and not world-accessible.
    os.chmod(home / "secrets", 0o500)
    try:
        with pytest.raises(RuntimeError, match="Cannot write to required directory"):
            paths.validate()
    finally:
        # Restore so tmp_path cleanup can remove the tree.
        os.chmod(home / "secrets", 0o700)


def test_missing_sensitive_dir_is_skipped(tmp_path):
    """Non-existent sensitive dirs are tolerated (init_dirs is best-effort)."""
    home = tmp_path / "aspace" / "dev"
    paths = _make_tree(home)
    # Remove one sensitive dir entirely; validate should still pass.
    (home / "runtime").rmdir()
    assert not (home / "runtime").exists()
    paths.validate()  # must not raise


def test_validate_checks_documented_sensitive_set():
    """The hardened set is exactly home/config/secrets/db/runtime."""
    assert AppPaths.SENSITIVE_DIR_ATTRS == (
        "home",
        "config_dir",
        "secrets_dir",
        "db_dir",
        "runtime_dir",
    )
    # World-accessible mode bit constant sanity.
    assert stat.S_IRWXO == 0o007
