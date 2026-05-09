# Decision 0004: Vendor Context Files Are Generated Adapters, Not Source of Truth

## Status
Accepted

## Context
Claude Code uses `CLAUDE.md`, Codex uses `AGENTS.md`, Cursor uses `.cursorrules`. Early versions put architecture decisions and user preferences directly in these files. Problems:
- Context locked into a vendor format
- Files could be modified by the CLI agent, corrupting "source of truth"
- No connection between changes in these files and long-term memory
- Token waste: dumping all memory as JSON into the prompt

## Decision
**Vendor-specific files (CLAUDE.md, AGENTS.md, Cursor rules) are generated adapter files, not source of truth.**

The source of truth is:
- `MemoryStore` — long-term scoped context
- `ContextBuilder` — assembles context per space/user/workspace
- `ContextCompiler` — formats it for a specific CLI target

Generated files:
- Are written by `ContextCompiler` to the sandbox directory only
- Are ephemeral — recreated fresh for each run
- Are never written to the real workspace by default
- Are never committed to source control

## Consequences

- `CLAUDE.md` and `AGENTS.md` in the real workspace (if present) are stable, human-authored project docs — not run-specific context
- Run-specific context (memories, preferences, policies, task goal) is always compiled fresh per run
- Changes an agent makes to CLAUDE.md inside its sandbox do not auto-propagate to MemoryStore
- Long-term memory updates still require: agent run → MemoryReflector → MemoryProposal → user approval
- ContextCompiler supports targets: `claude`, `codex`, `cursor`, `generic` — extensible for future tools
- Context is concise: only title + content per memory item, capped per scope
