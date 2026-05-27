# Module: Agents

## Purpose

Define AI agents and wire them to execution. An agent is a configured product-level actor — separate from the human user who owns it and separate from the runtime adapter that executes it.

## Three-Way Separation

```
Agent            — product-level actor (owned by user/space/workspace, has policy)
    ↓ dispatches via
Runtime Adapter  — technical execution backend (echo, claude_code, codex_cli, …)
    ↓ calls
Model Provider   — underlying LLM (Anthropic, OpenAI, Ollama, …)
```

See `runtime-adapters.md` for the full adapter registry and license notes.

> **Note:** configs may still say `claude_cli`; the backend maps that id to the same adapter implementation as `claude_code`. Prefer `claude_code` in new manifests.

## Owns

- `Agent` ORM model and CRUD
- `AgentVersion` model (immutable execution config snapshot per `Run`)
- `Run` rows created through `RunService` (queued work, lifecycle, delegation links)
- Adapter implementations: `echo`, `claude_code`, `codex_cli`
- Agent seeding (built-in system agents)
- Adapter registry and post-run hooks in `app/agents/runner.py`

## Does Not Own

- Memory content (memory module)
- Policy decisions (policy module)
- Sandbox container lifecycle (`workspace/sandbox_manager.py`)
- Capability definitions (capability module)
- Provider credentials (`ModelProvider` encrypted config + `runtimes/credentials.py`; not env vars for runtime execution)
- Run execution orchestration (`app/runs/execution.py` + job worker)

## Key Models

```
Agent:
  id, space_id, name, description, visibility
  role_instruction          — public identity/role description
  current_version_id        — convenience pointer to latest AgentVersion
  status (active|inactive|archived)

AgentVersion:
  id, agent_id, space_id
  version                   — immutable label, e.g. "v1", "v2"
  system_prompt             — immutable execution prompt text
  model_provider_id           — FK to ModelProvider (LLM backend for this version)
  model_name                  — model id string for the selected provider
  model_config_json         — {model, temperature, max_tokens, ...}
  runtime_config_json       — {risk_level, max_run_time_seconds}
  context_policy_json       — {readable_scopes, writable_scopes}
  memory_policy_json        — {readable_scopes, writable_scopes, requires_proposal}
  capabilities_json         — list of capability IDs
  tool_permissions_json     — {allowed_tools, allowed_adapter_types}
  runtime_policy_json       — {sandbox_required, allowed_adapter_types}
  source_proposal_id        — proposal that approved this version, when post-create
  source_activity_id        — activity record for the config change, when post-create
  created_at
  Note: AgentVersion is append-only. Agent.current_version_id is updated on save.
        Existing runs keep their agent_version_id and remain reproducible.

Run:
  id, space_id, agent_id, agent_version_id
  status (queued|running|succeeded|failed|cancelled|degraded|waiting_for_review)
  mode (live|dry_run)
  parent_run_id               — user-created run lineage (follow-up, retry, continuation)
  instructed_by_agent_id      — internal-only ORM field for actor resolution; not settable via public API
  prompt, instruction, output_json, error_json, sandbox metadata fields
```

## Main Flows

**Queued run creation**

1. HTTP (`POST /agents/{id}/runs`, task board endpoints, or agent helpers) → `RunService.create_run`
2. Worker picks up `agent_run` jobs → `RunExecutionService` selects adapters from policy
3. Adapters execute with sandbox routing managed outside `AgentService`

**Run lineage (parent_run_id)**

`parent_run_id` supports user-created lineage: follow-up runs, retries, manual continuations, and
external run imports. `trigger_origin="parent_run"` is not a valid trigger origin — parent lineage
is a structural link, not a trigger type. Valid trigger origins: `manual`, `automation`, `job`, `system`.

Agent-to-agent delegation is not a current canonical capability and is deferred.
Future multi-agent child-run creation must be designed as `run.spawn_child` / `run.create_child`
with explicit control-plane policy and evaluation gates. `runtime.execute` controls adapter
execution only; it is not a delegation replacement.

**Agent execution config changes**

Initial agent creation may create its first immutable `AgentVersion` directly.
Post-create execution config changes must go through
`POST /api/v1/agents/{agent_id}/config-proposals`.

`PATCH /agents/{agent_id}` is limited to identity fields. Execution fields such
as model, runtime adapter, system prompt, model/runtime/context/memory policies,
capabilities, and tool permissions return a conflict/validation error pointing
callers to the config proposal route.

Accepting an `agent_config_update` proposal validates that the agent, model
provider, runtime adapter, and base version are in the same space. It rejects a
stale `base_version_id`, creates a new immutable `AgentVersion`, records
proposal/activity provenance, advances `Agent.current_version_id`, and marks
the affected agent digest dirty.

## Built-in Agents

- `system.echo-agent` — deterministic test adapter, no LLM needed
- `system.memory-curator-agent` — reflects on sessions, proposes memory updates

## Adapter Registry

| Adapter       | Required risk_level | Sandbox Level   | Notes                                                     |
|---------------|---------------------|-----------------|-----------------------------------------------------------|
| `echo`        | any                 | none            | Test/demo only; always available; no file access          |
| `claude_code` | **high** (required) | worktree        | CLI installed in backend image; fails validation if risk_level < high |
| `codex_cli`   | **high** (required) | worktree        | CLI installed in backend image; fails validation if risk_level < high |

## Invariants

- `claude_code` and `codex_cli` stay in the sandboxed adapter set — cannot be downgraded to host execution
- Context snapshots captured at run creation stay immutable
- No vendor adapter is the source of truth for memory, policy, or audit
- `agent_version_id` on `Run` is immutable per row — historical runs stay reproducible after edits to `Agent`
- `AgentVersion` is append-only — prior rows are not rewritten in place
- Public post-create execution config mutation is proposal-only. Direct public
  AgentVersion creation must not advance `Agent.current_version_id`.
- Accepted config proposals leave provenance from the new AgentVersion to the
  accepted Proposal and ActivityRecord.
- Execution config fields that affect context, memory, runtime, model, tools,
  capabilities, or system prompt dirty the agent digest. Identity-only fields do not.

## Related Files

- `core/backend/app/agents/agent_service.py` — AgentService CRUD and run creation helpers
- `core/backend/app/runs/run_service.py` — Run creation and listing
- `core/backend/app/runs/execution.py` — `RunExecutionService` (canonical orchestrator)
- `core/backend/app/runs/runtime_policy.py` — risk→sandbox mapping, file-access adapter validation
- `core/backend/app/runtimes/registry.py` — adapter registration
- `core/backend/app/runtimes/adapters/cli_runtime.py` — CLI bridge (CliRuntimeAdapter)
- `core/backend/app/cli_adapters/claude.py` — ClaudeCLIAdapter (subprocess wrapper)
- `core/backend/app/cli_adapters/codex.py` — CodexCLIAdapter (subprocess wrapper)
- `core/backend/app/cli_adapters/executors.py` — LocalExecutor, DockerExecutor
- `core/backend/app/agents/seeder.py` — built-in agent definitions

## Related Decisions

- [0002-agent-model.md](../decisions/0002-agent-model.md)
- [0004-context-wrapper.md](../decisions/0004-context-wrapper.md)

## Related Docs

- [runtime-adapters.md](runtime-adapters.md) — adapter registry, three-way separation, license notes
- [sandbox.md](sandbox.md) — sandbox levels, worktree vs Docker routing
- [provider-policy.md](provider-policy.md) — model provider configuration
