# Architecture Boundaries

Load this file for any task that changes structure, models, APIs, or agent behaviour.

---

## Data Boundaries

**B1** — `core/` must remain open-source-ready. It must not contain private instance data, real user memory, secrets, or deployment-specific config.

**B2** — `instance/` contains all deployment-specific state: database, logs, config, secrets, storage, cache. It is never committed to source control.

**B3** — One deployment instance can host many spaces. Do not create one instance per user or one instance per space.

**B4** — Space is the product-level isolation boundary. Data in space A must never be accessible to code running in the context of space B.

**B5** — `space_id` is required on every core data entity. The ContextBuilder enforces this boundary; it refuses to build context without an explicit `space_id`.

---

## User / Agent Boundaries

**B6** — User and Agent are separate models. A user is a person; an agent is an AI runtime. One user can own multiple agents.

**B7** — Users and agents have independent identity, permissions, and memory policies. Do not merge them into a single model.

**B8** — Agents can be user-owned, space-owned, workspace-owned, or system-owned. Ownership affects visibility and permission inheritance.

---

## Memory Boundaries

**B9** — Memory is scoped long-term context, not raw business data. Raw input must enter `activity_records` first.

**B10** — Agents do not directly write active memory. All memory updates must go through the proposal → user approval → activation flow.

**B11** — Every memory read must be logged in `MemoryReadTrace` (table `memory_access_logs`). This feeds the MemoryEvolver fitness function.

**B12** — External chat capture (e.g. conversation imports) must create activity records first, not active memory.

---

## Execution Boundaries

**B13** — `_SANDBOXED_ADAPTERS` (claude_code, codex_cli, and future coding runtimes) are always sandboxed. Current implemented sandbox routing is git worktree + local executor for file-access CLI runs. one-shot Docker is not implemented in the backend product path yet; high/critical paths must fail closed rather than silently downgrading. An agent can escalate `risk_level` but cannot remove an adapter from `_SANDBOXED_ADAPTERS`.

**B14** — Vendor context files (CLAUDE.md, AGENTS.md, Cursor rules) are generated artefacts written by ContextCompiler to the sandbox directory. They are not the source of truth and are never written directly to the real workspace by default.

**B15** — Formal agent runs (automated, tracked, sandbox-enforced) must go through agent-space managed mode. IDE plugin usage is assist/manual mode — it is not tracked the same way.

**B16** — Windows desktop is not a full runtime. The agent loop runs in Linux/WSL/server. A desktop app, if built later, is only a launcher/control panel. See [0005](decisions/0005-desktop-runtime.md).

---

## Workspace Boundaries

**B17** — Workspace file access must go through `WorkspaceManager` and `PathPolicy`. Adapters must not access arbitrary host paths.

**B18** — Sandboxes are short-lived execution areas. Long-term records are: artifacts, diffs, logs, and approved proposals. Sandbox directories may be cleaned up after artifact collection.

**B19** — Agents should not directly modify real workspaces. Preferred flow: `workspace → git worktree/sandbox → agent execution → validation → diff/artifacts → approval → apply patch`.

**B19A** — Workspace console reads are policy-gated. `workspace.read` is enforced for tree, file, git status, and git diff. system_core, external-root, restricted/protected, full-diff, and secret-like reads force durable audit records.

---

## Capability Boundaries

**B20** — Capability changes require the full lifecycle: draft → proposed → testing → approval → enabled. Self-evolution (an agent modifying its own capabilities) must go through this flow via capability proposals.

**B21** — Capabilities are code-defined (manifest + code + prompts + tests), not only prompt-defined. A capability without tests or a manifest is incomplete.

---

## Frontend / UI Boundaries

**B23** — The frontend is not an admin-only console. It is the primary user-facing product surface including personal use (capture, review, knowledge reading, assistant chat). Design for non-technical users.

**B24** — Raw user inputs (thoughts, life logs, file imports, chat captures) must enter via `ActivityRecord` first. The frontend must not write to Memory, KnowledgeItem, or FlashCard directly — always via proposals or the activity intake flow. KnowledgeItem rows must not automatically enter Memory or ContextBuilder.

**B25** — The workspace console (file browser, diff viewer) is for workspace operators. It must not be shown as the primary entry point for personal-use features (capture, review, chat).

**B26** — Git diff review is approval-oriented, not merge-tool-oriented. The UI must show attribution (which agent run produced the diff) and make accept/reject the primary actions. Inline editing in the diff view is not supported in v1.

**B27** — Server status (RuntimeStatusBar) must always be visible in the shell. It must not be hidden behind a settings page. Degraded/error states must be immediately apparent to the user.

---

## Mobile Boundaries

**B28** — Mobile is a thin client. Agent execution always runs server-side. The mobile client must never attempt to run agent code locally.

**B29** — Quick capture on mobile must work offline. The client must queue the ActivityRecord in IndexedDB and sync when the connection is restored.

**B30** — Card review on mobile must pre-fetch the next N due cards so review can continue without a live connection.

---

## Sync Boundaries

**B31** — All model primary keys must be UUIDs (or equivalent globally-unique strings). Auto-increment integer PKs are not allowed — they break sync across devices.

**B32** — Sync must never overwrite user data without explicit conflict resolution. Sync conflicts surface in the UI; the user decides. Memory changes through sync still require the proposal → approval flow.

---

## Resilience Boundaries

**B-R1** — `Run.status` includes `degraded` in addition to `queued|running|succeeded|failed|cancelled|waiting_for_review`. A run is `degraded` when it completes but with partial or compromised quality — the output is accessible but flagged for user review.

**B-R2** — `Run.mode` includes `live` (real execution, persists changes) and `dry_run` (preview, no persistent changes, artifacts not saved).

**B-R3** — Artifact export is explicit: every artifact has `path` and/or `content`; `GET /api/v1/artifacts/{id}/export` returns a file download. Artifact paths point to persistent storage (`~/.aspace/artifacts/`), not sandbox working directories.

**B-R4** — `Proposal` has explicit temporal fields: `created_at`, `decided_at`, `deadline` (soft, optional), and computed `expired` (true when deadline passed and status is still `pending`). `urgency` field (`low|normal|high|critical`) affects sort order.

**B-R5** — All temporal fields are explicit on Run: `created_at`, `started_at`, `completed_at`, `scheduled_at`. No derived timestamps.

---

## Module / Plugin Boundaries

**B33** — Modules must not import from each other. A module may only import from the kernel (`app.db`, `app.config`, `app.models`, `app.schemas`, `app.auth`). Exceptions are documented in [ADR 0007](decisions/0007-plugin-module-architecture.md) and must not grow without updating that ADR.

**B34** — Every module's HTTP routes must live in `<module>/api.py` (plus optional `<module>/*_api.py` for large route groups). Routes must not be defined in `main.py` or in any shared `api/` directory.

**B35** — The backend module registry (`app/modules/registry.py`) and frontend module registry (`apps/web/src/modules/registry.ts`) are the single sources of truth for which features are active. Do not hardcode route lists or nav items elsewhere.

**B36** — Frontend module pages must use `React.lazy()` entry points. A module must not be eagerly imported in `apps/web/src/App.tsx` or `apps/web/src/core/Shell.tsx`. This preserves Vite's ability to produce separate chunks per module for build-time exclusion.

**B37** — `planned: true` modules must have a working stub page (not a blank component, not a 404). The stub must name the feature, state that it is planned, and reference the relevant `.agent/modules/` doc.

---

## Runtime Adapter Boundaries

**B38** — The agent-space core is runtime-agnostic. OpenCode, Claude Code, Codex, Cursor, and any other vendor CLI are optional runtime adapters, not the foundation. Core features (memory, knowledge, flashcards, activity capture, proposals, assistant chat) must work without any coding-agent runtime installed.

**B39** — No vendor CLI or external runtime is the source of truth for memory, policy, permissions, or audit records. These always live in the agent-space database regardless of which runtime adapter is active.

**B40** — An enterprise or commercial deployment must be able to disable any runtime adapter (for example `claude_code`) without breaking the rest of the system. Adapter availability is checked at run time via runtime-generic status/detection; unavailability must be surfaced as a clear error, not a silent fallback to unsandboxed execution.

---

## CLI Credential Boundaries

**B45** — CLI credential profiles are owned by agent-space. Sandboxes never receive the full backend container HOME or the full `instance/secrets/` directory.

**B46** — Every CLI credential grant or denial is audited in `cli_credential_events`. Manual and automation CLI runs require an explicit CredentialBroker profile. Runs with no profile configured fail before adapter invocation and record `credential_source="none"` with `fallback_reason="no_profile_configured"`.

**B47** — Future Docker sandboxes may receive at most one credential profile dir, mounted read-only by default. Write access requires explicit `readonly: false` in the profile config. Until one-shot Docker is implemented, documentation must describe high/critical Docker paths as fail-closed, not available.

**B48** — Credential profiles are never written back from the sandbox automatically. If a CLI updates its login state during a run, only the profile's source directory is affected (via symlink for worktree, via writable volume for Docker). No automatic propagation to other profiles.

**B49** — The CredentialBroker never exposes raw secret values through the API. The credentials API returns path metadata only (source_path, exists, non_empty).

## API Entrypoint Boundaries

**B50** — `control-plane` is the default client-facing API entrypoint for web, dev, test, and prod. Existing Python-owned `/api/v1/*` routes continue through the temporary legacy Python proxy; the permanent gateway module inside `control-plane` owns routing and request context. Backend remains the Python authority for existing routes, writes, commands, policy, proposals, memory, runs, jobs, artifacts, provider invocation, and migrations. No business authority moves to TypeScript without an explicit later ownership decision.

---

## Deployment Boundaries

**B41** — The main app container does not directly restart or rebuild itself. Host-level deployment actions are handled exclusively by the deployer process (`deployer/deployer.py`) through a Unix domain socket.

**B42** — The deployer Unix socket is never exposed on a public TCP port. Access is controlled by filesystem permissions on the socket file.

**B43** — The deployer accepts only allowlisted job types (`rebuild_agent_space`, `restart_agent_space`, `health_check`). It never executes arbitrary shell commands. Agent-generated code cannot trigger deployment without a human-approved proposal.

**B44** — The Docker socket (`/var/run/docker.sock`), if present, is not used for deployment control. Deployment goes through the deployer Unix socket. High-risk one-shot Docker sandboxing is not currently implemented in the backend product path and must not be represented as active isolation.

---

## Open-Source Boundary

**B22** — The project is private-first but open-source-ready. Do not put private data, real user memory, or non-shareable credentials into `core/`. See [0006](decisions/0006-open-source-readiness.md).
