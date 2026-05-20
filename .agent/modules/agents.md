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
  role_instruction          — system prompt text
  current_version_id        — convenience pointer to latest AgentVersion
  status (active|inactive|archived)

AgentVersion:
  id, agent_id, space_id
  version                   — immutable label, e.g. "v1", "v2"
  model_provider_id           — FK to ModelProvider (LLM backend for this version)
  model_name                  — model id string for the selected provider
  model_config_json         — {model, temperature, max_tokens, ...}
  runtime_config_json       — {risk_level, can_delegate, max_delegation_depth, max_run_time_seconds}
  context_policy_json       — {readable_scopes, writable_scopes}
  memory_policy_json        — {readable_scopes, writable_scopes, requires_proposal}
  capabilities_json         — list of capability IDs
  tool_permissions_json     — {allowed_tools, allowed_adapter_types}
  runtime_policy_json       — {sandbox_required, allowed_adapter_types}
  created_at
  Note: AgentVersion is append-only. Agent.current_version_id is updated on save.
        Existing runs keep their agent_version_id and remain reproducible.

Run:
  id, space_id, agent_id, agent_version_id
  status (queued|running|succeeded|failed|cancelled|degraded|waiting_for_review)
  mode (live|dry_run)
  parent_run_id, delegation_depth, instructed_by_agent_id
  prompt, instruction, output_json, error_json, sandbox metadata fields
```

## Main Flows

**Queued run creation**

1. HTTP (`POST /agents/{id}/runs`, task board endpoints, or agent helpers) → `RunService.create_run`
2. Worker picks up `agent_run` jobs → `RunExecutionService` selects adapters from policy
3. Adapters execute with sandbox routing managed outside `AgentService`

**Delegation**

- `AgentService.delegate()` creates a child `Run` with `parent_run_id` populated
- `delegation_depth` increments; max checked against `runtime_policy.max_delegation_depth`

## Built-in Agents

- `system.echo-agent` — deterministic test adapter, no LLM needed
- `system.memory-curator-agent` — reflects on sessions, proposes memory updates

## Adapter Registry

| Adapter       | Sandbox Level                     | Notes                                                    |
|---------------|-----------------------------------|----------------------------------------------------------|
| `echo`        | none                              | Test/demo only; always available                         |
| `claude_code` | worktree (default) / one_shot_docker (high) | CLI installed in backend image; no new container at medium risk |
| `codex_cli`   | worktree (default) / one_shot_docker (high) | CLI installed in backend image; no new container at medium risk |

## Invariants

- `claude_code` and `codex_cli` stay in the sandboxed adapter set — cannot be downgraded to host execution
- Agents cannot exceed declared `max_delegation_depth`
- Context snapshots captured at run creation stay immutable
- No vendor adapter is the source of truth for memory, policy, or audit
- `agent_version_id` on `Run` is immutable per row — historical runs stay reproducible after edits to `Agent`
- `AgentVersion` is append-only — prior rows are not rewritten in place

## Related Files

- `core/backend/app/agents/runner.py` — adapter registry + post-run hooks
- `core/backend/app/agents/agent_service.py` — AgentService CRUD and delegation helpers
- `core/backend/app/runs/run_service.py` — Run creation and listing
- `core/backend/app/runs/execution.py` — `RunExecutionService`
- `core/backend/app/jobs/handlers.py` — `agent_run` queue handler
- `core/backend/app/agents/claude_adapter.py` — ClaudeCLIAdapter
- `core/backend/app/agents/codex_adapter.py` — CodexCLIAdapter
- `core/backend/app/agents/cli_adapter.py` — EchoAgentAdapter + executors
- `core/backend/app/agents/seeder.py` — built-in agent definitions
- `core/backend/app/workspace/sandbox_manager.py` — SandboxManager, SandboxContext

## Related Decisions

- [0002-agent-model.md](../decisions/0002-agent-model.md)
- [0004-context-wrapper.md](../decisions/0004-context-wrapper.md)

## Related Docs

- [runtime-adapters.md](runtime-adapters.md) — adapter registry, three-way separation, license notes
- [sandbox.md](sandbox.md) — sandbox levels, worktree vs Docker routing
- [provider-policy.md](provider-policy.md) — model provider configuration
