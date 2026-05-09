# ADR 0008 — Managed Multi-CLI Usage as MVP Focus

## Status

Accepted — 2026-05-06

## Context

The original system contained a `model_config_json` field on the `Agent` model and `DEFAULT_MODEL_CONFIG` in schemas, implying that agent-space would act as a direct model-provider API gateway in the first phase. This is incorrect for the personal/family-first use case.

The actual motivation:

- Users subscribe to multiple AI/agent CLI tools (Claude Code, Codex CLI, OpenCode, Gemini CLI, etc.).
- Each subscription has a monthly quota that may run out before month end.
- The user wants one unified workspace to switch between CLI tools without losing workspace context, run history, artifacts, proposals, or approval flows.
- Each CLI tool continues using its own account, model selection, and subscription.
- Agent-space is the governance and context layer, not a model-provider router.

## Decision

**Agent-space MVP focuses on managed multi-CLI usage, not direct multi-provider model orchestration.**

### Architecture

```
AgentSpace Core
├── WorkspaceManager      — workspace isolation and path policy
├── SandboxManager        — worktree / Docker execution environments
├── ContextCompiler       — compiles unified context into vendor-specific files
├── CLIAdapterRegistry    — which CLIs are installed, enabled, and available
├── RunManager            — orchestrates run lifecycle + delegation chain
├── UsageTracker          — approximate usage per run (accuracy-first)
├── ArtifactStore         — diffs, logs, validation results
└── ProposalSystem        — human-in-the-loop approval for agent changes
```

CLI Tools are adapters to the core, not the foundation.

### Three-layer separation (preserved)

| Layer | What it is | Examples |
|---|---|---|
| Agent (product layer) | Configured actor with policy, memory, delegation rules | system.coding-agent |
| Runtime Adapter | CLI tool that executes the task | claude_code, codex_cli, opencode |
| Model Provider | LLM API (future optional) | Anthropic, OpenAI, Google |

### Model selection modes

Runs carry a `model_selection_mode` field:

| Mode | Meaning | Phase |
|---|---|---|
| `cli_default` | CLI uses its own configured model/account | **MVP** |
| `cli_model_override` | Agent-space passes `--model` flag to the CLI | Future (CLI must support it) |
| `agent_space_provider` | Agent-space calls model API directly | Future (Phase 2+) |

The default is `cli_default` for all MVP runs.

### CLIAdapterConfig

A new per-space table (`cli_adapter_configs`) stores:
- Which CLI tools the user has configured for this space
- Manual quota status (enough / medium / low / exhausted / unknown)
- Optional custom executable path
- Enabled/disabled flag

This is the source of truth for the "Monthly Quota Board" UI.

### Usage tracking (accuracy-first)

Because monthly subscription CLIs do not expose token counts programmatically, usage tracking uses an accuracy hierarchy:

1. `precise` — provider API returns token counts (future: agent_space_provider mode)
2. `estimated` — CLI output contains parseable usage lines
3. `unknown` — runtime seconds + run count only (default for MVP)

The `AgentRun` table carries `runtime_seconds`, `usage_accuracy`, `estimated_input_tokens`, `estimated_output_tokens`.

A separate `UsageEvent` table records per-run events for quota dashboards.

### Context compilation

The ContextCompiler remains the source of truth. Vendor context files are generated per run inside the sandbox directory:

| CLI | Vendor file |
|---|---|
| Claude Code | `sandbox/CLAUDE.md` |
| Codex CLI | `sandbox/AGENTS.md` |
| OpenCode / custom | `sandbox/prompt.md` |

Vendor files are never the source of truth and are never written to the real workspace.

## Consequences

**Positive:**
- The personal/family MVP does not require building a model-provider billing gateway.
- Users can switch CLI tools on a per-run basis without losing context.
- Quota awareness is manual but practical (no API access to subscription data needed).
- Architecture stays clean for future Phase 2 where agent_space_provider mode adds direct API calls.

**Negative:**
- Precise token accounting is not available in Phase 1.
- The `model_config_json` field on the `Agent` model is now forward-looking (used in cli_model_override and agent_space_provider modes only).

## Out of scope (deferred to Phase 2+)

- Full ModelProviderRegistry
- Provider billing / cost accounting
- Automatic reading of subscription quota from vendors
- Complex model router
- Enterprise billing and multi-tenant SaaS admin
- Tool recommendation engine (basic heuristics only, optional)
