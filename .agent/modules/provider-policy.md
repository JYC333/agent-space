# Module: Provider Policy

## Current Approach (Personal/Family Use)

Provider configuration is simple: environment variables per deployment instance.

```env
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
DEFAULT_MODEL=claude-sonnet-4-6
```

The backend forwards only the relevant key(s) to the sandbox container. Keys are never logged or stored in the database.

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

These are deferred until commercial need. The env-var approach is sufficient for personal use.

## Provider Risks to Document

| Provider | Risk |
|---|---|
| Anthropic (Claude) | Data sent to Anthropic servers; not for private/sensitive enterprise data without a data processing agreement |
| OpenAI (Codex) | Same; OpenAI API terms apply |
| Any cloud LLM | Prompts include context_snapshot (memory + workspace). Review what goes in context before using a third-party provider |
| Ollama / local | No external data transmission; safe for private data |

## When Adding a New Provider

1. Add the API key env var to `config.py` (forwarded to sandbox containers in `sandbox_manager.py`)
2. Create or configure the runtime adapter to use the provider's SDK/CLI
3. Document the provider in this file's risk table
4. Note any license or terms-of-service constraint in `runtime-adapters.md`

No other changes needed for the current personal-use deployment model.

## Related Files
- `core/backend/app/config.py` — `anthropic_api_key`, `default_model`
- `core/backend/app/workspace/sandbox_manager.py` — env forwarding to Docker containers
- `core/backend/app/agents/` — runtime adapter implementations
- `.agent/modules/runtime-adapters.md` — adapter registry and license notes
