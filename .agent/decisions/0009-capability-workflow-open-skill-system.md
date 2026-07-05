# ADR 0009: Capability, Workflow, And Open Skill Framework

Date: 2026-06-20

## Status

Accepted

## Context

Agent-space needs a vendor-neutral way to represent canonical capabilities,
group them into packs, compose them into workflow templates, configure them per
project, import external Agent-Skills-compatible packages safely, and render
capabilities for runtime adapters such as Claude Code, Codex, and `model_api`.

The existing capability surface is catalog metadata only. Runtime adapters are
already modeled separately, and vendor context files are generated artifacts,
not source of truth.

## Decision

Add a server-owned `capabilities` control-plane module beside the existing
`catalog` module.

`catalog` remains the raw on-disk manifest reader. `capabilities` owns canonical
framework data and APIs for:

- capability definitions
- capability packs
- workflow templates
- project workflow profiles
- imported skill sources/packages
- normalized skills
- runtime skill bindings
- runtime skill rendering

External Open Skills are untrusted source material. Imports are disabled by
default, scripts are not executed, dependencies are not installed, and vendor
permission declarations are treated as permission requests only.

Claude Code, Codex, `model_api`, and future runtimes are rendering/invocation
targets. Runtime skill files are generated artifacts and do not become
agent-space source of truth.

## Consequences

- Capability lifecycle remains reviewable and can later use proposal types such
  as `capability_install`, `capability_update`, and `capability_enable`.
- Research can be modeled first as a capability pack and workflow templates
  rather than as a product plugin.
- Imported skills can be stored, inspected, normalized, risk-scanned, and
  converted to capability candidates without enabling execution.
- The native `capability` runtime remains disabled until a separate executor
  design is approved.

## Non-Goals

- Full marketplace.
- Arbitrary third-party code execution.
- Runtime hot-loading of plugin/server code.
- Native web search provider.
- Research product UI.
- Capability executor rewrite.

