# Comparable Projects, by Capability

Temporary research note, not source of truth. Every repo/product surfaced so
far while researching a possible rename and while comparing against prior
systems (PilotDeck, Hermes) and public references (OpenClaw, GBrain) is
collected here once, grouped by **what it does**, not by which search turned
it up or which name it happened to collide with. Each row links back to the
agent-space doc for that capability so the two can be read side by side.
Check a box once you've actually reviewed that project. Delete this file or
fold findings into a decision record once the review is done.

---

## A. Multi-agent / multi-CLI orchestration

Compares to agent-space's Runtime Adapter abstraction (`claude_code`,
`codex_cli`, `opencode`, `model_api`) and the deferred self-hosted agent loop
— see [EXECUTION_MODEL.md](../architecture/EXECUTION_MODEL.md),
[runtime-adapters.md](../modules/runtime-adapters.md), and backlog items P6/P7
in [ROADMAP_AND_FUTURE_RISKS.md](../architecture/ROADMAP_AND_FUTURE_RISKS.md).

- [ ] [github.com/HKUDS/AgentSpace](https://github.com/HKUDS/AgentSpace) — "Human + Agents. One Team. One Workspace"
- [ ] [github.com/agent0ai/space-agent](https://github.com/agent0ai/space-agent) — "The agent that re-shapes the Space"
- [ ] [github.com/colinds/agentry](https://github.com/colinds/agentry) — compose/reuse AI agents like React components
- [ ] [github.com/googlicius/obsidian-steward](https://github.com/googlicius/obsidian-steward) — vault agent that can "jump" into other CLI agents (Claude, Gemini, etc.) — closest match to agent-space's multi-CLI adapter idea
- [ ] **Hermes / PilotDeck** (P6/P7, prior systems, no public repo) — self-hosted TS agent loop (AgentSession/TurnRunner/AgentLoop), tool scheduler, MCP client integration

## B. Personal / family self-hosted data management

Compares to agent-space's Space model (Personal/Family/Team isolation) — see
[README.md](../../README.md) and [BOUNDARIES.md B3](../BOUNDARIES.md).

- [ ] [github.com/ulsklyc/oikos](https://github.com/ulsklyc/oikos) — self-hosted family planner: tasks, calendars, shopping, meals, budget, your own server. Closest thematic overlap found in the whole search.

## C. Long-term memory / knowledge graph / retrieval

Compares to agent-space's Memory + Knowledge Base modules
([MEMORY_MODEL.md](../architecture/MEMORY_MODEL.md),
[CLAIM_FACT_ATOM_MODEL.md](../architecture/CLAIM_FACT_ATOM_MODEL.md)) and
[CONTEXT_AND_RETRIEVAL_LAYER.md](../architecture/CONTEXT_AND_RETRIEVAL_LAYER.md)
(hybrid vector/lexical/graph recall, RRF).

- [ ] [github.com/garrytan/gbrain](https://github.com/garrytan/gbrain) — Markdown → living knowledge graph (entities + relationships), MCP server over Postgres pgvector + BM25/ripgrep hybrid search, overnight self-consolidation

## D. AI governance / policy enforcement / oversight

Compares to agent-space's Policy module and credential broker — see
[POLICY_ENFORCEMENT_INVENTORY.md](../architecture/POLICY_ENFORCEMENT_INVENTORY.md)
and backlog item H3 in
[ROADMAP_AND_FUTURE_RISKS.md](../architecture/ROADMAP_AND_FUTURE_RISKS.md).

- [ ] [github.com/agenisea/steward](https://github.com/agenisea/steward) — governance calculus for AI systems (PROCEED / ESCALATE / BLOCKED)
- [ ] [github.com/NawazHaider/steward](https://github.com/NawazHaider/steward) — runtime governance for AI systems
- [ ] [github.com/kim7hg/steward](https://github.com/kim7hg/steward) — governs AI actions with real-time oversight
- [ ] [github.com/Steward-Fi/steward](https://github.com/Steward-Fi/steward) — self-hostable, multi-tenant agent wallet infra: encrypted keys, policy enforcement, credential proxy, auth platform. Structurally close to agent-space's own credential/policy layer.
- [ ] [getsteward.ai](https://getsteward.ai/) — funded AI compliance/AML platform (commercial)
- [ ] [stewardautomation.com](https://www.stewardautomation.com/) — business automation / custom agents (commercial)
- [ ] **Hermes** H3 (prior system, no public repo) — provider privacy/compliance policy: data-collection deny, provider allow/deny, required parameter rules

## E. Credential / secrets patterns — rejected references

Not open comparisons, recorded as patterns agent-space deliberately did not
follow — see [CREDENTIAL_STORAGE.md](../architecture/CREDENTIAL_STORAGE.md)
and [ADR 0008](../decisions/0008-credential-channel-isolation.md).

- [ ] **Hermes** local `auth.json` credential pool state — rejected
- [ ] **PilotDeck** secrets in YAML / `${ENV}` substitution, global single-scope config ignoring `space_id` — rejected

## F. Channel / messaging automation (IM, email ingestion, real-world actions)

agent-space's own backlog item **P8** ("Channel adapters: IM/email/channel
ingestion") is explicitly deferred until intake/evidence provenance is
stable — see
[ROADMAP_AND_FUTURE_RISKS.md](../architecture/ROADMAP_AND_FUTURE_RISKS.md).

- [ ] [github.com/openclaw/openclaw](https://github.com/openclaw/openclaw) · [openclaw.ai](https://openclaw.ai/) — personal AI assistant, MIT-licensed Gateway, connects through WhatsApp/Telegram/Slack/Discord/WeChat/etc., executes shell/browser/email/calendar actions directly from chat. Closest match found for the P8 gap.

## G. Self-evolving skill / capability systems

Compares to agent-space's Capability/Workflow/Open Skill framework
([ADR 0009](../decisions/0009-capability-workflow-open-skill-system.md)) and
the Learning Loop / Self-Evolution roadmap capability.

- [ ] [github.com/HKUDS/OpenSpace](https://github.com/HKUDS/OpenSpace) — "Make Your Agents: Smarter, Low-Cost, Self-Evolving" — living skill entities with full select/apply/monitor/analyze/evolve lifecycle
- [ ] [github.com/EvoMap/evolver](https://github.com/EvoMap/evolver) — GEP-powered self-evolving engine for AI agents; auditable evolution via Genes, Capsules, and Events (likely the repo meant by "evlover")

## H. Enterprise multi-agent platforms (market context, not a direct peer)

- [ ] Google Cloud **Agentspace**, now folded into **Gemini Enterprise** — enterprise-wide search + assistant + custom agent creation for employees. Different scale/audience (enterprise IT) than agent-space's personal/family/small-team target, but same "agentic platform" category — see [coverage](https://thenextweb.com/news/google-cloud-next-ai-agents-agentic-era).

## I. Narrow / low relevance (kept for completeness)

- [github.com/apache/airflow-steward](https://github.com/apache/airflow-steward) — agent-assisted maintainership for Apache projects specifically (triage, drafting, mentoring); narrow OSS-maintenance use case
- [github.com/jonathanfilsaime/warren](https://github.com/jonathanfilsaime/warren) — unrelated (React/Storybook tooling), turned up only as a name match
- SAP Syclo Agentry — legacy enterprise mobile field-service platform (acquired by SAP 2012); weak functional overlap, name match only
- [github.com/oikos-cash/oikos](https://github.com/oikos-cash/oikos) + [oikos-js](https://github.com/oikos-cash/oikos-js) — DeFi/stablecoin project, unrelated domain, name match only
- [stewards.ai](https://www.stewards.ai/) — municipal/civic impact platform, unrelated domain, name match only
- [steward.ae](https://www.steward.ae/) — generic AI chatbot SaaS, weak overlap, name match only
- Oikos® Greek yogurt — trademark reference only, not software
