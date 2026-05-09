# Module: Agents

## Purpose
Define and execute AI agents. An agent is a configured product-level actor — separate from the human user who owns it and separate from the runtime adapter that executes it.

## Three-Way Separation

```
Agent            — product-level actor (owned by user/space/workspace, has policy)
    ↓ dispatches via
Runtime Adapter  — technical execution backend (echo, claude_cli, codex_cli, …)
    ↓ calls
Model Provider   — underlying LLM (Anthropic, OpenAI, Ollama, …)
```

See `runtime-adapters.md` for the full adapter registry and license notes.

## Owns
- `Agent` ORM model and CRUD
- `AgentRun` records (lifecycle, adapter dispatch, sandbox routing)
- Adapter implementations: `echo`, `claude_cli`, `codex_cli`
- Agent seeding (built-in system agents)
- Delegation chain tracking (parent_run_id, delegation_depth)

## Does Not Own
- Memory content (memory module)
- Policy decisions (policy module)
- Sandbox container lifecycle (workspace/sandbox_manager.py)
- Capability definitions (capability module)
- Provider credentials (env vars in config.py)

## Key Models

```
Agent:
  id, space_id, name, description
  owner_type (system|user|space|workspace), owner_id
  system_prompt, model_config_json
  memory_policy_json   — readable/writable scopes, requires_proposal
  capabilities_json    — list of capability IDs
  tool_permissions_json
  runtime_policy_json  — risk_level, can_delegate, max_depth, allowed_adapter_types
  status (active|inactive|archived)

AgentRun:
  id, task_id, space_id, workspace_id, user_id, agent_id
  adapter_type, prompt, context_snapshot
  status (pending|running|completed|failed)
  parent_run_id, delegation_depth
  sandbox_level, sandbox_path, executor_type   ← set after _resolve_adapter()
  output, error, exit_code, started_at, completed_at
```

## Main Flows

**Run flow:**
1. API → `AgentService` → creates `AgentRun` (pending)
2. FastAPI BackgroundTask → `execute_pending_run(run_id, …, risk_level)`
3. `_resolve_adapter()` — routes by risk_level: worktree+local subprocess (default, no new container), one_shot_docker (high/critical)
4. For worktree: `SandboxManager.create_worktree()` + `ContextCompiler` writes CLAUDE.md / AGENTS.md; CLI runs as backend subprocess
5. Adapter runs CLI → returns `AgentRunResult`
6. `AgentRun` updated with status, output, error, timing, sandbox metadata

**Delegation flow:**
- Agent A calls `AgentService.delegate()` → creates child `AgentRun` with `parent_run_id=A`
- `delegation_depth` incremented; max checked against `runtime_policy.max_delegation_depth`

## Built-in Agents
- `system.echo-agent` — deterministic test adapter, no LLM needed
- `system.memory-curator-agent` — reflects on sessions, proposes memory updates

## Adapter Registry
| Adapter      | Sandbox Level   | Notes                                    |
|--------------|-----------------|------------------------------------------|
| `echo`       | none            | Test/demo only; always available         |
| `claude_cli` | worktree (default) / one_shot_docker (high) | CLI installed in backend image; no new container at medium risk |
| `codex_cli`  | worktree (default) / one_shot_docker (high) | CLI installed in backend image; no new container at medium risk |

## Invariants
- `claude_cli` and `codex_cli` are always sandboxed (`_SANDBOXED_ADAPTERS`) — cannot be downgraded
- An agent can escalate `risk_level` via `runtime_policy_json.risk_level` but cannot exit `_SANDBOXED_ADAPTERS`
- An agent cannot exceed its declared `max_delegation_depth`
- `context_snapshot` stored at run creation — immutable after that
- No vendor adapter is the source of truth for memory, policy, or audit

## Related Files
- `core/backend/app/agents/runner.py` — AgentRunService, execute_pending_run, _resolve_adapter, _SANDBOXED_ADAPTERS
- `core/backend/app/agents/agent_service.py` — AgentService CRUD and delegation
- `core/backend/app/agents/claude_adapter.py` — ClaudeCLIAdapter
- `core/backend/app/agents/codex_adapter.py` — CodexCLIAdapter
- `core/backend/app/agents/cli_adapter.py` — LocalExecutor, DockerExecutor, EchoAgentAdapter
- `core/backend/app/agents/seeder.py` — built-in agent definitions
- `core/backend/app/workspace/sandbox_manager.py` — SandboxManager, SandboxContext

## Related Decisions
- [0002-agent-model.md](../decisions/0002-agent-model.md)
- [0004-context-wrapper.md](../decisions/0004-context-wrapper.md)

## Related Docs
- [runtime-adapters.md](runtime-adapters.md) — adapter registry, three-way separation, license notes
- [sandbox.md](sandbox.md) — sandbox levels, worktree vs Docker routing
- [provider-policy.md](provider-policy.md) — model provider configuration
