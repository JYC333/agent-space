# Multi-Agent Runtime Strategy

## Core principle: kernel is source of truth

The agent kernel — server agents + `RunOrchestrationService` — owns all agent state:
identity, memory policy, delegation rules, run logs, and context assembly.
Adapters are thin execution wrappers. They receive a pre-built prompt + context
snapshot and return a result. They own nothing.

```
User / Agent
    │
    ▼
Agent run creation / delegation
    ├── validates status, adapter whitelist, delegation policy
    ├── ContextBuilder.build()  ← memory policy scoping
    │
    ▼
RunOrchestrationService execution
    ├── writes Run record (status=running)
    ├── gets adapter from _ADAPTER_REGISTRY
    │
    ▼
AgentAdapter.run(prompt, context_snapshot, ...)
    │   (pure execution — no DB access, no memory writes)
    ▼
RuntimeExecutionResult
    │
    ▼
Run record updated (status, output, error, completed_at)
```

## Adapter boundary

An `AgentAdapter` is a runtime execution backend, not an agent configuration.
The same agent record can use different adapters on different runs, subject to
`runtime_policy_json.allowed_adapter_types`.

**Built-in adapters**

| adapter_type | Backend | Notes |
|---|---|---|
| `capability` | Local capability execution | Deterministic when the selected capability is deterministic; no provider credentials |
| `model_api` | Managed API runtime | Uses encrypted ModelProvider credentials |
| `claude_code` | Claude Code CLI subprocess | Requires active `claude_code` runtime tool |
| `codex_cli` | OpenAI Codex CLI subprocess | Requires active `codex_cli` runtime tool |

**Wiring in an external framework**

External frameworks (OpenAI Agents SDK, LangGraph, CrewAI, Letta, etc.) can be
added as adapters without touching the kernel:

```ts
// server/src/modules/runtimeAdapters/specs.ts
my_framework: {
  adapter_type: "custom",
  display_name: "My Framework",
  runtime_kind: "custom",
  implementation_status: "planned",
  enabled_by_default: false,
  // Add invocation, credential, sandbox, model, usage, and output policy
  // before this becomes executable.
}
```

Then add the corresponding server runtime execution implementation and tests before
marking the adapter `implemented`.

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

## Built-in system templates (no built-in concrete agents)

There are **no** seeded built-in concrete agents. The old seeded concrete agents
and the old concrete agent seeder were removed. Built-in product
behavior comes from system **AgentTemplates** — reusable factories, never runtime
objects — seeded once globally by the server agents module. A concrete `Agent`
is created on demand via `AgentTemplateService.create_agent_from_template`
(copy-on-create); runtime always loads config from the resulting `AgentVersion`,
never from a template.

Output policy uses **`allowed_output_types`** (a ceiling), with
`classification_mode: model_selects` (the model picks which output type(s) to emit inside
the set), `allow_multiple_outputs_per_run` / `allow_multiple_outputs_per_activity`,
`required_run_outputs`, and per-type `default_review_mode`. Durable changes are proposal-only.
Context policy uses product-level `allowed_input_contexts` (ceiling) + `default_input_contexts`.

The initial seeded catalog is five **public** specialized factories plus the `personal_assistant`
**internal seed spec**. **There is no `general_chat` template** and no DirectChat — a generic
session-only chat object would be a naked DirectChat with no space awareness. Chat in this system
is the per-space **system-managed default Assistant Agent** instead.

### personal_assistant (assistant — internal seed spec, `visibility=system_internal`)

- NOT a normal reusable template: hidden from the public Template Library and not user-instantiable
  via create-from-template (so users cannot create duplicate Assistants).
- Provenance seed spec for each space's **system-managed default Assistant** (the Chat identity):
  `agent_kind="system_assistant"`, system/space-owned (`owner_user_id` NULL), named *Personal
  Assistant* in personal spaces / *Space Assistant* in shared ones, with at most one active per
  space (DB partial-unique index + resolve-before-create).
- Selects relevant context per run via `ContextBuilder` (no new `AgentVersion` needed for per-run
  context selection; per-run toggles live in session/run context state, not `AgentVersion`).
- Outputs: `chat_message` plus proposal-only `task_create` / `idea_create` / `memory_update` /
  `knowledge_item` proposals; no shell / file write / workspace write / credential access / direct
  memory write.
- Resolved/created per space via the server agents module
  (`get_default_assistant` / `get_or_create_default_assistant`;
  `GET`/`POST /api/v1/agents/default-assistant`) — an ordinary copy-on-create Agent at runtime.
- Soft preferences (response style, verbosity, default context toggles, default project, proposal
  style, model preferences) live in `space_assistant_settings`
  (`GET`/`PATCH /api/v1/agents/default-assistant/settings`) and never edit the core prompt or any
  hard policy.

### activity_reflector (reflection)

- Model-only; processes raw captures / activity records into typed outputs
- Outputs: task / idea / memory / knowledge proposals, `reflection_summary_artifact`,
  `archive_suggestion`; model classifies each activity into a primary output type
- Long-term changes are proposal-only; daily schedule defined but disabled (manual runs allowed)

### memory_reflector (memory)

- Model-only memory reflection over selected activities/conversations + approved memory
- Outputs: `memory_update` / `memory_merge` / `memory_delete` proposals (plus `noop`);
  never writes, merges, or deletes memory directly

### knowledge_curator (knowledge)

- Organizes Knowledge items, relations, and source links
- Proposes the appropriate semantic KnowledgeItem type (experience / reflection / lesson /
  procedure / decision / question / summary / generic), plus relations and source links
- A source is **not** a KnowledgeItem type; an answer is represented as a **relation**

### research_reader (research)

- Reads only user-selected sources — **no web search and no arbitrary crawling** by default
- Outputs: `source_summary_artifact`, summaries, questions, knowledge proposals, source links

### coding_reviewer (workspace)

- Read-only workspace review (files, git diff, docs, run artifacts)
- Outputs: `review_report_artifact`, `architecture_risk_summary`, `code_change_suggestion`,
  `task_create_proposal` — **no code patch, no file write, no shell, no patch apply**
- This is review only; a code-writing `coding_task_agent` is future scope

Memory reflection itself is exposed as an **internal service**
(the memory consolidation/reflection path via the `memory.reflect` capability,
`POST /sessions/{id}/reflect`) — it does not run through a built-in agent. The
`memory_reflector` template is the factory for a standalone reflection Agent instance.

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
proposal review: propose → user reviews → accept/reject.

## Design constraints

1. Never import agents module internals or DB models inside an adapter — adapters are stateless.
2. Never call adapters outside of `RunOrchestrationService` — the run record must exist before execution.
3. `delegation_depth` is set by the kernel, not the adapter.
4. An agent's `space_id` never changes after creation. Cross-space delegation is not supported.
