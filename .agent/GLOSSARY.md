# Glossary

Key terms used consistently across agent-space.

---

**Deployment Instance**
One running installation (one server, one database). Hosts many spaces.

**Space**
Product-level isolation boundary. Personal, household, or team. All data scoped by `space_id`.

**User**
A human person. Referenced by `user_id` string across the schema. Can belong to multiple spaces.

**Agent**
An AI runtime actor. Separate from User. Has profile, memory policy, capabilities, and runtime policy.

**Workspace**
A project or knowledge area within a space. Has an optional local filesystem `path`.

**Activity Record**
Raw input or external event. Source types: `user_input`, `imported_chat`, `web_capture`, `file_import`, `agent_run`, `task_log`, `manual`. Never becomes active memory directly — flows through proposals first. `app/activity/`.

**Memory**
Scoped long-term context. Written only via the proposal → approval workflow. Not raw data.

**Memory Proposal**
Agent-generated proposed change to active memory. Requires user approval before activation. Has `source_evidence`, `risk_level`, and `needs_changes` support.

**Context Attachment**
Structured reference to a piece of context (file, git_diff, memory_entry, etc.) for a run or session. Resolved and security-scanned by ContextBuilder. Stored in `context_attachments`.

**Context Builder**
Assembles a `ContextPackage` from MemoryStore for a space/user/workspace. Enforces space isolation. Resolves ContextAttachments. Logs all memory access.

**Context Compiler**
Translates a ContextPackage into a vendor instruction file (CLAUDE.md, AGENTS.md, SOUL.md, etc.) written to the sandbox. Runs security scanning, enforces token budgets, and loads `.agent/` docs progressively.

**Context Snapshot**
Frozen ContextPackage captured at run-start. Immutable — memory writes during the run do not mutate it. Stored in `context_snapshots` for audit.

**Memory Provider**
Abstract interface for memory storage backends. `LocalMemoryProvider` (DB-backed) is the only enabled provider in MVP.

**Knowledge Item**
Structured wiki entry. *(Planned)*

**Card**
Spaced repetition review item generated from knowledge or activities. *(Planned)*

**Capability**
A code-defined skill registered via `capability.yaml`. Lifecycle: draft → enabled.

**Tool**
A specific action a capability can perform. Permissions declared per-agent, enforced by PolicyEngine.

**Sandbox**
Isolated execution environment for an agent run. Worktree (default) or Docker (high-risk).

**Artifact**
Persistent output of an agent run: file, diff, log, report. Survives sandbox cleanup.

**Proposal**
Pending change awaiting human approval. Types: `memory_update`, `code_patch`, `capability_install`, `schema_migration`, `policy_change`, `report`, `classification`.

**Managed Mode**
Agent run tracked, sandboxed, and logged by agent-space. Proposals and artifacts captured.

**IDE Assist Mode**
Direct CLI use (Claude Code, Codex) without agent-space orchestration. Not fully tracked.
