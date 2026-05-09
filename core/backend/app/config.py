import os
import stat
from pathlib import Path
from pydantic_settings import BaseSettings

# Agent Space local data root.
# Defaults to ~/aspace; override with AGENT_SPACE_HOME env var.
# In Docker, set AGENT_SPACE_HOME=/app/aspace via docker-compose environment.
_ASPACE_HOME = Path(
    os.getenv("AGENT_SPACE_HOME", str(Path.home() / "aspace"))
).expanduser().resolve()


class AppPaths:
    """Central path resolver — all runtime data lives under AGENT_SPACE_HOME."""

    def __init__(self, home: Path | None = None):
        self.home           = (home or _ASPACE_HOME).resolve()
        self.config_dir     = self.home / "config"
        self.secrets_dir    = self.home / "secrets"
        self.db_dir         = self.home / "db"
        self.storage_dir    = self.home / "storage"
        self.logs_dir       = self.home / "logs"
        self.cache_dir      = self.home / "cache"
        self.runtime_dir    = self.home / "runtime"
        self.workspaces_dir = self.home / "workspaces"
        self.sandboxes_dir  = self.home / "sandboxes"
        self.artifacts_dir  = self.home / "artifacts"

    @property
    def db_file(self) -> Path:
        return self.db_dir / "agent_space.sqlite"

    @property
    def cli_credentials_dir(self) -> Path:
        return self.secrets_dir / "cli-credentials"

    @property
    def cli_credentials_config(self) -> Path:
        return self.config_dir / "cli-credentials.yaml"

    @property
    def provider_keys_key(self) -> Path:
        """AES-256-GCM master key for encrypting provider API keys at rest."""
        return self.secrets_dir / "provider_keys.key"

    def init_dirs(self) -> None:
        """Create all required directories with correct permissions (idempotent)."""
        entries = [
            (self.home,           0o700),
            (self.config_dir,     0o700),
            (self.secrets_dir,    0o700),
            (self.db_dir,         0o700),
            (self.runtime_dir,    0o700),
            (self.storage_dir,    0o750),
            (self.logs_dir,       0o750),
            (self.cache_dir,      0o750),
            (self.workspaces_dir, 0o750),
            (self.sandboxes_dir,  0o750),
            (self.artifacts_dir,  0o750),
        ]
        for path, mode in entries:
            path.mkdir(parents=True, exist_ok=True)
            path.chmod(mode)

    def validate(self) -> None:
        """Fail fast if sensitive dirs are world-accessible or not writable."""
        sensitive = [self.home, self.secrets_dir, self.db_dir, self.runtime_dir, self.config_dir]
        for path in sensitive:
            if not path.exists():
                continue
            mode = path.stat().st_mode
            if mode & stat.S_IRWXO:
                raise RuntimeError(
                    f"Security: {path} is world-accessible (mode {oct(mode)}). "
                    f"Fix with: chmod 700 {path}"
                )
            if not os.access(path, os.W_OK):
                raise RuntimeError(f"Cannot write to {path}. Check permissions.")


paths = AppPaths()


class Settings(BaseSettings):
    app_name: str = "agent-space"
    app_version: str = "0.1.0"
    debug: bool = False

    # Database — defaults to $AGENT_SPACE_HOME/db/agent_space.sqlite
    database_url: str = f"sqlite:///{paths.db_file}"

    # Defaults for single-user / personal-space mode
    default_space_id: str = "personal"
    default_user_id: str = "default_user"

    # LLM configuration
    anthropic_api_key: str = ""
    default_model: str = "claude-sonnet-4-6"

    # AGENT_SPACE_HOME — single local data root (all runtime data lives here)
    agent_space_home: str = str(_ASPACE_HOME)

    # Runtime paths — all overridable via env vars; derive from AGENT_SPACE_HOME by default.
    # instance_root kept for internal compatibility; aliases agent_space_home.
    instance_root: str = str(_ASPACE_HOME)
    workspace_root: str = str(Path(os.getenv("WORKSPACE_ROOT", str(paths.workspaces_dir))))
    sandbox_root: str = str(Path(os.getenv("SANDBOX_ROOT", str(paths.sandboxes_dir))))
    capabilities_dir: str = str(Path(__file__).parent.parent.parent / "capabilities")
    memory_dir: str = str(Path(__file__).parent.parent.parent / "memory")

    # Memory reflector
    reflector_mode: str = "placeholder"  # "placeholder" | "llm"

    # Google OAuth
    google_client_id: str = ""
    google_client_secret: str = ""
    # Redirect URI registered in Google Console — must go through Vite proxy in dev
    google_redirect_uri: str = "http://localhost:5173/api/v1/auth/google/callback"
    # Frontend base URL — used for post-OAuth redirects
    frontend_url: str = "http://localhost:5173"

    # Session config
    session_expire_days: int = 30
    # Allowed CORS origins (restrict in production)
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    # Sandbox concurrency — max Docker containers running simultaneously
    # Runs beyond this limit queue and wait rather than all firing at once
    max_concurrent_docker_runs: int = 3
    # Default sandbox level: dry_run | worktree | one_shot_docker
    default_sandbox_level: str = "worktree"

    # Deployer Unix socket path (host deployer process, outside the app container)
    deployer_socket_path: str = "/var/run/agent-space/deployer.sock"

    # CLI credential management
    # Root directory for CLI login state profiles (one subdir per runtime/profile)
    cli_credentials_dir: str = str(paths.cli_credentials_dir)
    # Path to the credential profile config file
    cli_credentials_config: str = str(paths.cli_credentials_config)

    # Claude Code local data — override in Docker via CLAUDE_HOME env var
    claude_home: str = str(Path.home() / ".claude")

    # HOME directory to use when running `claude` in a PTY (quota fetch, etc.).
    # Set this to the directory that contains .claude/ and .claude.json so the
    # subprocess finds credentials without going through the credential broker.
    # Example: CLAUDE_PTY_HOME=/home/yuchuan   (host user home, bind-mounted)
    claude_pty_home: str = ""

    # Context builder limits
    context_max_memories: int = 20
    context_max_episodes: int = 5

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
