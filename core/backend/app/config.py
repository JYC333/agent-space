import os
import stat
from pathlib import Path
from typing import Optional
from pydantic import Field, field_validator
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
        self.backups_dir    = self.home / "backups"

    @property
    def artifact_storage_root(self) -> Path:
        """Root for persisted artifact files (``Artifact.storage_path`` is relative to this)."""
        p = os.getenv("ARTIFACT_STORAGE_ROOT")
        if p:
            return Path(p).expanduser().resolve()
        return (self.storage_dir / "artifacts").resolve()

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
    def instance_settings_config(self) -> Path:
        return self.config_dir / "settings.yaml"

    @property
    def provider_keys_key(self) -> Path:
        """AES-256-GCM master key for encrypting provider API keys at rest."""
        return self.secrets_dir / "provider_keys.key"

    def system_core_workspace_dir_for_space(self, space_id: str) -> Path:
        """Git worktree root for agent-space self-evolution in a specific space."""
        return self.workspaces_dir / space_id / "agent-space"

    def init_dirs(self) -> None:
        """Create all required directories with correct permissions (idempotent)."""
        import os

        def _skip_path(p: Path) -> bool:
            """Skip if path is a mount point or not writable by current user."""
            try:
                if os.path.ismount(p):
                    return True
                stat_info = p.stat()
                # Skip if we don't own it (and we're not root)
                if stat_info.st_uid != 0 and stat_info.st_uid != os.getuid():
                    # Check if we can actually write
                    if not os.access(p, os.W_OK):
                        return True
            except (OSError, PermissionError):
                pass
            return False

        def safe_mkdir(p: Path, mode: int) -> None:
            """Create directory, skip if mount point or no permission."""
            try:
                if _skip_path(p):
                    return
                p.mkdir(parents=True, exist_ok=True)
            except (OSError, PermissionError):
                pass

        entries = [
            (self.home,           0o700),
            (self.config_dir,     0o700),
            (self.secrets_dir,    0o700),
            (self.db_dir,         0o700),
            (self.runtime_dir,    0o700),
            (self.storage_dir,    0o700),
            (self.logs_dir,       0o700),
            (self.cache_dir,      0o700),
            (self.workspaces_dir, 0o700),
            (self.sandboxes_dir,  0o700),
            (self.artifacts_dir,  0o700),
            (self.artifact_storage_root, 0o700),
            (self.backups_dir,    0o700),
        ]
        for path, mode in entries:
            safe_mkdir(path, mode)

    def validate(self) -> None:
        """Fail fast if sensitive dirs are world-accessible or not writable.

        In Docker containers (non-root, uid != 0), skip this check because:
        - Docker bind mounts inherit host permissions which may be 755 for group access
        - The container user (uid 1000) can't chmod host directories from inside the container
        - group_add is the correct mechanism for Docker permission handling
        """
        import os
        # In a non-root container, skip all permission checks — we can't chmod host volumes
        if os.getuid() != 0:
            return
        sensitive = [self.home, self.secrets_dir, self.db_dir, self.runtime_dir, self.config_dir]
        for path in sensitive:
            if not path.exists():
                continue
            # Skip mount points (e.g. /instance when running in Docker)
            try:
                if os.path.ismount(path):
                    continue
            except (OSError, PermissionError):
                pass
            try:
                mode = path.stat().st_mode
            except (OSError, PermissionError):
                continue
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
    # instance_root mirrors agent_space_home for kernel helpers that still read this field.
    instance_root: str = str(_ASPACE_HOME)
    instance_storage_root: str = str(paths.storage_dir)
    artifact_storage_root: str = Field(
        default=str(paths.artifact_storage_root),
        description="Directory where artifact files are stored; ARTIFACT_STORAGE_ROOT env overrides.",
    )
    workspace_root: str = str(Path(os.getenv("WORKSPACE_ROOT", str(paths.workspaces_dir))))
    sandbox_root: str = str(Path(os.getenv("SANDBOX_ROOT", str(paths.sandboxes_dir))))
    capabilities_dir: str = str(Path(__file__).parent.parent.parent / "capabilities")
    memory_dir: str = str(Path(__file__).parent.parent.parent / "memory")

    # Memory reflector
    reflector_mode: str = "pattern"  # "pattern" (deterministic) | "llm"
    # LLM reflector model provider — must reference a configured ModelProvider row.
    # Set REFLECTOR_MODEL_PROVIDER_ID to the provider's UUID/ULID.
    # Set REFLECTOR_MODEL to override the provider's default_model (optional).
    # Do NOT set REFLECTOR_ANTHROPIC_API_KEY — Anthropic is CLI-only.
    reflector_model_provider_id: Optional[str] = None
    reflector_model: Optional[str] = None

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
    deployer_socket_path: str = "/aspace/run/deployer.sock"

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

    # System evolution — registers the agent-space worktree as a system_core workspace
    # in the owner user's personal space on backend startup.
    enable_system_evolution: bool = False
    system_core_owner_email: str = ""
    system_core_base_branch: str = "master"

    # Agent Space environment (dev, test, prod)
    agent_space_env: str = "dev"

    # ── Daily Capture Report scheduler ───────────────────────────────────────
    # Set daily_report_scheduler_enabled=false to disable the background scheduler
    # (e.g., in environments where a separate cron process drives report generation).
    # Minimum interval is 30 seconds; values below 30 are rejected at startup.
    daily_report_scheduler_enabled: bool = True
    daily_report_scheduler_interval_seconds: int = 60

    @field_validator("daily_report_scheduler_interval_seconds")
    @classmethod
    def validate_daily_report_scheduler_interval(cls, v: int) -> int:
        if v < 30:
            raise ValueError(
                f"daily_report_scheduler_interval_seconds must be at least 30, got {v}"
            )
        return v

    # ── Backup ────────────────────────────────────────────────────────────────
    # Primary backup is BackupService (automatic, scheduled).
    # backup.sh / restore.sh are fallback operator tools only.
    #
    # Two-person dogfooding MUST set BACKUP_ENABLED=true.
    # Default is False (safe for tests and unattended CI).
    backup_enabled: bool = False
    backup_interval_hours: int = 24
    backup_retention_count: int = 7
    backup_include_logs: bool = False
    backup_on_startup: bool = True
    backup_root: str = str(_ASPACE_HOME / "backups")

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
