# ADR 0009 — Anthropic is CLI-only; No Direct Anthropic API Runtime Adapters

## Status

Accepted — 2026-05-20

## Context

During `runtime` branch cleanup, three Anthropic direct API code paths were found:

1. `agents/api_adapter.py` — `AnthropicAPIAdapter` reading `settings.anthropic_api_key` inline.
   Dead code (no live callers); violated the M4 credential boundary.
2. `app/runtimes/adapters/anthropic_messages.py` — a canonical `BaseRuntimeAdapter` subclass
   calling the Anthropic Messages API directly with a key from `Credential.secret_ref`.
3. `app/memory/reflector.py` — `reflector_mode=llm` importing the `anthropic` Python package
   and reading `settings.anthropic_api_key` directly (bypassing `Credential.secret_ref`).

All three conflicted with the product direction established in ADR 0008 (managed multi-CLI usage).
The goal of agent-space is to be the governance layer over CLI tools, not a model-provider gateway.

## Decision

**Anthropic/Claude execution must go through CLI integrations only.**

Specifically:
- `adapter_type=anthropic_api` — not a supported adapter type. Must not appear in `app.runtimes`.
- `adapter_type=anthropic_messages` — removed from `app.runtimes`. Deleted.
- `provider_type=anthropic` in `ModelProvider` — valid as metadata, but the reflector and any
  future service that calls an LLM must reject it with `unsupported_provider_for_reflector` or
  equivalent. Anthropic API calls go through `claude_code` / `claude_cli` CLI paths.
- `reflector_mode=llm` — must use a configured `ModelProvider` (OpenAI-compatible only) resolved
  through `Credential.secret_ref`. Config: `reflector_model_provider_id` + `reflector_model`.
  If no provider is configured, fails clearly with `reflector_model_provider_missing`.

## Consequences

### Files changed
- Deleted: `app/runtimes/adapters/anthropic_messages.py`
- Deleted: `app/agents/api_adapter.py` (already dead before this ADR)
- Removed: `anthropic_messages` from `runtimes/registry.py`, `execution_planes/service.py`,
  `schemas.py` (allowed_adapter_types), `runtimes/adapters/__init__.py`
- Removed: `anthropic_api` downgrade from `router/task_router.py`,
  plane mapping from `execution_planes/service.py`
- Added: `app/memory/provider_client.py` — reflector provider resolver + litellm dispatcher
- Added: `reflector_model_provider_id`, `reflector_model` to `app/config.py`

### Guard tests
- `tests/unit/test_anthropic_policy.py` — 13 tests; must never be weakened
- `tests/unit/test_reflector_model_provider.py` — 29 tests; source guards + integration

### Valid remaining ANTHROPIC_API_KEY references

| Location | Reason |
|---|---|
| `app/config.py` — `anthropic_api_key` field | CLI subprocess env passthrough only |
| `app/runtimes/credentials.py` — `_INLINE_SECRET_FIELDS` | Preventive guard; does not read the key |
| `app/runs/redaction.py` — redaction list | Prevents key from appearing in Run error fields |
| `app/cli_adapters/executors.py` — `DockerExecutor` env passthrough | CLI subprocess container auth |
| `app/workspace/sandbox_manager.py` — env passthrough | Same |
| `app/credentials/login.py`, `broker.py` | `claude_code` CLI login credential maps |
| `app/cli_adapters/claude.py` | CLI subprocess credential spec |
| `docs/`, `.agent/` env var tables | Documents required env vars for CLI adapters |

None of these are direct API runtime adapters.

### Future work

To gain Run observability for CLI-based Anthropic execution, the path is:

1. Create a `BaseRuntimeAdapter` wrapper in `runtimes/adapters/` that shells out to the
   `claude` CLI subprocess (reusing `ClaudeCLIAdapter` logic from `cli_adapters/claude.py`)
2. Read credentials through canonical `ctx.resolved_credentials` (CLI env passthrough stays
   confined to `app.cli_adapters`)
3. Register the wrapper in `runtimes/registry.py`

Do NOT add a `provider_type=anthropic` direct API path to `app.runtimes`.
