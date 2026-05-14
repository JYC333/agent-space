# Roadmap

## Shipped foundations

- Space / user / workspace data model
- Memory system (store, evolver, read audit rows)
- ContextBuilder (space-scoped context assembly)
- ContextCompiler (vendor-neutral context formatting)
- Memory proposal / approval workflow
- Session and message model
- Capability registry (YAML manifest loader)
- Sandbox execution (DockerExecutor, SandboxManager)
- CLI adapters: echo, claude_code, codex_cli
- Run-centric execution (`Run`, `RunService`, `RunExecutionService`, `agent_run` jobs)
- Task board ORM (`Task`, `Board`, `TaskRun`, …)
- Layered `.agent/` context documentation

## Active engineering themes

- Hardening Alembic migrations for long-lived installs
- Policy engine wiring on sensitive routes
- Workspace console persistence (sessions, API keys) once canonical tables land
- Home summary and review surfaces as UX matures

## Intentionally deferred

- Full mobile app (PWA stubs only)
- Full desktop app (Tauri deferred; see [0005](decisions/0005-desktop-runtime.md))
- Full local-first sync
- Complete Notion / Obsidian replacement
- Complete Anki replacement
- Full coding-agent automation loops
- Public open-source release polish
- Multi-tenant SaaS deployment
- Full WebSocket / SSE streaming
- PostgreSQL migration path

## Reference

- [ARCHITECTURE.md](ARCHITECTURE.md) — layer map
- [BOUNDARIES.md](BOUNDARIES.md) — invariants
- [tasks/current-focus.md](tasks/current-focus.md) — short-term priorities
- [docs/MEMORY_CONTEXT_ROADMAP.md](../docs/MEMORY_CONTEXT_ROADMAP.md) — future extension paths for the memory/context system
