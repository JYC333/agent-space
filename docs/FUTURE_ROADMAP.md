# Future Roadmap

## Runtime target (locked)

The MVP and primary runtime is **Linux / WSL / server + browser UI**.

```
Windows host
→ WSL / Linux runtime
→ Python / FastAPI agent-space server
→ CLI tools: Claude Code CLI, Codex CLI
→ Docker sandboxes for agent execution
→ browser-based UI (React + Vite)
```

Desktop support is **deferred and optional**. If added later, it will be a lightweight
Windows/macOS launcher only — checking dependencies, starting/stopping the WSL server,
opening the browser. It will NOT reimplement the backend or run CLI tools natively.

---

## Phase 1 (done): Agent Memory Core

- [x] Memory store with scopes, types, namespaces
- [x] Memory proposal → approval → active memory workflow
- [x] Session + message system
- [x] Memory reflector (placeholder + LLM mode)
- [x] Context builder
- [x] Capability registry
- [x] Agent run logging (echo, Claude CLI, Codex CLI adapters)
- [x] Multi-tenant-ready schema (ULID IDs, soft deletes, space/user/workspace fields)

## Phase 2 (in progress): React Web App + PWA

**Stack decisions (locked)**

| Platform | Technology | Rationale |
|---|---|---|
| Web | React + Vite | Browser-based, no install required |
| PWA | vite-plugin-pwa + Workbox | Installable on iOS via Safari, works offline |

**Phase 2 deliverables:**
- [x] React + Vite app with proxy to FastAPI backend
- [x] Environment-based API URL config (VITE_API_URL)
- [ ] Wire frontend to backend API (agents, runs, memory, proposals)
- [ ] PWA (installable on iPhone via Safari, works offline)
- [ ] Real-time run progress (WebSocket or SSE)

## Phase 3: CLI Agent Loop

- Full Claude Code CLI integration (sandboxed)
- Task queue with async execution
- Artifact capture from agent runs
- Automatic episodic memory from completed runs
- Approval workflow for agent-generated diffs

## Business Data Domains

Business data domains are distinct from agent memory.

- **Business data** — primary facts and records (transactions, events, calendar entries)
- **Agent memory** — interpretations, preferences, rules, and summaries *derived* from business data

A transaction is not memory. An energy check-in is not memory. A calendar event is not memory.
Agent memory is what the system *learns* from patterns, user feedback, or decisions about that data.

Planned domains (none implemented yet):

| Domain | Description |
|---|---|
| `knowledge/` | Documents, notes, reference material |
| `finance/` | Transactions, budgets, classifications |
| `energy/` | Daily check-ins, patterns |
| `calendar/` | Events, scheduling preferences |
| `tasks/` | User-facing task records (distinct from the agent `Task` execution model) |
| `projects/` | Project metadata and status |
| `household/` | Household-specific records |

These will live under `core/backend/app/` as domain modules once implemented.

---

## Phase 4: Coding + Research Capabilities

- `coding.agent` — full code-writing capability with diff review
- `research.web` — web search + summarization + memory storage
- `knowledge.wiki` — personal wiki backed by memory store
- Tool call logging (scaffolded in `tool_calls` table already)

## Phase 5: Database Migrations + Multi-user Auth

- Alembic migrations (replace `create_all` dev setup)
- JWT / session auth
- Role-based access per workspace
- Tenant admin panel
- Cross-user memory sharing with approval

## Phase 6: Self-evolving Capability Creation

- `system.evolve` capability
- Generate new capability YAML + code in sandbox
- Propose new capability for user approval
- One-click install flow

## Phase 7: React Native Mobile (iOS + Android)

- React Native + Expo (shared business logic with web)
- **iOS**: Expo EAS Build (cloud Mac build — no Mac device required)
- **Android**: Expo EAS Build or local Android Studio
- Offline memory browsing
- Push notifications for proposal approvals

## Phase 8 (optional/deferred): Desktop Launcher

A lightweight native app for Windows/macOS that:
- Checks whether WSL / Docker / server dependencies are present
- Starts or stops the WSL / server runtime
- Opens the local browser UI
- Shows runtime status and logs

It will NOT:
- Reimplement the backend or agent loop
- Run CLI tools directly outside the Linux/server runtime
- Replace the browser UI

## Design principles that hold across all phases

1. The memory system is the source of truth — agents are stateless executors.
2. No agent writes long-term memory without user approval.
3. All IDs are ULIDs for local-first compatibility.
4. Multi-tenant schema from day one; single-user is just a degenerate case.
5. Capability system is the extension point — not hard-coded plugins.
6. The core runtime is always Linux/WSL/server. Desktop and mobile are clients.
