# Current Focus

Last updated: 2026-05-06

## Current Implementation Focus

1. **Layered `.agent/` context documentation** — completed in this session
2. **ContextCompiler** — implemented and tested (22 tests passing)
3. **Sandbox infrastructure stabilization** — Docker socket permissions, DOCKER_GID, path translation all fixed
4. **Architecture boundaries explicitly documented** — BOUNDARIES.md with 22 invariants

### Immediate next tasks (in priority order)

- Verify `claude_cli` adapter works end-to-end through Docker after socket permission fix
- Add `ActivityRecord` model to `models.py` (capture layer prerequisite)
- Alembic migrations — replace `create_all()` dev shortcut
- Wire `PolicyEngine` to all sensitive API routes
- `RunMetrics` written at end of every `execute_pending_run`
- Memory reflection auto-triggered after session completion
- `WorkspaceManager` CRUD API (Workspace model now exists in models.py)

## Current Non-goals

- Full desktop app (Tauri deferred — see [decisions/0005](../decisions/0005-desktop-runtime.md))
- Full mobile app
- Local-first sync
- Complete Notion/Obsidian replacement
- Complete Anki replacement
- Full agentic coding loop automation (multi-step, multi-file autonomous changes)
- Public open-source release polish
- LLM Wiki (planned Phase 2)
- Spaced repetition cards (planned Phase 3)
- Browser extension for capture
- Multi-tenant SaaS deployment

## System Status

| Component | Status |
|---|---|
| Space / memory data model | Done |
| ContextBuilder | Done |
| ContextCompiler | Done, tested |
| Memory proposals | Done |
| Sandbox (DockerExecutor) | Done |
| claude_cli adapter | Done (needs e2e verify) |
| codex_cli adapter | Done |
| Policy engine | Partial (not fully wired) |
| Activity records | Planned |
| LLM Wiki | Planned |
| Spaced repetition | Planned |
| Workspace console UI | Planned |
| Alembic migrations | TODO |
| RunMetrics | TODO |
