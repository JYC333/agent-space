# Runtime Adapter Standard

The runtime adapter standard separates product orchestration from vendor
execution tools.

Agent-space owns run lifecycle, context snapshots, policy gates, credential
gating, sandbox/worktree governance, artifacts, proposals, and audit/events.
Vendor CLIs such as Claude Code and Codex CLI are local CLI runtime adapters.

`RuntimeAdapterSpec` defines built-in adapter semantics. For server-owned execution
the catalog lives in `server/src/modules/runtimeAdapters/specs.ts`.
Specs cover credential mode, sandbox requirement, context
target, invocation template, permission bypass capability, usage behavior,
output parser, and catalog display.
`RuntimeAdapter` rows no longer configure space-local instances. They remain
only as legacy nullable FK targets for trace/read-model compatibility.

`GenericCliRuntimeAdapter` executes all implemented local CLI specs through the
same command rendering, credential, context, subprocess, output parser, and
usage provider path. Native adapters are limited to `capability`.

Use `/runtime-tools` for CLI binary installation/status and
`RuntimeAdapterSpec` / `adapter_type` for runtime semantics. The old
`/runtime-adapters` instance API is retired.

Runtime tool status is non-mutating: it checks the active allowlisted binary
under `$AGENT_SPACE_HOME/runtime-tools` and credential profile readiness without
creating runs, sandboxes, events, credential grants, or model calls.

Credential profile binding uses stable profile ids such as
`claude_code/default` and `codex_cli/default`. Permission bypass is policy
controlled and denied before invocation unless both runtime config and runtime
policy allow it under worktree isolation.

Credential profile readiness requires the selected source path to exist.

Vendor context files (`CLAUDE.md`, `AGENTS.md`, `prompt.md`) are generated only
inside the run worktree. They are never written to the real workspace because
agent-space remains the source of truth for context snapshots and proposals.

`one_shot_docker` is not implemented. Specs must set
`supports_one_shot_docker=false` until execution can actually provide it.

Usage providers are runtime-generic. Adapters without a real probe return
unknown accuracy plus fallback run statistics. Claude Code quota refresh is
cached-only in this build.

Output parsers must describe real behavior. Current local CLI specs use
generic/plain-text parsing unless an adapter-specific parser is implemented.

To add a new local CLI adapter, add a validated `RuntimeAdapterSpec` and the
corresponding server adapter behavior if command rendering, parsing, or credential
handling differs from the generic local CLI path.
