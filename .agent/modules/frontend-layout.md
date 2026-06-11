# Module: Frontend Layout

## Status
**PLANNED** — current frontend is single-column pages. Multi-panel layout not yet built.

## Purpose
Define the structural layout pattern for the product UI. The layout should be modular, reusable, and support a multi-panel workspace without hard-coding every page as a one-off layout.

## Layout Pattern

```
┌──────────────────────────────────────────────────────────────────┐
│  Shell: SpaceSwitcher | NavRail | CommandPalette | RuntimeStatus │
├────────────┬────────────────────────────────┬────────────────────┤
│            │                                │                    │
│  Left      │  Center                        │  Right             │
│  Panel     │  Panel                         │  Panel             │
│            │                                │                    │
│  Spaces    │  Main content:                 │  Assistant / chat  │
│  Workspaces│  - Knowledge page              │  Context preview   │
│  Nav tree  │  - Card review                 │  Memory summary    │
│  File tree │  - File viewer                 │  Proposal summary  │
│  Activity  │  - Diff viewer                 │  Metadata / actions│
│  filters   │  - Proposal detail             │                    │
│            │  - Agent run detail            │                    │
│            │  - Activity detail             │                    │
├────────────┴────────────────────────────────┴────────────────────┤
│  Bottom Panel: logs | validation output | runtime status         │
└──────────────────────────────────────────────────────────────────┘
```

## Reusable Primitives (Planned)

| Primitive | Description |
|---|---|
| `PageShell` | Wraps a page: header + content + optional right rail |
| `PanelLayout` | Two or three-column panel split |
| `EntityCard` | Generic card shell: title, summary, status, actions |
| `ActivityCard` | Extends EntityCard for activity_records |
| `MemoryCard` | Extends EntityCard for Memory items |
| `ProposalCard` | Extends EntityCard for Proposals, with approve/reject |
| `ServerStatusCard` | Runtime health indicator |
| `WorkspaceFileTree` | File tree for workspace console |
| `DiffViewer` | Unified/split diff (git patch or inline) |
| `ReviewCard` | Spaced repetition card with Again/Hard/Good/Easy |

## Panel Responsibilities

**Left panel:** navigation, context selection, filtering
- Space and workspace switcher (if not in shell)
- File tree (workspace console)
- Activity type / status filters
- Memory scope / type filters

**Center panel:** primary content — always changes per route
- Never hardcode layout — use `PanelLayout` + route-specific content component

**Right panel:** contextual assist and metadata (collapsible on mobile)
- Assistant chat / capture
- Context preview (what memories are active)
- Related proposals for the current entity
- Quick actions (approve/reject/edit)

**Bottom panel:** logs and status (collapsible)
- Agent run logs (streaming, future)
- Validation command output
- Runtime/connection status

## Invariants
- Layout must be modular — adding a new route must not require layout changes
- Right panel is optional — every page must work without it
- Bottom panel is opt-in per page — not forced on unrelated views
- Mobile: collapse to single column; left and right panels become drawers/sheets

## Related Files
- `apps/web/src/App.tsx` — routing
- `apps/web/src/components/` — primitive components (need PanelLayout, EntityCard, etc.)
- `apps/web/src/modules/` — page components (each uses PageShell / PanelLayout)

## Related Modules
- [product-shell.md](product-shell.md) — navigation chrome that wraps this layout
- [mobile-client.md](mobile-client.md) — mobile layout constraints
