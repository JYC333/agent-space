# Roadmap

## Current Phase — Foundation

Build the agent-space foundation before adding features:

- [x] Space / user / workspace data model
- [x] Memory system (store, evolver, access logs)
- [x] ContextBuilder (space-scoped context assembly)
- [x] ContextCompiler (vendor-neutral context formatting)
- [x] Memory proposal / approval workflow
- [x] Session and message model
- [x] Capability registry (YAML manifest loader)
- [x] Sandbox execution (DockerExecutor, SandboxManager)
- [x] CLI adapters: echo, claude_cli, codex_cli
- [x] Layered `.agent/` context documentation
- [ ] Activity records model and API
- [ ] Generalized proposal system (code_patch, capability_install, schema_migration)
- [ ] PolicyEngine fully wired to API routes
- [ ] Workspace model and WorkspaceManager API
- [ ] Alembic migrations (replace create_all dev shortcut)
- [ ] RunMetrics written at end of every run
- [ ] Memory reflection auto-triggered after sessions

## Not Current Phase

These are intentionally deferred:

- Full mobile app
- Full desktop app (Tauri deferred; see [0005](decisions/0005-desktop-runtime.md))
- Full local-first sync
- Complete Notion / Obsidian replacement
- Complete Anki replacement
- Full coding agent automation (agentic loops, multi-step planning)
- Public open-source release polish
- Multi-tenant SaaS deployment

## Future Phases

**Phase 2 — Knowledge and Capture**
- Activity records (raw input capture)
- Personal assistant / capture module
- LLM Wiki (KnowledgeItem, KnowledgeRelation)
- Agent-generated wiki proposals

**Phase 3 — Spaced Repetition**
- Card generation from knowledge items and activities
- FSRS scheduling algorithm
- User-specific review state

**Phase 4 — Workspace Console**
- File browser, git status, diff review in UI
- Agent run log viewer
- Artifact browser, approval UI

**Phase 5 — Advanced Agents**
- Multi-agent delegation (partial: already in runner.py)
- Long-running agent loops
- Credential vault for agent secrets
- Capability self-evolution workflow

**Phase 6 — Scale and Polish**
- PostgreSQL migration path
- Alembic migrations hardened
- Multi-user auth (beyond single-user default)
- API key management UI
- Optional desktop launcher (Tauri, thin shell only)
