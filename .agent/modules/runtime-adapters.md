# Module: Runtime Tools And Adapter Types

Agent-space owns agents, runs, context snapshots, policy, credential gating,
worktree governance, artifacts, proposals, audit records, and events. Vendor
CLIs are runtime adapter types, but their binaries are installed as controlled
runtime tools.

## Canonical Standard

`RuntimeAdapterSpec` is the source of truth for adapter behavior. Built-in specs
live in `control-plane/src/modules/runtimeAdapters/specs.ts` for TS-owned
execution and tooling. Python `backend/app/runtimes/specs.py` remains a
migration-period reference for Python-owned execution paths. Specs define:

- runtime kind and implementation status
- runtime tool requirement, command argv template, and parser behavior
- context target file and compiler target
- credential mode and credential profile runtime name
- sandbox and workspace requirements
- model override support
- permission bypass capability and policy key
- output parser and artifact strategy
- frontend catalog metadata

`RuntimeAdapter` database rows are no longer a product configuration surface.
They remain only as legacy nullable foreign-key targets for trace/read-model
compatibility during the migration period. New run creation, preflight, policy
simulation, TS execution, and frontend configuration must resolve by
`adapter_type` plus `AgentVersion.runtime_config_json` /
`AgentVersion.runtime_policy_json`.

The old `/api/v1/runtime-adapters` CRUD, detect, status, probe, and usage API
is retired. Do not reintroduce instance-level runtime adapter configuration.

## Built-In Adapter Types

| adapter_type | kind | status | credentials | context | sandbox |
|---|---|---|---|---|---|
| `capability` | native | implemented | none | none | none |
| `model_api` | managed_api | implemented | `model_provider_api_key` (`python_runtime`) | none | none |
| `ts_agent_host` | managed_api | implemented / disabled by default | `model_provider_api_key` (`control_plane_runtime_host`) | canonical host request | none |
| `claude_code` | local_cli | implemented | `cli_profile` | `CLAUDE.md` | worktree |
| `codex_cli` | local_cli | implemented | `cli_profile` | `AGENTS.md` | worktree |
| `opencode` | local_cli | planned | disabled | prompt/custom | worktree |
| `gemini_cli` | local_cli | planned | disabled | prompt/custom | worktree |
| `custom` | custom | planned | disabled | custom | custom |

Planned adapters may appear in code/catalog metadata but cannot be enabled or
executed. No adapter currently supports `one_shot_docker`; critical-risk
execution fails before adapter invocation until that sandbox mode is designed.

## Product API Surface

Runtime tool installation and status are TypeScript-owned:

- `GET /api/v1/runtime-tools/catalog`
- `GET /api/v1/runtime-tools`
- `GET /api/v1/runtime-tools/{runtime}`
- `POST /api/v1/runtime-tools/{runtime}/install`
- `POST /api/v1/runtime-tools/{runtime}/activate`

CLI credential login and status are served by the TS providers/credentials
authority under `/api/v1/credentials/cli/*`. The frontend runtime page is
`/runtime-tools`.

## Generic CLI Lifecycle

1. control-plane `runs` resolves the final adapter type from `Run.adapter_type`, then
   `AgentVersion.runtime_config_json.adapter_type`, then
   `AgentVersion.runtime_policy_json.default_adapter_type`, then `model_api`.
2. `control-plane/src/modules/runtimeAdapters` validates that the adapter exists
   and is implemented.
3. Native adapters instantiate their native class (`capability`).
4. TS local CLI runtime specs use `control-plane/src/modules/runs/vendorCliAdapter.ts`.
5. `RuntimeToolRegistry` resolves the allowlisted active CLI binary from
   `$AGENT_SPACE_HOME/runtime-tools/<runtime>/active`. If no active tool is
   installed, execution fails closed with `cli_tool_not_installed`.
6. Credential profiles are granted through the TS CLI credential broker.
7. Python-owned `workspace.prepare` validates/prepares the worktree. TS
   `ContextPrepareService` renders runtime context files only inside the
   sandbox/worktree.
8. TS command rendering produces `string[]` argv and never uses `shell=True`.
9. The TS CLI executor starts the subprocess and registers it in the shared
   `CliProcessRegistry`; `PATCH /runs/{id}/stop` SIGTERMs the registered
   process before writing terminal cancellation state.
10. The output parser normalizes stdout/stderr, errors, usage estimates, and
    artifacts.
11. Run events, proposals, artifacts, validation, and audit stay owned by
    agent-space contexts.

## Controlled CLI Tool Installation

Vendor CLIs are not installed into backend, control-plane, or sandbox Docker
images. They are instance runtime state under:

```
$AGENT_SPACE_HOME/runtime-tools/
  claude_code/
    versions/<version>/
      tool.json
      node_modules/.bin/claude
    active -> versions/<version>
  codex_cli/
    versions/<version>/
      tool.json
      node_modules/.bin/codex
    active -> versions/<version>
```

The TS-owned `runtimeTools` module provides the controlled installer. The
installer accepts only code-allowlisted runtime/package mappings:

| runtime | package | bin |
|---|---|---|
| `claude_code` | `@anthropic-ai/claude-code` | `claude` |
| `codex_cli` | `@openai/codex` | `codex` |

It invokes `npm` with argv (`shell=false`) and writes into
`$AGENT_SPACE_HOME/runtime-tools`; npm cache is under
`$AGENT_SPACE_HOME/cache/npm`. API callers cannot provide arbitrary package
names or shell commands. Runtime execution and CLI login flows both resolve the
active binary through `RuntimeToolRegistry`; neither falls back to ambient PATH
or image-global installs.

## Credential Profile Binding

CLI credential profile ids are stable runtime/name values such as:

- `claude_code/default`
- `codex_cli/default`

CLI runs fail closed with `runtime_credential_profile_required` when a required
profile is missing. No ambient HOME or inherited API-key fallback is allowed.
`credential_id` remains reserved for DB/vault credentials and model-provider
API keys.

Credential audit rows record metadata only: legacy runtime adapter id when
available, adapter type, credential profile id, trigger origin, fallback
flags/reason, and cleanup status. Raw tokens, HOME paths, and credential file
content are never stored.

## Managed API Lifecycle

Managed API adapters do not detect a local executable. They are considered
installed when implemented:

- `model_api` and `ts_agent_host` execute a single provider-backed no-tool turn
  through control-plane `runs` and `POST /internal/runtime-host/execute` when
  runs authority is TS. The provider key is released inside the TS
  providers/credentials broker over the internal channel and is never passed
  through ambient environment variables.

The current TS host implementation supports provider-backed no-tool turns and
fails closed for tool execution (`runtime_tools_not_implemented`). MCP/tool
scheduling is deferred to the extended TS runtime stage; CLI adapters remain
the tool-bearing agent loop path for the near term.

## Permission Bypass

Permission bypass is disabled by default. It can be used only when:

- the spec declares support
- `AgentVersion.runtime_config_json.permission_bypass` requests it
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

There is no product runtime-adapter usage endpoint in the new flow. Run history
and trace read models remain the source for execution evidence. Current CLI
specs use generic/plain-text parser behavior: normalized output text, redacted
stdout/stderr, stable nonzero/timeout error codes, and no artifact paths unless
explicitly parseable.

## Adding an Adapter

To add a new local CLI runtime, add a validated `RuntimeAdapterSpec` with
invocation, context, credentials, sandbox, model, permission, usage, and output
sections, then add a `RuntimeToolRegistry` allowlist entry for the installable
tool package/bin. If existing parsers are sufficient, no Python runtime class or
hardcoded factory change is required.

To add a managed API adapter, add the spec and a concrete adapter class or TS
runtime-host handler that maps to the stable runtime boundary. Pick the
credential release channel explicitly: `python_runtime` only when the adapter
itself must consume the decrypted key, or `control_plane_runtime_host` when the
control plane owns the secret release point.
