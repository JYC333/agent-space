# Runtime Adapter Standard

The runtime adapter standard separates product orchestration from vendor
execution tools.

Agent-space owns run lifecycle, context snapshots, policy gates, credential
gating, sandbox/worktree governance, artifacts, proposals, and audit/events.
Vendor CLIs such as Claude Code and Codex CLI are local CLI runtime adapters.

`RuntimeAdapterSpec` defines built-in adapter semantics: detection, credential
mode, sandbox requirement, context target, invocation template, permission
bypass capability, usage behavior, output parser, and catalog display.
`RuntimeAdapter` rows configure space-local instances: enabled state,
credential profile binding, executable override, health status, quota status,
and non-secret adapter config.

`GenericCliRuntimeAdapter` executes all implemented local CLI specs through the
same command rendering, credential, context, subprocess, output parser, and
usage provider path. Native adapters are limited to `echo` and `capability`.

Use `/runtime-adapters` and RuntimeAdapter/RuntimeAdapterSpec terminology.

Host detection is spec-level and non-mutating: it checks executable
availability and credential profile readiness without creating runs, sandboxes,
events, credential grants, or model calls. Configured adapter status is
instance-specific and may use the row's executable override.

Probe is also non-mutating. It validates the configured runtime instance enough
to report readiness, but it does not execute a prompt or create a run.

Credential profile binding is explicit through
`runtime_adapters.credential_profile_id`. Permission bypass is policy controlled
and denied before invocation unless both adapter config and runtime policy allow
it under worktree isolation.

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

To add a new local CLI adapter, add a validated RuntimeAdapterSpec. Python
runtime code is needed only for a native adapter or genuinely new
invocation/parsing behavior.
