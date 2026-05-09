# Sandbox Policy

## Purpose

Sandboxes provide isolated temporary environments where agents can make changes
without modifying real workspaces directly.

## Default flow

```
registered workspace
→ create sandbox (git worktree or copy)
→ agent modifies sandbox
→ run validation
→ export diff / log / artifacts
→ user approves
→ apply patch to real workspace
→ clean sandbox
```

## Path policy

Sandbox paths live under `sandboxes/` at the repo root. Agents must not
write outside their assigned sandbox directory.

## Retention

| State | Keep for |
|-------|----------|
| Completed | 72 hours (configurable) |
| Failed | 7 days (configurable) |

Always keep:
- diff output
- agent run log
- context snapshot

Do not keep the full workspace copy after a sandbox is cleaned.

## Strategy

Prefer `git worktree` over full copies to avoid duplicating large repos.
Exclude `node_modules/`, build artifacts, and compiled binaries from copies.
Use shared dependency caches where possible.
