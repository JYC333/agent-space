# Product and Boundaries

## What Agent-Space Is

Agent-Space is a **server-authoritative personal/household agent operating system** and **human-agent collaboration server**. It captures inputs, runs agents, produces reviewable artifacts and proposals, and governs what becomes durable memory or action.

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
→ Memory / Knowledge / Domain Object / Task / Action
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

- `ModelProvider` = model/vendor/API endpoint (OpenAI-compatible, Anthropic-compatible, OpenRouter, Ollama, or other).
- Configured per space via `GET/POST/PATCH /api/v1/providers`. API keys are encrypted server-side; responses expose `has_api_key` only.
- `RuntimeAdapter` = execution loop/tool environment (capability, model_api, claude_code, codex_cli, etc.).
- Agents select a default provider/model on `AgentVersion` (`model_provider_id`, `model_name`); runs resolve provider at creation time.
- **Canonical path for new adapters:** add a validated `RuntimeAdapterSpec` in `server/src/modules/runtimeAdapters/` and implement server adapter behavior when generic CLI execution is insufficient.

### Credential resolution boundary

- Runtime adapters obtain credentials through the server provider/credential broker in `server/src/modules/providers/`.
- Raw secret values must never appear in adapter config outputs, run steps, artifacts, or logs.
- Direct env-variable credential reads in adapters are not allowed for new work.

### Sandbox and path policy boundary

- All file access from agent execution is mediated by `WorkspaceManager` and `PathPolicy`.
- Sandboxed file-access adapters currently run inside a git worktree. One-shot Docker
  is planned for stricter process isolation and must fail closed until implemented.
- Adapters must not access arbitrary host paths.

### Proposal-first for durable change

- Consequential durable changes (memory writes, knowledge writes, code patches, policy changes) go through Proposal → human review → apply.
- Agents do not directly write active memory.
- Agents do not directly write active KnowledgeItem rows. Knowledge writes use `knowledge_*` proposals and accepted proposal apply handlers.
- The public memory write API returns a `ProposalOut` with HTTP 202, not a direct memory mutation.

### Knowledge is not Memory

- Memory is agent context. Knowledge is human-browsable, reviewable, relational long-term content.
- Knowledge items must not automatically enter ContextBuilder.
- Promoting Knowledge into Memory must be a separate future proposal flow, not an implicit side effect.
- Activity, Run, and Artifact are source inputs for Knowledge proposals.
- Project and workspace are contextual associations for Knowledge, not Knowledge content types.
- Knowledge reads enforce MVP visibility: shared rows are readable within the current space; private and restricted rows are owner-readable only.
- Knowledge relations are database-backed and relation reads omit any row whose endpoints are not both readable by the viewer.

### PolicyEngine evaluates built-in runtime rules; persisted policy enforcement is domain-specific

- `PolicyEngine` evaluates stateless built-in rules. It does not load persisted Policy rows.
- Domain-specific persisted-policy enforcement (e.g. `memory.private_placement`, `run.user_private_scope`) lives in `server/src/modules/policy/`.
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
| Space membership / selected space access | server auth middleware + policy role helpers | Active |
| Memory write (public API) | Returns Proposal (HTTP 202), not direct write | Active |
| Memory proposal apply | Proposal gate + SourceMonitoring gate | Active |
| Memory write boundary | server proposal apply service; no public direct active-memory mutation | Active |
| Knowledge write boundary | `knowledge.*` actions wired via `proposal.apply`; `knowledge_*` handlers in ProposalApplyService | Active |
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
