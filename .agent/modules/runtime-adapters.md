# Module: Runtime Adapters

Agent-space owns agents, runs, context snapshots, policy, credential gating,
worktree governance, artifacts, proposals, audit records, and events.
Vendor CLIs are runtime adapters only.

## Canonical Standard

`RuntimeAdapterSpec` is the source of truth for adapter behavior. Built-in specs
live in `core/backend/app/runtimes/specs.py` and define:

- runtime kind and implementation status
- executable detection and version probes
- safe argv invocation templates
- context target file and compiler target
- credential mode and credential profile runtime name
- sandbox and workspace requirements
- model override support
- permission bypass capability and policy key
- usage probe and parser type
- output parser and artifact strategy
- frontend catalog metadata

`RuntimeAdapter` database rows are per-space configuration:

- enabled/disabled state
- optional executable override
- optional `credential_profile_id`
- optional `credential_id` for DB/vault credentials
- optional provider binding for future API-backed runtimes
- adapter-specific non-secret config

The row never defines adapter semantics. The spec does.

## Built-In Adapter Types

| adapter_type | kind | status | credentials | context | sandbox |
|---|---|---|---|---|---|
| `echo` | native | implemented | none | none | none |
| `capability` | native | implemented | none | none | none |
| `claude_code` | local_cli | implemented | `cli_profile` | `CLAUDE.md` | worktree |
| `codex_cli` | local_cli | implemented | `cli_profile` | `AGENTS.md` | worktree |
| `opencode` | local_cli | planned | disabled | prompt/custom | worktree |
| `gemini_cli` | local_cli | planned | disabled | prompt/custom | worktree |
| `custom` | custom | planned | disabled | custom | custom |

Planned adapters may appear in the catalog but cannot be enabled or executed.
No adapter currently supports `one_shot_docker`; critical-risk execution fails
before adapter invocation until that sandbox mode is implemented.

## API Surface

Product-facing runtime adapter endpoints are:

- `GET /api/v1/runtime-adapters/catalog`
- `GET /api/v1/runtime-adapters`
- `POST /api/v1/runtime-adapters`
- `GET /api/v1/runtime-adapters/{id}`
- `PATCH /api/v1/runtime-adapters/{id}`
- `DELETE /api/v1/runtime-adapters/{id}`
- `GET /api/v1/runtime-adapters/detect`
- `GET /api/v1/runtime-adapters/{id}/detect`
- `GET /api/v1/runtime-adapters/{id}/status`
- `POST /api/v1/runtime-adapters/{id}/probe`
- `GET /api/v1/runtime-adapters/{id}/usage`
- `POST /api/v1/runtime-adapters/{id}/usage/refresh`

## Generic CLI Lifecycle

1. `RunExecutionService` resolves the final adapter type.
2. `RuntimeAdapterSpecCatalog` validates that the adapter exists and is implemented.
3. Native adapters instantiate their native class (`echo`, `capability`).
4. Local CLI runtime specs instantiate `GenericCliRuntimeAdapter(spec)`.
5. Credential profiles are granted through `CredentialBroker.grant_for_run()`.
6. `ContextCompiler` writes vendor context files only inside the sandbox/worktree.
7. `CommandRenderer` renders `list[str]` argv and never uses `shell=True`.
8. `LocalExecutor` starts the subprocess and registers its process for cancellation.
9. The output parser normalizes stdout/stderr, errors, usage estimates, and artifacts.
10. Run events, proposals, artifacts, validation, and audit stay owned by agent-space.

## Credential Profile Binding

`runtime_adapters.credential_profile_id` binds CLI login state such as:

- `claude_code/default`
- `codex_cli/default`

`credential_id` remains reserved for DB/vault credentials and model-provider API
keys. CLI runs fail closed with `runtime_credential_profile_required` when a
required profile is missing. No ambient HOME or inherited API-key fallback is
allowed.

Credential audit rows record metadata only: runtime adapter id, adapter type,
credential profile id, trigger origin, fallback flags/reason, and cleanup status.
Raw tokens, HOME paths, and credential file content are never stored.

## Permission Bypass

Permission bypass is disabled by default. It can be used only when:

- the spec declares support
- `RuntimeAdapter.config_json.permission_bypass` requests it
- `AgentVersion.runtime_policy_json.allow_permission_bypass` is true
- the run is high or critical risk
- execution uses a worktree workspace

Blocked requests fail before invocation with `permission_bypass_not_allowed`.

## Isolation Limits

Worktree isolation protects repository state and proposal review flow. It does
not provide OS, process, network, or resource isolation. Vendor context files
are generated into the worktree only so real workspace files such as
`CLAUDE.md`, `AGENTS.md`, or `prompt.md` are never mutated by runtime context
rendering.

`one_shot_docker` is a policy level but is not implemented by any current
runtime adapter. Runtime status must not advertise Docker support.

## Usage And Output Parsing

Usage is exposed through runtime-generic endpoints. This build reports fallback
usage (`run_count`, `last_run_at`, `runtime_seconds`) for adapters without a
real probe. Claude Code quota refresh is cached-only; no live PTY quota probe is
implemented in this build.

Output parsing is intentionally generic unless a parser performs real
adapter-specific parsing. Current CLI specs use the generic/plain-text parser
behavior: normalized output text, redacted stdout/stderr, stable nonzero/timeout
error codes, and no artifact paths unless explicitly parseable.

## Adding an Adapter

To add a new local CLI runtime, add a validated `RuntimeAdapterSpec` with
executable, invocation, context, credentials, sandbox, model, permission, usage,
and output sections. If existing parsers are sufficient, no Python runtime class
or hardcoded factory change is required.
