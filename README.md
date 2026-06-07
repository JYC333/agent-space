# agent-space

A space-based, multi-user, agent-first system for personal, family, and small team use.
The runtime target is **Linux / WSL / server + a browser UI**. By default agent runs are
isolated with **git worktrees** (plus `PathPolicy`) so file access is confined to the run's
workspace; stronger one-shot Docker isolation is an opt-in path for high-risk execution.
PostgreSQL is the only supported server database.

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
├── scripts/          # Utility scripts (start.sh, db/, system/)
├── docs/             # Architecture and design documentation
│
├── core/             # Agent system kernel (FastAPI backend + capabilities)
├── frontend/         # React/Vite web frontend (PWA)
├── deployer/         # Host-side deployer (holds the Docker socket; spawns sandbox containers)
└── deployments/      # Deployment templates
    ├── local/        # docker-compose for local development
    └── sandbox/      # Dockerfile for the agent execution sandbox image
```

Runtime data (DB, config, secrets, logs, workspaces, sandboxes) never lives in the repo.
It lives under a host-side parent `ASPACE_ROOT` (default `~/.aspace`), one mode root per
environment: `$ASPACE_ROOT/dev`, `$ASPACE_ROOT/test`, `$ASPACE_ROOT/prod`. Each mode root
is bind-mounted into the containers as `AGENT_SPACE_HOME=/aspace`.
Local DB/system scripts use the same compose/env path as `scripts/start.sh`: mode validation,
`$ASPACE_ROOT/<mode>`, `$ASPACE_ROOT/<mode>/.env`, `AGENT_SPACE_MODE_ROOT`, compose project,
and `docker compose --env-file ...` are centralized in `scripts/lib/local-compose.sh`.
The local PostgreSQL containers use stable names: `agent-space-dev-postgres`,
`agent-space-test-postgres`, and `agent-space-prod-postgres`.

## Quick Start

```bash
# 1. Start everything (creates ~/.aspace/dev/ and .env from template on first run)
./scripts/start.sh

# 2. Add a model provider in the app
#    Open the web app → Providers and paste your API key (stored encrypted; never in .env).
#    ~/.aspace/dev/.env holds infra-only settings (e.g. POSTGRES_PASSWORD for --prod).
```

`start.sh` builds the sandbox image on first run, then starts backend + frontend + deployer via Docker Compose. Data lives under **`~/.aspace/<mode>/`** (default mode `dev`).

```
Web UI:           http://localhost:3000   # Docker maps container 5173 → host 3000 (dev compose)
API:              http://localhost:8000
Interactive docs: http://localhost:8000/docs
```

### Options

```bash
./scripts/start.sh           # Docker Compose — dev (default)
./scripts/start.sh --test    # separate ports + ~/.aspace/test
./scripts/start.sh --prod
./scripts/start.sh --build   # force image rebuild
```

Test mode keeps the external API at `http://localhost:8100`, while the backend container
still listens on internal port `8000`; the test frontend talks to `http://backend:8000`.
Docker-native `scripts/db/migrate.sh`, DB-only `scripts/db/{dump,restore,reset-postgres}.sh`,
and offline `scripts/system/{backup,restore,verify-restore}.sh` start PostgreSQL
when needed and stop it after completion only when that script had to start it;
they leave already-running app stacks alone.

### Runtime target

The runtime is **Linux / WSL / server + browser UI**. A `frontend/src-tauri/` directory exists
but desktop support is **deferred and not part of the current product**. If it ships later it
will be a lightweight launcher (start/stop the server, open the browser) — not a reimplementation
of the backend.

## Sandbox Architecture

LLM agents can execute arbitrary shell commands. To protect the host:

- **Default — filesystem isolation**: git worktrees + `PathPolicy` confine file access to the
  run's workspace. This is the default execution isolation (`default_sandbox_level=worktree`).
- **High-risk — one-shot Docker**: runs that require `one_shot_docker` isolation execute in a
  dedicated, throwaway container (`agent-space-sandbox`). This is an opt-in path used only when
  configured; critical-risk runs that demand it are refused until it is wired up.

The **backend does not mount the Docker socket** and does not spawn containers directly. Sandbox
containers are launched by the host-side **deployer** service, which is the only component with
`/var/run/docker.sock` mounted. The backend talks to the deployer over a Unix socket
(`/aspace/run/deployer.sock`).

See [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md) for the full threat analysis.

## Authentication

Local development runs without authentication. Optional Google OAuth sign-in is supported when
`GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` are configured (see `core/backend/app/config.py`).
Persisted API keys are feature-gated and not enabled in the current build.

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
| Sandbox | Per-run isolation; git worktree by default, one-shot Docker for high-risk runs |
| Adapter | Execution backend: `echo`, `claude_cli`, `codex_cli` |

## Built-in Templates

No concrete agents are seeded. Built-in behavior comes from system **AgentTemplates**
(reusable factories, seeded once globally); a concrete Agent is created on demand via
copy-on-create, and runtime always loads config from its `AgentVersion` — never a template.

There is no `general_chat` template and no DirectChat — chat is the per-space **system-managed
default Assistant** (`agent_kind=system_assistant`), minted from the internal `personal_assistant`
seed spec. That seed spec is `visibility=system_internal`: hidden from the public Template Library
and not user-instantiable (at most one active Assistant per space). The reusable specialized
templates below are the public library:

| Template | Category | Purpose |
|----------|----------|---------|
| `activity_reflector` | reflection | Processes captures/activity into typed proposals + reflection summary; model selects output type |
| `memory_reflector` | memory | Memory update/merge/delete proposals only (no direct write) |
| `knowledge_curator` | knowledge | Proposes semantic KnowledgeItem types, relations, source links (proposal-only) |
| `research_reader` | research | Reads selected sources only (no web search/crawl); summaries, questions, knowledge proposals |
| `coding_reviewer` | workspace | Read-only review/report outputs; no file write, shell, or patch apply |

Memory reflection is also exposed as an internal service (`MemoryReflector` via the
`memory.reflect` capability, `POST /sessions/{id}/reflect`).

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Multi-Agent Runtime](docs/MULTI_AGENT.md)
- [Space Model](docs/SPACE_MODEL.md)
- [Memory Model](docs/MEMORY_MODEL.md)
- [Capability System](docs/CAPABILITY_SYSTEM.md)
- [Sandbox Policy](docs/SANDBOX_POLICY.md)
- [Threat Model](docs/THREAT_MODEL.md)
- [Memory Evolver Integration](docs/EVOLVER_INTEGRATION.md)
