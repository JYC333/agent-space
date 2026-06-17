# Decision 0006: Private-First, Open-Source-Ready

## Status
Accepted

## Context
The project may eventually be open-sourced. However, optimizing for public release prematurely would:
- Slow down development with polish and cleanup work
- Require removing all private data from history
- Force decisions about licensing, contribution guides, and community management before the system is stable

## Decision
The project is **private-first but open-source-ready**.

This means:
- Do not optimize for public release now
- Do not spend time on contributor guides, public-facing README polish, or package publishing
- DO maintain clean boundaries that would make open-sourcing easy later
- DO keep private instance data out of `core/`
- DO use example/template data instead of real user data in tests and seeds
- DO maintain a clean git history without secrets or real personal data

## Consequences

- `core/` must never contain: real user data, real memories, real credentials, private config
- `instance/` holds all deployment-specific state and is gitignored
- Tests use seeded example data (`SPACE=personal`, `USER=default_user`)
- Capability manifests in `catalog/capabilities/` are templates — no private capability logic
- Provider API keys and CLI login state live in the server credential stores under the instance root; real secrets must not be committed to source
- If open-sourcing later: scrub git history, add LICENSE, write CONTRIBUTING.md
- The `core/` directory is the open-source candidate; `instance/` and `ops/env/.env` remain private
