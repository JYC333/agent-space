"""
Tests for self-evolution configuration (settings and env vars).
"""
import pytest


class TestSystemEvolutionSettings:
    """Tests for system evolution settings."""

    def test_enable_system_evolution_defaults_false(self):
        """enable_system_evolution defaults to False."""
        from app.config import settings
        assert settings.enable_system_evolution is False

    def test_sandbox_root_is_under_agent_space_home(self):
        """sandbox_root is always a subdirectory of AGENT_SPACE_HOME."""
        from app.config import settings, paths
        # sandbox_root derives from AGENT_SPACE_HOME/sandboxes
        assert str(paths.sandboxes_dir).startswith(settings.agent_space_home)
        assert "sandboxes" in str(paths.sandboxes_dir)

    def test_agent_space_env_defaults_dev(self):
        """AGENT_SPACE_ENV defaults to 'dev'."""
        from app.config import settings
        assert settings.agent_space_env == "dev"

    def test_system_core_base_branch_defaults_master(self):
        """SYSTEM_CORE_BASE_BRANCH defaults to 'master'."""
        from app.config import settings
        assert settings.system_core_base_branch == "master"

    def test_agent_space_home_derives_from_env_or_home_default(self):
        """agent_space_home defaults to $HOME/aspace."""
        from app.config import settings
        from pathlib import Path
        assert settings.agent_space_home == str(Path.home() / "aspace")

    def test_system_core_owner_email_empty_by_default(self):
        """system_core_owner_email is empty by default."""
        from app.config import settings
        assert settings.system_core_owner_email == ""


class TestPathPolicySelfEvolution:
    """Tests for PathPolicy with system_core workspaces."""

    def test_system_core_blocks_git_access(self, tmp_path):
        """system_core workspace forbids direct .git access."""
        from app.workspace.path_policy import PathPolicy, PathPolicyError
        from pathlib import Path

        ws_root = str(tmp_path / "workspaces")
        sb_root = str(tmp_path / "sandboxes")
        (tmp_path / "workspaces").mkdir()
        (tmp_path / "sandboxes").mkdir()
        policy = PathPolicy(workspace_root=Path(ws_root), sandbox_root=Path(sb_root))

        root = str(tmp_path / "repo")
        import os
        os.makedirs(os.path.join(root, ".git"))

        # system_core workspace should block .git access
        with pytest.raises(PathPolicyError, match=".git"):
            policy.validate(os.path.join(root, ".git"), allowed_root=root, mode="read", workspace_type="system_core")

    def test_system_core_allows_non_git_paths(self, tmp_path):
        """system_core workspace allows non-.git paths for reading."""
        from app.workspace.path_policy import PathPolicy
        from pathlib import Path

        ws_root = str(tmp_path / "workspaces")
        sb_root = str(tmp_path / "sandboxes")
        (tmp_path / "workspaces").mkdir()
        (tmp_path / "sandboxes").mkdir()
        policy = PathPolicy(workspace_root=Path(ws_root), sandbox_root=Path(sb_root))

        root = str(tmp_path / "repo")
        import os
        os.makedirs(root)
        Path(os.path.join(root, "README.md")).write_text("# Hello")

        # Should be allowed
        result = policy.validate(os.path.join(root, "README.md"), allowed_root=root, mode="read", workspace_type="system_core")
        assert result.name == "README.md"