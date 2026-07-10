# Module: Runtime Tools And Adapter Types

Agent-space owns agents, runs, context snapshots, policy, credential gating,
worktree governance, artifacts, proposals, audit records, and events. Vendor
CLIs are runtime adapter types, but their binaries are installed as controlled
runtime tools.

## Canonical Standard

`RuntimeAdapterSpec` is the source of truth for adapter behavior. Built-in specs
live in `server/src/modules/runtimeAdapters/specs.ts`. Specs define:

- runtime kind and implementation status
- runtime tool requirement, command argv template, and parser behavior
- context target file and compiler target
- credential mode and credential profile runtime name
- sandbox and workspace requirements
- model override support
- permission bypass capability and policy key
- output parser and artifact strategy
- frontend catalog metadata

Runtime adapter database rows are not part of the current product schema. Product
run creation and frontend configuration resolve through an Agent's selected or
default `AgentRuntimeProfile`. Server execution then uses the resulting
`Run.adapter_type` plus the run's snapshotted
`runtime_profile_snapshot_json.runtime_config_json`. Agents without an enabled
runtime profile cannot create normal agent runs.

The old `/api/v1/runtime-adapters` CRUD, detect, status, probe, and usage API
is retired. Do not reintroduce instance-level runtime adapter configuration.

## Built-In Adapter Types

| adapter_type | kind | status | credentials | context | sandbox |
|---|---|---|---|---|---|
| `capability` | native | planned | none | none | none |
| `model_api` | managed_api | implemented | `model_provider_api_key` | none | none |
| `ts_agent_host` | managed_api | implemented / disabled by default | `model_provider_api_key` (`server_runtime_host`) | canonical host request | none |
| `claude_code` | local_cli | implemented | `cli_profile` | `CLAUDE.md` | worktree |
| `codex_cli` | local_cli | implemented | `cli_profile` | `AGENTS.md` | worktree |
| `opencode` | local_cli | planned | disabled | prompt/custom | worktree |
| `gemini_cli` | local_cli | planned | disabled | prompt/custom | worktree |
| `custom` | custom | planned | disabled | custom | custom |

Planned adapters may appear in code/catalog metadata but cannot be enabled or
executed. No adapter currently supports `one_shot_docker`; critical-risk
execution fails before adapter invocation until that sandbox mode is designed.

## Product API Surface

Runtime tool installation and status are server-owned:

- `GET /api/v1/runtime-tools/catalog`
- `GET /api/v1/runtime-tools`
- `GET /api/v1/runtime-tools/{runtime}`
- `GET /api/v1/runtime-tools/space-policy`
- `GET /api/v1/runtime-tools/space-policy/{runtime}`
- `PUT /api/v1/runtime-tools/space-policy/{runtime}`
- `POST /api/v1/runtime-tools/{runtime}/install`
- `POST /api/v1/runtime-tools/{runtime}/activate`

Runtime tool installs are instance operations. `INSTANCE_ADMIN_EMAIL` identifies
the single user allowed to install or activate CLI tool versions. Space
owners/admins do not install binaries; they manage `space_runtime_tool_policies`
for their space: enabled/disabled state, default version, and optional allowed
version list. Runtime tool installs run npm from the server container. The
compose server service passes proxy and npm network settings (`HTTP_PROXY`,
`HTTPS_PROXY`, `ALL_PROXY`, `NO_PROXY`, `NPM_CONFIG_REGISTRY`,
`NPM_CONFIG_STRICT_SSL`, and `NPM_CONFIG_CAFILE`) into the container, and the
server allowlists only network settings for the npm subprocess. Provider API
keys and CLI credentials must not be passed through this path.

CLI credential login and status are served by the server providers/credentials
authority under `/api/v1/credentials/cli/*`. The frontend runtime page is
`/runtime-tools`.

## Generic CLI Lifecycle

1. server `runs` creates a run by resolving the final adapter/model binding
   from the selected/default `AgentRuntimeProfile`, then space default provider
   fallback when the adapter requires a provider. The chosen profile is
   snapshotted on the run. Execution resolves the final adapter type from
   `Run.adapter_type` and the immutable
   `runtime_profile_snapshot_json.runtime_config_json`.
2. `server/src/modules/runtimeAdapters` validates that the adapter exists
   and is implemented.
3. Native adapters are planned; no native capability executor is active today.
4. server local CLI runtime specs enter through
   `server/src/modules/runs/vendorCliAdapter.ts`. Shared local CLI execution
   details are split by responsibility: command rendering in
   `cliCommandRendering.ts`, subprocess execution and process registration in
   `localCliExecution.ts`, subprocess env allowlisting in `cliSubprocessEnv.ts`,
   runtime provider binding in `runtimeProviderBinding.ts`, and Codex config
   materialization in `codexProviderConfig.ts`.
5. For local CLI runtimes, `RunOrchestrationService` resolves the run's
   effective tool version from immutable
   `Run.runtime_profile_snapshot_json.runtime_config_json`, active-space
   `space_runtime_tool_policies`, and installed instance tool versions.
   Disabled, disallowed, or missing versions fail closed before credential
   release. `RuntimeToolRegistry` then resolves that exact installed version
   under `$AGENT_SPACE_HOME/runtime-tools/<runtime>/versions/<version>`.
6. Credential profiles are granted through the server CLI credential broker.
   Claude Code may also receive a per-run Claude-compatible ModelProvider
   binding. When selected, the server resolves the provider's
   `claude_compatible_base_url` and model, creates a short-lived provider proxy
   lease, then injects only the local proxy URL, lease token, and model
   environment variables into the Claude subprocess. Codex CLI may also receive
   a per-run OpenAI Responses-compatible ModelProvider binding. When selected,
   the server resolves `openai_compatible_base_url`, creates a short-lived
   provider proxy lease, materializes the run's temporary `CODEX_HOME`, and
   writes a run-scoped `config.toml` with `wire_api = "responses"` plus a
   generated model catalog. The Codex subprocess receives `CODEX_HOME` for both
   provider-backed and CLI-default runs, and the Codex config stores only the
   local proxy URL and lease token, not the real provider key. The internal
   provider proxy listener is started by the server process on an OS-assigned
   loopback port and is not user-configurable through env or compose. Provider
   API keys are resolved only inside the server proxy and are not released to
   CLI subprocess env. When a provider is selected, upstream proxy/direct
   routing is taken from the Provider's NetworkProfile. No provider selected
   means no base URL override; the CLI uses its managed login state and the
   CLI credential profile's default NetworkProfile, if one is configured.
7. server workspace/sandbox services validate and prepare the worktree.
   `ContextPrepareService` renders runtime context files only inside the
   sandbox/worktree.
8. server command rendering produces `string[]` argv and never uses `shell=True`.
   Codex CLI headless runs use
   `codex --ask-for-approval never exec --skip-git-repo-check --sandbox workspace-write <prompt>`;
   invoking `codex <prompt>` enters the interactive TUI and requires a
   terminal, the default `codex exec` sandbox is read-only, and the git-repo
   check would block ephemeral/no-workspace sandbox directories. When the
   prompt is rendered through argv, the CLI executor does not open a stdin
   pipe; otherwise Codex treats piped stdin as additional input context.
9. The server CLI executor starts the subprocess and registers it in the shared
   `CliProcessRegistry`; `PATCH /runs/{id}/stop` SIGTERMs the registered
   process before writing terminal cancellation state.
10. The output parser normalizes stdout/stderr, errors, usage estimates, and
    artifacts.
11. Run events, proposals, artifacts, validation, and audit stay owned by
    agent-space contexts.

## Controlled CLI Tool Installation

Vendor CLIs are not installed into backend, server, or sandbox Docker
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

The server-owned `runtimeTools` module provides the controlled installer. The
installer is restricted to the configured instance admin and accepts only
code-allowlisted runtime/package mappings:

| runtime | package | bin |
|---|---|---|
| `claude_code` | `@anthropic-ai/claude-code` | `claude` |
| `codex_cli` | `@openai/codex` | `codex` |

It invokes `npm` with argv (`shell=false`) and writes into
`$AGENT_SPACE_HOME/runtime-tools`; npm cache is under
`$AGENT_SPACE_HOME/cache/npm`. API callers cannot provide arbitrary package
names or shell commands. The installer passes through only npm network
configuration such as proxy, registry, strict-ssl, cafile, and fetch retry env
vars; provider/API tokens are not inherited. Codex CLI and Claude Code validate
their platform native optional packages (for example
`@openai/codex-linux-x64` and `@anthropic-ai/claude-code-linux-x64`) and
explicitly install the package spec declared by `optionalDependencies` when npm
does not materialize it automatically. Claude Code also reruns its fixed
postinstall script so the wrapper package places the native binary under
`bin/claude.exe`. CLI login resolves the instance active binary through
`RuntimeToolRegistry`. Runtime execution resolves the version pinned on
`AgentRuntimeProfile.runtime_config_json.runtime_tool_version`, after applying
the active-space runtime policy. Neither path falls back to ambient PATH or
image-global installs.

## Space Runtime Version Policy

Installed CLI binaries are shared instance state; spaces do not own separate
installs. Each space can set a policy row per CLI runtime:

- `enabled=false` blocks that runtime in the space.
- `default_version` is used when an agent does not request a version.
- `allowed_versions_json` optionally constrains which installed versions can be
  selected in that space. Empty means any installed version is allowed.

Agent create/update resolves the effective CLI tool version and stores it on
the default `AgentRuntimeProfile.runtime_config_json.runtime_tool_version`. Runs
snapshot the selected profile at creation; HTTP workflow execution selects a
runtime profile instead of overriding adapter config. If the pinned version is
later uninstalled, disabled, or removed from the space allowlist, the run fails
closed with `runtime_tool_version_unavailable` before credential resolution.

## Credential Profile Binding

CLI credential profile ids are UUIDs from `cli_credential_profiles.id`.
`AgentRuntimeProfile` stores the selected `credential_profile_id`; runs snapshot
it at creation. When absent, execution falls back to the active-space default
grant for that runtime.

CLI runs fail closed with `runtime_credential_profile_required` when a required
profile is missing. No ambient HOME or inherited API-key fallback is allowed.
`credential_id` remains reserved for DB/vault credentials and model-provider
API keys.

Credential audit rows record metadata only: adapter type, credential profile id,
trigger origin, fallback flags/reason, and cleanup status. Raw tokens, HOME
paths, and credential file content are never stored.

## Managed API Lifecycle

Managed API adapters do not detect a local executable. They are considered
installed when implemented:

- `model_api` and `ts_agent_host` execute provider-backed turns through server
  `runs` and `POST /internal/runtime-host/execute` when runs authority is the
  server. The provider key is released inside the server providers/credentials
  broker over the internal channel and is never passed through ambient
  environment variables.
- Runs default to `tool_mode: disabled`. Managed runs can expose authorized
  internal retrieval tools through the runtime host when enabled per space
  (`retrieval.space.settings` `retrieval_tool_mode`) or per run. Knowledge tools
  are `retrieval.search` / `retrieval.brief`; Memory and Project public-summary
  tools are exposed only by explicit domain opt-in as
  `memory.retrieval.search`, `memory.retrieval.brief`,
  `project_public_summary.search`, and `project_public_summary.brief`. Each tool
  call passes a policy-gateway action before search/brief execution; preflight
  modes append explicit retrieval evidence before the model turn rather than
  silently injecting ContextBuilder state. The provider invocation layer maps the
  canonical tool schema to OpenAI-compatible function calls or Anthropic Messages
  `tool_use` / `tool_result` blocks. The runtime host reports an unsupported
  provider with the `runtime_tool_provider_unsupported` code, and the managed-run
  tool loop degrades to a single no-tool turn rather than failing the run.
- Managed API runs inside Agent Rooms expose room tools when the run belongs to
  an active group. `agent.delegate` is available when there are active target
  members and creates child runs through the agent group service and
  `run.spawn_child` policy gate. `agent.wait_for_results` lets the current run
  pause on current-turn sibling runs, its own delegated child runs, or explicit
  same-room run ids; orchestration stores `waiting_for_dependency` and the
  lifecycle projector requeues the same run after every dependency is terminal.
  These tools are not free-form provider tools and do not parse natural-language
  text server-side.

General MCP/tool scheduling is deferred to the extended server runtime stage;
CLI adapters remain the broad tool-bearing agent loop path for the near term.

## Permission Bypass

Permission bypass is disabled by default. It can be used only when:

- the spec declares support
- the run's snapshotted runtime profile config requests `permission_bypass`
- the run's snapshotted runtime profile policy allows `allow_permission_bypass`
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

The retired `/runtime-adapters/*/usage` endpoint is not part of the current
product. Run history and trace read models remain the source for execution
evidence, while token accounting lives under `/usage`: managed provider calls
and provider-proxy responses emit ledger events, and managed CLI profiles can
import transcript-derived lower bounds. CLI login/quota snapshots remain under
`/credentials/cli/usage*` and are not token-accounting events.

Current CLI specs use generic/plain-text output parser behavior: normalized
output text, redacted stdout/stderr, stable nonzero/timeout error codes, and no
artifact paths unless explicitly parseable. Raw output and transcripts are not
stored in the usage ledger.

## Adding an Adapter

To add a new local CLI runtime, add a validated `RuntimeAdapterSpec` with
invocation, context, credentials, sandbox, model, permission, usage, and output
sections, then add a `RuntimeToolRegistry` allowlist entry for the installable
tool package/bin. If existing parsers are sufficient, no hardcoded factory
change is required.

To add a managed API adapter, add the spec and a concrete adapter class or
runtime-host handler that maps to the stable runtime boundary. Use
`server_runtime_host` only when the server owns the secret release
point.
