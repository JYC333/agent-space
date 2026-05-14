# agent-space

A space-based, multi-user, agent-first system for personal, family, and small team use.
Agents run inside isolated Docker containers so LLM-generated shell commands never touch the host.

## Concept

```
One deployment instance
  ├── Personal Space
  ├── Family Space
  └── Team Space
```

Each space has its own users, workspaces, memories, permissions, agents, and tool access.

## Repository Layout

```
agent-space/
├── README.md
├── CLAUDE.md
├── .gitignore
├── scripts/          # Utility scripts (start.sh, etc.)
├── docs/             # Architecture and design documentation
│
├── core/             # Agent system kernel (FastAPI backend + capabilities)
├── frontend/         # React/Vite web frontend (PWA)
├── instance/         # Private deployment data — DB, config, secrets, logs (not tracked)
├── workspaces/       # Managed external repos/projects (not tracked)
├── sandboxes/        # Per-run agent sandbox directories (not tracked)
└── deployments/      # Deployment templates
    ├── local/        # docker-compose for local development
    └── sandbox/      # Dockerfile for the agent execution sandbox image
```

## Quick Start

```bash
# 1. Start everything (creates ~/aspace/dev/ and .env from template on first run)
./scripts/start.sh

# 2. Edit secrets
#    ~/aspace/dev/.env — set ANTHROPIC_API_KEY at minimum, then re-run ./scripts/start.sh
```

`start.sh` builds the sandbox image on first run, then starts backend + frontend + deployer via Docker Compose. Data lives under **`~/aspace/<mode>/`** (default mode `dev`).

```
Web UI:           http://localhost:3000   # Docker maps container 5173 → host 3000 (dev compose)
API:              http://localhost:8000
Interactive docs: http://localhost:8000/docs
```

### Options

```bash
./scripts/start.sh           # Docker Compose — dev (default)
./scripts/start.sh --test    # separate ports + ~/aspace/test
./scripts/start.sh --prod
./scripts/start.sh --build   # force image rebuild
```

### Runtime target

The MVP runtime is **Linux / WSL / server + browser UI**. The `frontend/src-tauri/` directory
exists but desktop support is deferred. If added later, it will be a lightweight launcher
(start/stop the server, open the browser) — not a reimplementation of the backend.

## Sandbox Architecture

LLM agents can execute arbitrary shell commands. To protect the host:

- **Tier 1 — filesystem isolation**: git worktrees + PathPolicy restrict file access to the run's workspace
- **Tier 2 — process isolation**: agents with `runtime_policy.sandbox_required = true` run in a
  dedicated Docker container (`agent-space-sandbox`) with 1 GB RAM, 1 CPU, and no host filesystem access

The backend spawns sandbox containers at run time via the Docker socket (`/var/run/docker.sock`).
Network access per adapter:
- `echo` → `none` (no internet)
- `claude_cli` / `codex_cli` → `bridge` (needs LLM provider API)

See [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md) for the full threat analysis.

## Authentication

Auth is **off by default** for local development. To enable:

```bash
AUTH_ENABLED=true  # in deployments/local/.env
```

With auth enabled, all API requests must include `Authorization: Bearer ask_<key>`.
Keys are created via `POST /api/v1/auth/keys`. In debug mode (`DEBUG=true`), a dev key
is seeded automatically and printed to the server log on startup.

## Running Tests

```bash
cd core/backend && python3 -m pytest tests/unit tests/contracts tests/invariants tests/workflows -v --tb=short
```

``tests/conftest.py`` sets an isolated ``AGENT_SPACE_HOME`` before importing the app, so the suite does not open a real mode database.

## Key Concepts

| Term | Meaning |
|------|---------|
| Space | Personal / family / team container; every record is scoped by `space_id` |
| User | A person, may belong to multiple spaces |
| Workspace | A project, repo, or knowledge area within a space |
| Memory | Scoped long-term information; written only via proposal → approval workflow |
| Capability | Code-defined skill registered via `capability.yaml` manifest |
| Sandbox | Per-run Docker container; isolated filesystem, network, and resources |
| Adapter | Execution backend: `echo`, `claude_cli`, `codex_cli` |

## Built-in Agents

| Agent | Adapter | Sandbox | Purpose |
|-------|---------|---------|---------|
| `system.echo-agent` | echo | No | Deterministic test/echo agent |
| `system.memory-curator-agent` | claude_cli | Yes | Reflects on sessions, proposes memory updates |

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Multi-Agent Runtime](docs/MULTI_AGENT.md)
- [Space Model](docs/SPACE_MODEL.md)
- [Memory Model](docs/MEMORY_MODEL.md)
- [Capability System](docs/CAPABILITY_SYSTEM.md)
- [Sandbox Policy](docs/SANDBOX_POLICY.md)
- [Threat Model](docs/THREAT_MODEL.md)
- [Memory Evolver Integration](docs/EVOLVER_INTEGRATION.md)
