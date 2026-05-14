# Agent Core — Agent Memory Foundation

An agent-first runtime focused on structured, user-controlled long-term memory.

## What this is

Agent Core is not a chatbot or a CRUD app.
It is a **harness around agents**: owning memory, context, proposals, permissions, and run logs while treating CLI tools (Claude, Codex, etc.) as pure execution engines.

## Quick start

### Backend
```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

### Frontend (React web app + PWA)
```bash
cd frontend/web
npm install
npm run dev        # → http://localhost:5173
```

### Desktop (Tauri — requires Rust)
```bash
cd frontend/web
npm install
npm run tauri dev  # opens native desktop window
```

Prerequisites for desktop: [Rust](https://rustup.rs) + [Tauri CLI v2](https://tauri.app/start/prerequisites/)

## Frontend stack

| Platform | Technology | Status |
|---|---|---|
| Web | React + Vite | ✅ Active |
| PWA | vite-plugin-pwa (installable on iPhone) | ✅ Active |
| Desktop | Tauri + same React app | ✅ Scaffolded |
| Mobile | React Native + Expo EAS Build | 🔜 Phase 6 |

The web app and desktop app share the same React codebase.
The PWA lets you install the web app on your iPhone from Safari with no App Store needed.
React Native (future) will share API calls and business logic with the web app.

## First milestone flow

1. Create a session
2. Add messages describing preferences and goals
3. Click "Reflect → Proposals" — system generates memory proposals
4. Review and accept/reject proposals
5. Build a context package — it reflects accepted memories

## Running tests

```bash
cd core/backend && python3 -m pytest tests/unit tests/contracts tests/invariants tests/workflows -v --tb=short
```

``tests/conftest.py`` sets an isolated ``AGENT_SPACE_HOME`` before importing the app, so pytest does not open a real mode database.

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./data/agent_core.db` | Backend DB |
| `REFLECTOR_MODE` | `pattern` | `pattern` or `llm` |
| `ANTHROPIC_API_KEY` | `` | Required for `llm` reflector mode |
| `VITE_API_URL` | `/api/v1` | Frontend API base URL |

## Project structure

```
agent-core/
├── backend/           FastAPI backend (Python)
│   ├── app/
│   │   ├── memory/    MemoryStore, ContextBuilder, Reflector, Proposals
│   │   ├── sessions/  Session + Message service
│   │   ├── agents/    Agent adapters + runner
│   │   ├── capabilities/  CapabilityRegistry
│   │   ├── tasks/     Task service
│   │   └── api/       FastAPI routers
│   └── tests/
├── frontend/
│   └── web/           React + Vite app (web + PWA + Tauri desktop)
│       ├── src/       React components and pages
│       └── src-tauri/ Tauri desktop wrapper config
├── capabilities/      Capability manifests
├── memory/            Memory scaffold files
└── docs/              Architecture and design docs
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full design.
See [docs/FUTURE_ROADMAP.md](docs/FUTURE_ROADMAP.md) for the platform strategy.
