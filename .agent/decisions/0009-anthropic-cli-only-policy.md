# ADR 0009 - Anthropic Is CLI-Only

## Status

**Superseded by [ADR 0010 - Credential Channel Isolation](0010-credential-channel-isolation.md) (2026-06-02).**

Accepted - 2026-05-20

> **Why superseded:** The "Anthropic is CLI-only" framing was too broad. The real
> requirement was credential *channel isolation* — keeping an Anthropic API key out of
> the Claude Code CLI subprocess environment — not forbidding the Anthropic API. ADR 0010
> restates the invariant correctly and permits the in-process encrypted API channel
> (reflector, `/providers/chat`, the future `model_api` adapter) to serve any provider,
> Anthropic included. The retained invariants below (CLI subprocess env hygiene, no
> ambient key fallback, vendor-neutral runtime standard) remain in force under 0010.

## Context

Agent-space is the governance layer over runs, context, policy, credentials,
worktrees, artifacts, proposals, and audit records. It is not the foundation for
vendor execution logic.

For Anthropic/Claude, the supported product path is Claude Code as a runtime
adapter.

## Decision

Anthropic/Claude execution must use `adapter_type=claude_code`.

`claude_code` is represented by:

- a `RuntimeAdapterSpec` entry with `runtime_kind=local_cli`
- a space-local `RuntimeAdapter` row when configured
- explicit `credential_profile_id` binding for CLI login state
- `GenericCliRuntimeAdapter` for command rendering, credential grants, context
  rendering, subprocess execution, output parsing, and usage reporting

`provider_type=anthropic` may exist as model-provider metadata for future
features, but it does not affect runtime execution.

## Current Rules

- No ambient `ANTHROPIC_API_KEY` fallback for runtime execution.
- No inherited HOME fallback for Claude Code.
- Claude Code credentials are granted by `CredentialBroker` from an explicit
  CLI credential profile.
- Vendor context is written only inside the run worktree as `CLAUDE.md`.
- Permission bypass is disabled unless both adapter config and runtime policy
  explicitly allow it under worktree isolation.
- Claude quota usage is cached-only in this build; no live PTY quota probe is
  implemented.
- `one_shot_docker` is not implemented or advertised for Claude Code.

## Consequences

The runtime adapter standard remains vendor-neutral. Adding or changing vendor
CLI support happens through RuntimeAdapterSpec data and the generic CLI runtime
path unless genuinely new native behavior is required.

Vendor CLI execution remains a RuntimeAdapter concern, not an Agent or provider
foundation.

## Superseded — see ADR 0010

The original framing here ("Anthropic is CLI-only") is superseded by
[ADR 0010 - Credential Channel Isolation](0010-credential-channel-isolation.md).
The correct invariant is: an Anthropic API key must never enter a Claude Code CLI
subprocess environment. The in-process encrypted API channel may serve any provider,
Anthropic included. Read 0010 for the authoritative position; the retained invariants
in the section above (CLI env hygiene, no ambient key fallback, vendor-neutral runtime
standard) continue to apply.
