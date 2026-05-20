# Module: Runtime Adapters

## MVP Design Statement

**Agent-space focuses on managed multi-CLI usage, not direct multi-provider model orchestration.**

Users subscribe to multiple AI CLI tools. Each has its own monthly quota. Agent-space provides
one unified workspace to switch between CLI tools while maintaining shared context, run history,
artifacts, proposals, usage awareness, and sandbox governance.

Each CLI tool continues using its own account, model, and subscription. Agent-space is the
control layer, not the billing or routing layer.

See [ADR 0008](../decisions/0008-multi-cli-mvp.md) for the full rationale.

## Three-Way Separation

```
Agent            — product-level actor (space-scoped, policy-governed, memory-owning)
    ↓ dispatches via
Runtime Adapter  — CLI tool or execution backend (replaceable)
    ↓ optionally calls
Model Provider   — underlying LLM API (Anthropic, OpenAI, …) [future direct mode]
```

These are three distinct concerns. Mixing them (e.g. "Claude IS the agent") is a design error.
The agent-space core owns the Agent layer. CLI tools and providers are pluggable.

## Current Adapters

| Adapter ID    | Type        | Vendor file  | Status | Notes                                    |
|---------------|-------------|-------------|--------|------------------------------------------|
| `echo`        | local       | none         | active | Deterministic test adapter, no LLM       |
| `capability`  | local       | none         | active | Executes enabled local capability manifests |
| `claude_code` | CLI wrapper | `CLAUDE.md`  | active | Wraps `claude` CLI (Claude Code)         |
| `codex_cli`   | CLI wrapper | `AGENTS.md`  | active | Wraps `codex` CLI (OpenAI Codex CLI)     |

> Configs may still say `claude_cli`; the backend maps that id to the same adapter as `claude_code`. Prefer `claude_code` in new manifests.

## Planned / Future Adapters

| Adapter ID    | Notes                                                            |
|---------------|------------------------------------------------------------------|
| `opencode`    | Open-source, provider-agnostic; preferred future candidate       |
| `gemini_cli`  | Google Gemini CLI                                                |
| `custom`      | Custom executable or script                                      |

## Model Selection Modes

Runs carry a `model_selection_mode` field:

| Mode | Meaning | Status |
|---|---|---|
| `cli_default` | CLI uses its own configured model/account/subscription | Active |
| `cli_model_override` | Agent-space passes `--model` flag to the CLI | Future |
| `agent_space_provider` | Agent-space calls model API directly | Future |

Default is always `cli_default`.

## Backend Adapter Contract

Backend Run execution uses `app.runtimes`, not the older `app.agents.runner` registry. Product runtime adapters subclass `BaseRuntimeAdapter` in `core/backend/app/runtimes/base.py`, return `RuntimeAdapterResult`, and are registered in `core/backend/app/runtimes/registry.py`.

The `capability` adapter is a local runtime adapter. It resolves `Run.capability_id`, loads the installed manifest from builtin registry roots or explicitly configured local capability-library workspaces, checks the enabled flag and v1 permission guardrails, calls a local `python_module` entrypoint, and returns normalized `output_json` for the standard Run materializer. Remote repositories are future install sources, not runtime scan targets.

## Legacy Agent Adapter Contract

All adapters subclass `AgentAdapter` (`agents/base.py`) and implement:

```python
@property
def adapter_type(self) -> str: ...     # stable ID used in _ADAPTER_REGISTRY

def is_available(self) -> bool: ...    # check if CLI/SDK is installed

def run(self, prompt, context, workspace_path, timeout) -> RuntimeExecutionResult: ...

# Optional (have defaults in base class):
def detect(self) -> CLIStatus: ...              # probe version, executable path
def get_capabilities(self) -> CLIAdapterCapabilities: ...  # static capability flags
```

`detect()` and `get_capabilities()` drive the CLI Tool Status page.

## Context Compilation

The ContextCompiler is the source of truth. Vendor context files are generated
per run inside the sandbox directory — they are never written to the real workspace:

| CLI | Vendor file |
|---|---|
| Claude Code | `sandbox/CLAUDE.md` |
| Codex CLI | `sandbox/AGENTS.md` |
| OpenCode / custom | `sandbox/prompt.md` |

## Usage Tracking

Because monthly subscription CLIs don't expose token counts programmatically,
tracking uses an accuracy hierarchy:

| Accuracy | Source |
|---|---|
| `precise` | Provider API (future: agent_space_provider mode) |
| `estimated` | Parsed from CLI stdout |
| `unknown` | Runtime seconds + run count only (MVP default) |

The `Run` table carries `runtime_seconds`, `usage_accuracy`, `estimated_input_tokens`,
`estimated_output_tokens`. A `UsageEvent` table records per-run events.

## CLIAdapterConfig

A `cli_adapter_configs` table stores per-space CLI tool configurations:
- `adapter_id` — which CLI tool (claude_code, codex_cli, etc.)
- `quota_status` — manually set: enough / medium / low / exhausted / unknown
- `enabled` — whether this tool is available for new runs
- `executable_path` — optional custom path override

The frontend "CLI Tools" page shows the Monthly Quota Board and detection status.

## Sandbox Routing

See `sandbox.md`. Short version:
- `echo` — never sandboxed
- `claude_code`, `codex_cli` (and future coding runtimes) — always sandboxed
  - `medium` risk → git worktree + local subprocess (no new container)
  - `high`/`critical` risk → one-shot Docker container

## License & Compliance Notes

> These notes document known risks. They are NOT legal advice.

| Adapter       | License     | Commercial Use Risk |
|---------------|-------------|---------------------|
| `claude_code` | Proprietary | Claude Code terms do not explicitly permit embedding in a commercial product. Verify before shipping. |
| `codex_cli`   | Proprietary | OpenAI terms apply. May not be redistributable as part of a commercial product. Verify. |
| `opencode`    | Open source | Check specific license before commercial use. |
| `echo`        | Internal    | No risk — deterministic no-LLM test adapter. |

**Rule (B-RT-1):** No vendor CLI is the source of truth for memory, policy, permissions, or audit records.

**Rule (B-RT-2):** An enterprise deployment must be able to disable any individual runtime adapter
without breaking the core system (memory, wiki, cards, proposals, chat, activity capture).

## Adding a New Adapter

1. Subclass `AgentAdapter` in `core/backend/app/agents/<name>_adapter.py`
2. Implement `adapter_type`, `is_available()`, `run()`
3. Override `detect()` and `get_capabilities()` if the CLI supports version probing
4. Add to `_ADAPTER_REGISTRY` in `runner.py`
5. Add to `_SANDBOXED_ADAPTERS` if it executes agent-generated code
6. Add to `_BUILTIN_ADAPTERS` in `cli_adapters/service.py`
7. Update this doc's adapter table

## Related Files

- `core/backend/app/agents/base.py` — AgentAdapter, CLIStatus, CLIAdapterCapabilities
- `core/backend/app/agents/runner.py` — _ADAPTER_REGISTRY, _SANDBOXED_ADAPTERS, _resolve_adapter
- `core/backend/app/agents/claude_adapter.py` — ClaudeCLIAdapter
- `core/backend/app/agents/codex_adapter.py` — CodexCLIAdapter
- `core/backend/app/cli_adapters/` — CLIAdapterConfig CRUD and detection API
- `core/backend/app/memory/context_compiler.py` — ContextCompiler (writes CLAUDE.md, AGENTS.md)
- `.agent/decisions/0008-multi-cli-mvp.md` — ADR for this design
