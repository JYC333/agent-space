# Multi-Agent Runtime Strategy

## Core principle: kernel is source of truth

The agent kernel — `AgentService` + `AgentRunService` — owns all agent state:
identity, memory policy, delegation rules, run logs, and context assembly.
Adapters are thin execution wrappers. They receive a pre-built prompt + context
snapshot and return a result. They own nothing.

```
User / Agent
    │
    ▼
AgentService.run() / .delegate()
    ├── validates status, adapter whitelist, delegation policy
    ├── ContextBuilder.build()  ← memory policy scoping
    │
    ▼
AgentRunService.run()
    ├── writes AgentRun record (status=running)
    ├── gets adapter from _ADAPTER_REGISTRY
    │
    ▼
AgentAdapter.run(prompt, context_snapshot, ...)
    │   (pure execution — no DB access, no memory writes)
    ▼
AgentRunResult
    │
    ▼
AgentRun record updated (status, output, error, completed_at)
```

## Adapter boundary

An `AgentAdapter` is a runtime execution backend, not an agent configuration.
The same agent record can use different adapters on different runs, subject to
`runtime_policy_json.allowed_adapter_types`.

**Built-in adapters**

| adapter_type | Backend | Notes |
|---|---|---|
| `echo` | In-process string echo | Deterministic; no external deps |
| `claude_cli` | Claude Code CLI subprocess | Requires `claude` binary |
| `codex_cli` | OpenAI Codex CLI subprocess | Requires `codex` binary |

**Wiring in an external framework**

External frameworks (OpenAI Agents SDK, LangGraph, CrewAI, Letta, etc.) can be
added as adapters without touching the kernel:

```python
# core/backend/app/agents/my_framework_adapter.py
from .base import AgentAdapter, AgentRunResult

class MyFrameworkAdapter(AgentAdapter):
    adapter_type = "my_framework"

    def is_available(self) -> bool:
        try:
            import my_framework
            return True
        except ImportError:
            return False

    def run(self, prompt, context, workspace_path=None, timeout=300) -> AgentRunResult:
        # call my_framework here
        ...
```

Then register it in `runner.py`:

```python
_ADAPTER_REGISTRY["my_framework"] = MyFrameworkAdapter
```

No other files change.

## Multi-agent delegation

Agents can spawn child agents through the delegation API. The kernel enforces:

- **`can_delegate`** — must be `true` in the parent agent's `runtime_policy_json`
- **`max_delegation_depth`** — `delegation_depth` on the child = parent + 1; rejected if it would exceed the limit
- **Space isolation** — all runs in a delegation chain share the same `space_id`

```
User instructs Agent A (depth=0)
    Agent A delegates to Agent B (depth=1)
        Agent B delegates to Agent C (depth=2)
            ...
            ← rejected if depth > max_delegation_depth of delegating agent
```

Delegation chain is queryable via `GET /api/v1/agents/runs/{run_id}/chain`.

## Built-in system agents

Two agents are seeded at startup by `agents/seeder.py`:

### echo-agent (`system.echo-agent`)

- **Capability**: `agent.echo`
- **Adapter**: `echo` only
- **Memory**: read `system` + `user` scopes (no writes)
- **Delegation**: disabled (`can_delegate: false`)
- **Purpose**: smoke-testing, capability demos, integration tests

### memory-curator-agent (`system.memory-curator-agent`)

- **Capability**: `memory.reflect`
- **Adapters**: `echo`, `claude_cli`
- **Memory**: read `system` + `user`; write `user` via proposal (never direct)
- **Delegation**: disabled
- **Purpose**: session reflection → memory proposals for user approval

## Memory policy enforcement

Every agent has a `memory_policy_json` that restricts what the `ContextBuilder`
fetches before injecting context into the run:

```json
{
  "readable_scopes": ["system", "user"],
  "writable_scopes": ["agent"],
  "readable_types": ["preference", "semantic"],
  "requires_proposal": false
}
```

`ContextBuilder.build()` silently drops any scope not in `readable_scopes`.
This means a restricted agent literally cannot receive out-of-policy memory —
no separate permission check layer is needed.

Agents **never write memory directly**. All writes go through
`MemoryProposalService`: propose → user reviews → accept/reject.

## Design constraints

1. Never import `AgentService` or DB models inside an adapter — adapters are stateless.
2. Never call adapters outside of `AgentRunService.run()` — the run record must exist before execution.
3. `delegation_depth` is set by the kernel, not the adapter.
4. An agent's `space_id` never changes after creation. Cross-space delegation is not supported.
