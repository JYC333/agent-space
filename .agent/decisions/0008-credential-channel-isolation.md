# ADR 0008 - Credential Channel Isolation

## Status

Accepted - 2026-06-02.

## Context

An earlier internal policy required all Anthropic/Claude execution to go through
`adapter_type=claude_code`, framed as "Anthropic is CLI-only." That framing was too
broad. The real concern was never to forbid the Anthropic API — it was to prevent a
specific operational failure: an Anthropic API key leaking into the environment of a
**Claude Code CLI** subprocess, which conflicts with Claude Code's own auth (OAuth /
login state) and causes environment-conflict bugs.

Two credential channels exist and are already architecturally separate:

- **CLI channel** — `claude_code` / `codex_cli` run as subprocesses. Their environment
  is rebuilt from an allowlist by `server/src/modules/runs/vendorCliAdapter.ts::buildSubprocessEnv`
  (only `PATH`, `TERM`, `SHELL`, `LANG`, `LC_*`, plus keys the `CredentialBroker`
  explicitly injects for a configured credential profile). Ambient `os.environ` is NOT
  inherited wholesale.
- **In-process API channel** — the provider command/runtime path
  (`server/src/modules/providers/` and managed API runtime adapters),
  `/api/v1/providers/chat`, and the `model_api` runtime adapter resolve the key
  from the encrypted `ModelProvider` Credential (`resolveProviderApiKey`) and pass it
  to litellm as a parameter. This channel never writes `os.environ`, so it is
  unreachable from any subprocess.

## Decision

The governing invariant is **credential channel isolation**, not "Anthropic is CLI-only":

> An Anthropic API key must never enter the environment of a Claude Code CLI subprocess.

Consequences of this reframing:

- The in-process encrypted API channel **may serve any provider, including Anthropic**,
  as long as the key is passed in-process (litellm parameter) and never written to
  `os.environ`.
- The reflector no longer rejects `provider_type=anthropic`.
- A generic, vendor-neutral `model_api` runtime adapter (native, no-tools, no-file
  sandbox, `credential_mode=model_provider_api_key`) is sanctioned and may select any
  configured `ModelProvider` + model, Anthropic included. It must obey the invariant:
  resolve via `resolveProviderApiKey`, pass as a litellm parameter, never via env.

## Invariants

- `claude_code` remains a `local_cli` `RuntimeAdapterSpec` using `cli_profile`
  credentials granted by `CredentialBroker`; it is the path for agentic / tool-using /
  filesystem Claude work.
- No ambient `ANTHROPIC_API_KEY` fallback for CLI runtime execution.
- `build_subprocess_env` allowlist is the enforcement point keeping CLI subprocess
  environments clean. Canonical runtime adapters must not read `ANTHROPIC_API_KEY` from
  ambient env/settings (guarded by provider/runtime adapter tests such as
  `server/test/runVendorCliAdapter.test.ts` and `server/test/providersCredentialsAuthority.test.ts`).
- The runtime adapter standard stays vendor-neutral; vendor CLI support is
  RuntimeAdapterSpec data, not Agent/provider foundation code.

## Consequences

The distinction is now by **execution shape**, not vendor: tool-using / filesystem /
agentic work uses a CLI runtime adapter; no-tools text generation for any provider uses
the in-process API channel (`model_api`). Anthropic is permitted on both,
subject to the isolation invariant.
