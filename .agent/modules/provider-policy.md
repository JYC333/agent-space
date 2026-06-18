# Module: Provider Policy

## Current Approach (Personal/Family Use)

Provider configuration is database-backed and user-owned through
`ModelProvider` rows. API keys are encrypted server-side into user-owned
`Credential` rows, linked by `model_providers.credential_id`, and exposed
through APIs only as `has_api_key`.

Provider use in a space is explicit through `model_provider_space_grants`.
Creating a provider auto-grants it to the active space. Granting a provider to
another space lets eligible members of that space use it in runs, but only the
provider owner can edit provider metadata or replace secret material. Active
space default selection and provider `network_profile_id` are grant-level
fields.

`model_providers.base_url` is required and represents the Provider's managed API
endpoint for server-side model calls. Provider records may additionally carry CLI bridge endpoints in
`config_json`: `claude_compatible_base_url` for Anthropic-compatible Claude CLI
overrides and `openai_compatible_base_url` for OpenAI Responses-compatible Codex
CLI overrides.

Runtime adapters never read provider keys from ambient environment variables.
Managed API runtimes resolve credentials through `server/src/modules/providers/`
after the `runtime.use_credential` policy gate passes. CLI runtimes use the CLI
CredentialBroker profile channel instead.

Claude Code can optionally bind to a configured ModelProvider for
Claude-compatible endpoints. The Provider row remains the source of truth:
`config_json.claude_compatible_base_url` stores the Anthropic-compatible base
URL, and `default_model` / `available_models` store model choices. The server
creates a short-lived per-run provider proxy lease and renders only that lease
into the Claude CLI subprocess environment (`ANTHROPIC_BASE_URL`,
`ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_MODEL`,
`ANTHROPIC_DEFAULT_SONNET_MODEL`, `ANTHROPIC_DEFAULT_OPUS_MODEL`,
and `ANTHROPIC_DEFAULT_HAIKU_MODEL`) only for that run. If no provider is
selected for Claude Code, the server does not set `ANTHROPIC_BASE_URL`; Claude
Code uses its normal default endpoint/login state. Provider API keys are never
released to CLI subprocess environment variables; the provider proxy resolves
the real key server-side and forwards requests to the configured compatible URL
using the selected provider grant's NetworkProfile.

Codex CLI can optionally bind to a configured ModelProvider for OpenAI
Responses-compatible endpoints. The Provider row remains the source of truth:
`config_json.openai_compatible_base_url` stores the OpenAI-compatible base URL,
and `default_model` / `available_models` store model choices. The server creates
a short-lived per-run provider proxy lease, materializes the run's temporary
`CODEX_HOME` directory from the managed Codex profile, and writes a run-scoped
`config.toml` plus `model-catalogs/agent-space-provider.json` there. The
generated Codex config points at the local provider proxy with
`wire_api = "responses"` and stores only the lease token as
`experimental_bearer_token`. If no provider is selected for Codex CLI, the
server still sets `CODEX_HOME` to the run's temporary Codex profile path but
does not write a provider override; Codex uses its normal CLI login/config
state and the selected CLI credential profile's NetworkProfile, if configured.

NetworkProfiles are space-scoped reusable routing profiles. They support
`direct` and `http_proxy` modes. HTTP proxy URLs are not credential carriers;
proxy URLs with embedded usernames or passwords are rejected. `NO_PROXY` values
are applied to both server-side provider fetches and CLI subprocess proxy env.

## Per-Space Model Config (Lightweight Future-Proofing)

Agent records carry `model_config_json` — the model used for a specific agent can differ from the system default:

```json
{
  "model": "claude-opus-4-7",
  "max_tokens": 8192
}
```

This is the only per-agent provider customization implemented now. It covers the personal/family use case (e.g. use a cheaper model for routine tasks).

## What We Have NOT Built

- Per-space API key management UI (enterprise BYO keys)
- Provider routing table (route space A to Anthropic, space B to Azure OpenAI)
- Provider health dashboard
- Cost tracking / token usage metering
- On-premise LLM endpoint configuration UI

These are deferred until commercial need. The current provider store is enough
for personal/family use because keys are encrypted, space-owned, policy-gated,
and not injected as broad process environment.

## Provider Risks to Document

| Provider | Risk |
|---|---|
| Anthropic (Claude) | Data sent to Anthropic servers; not for private/sensitive enterprise data without a data processing agreement |
| OpenAI (Codex) | Same; OpenAI API terms apply |
| Any cloud LLM | Prompts include context_snapshot (memory + workspace). Review what goes in context before using a third-party provider |
| Ollama / local | No external data transmission; safe for private data |

## When Adding a New Provider

1. Add provider metadata and validation in `server/src/modules/providers/`.
2. Store API keys through the encrypted user-owned `Credential` + `ModelProvider`
   command store path; do not add ambient provider-key env vars.
3. Choose the active grant's `network_profile_id` when the provider needs proxy
   routing; use direct routing for local or internal providers.
4. Create or configure the runtime adapter to use the provider's SDK/CLI through
   the provider resolver or CLI CredentialBroker, depending on adapter type.
5. Document the provider in this file's risk table.
6. Note any license or terms-of-service constraint in `runtime-adapters.md`.

New managed API providers must be covered by provider-command-store tests and
runtime credential policy tests before they are considered wired.

## Related Files
- `server/src/config.ts` — provider/runtime config inputs
- `server/src/modules/workspaces/` — sandbox/workspace boundaries
- `server/src/modules/runs/` and `runtimeAdapters/` — runtime adapter implementations
- `.agent/modules/runtime-adapters.md` — adapter registry and license notes
