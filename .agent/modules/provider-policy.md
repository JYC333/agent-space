# Module: Provider Policy

## Current Approach (Personal/Family Use)

Provider configuration is database-backed and space-scoped through
`ModelProvider` rows. API keys are encrypted server-side into `Credential`
rows, linked by `model_providers.credential_id`, and exposed through APIs only as
`has_api_key`.

Runtime adapters never read provider keys from ambient environment variables.
Managed API runtimes resolve credentials through `server/src/modules/providers/`
after the `runtime.use_credential` policy gate passes. CLI runtimes use the CLI
CredentialBroker profile channel instead.

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
- Model endpoint proxy / gateway
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
2. Store API keys through the encrypted `Credential` + `ModelProvider`
   command store path; do not add ambient provider-key env vars.
3. Create or configure the runtime adapter to use the provider's SDK/CLI through
   the provider resolver or CLI CredentialBroker, depending on adapter type.
4. Document the provider in this file's risk table.
5. Note any license or terms-of-service constraint in `runtime-adapters.md`.

New managed API providers must be covered by provider-command-store tests and
runtime credential policy tests before they are considered wired.

## Related Files
- `server/src/config.ts` — provider/runtime config inputs
- `server/src/modules/workspaces/` — sandbox/workspace boundaries
- `server/src/modules/runs/` and `runtimeAdapters/` — runtime adapter implementations
- `.agent/modules/runtime-adapters.md` — adapter registry and license notes
