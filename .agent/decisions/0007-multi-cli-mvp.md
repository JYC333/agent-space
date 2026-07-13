# ADR 0007 - Managed Multi-CLI Runtime Usage

## Status

Accepted — 2026-05-06

## Context

Agent-space is the governance and context layer for users who work across
multiple AI/agent CLI tools.

- Users subscribe to multiple AI/agent CLI tools (Claude Code, Codex CLI, OpenCode, Gemini CLI, etc.).
- Each subscription has a monthly quota that may run out before month end.
- The user wants one unified workspace to switch between CLI tools without losing workspace context, run history, artifacts, proposals, or approval flows.
- Each CLI tool continues using its own account, model selection, and subscription.
- Agent-space is not a model-provider router.

## Decision

Agent-space focuses on managed multi-CLI runtime usage, not direct
multi-provider model orchestration.

## Architecture

```
AgentSpace Core
├── WorkspaceManager      - workspace isolation and path policy
├── SandboxManager        - worktree execution environments
├── ContextCompiler       - compiles unified context into vendor-specific files
├── RuntimeAdapterSpecCatalog — which runtime adapters exist and how they behave
├── RunManager            - orchestrates run lifecycle + delegation chain
├── UsageTracker          - fallback/cached runtime usage
├── ArtifactStore         - diffs, logs, validation results
└── ProposalSystem        - human-in-the-loop approval for agent changes
```

Runtime Adapters are adapters to the core, not the foundation.

## Three-Layer Separation

| Layer | What it is | Examples |
|---|---|---|
| Agent (product layer) | Configured actor with policy, memory, delegation rules | system.coding-agent |
| Runtime Adapter | Execution backend selected for a run | claude_code, codex_cli, capability, model_api |
| Model Provider | LLM API (future optional) | Anthropic, OpenAI, Google |

## Model Selection Modes

Runs carry a `model_selection_mode` field:

| Mode | Meaning | When |
|---|---|---|
| `cli_default` | CLI uses its own configured model/account | default |
| `cli_model_override` | Agent-space passes a model flag to the CLI | only when the spec supports it |
| `agent_space_provider` | Agent-space calls model API directly | Future |

The default is `cli_default`.

## RuntimeAdapterSpec And RuntimeAdapter

`RuntimeAdapterSpec` is the source of truth for adapter behavior. Per-space
`RuntimeAdapter` rows store configuration such as enabled state, executable
override, credential profile id, and health/usage status. There is no separate
configured-adapter product model.

Implemented local CLI specs execute through `GenericCliRuntimeAdapter`.
The native adapter is `capability`.

## Usage Tracking

Usage tracking uses an accuracy hierarchy:

1. `precise` — provider API returns token counts (future: agent_space_provider mode)
2. `estimated` — CLI output contains parseable usage lines
3. `unknown` — runtime seconds + run count only

The `Run` table carries `runtime_seconds`, `usage_accuracy`, `estimated_input_tokens`, `estimated_output_tokens`.

Runtime adapter rows also carry `quota_status` as a separate manual/cached
status. It is not overloaded into `health_status`.

Claude Code quota is cached-only in this build; no live quota probe is
implemented.

## Context Compilation

The ContextCompiler remains the source of truth. Vendor context files are generated per run inside the sandbox directory:

| CLI | Vendor file |
|---|---|
| Claude Code | `sandbox/CLAUDE.md` |
| Codex CLI | `sandbox/AGENTS.md` |
| OpenCode / custom | `sandbox/prompt.md` |

Vendor files are never the source of truth and are never written to the real workspace.

## Consequences

- Users can switch CLI tools on a per-run basis without losing context.
- Quota awareness is manual but practical (no API access to subscription data needed).
- Precise token accounting is not available for subscription CLI runtimes.
- `one_shot_docker` was not implemented in the original C1 MVP. C3 now provides
  the executor path; it remains deny-by-default (`--network none`) and
  fail-closed when Docker/image/path prerequisites are unavailable.
- Adding a new CLI adapter should usually mean adding a RuntimeAdapterSpec, not
  a new runtime class.
