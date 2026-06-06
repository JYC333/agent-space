# ADR 0010 - Credential Channel Isolation (supersedes 0009)

## Status

Accepted - 2026-06-02. Supersedes ADR 0009 (Anthropic Is CLI-Only).

## Context

ADR 0009 stated "Anthropic/Claude execution must use `adapter_type=claude_code`" and
was widely read as "Anthropic may only be used via the CLI." That framing was too
broad. The real concern was never to forbid the Anthropic API — it was to prevent a
specific operational failure: an Anthropic API key leaking into the environment of a
**Claude Code CLI** subprocess, which conflicts with Claude Code's own auth (OAuth /
login state) and causes environment-conflict bugs.

Two credential channels exist and are already architecturally separate:

- **CLI channel** — `claude_code` / `codex_cli` run as subprocesses. Their environment
  is rebuilt from an allowlist by `runtimes/local_executor.py::build_subprocess_env`
  (only `PATH`, `TERM`, `SHELL`, `LANG`, `LC_*`, plus keys the `CredentialBroker`
  explicitly injects for a configured credential profile). Ambient `os.environ` is NOT
  inherited wholesale.
- **In-process API channel** — the reflector (`memory/provider_client.py`),
  `/api/v1/providers/chat`, and any future `model_api` runtime adapter resolve the key
  from the encrypted `ModelProvider` Credential (`resolve_provider_api_key`) and pass it
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
  resolve via `resolve_provider_api_key`, pass as a litellm parameter, never via env.

## Retained invariants (unchanged from 0009)

- `claude_code` remains a `local_cli` `RuntimeAdapterSpec` using `cli_profile`
  credentials granted by `CredentialBroker`; it is the path for agentic / tool-using /
  filesystem Claude work.
- No ambient `ANTHROPIC_API_KEY` fallback for CLI runtime execution.
- `build_subprocess_env` allowlist is the enforcement point keeping CLI subprocess
  environments clean. Canonical runtime adapters must not read `ANTHROPIC_API_KEY` from
  ambient env/settings (guarded by `tests/unit/test_anthropic_policy.py`).
- The runtime adapter standard stays vendor-neutral; vendor CLI support is
  RuntimeAdapterSpec data, not Agent/provider foundation code.

## Consequences

The distinction is now by **execution shape**, not vendor: tool-using / filesystem /
agentic work uses a CLI runtime adapter; no-tools text generation for any provider uses
the in-process API channel (`model_api` when built). Anthropic is permitted on both,
subject to the isolation invariant.
