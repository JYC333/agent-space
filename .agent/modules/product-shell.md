# Module: Product Shell

## Status
**PLANNED** — scaffold exists (React/Vite SPA), shell structure not yet implemented.

## Purpose
The persistent application frame that wraps every page. The shell is always visible, always space-aware, and provides consistent navigation, search, capture, and status across all product features.

## Owns
- Top-level layout and navigation chrome
- Space switcher (select between personal / household / team spaces)
- Workspace switcher (select workspace within current space)
- Global command / search palette
- Assistant / quick-capture entry point
- Notification and proposal inbox badge
- Connection / runtime status indicator
- User / account / settings access

## Does Not Own
- Page content (owned by individual feature modules)
- Space or user data (space module)
- Proposal logic (proposals module)

## Top-Level Navigation

```
Today               — digest: recent activity, due cards, pending proposals
Assistant           — chat / quick capture
Activity Inbox      — raw activity_records
Memory              — memory review and governance
Wiki                — LLM-structured knowledge
Cards / Review      — spaced repetition queue
Agents              — agent list, runs, capabilities
Workspaces          — workspace console and file browser
Proposals           — pending approvals
Settings            — space config, user prefs, API keys, runtime
```

## Shell Components (Planned)

| Component | Purpose |
|---|---|
| `SpaceSwitcher` | Switch between spaces the user belongs to |
| `WorkspaceSwitcher` | Switch workspace within current space |
| `NavRail` | Primary navigation (collapsible sidebar) |
| `CommandPalette` | Global search / action (keyboard shortcut) |
| `AssistantEntry` | Quick capture / chat input (always accessible) |
| `ProposalInboxBadge` | Count of pending proposals |
| `RuntimeStatusBar` | Server / connection / adapter health |
| `UserMenu` | Account, settings, sign out |

## Invariants
- Every page must operate within a selected `space_id` — never assume a single global user
- `workspace_id` is optional but must be propagated when selected
- The shell must degrade gracefully when the server is unreachable (show connection status, allow read from cache in future)
- Navigation items that have no data must show empty state, not hide entirely

## Related Files
- `frontend/src/App.jsx` — current top-level app (needs shell refactor)
- `frontend/src/pages/` — page-level components (each needs space awareness)
- `frontend/src/components/` — reusable component library

## Related Decisions
- [0001-space-model.md](../decisions/0001-space-model.md)
- [0005-desktop-runtime.md](../decisions/0005-desktop-runtime.md)
