# Product and Boundaries

## What Agent-Space Is

Agent-Space is a **local-first personal/household agent operating system** and **human-agent collaboration control plane**. It captures inputs, runs agents, produces reviewable artifacts and proposals, and governs what becomes durable memory or action.

It is not:
- a chat app
- a coding agent wrapper
- a personal notes app
- a task manager
- an app gallery

The core loop is:

```
capture / trigger
→ Activity / Source
→ Agent Run / Job
→ Artifact + Proposal
→ Human Review
→ Memory / Wiki / Domain Object / Task / Action
```

## Durable Product Boundaries

### Space is the isolation boundary

- `space_id` is required on every core data entity.
- Data in one space must never be accessible from another space's execution context.
- A deployment instance may host multiple spaces (personal, household, team).

### User, Agent, and Actor are separate

- **User** — a human identity with space memberships.
- **Agent** — an AI execution profile with versioned config, model, runtime, and policy. Not the same as a User.
- **Actor** — the general execution/authorship identity: user, agent, system, automation, connector, or service account. New audit and RunStep surfaces carry actor identity.
- Do not merge User and Agent.

### Workspace is a context container, not a repository

- A workspace may contain activities, tasks, runs, artifacts, proposals, memory, files, attached repositories, and agents.
- A code repository is an attached resource, not the definition of workspace.

### ModelProvider and RuntimeAdapter are separate

- `ModelProvider` = model/vendor/API endpoint (Anthropic, OpenAI, OpenRouter, Ollama, custom OpenAI-compatible).
- Configured per space via `GET/POST/PATCH /api/v1/providers`. API keys are encrypted server-side; responses expose `has_api_key` only.
- `RuntimeAdapter` = execution loop/tool environment (echo, anthropic_messages, claude_code, codex_cli, etc.).
- Agents select a default provider/model on `AgentVersion` (`model_provider_id`, `model_name`); runs resolve provider at creation time.
- **Canonical path for new adapters:** `core/backend/app/runtimes/`.
- `core/backend/app/agents/` is a separate CLI adapter runner for existing CLI surfaces. Do not add new adapters here; use `core/backend/app/runtimes/`.

### Credential resolution boundary

- Runtime adapters obtain credentials through the runtime credential resolver (`runtimes/credentials.py`).
- Raw secret values must never appear in adapter config outputs, run steps, artifacts, or logs.
- Direct env-variable credential reads in adapters are not allowed for new work.

### Sandbox and path policy boundary

- All file access from agent execution is mediated by `WorkspaceManager` and `PathPolicy`.
- Sandboxed adapters run inside a git worktree (default) or Docker container (high-risk).
- Adapters must not access arbitrary host paths.

### Proposal-first for durable change

- Consequential durable changes (memory writes, code patches, policy changes) go through Proposal → human review → apply.
- Agents do not directly write active memory.
- The public memory write API returns a `ProposalOut` with HTTP 202, not a direct memory mutation.

### PolicyEngine enforces at least the selected persisted policy slice

- `PolicyEngine` loads active persisted `Policy` rows for the current space.
- The current active slice: `memory.write_direct` — an active deny policy prevents direct internal memory writes.
- Accepted policy proposals create active `Policy` rows that affect real enforcement decisions.

### App runtime must not self-deploy with arbitrary host authority

- The app container does not directly restart or rebuild itself.
- Deployment actions route through the host-level deployer via Unix domain socket.
- The deployer accepts only allowlisted job types. No arbitrary shell commands.

### External tools are adapters, not product foundations

- Claude Code, Codex, Cursor, LangGraph, OpenAI Agents SDK are runtime adapters.
- Memory, context, policy, proposals, audit, and workspace governance live in Agent-Space's database, not in vendor CLIs.

## Current Enforcement Points

| Enforcement point | Current mechanism | Status |
|---|---|---|
| HTTP auth/session identity | Session/API-key identity; no dev-identity fallback | Active |
| Space membership / selected space access | `auth/policy.py` membership + role helpers | Active |
| Memory write (public API) | Returns Proposal (HTTP 202), not direct write | Active |
| Memory proposal apply | Proposal gate + SourceMonitoring gate | Active |
| Memory direct write (`memory.write_direct`) | `PolicyEngine` checks active persisted policy row | Active |
| Policy proposal apply | Proposal gate creates active Policy row | Active |
| Runtime execution | Runtime policy JSON, adapter resolver, credential resolver | Active |
| Runtime credential use | Credential resolver + secret redaction | Active |
| Workspace file read | Route workspace-space check + `PathPolicy` | Active |
| Workspace file write / code patch | Approved `code_patch` proposal gate + `PathPolicy` | Active |
| Sandbox path access | Execution workspace boundary, worktree root validation | Active |
| Deployment / deployer calls | Feature-gated; deployer allowlist only | Active |
| Self-evolution execution | Disabled by default (`ENABLE_SYSTEM_EVOLUTION=false`) | Active |
| Future automation trigger | No model yet — reserved | Not built |
| Future connector sync | No model yet | Not built |

## Architecture Fitness Checks

Run these before structural changes:

**Boundary checks:**
- Is Space still the isolation boundary?
- Are User and Agent still separate?
- Is Actor available for authorship/execution identity on new surfaces?
- Is ModelProvider separate from RuntimeAdapter?
- Is Workspace a context container, not a repo?
- Are vendor instruction files generated artifacts, not source of truth?

**Flow checks:**
- Are durable changes still proposal-first?
- Are raw inputs still Activity-first (not session-first for non-chat)?
- Are memory writes reviewed before apply?
- Can Run explain what happened (via RunStep)?
- Are Jobs separate from Runs?

**Safety checks:**
- Are secrets absent from run output, steps, artifacts, and logs?
- Does an accepted active Policy row change a real enforcement decision?
- Is deployment still manual or allowlisted-deployer-only?
- Is self-evolution disabled by default?
- Does workspace scan mark paths `stale` rather than hard-delete?
