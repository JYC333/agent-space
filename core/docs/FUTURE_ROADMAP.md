# Future Roadmap

## Phase 1 (done): Agent Memory Core

- [x] Memory store with scopes, types, namespaces
- [x] Memory proposal → approval → active memory workflow
- [x] Session + message system
- [x] Memory reflector (placeholder + LLM mode)
- [x] Context builder
- [x] Capability registry
- [x] Agent run logging (echo, Claude Code, Codex CLI RuntimeAdapterSpec paths)
- [x] Minimal admin UI (vanilla HTML)
- [x] Multi-tenant-ready schema (ULID IDs, soft deletes, tenant/user/workspace fields)

## Phase 2 (in progress): React Web App + PWA + Desktop

**Stack decisions (locked)**

| Platform | Technology | Rationale |
|---|---|---|
| Web | React + Vite | Industry standard, shared with desktop |
| PWA | vite-plugin-pwa + Workbox | Free iOS install via Safari, no App Store needed |
| Desktop | Tauri + React | Lightweight (~5MB), wraps same React app, native OS access |
| Mobile (future) | React Native + Expo | Real native components, EAS cloud builds (no Mac needed) |

**Why these choices:**
- Capacitor was considered but rejected: webview-based, Apple increasingly strict on wrapped webapps
- React Native renders real native iOS components; Expo EAS Build compiles on cloud Macs
- Tauri reuses the React web app with near-zero extra code
- PWA covers iPhone use today for free while full native app is built later

**Phase 2 deliverables:**
- [ ] React + Vite app replacing minimal HTML UI
- [ ] PWA (installable on iPhone via Safari, works offline)
- [ ] Tauri desktop wrapper (Windows/Linux/macOS)
- [ ] Vite dev proxy to FastAPI backend
- [ ] Environment-based API URL config

## Phase 3: CLI Agent Loop

- Full Claude Code CLI integration
- Task queue with async execution
- Artifact capture from agent runs
- Automatic episodic memory from completed runs
- Approval workflow for agent-generated diffs
- WebSocket/SSE for real-time run progress in UI

## Phase 4: Docker Sandbox

- `DockerExecutor` implementation
- Sandboxed capability execution (isolated filesystem)
- Agent-produced diffs reviewed before applying
- Resource limits (CPU, memory, network)

## Phase 5: Coding + Research Capabilities

- `coding.agent` — full code-writing capability with diff review
- `research.web` — web search + summarization + memory storage
- `knowledge.wiki` — personal wiki backed by memory store
- Tool call logging (scaffolded in `tool_calls` table already)

## Phase 6: React Native Mobile (iOS + Android)

- React Native + Expo (shared business logic with web)
- **iOS**: Expo EAS Build (cloud Mac build — no Mac device required)
- **Android**: Expo EAS Build or local Android Studio
- Offline memory browsing
- Push notifications for proposal approvals
- Mobile-optimised proposal review flow

**Distribution:**
- iOS: App Store ($99/yr Apple Developer account) or TestFlight for personal use
- Android: Play Store ($25 one-time) or direct APK sideload

## Phase 7: Self-evolving Capability Creation

- `system.evolve` capability
- Generate new capability YAML + code in sandbox
- Propose new capability for user approval
- One-click install flow

## Phase 8: Multi-user Auth and Permissions

- JWT / session auth
- Role-based access per workspace
- Tenant admin panel
- Cross-user memory sharing
- Audit log

## Phase 9: Server-side Heavy Agents

- Long-running background tasks
- Multi-agent orchestration
- Scheduled capability runs (cron)

## Design principles that hold across all milestones

1. The memory system is the source of truth — agents are stateless executors.
2. No agent writes long-term memory without user approval.
3. All IDs are ULIDs (client-generatable) for local-first coexistence across clients.
4. Multi-tenant schema from day one.
5. Capability system is the extension point — not hard-coded plugins.
6. One React codebase serves web, PWA, and desktop (Tauri). Mobile shares logic, not components.
