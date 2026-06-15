# Frontend Information Architecture

## 1. Frontend Role

The frontend is the primary command surface for the agent-space product loop. It provides
access to: capture, activity inbox, proposals, runs, tasks, memory, workspaces, and runtime
status.

The frontend must respect backend security and access boundaries at all times. Every data
call is made inside `RequireAuth`; the backend enforces space-scoped visibility, and the
frontend must not expose information about objects the user cannot access.

The frontend should guide users through the product loop rather than act as an app gallery.
The goal is a working system the user interacts with daily — not a navigation menu of features.

---

## 2. Dogfooding Loop

The primary product loop:

```
capture
  → activity inbox
  → activity detail / consolidate
  → generated proposals
  → proposal review (accept / reject)
  → accepted memory / task / code result
  → continue working
```

All frontend modules are oriented around this loop. Home is the entry point. Activity Inbox
is the processing queue. Proposals is the review and acceptance surface. Memory, Tasks, and
Artifacts are the outputs.

---

## 3. Home and Space Scope Model

There are exactly two route scopes (`routeScopeForPath` in `src/core/navigation.tsx`):

| Scope | Routes | Data source | Write target |
|---|---|---|---|
| `home` | `/`, `/home`, and neutral system surfaces (`/settings`) | `meApi` cross-space `/me/*` aggregate (no `space_id` param) | explicit `writeTargetSpaceId` (defaults to the user's **Personal Space**) |
| `space` | `/spaces/:spaceId/*` (`…/today`, `…/activity`, `…/knowledge`, …) | space-scoped APIs bound to the URL's `:spaceId` | the active Space (the URL's `:spaceId`) |

**The active Space lives in the URL.** Space-scoped routes are `/spaces/:spaceId/<module>`;
`activeSpaceId` is **derived from the route params** (`useMatch('/spaces/:spaceId/*')` in
`SpaceContext`), never from local/`localStorage` state. This makes Space a first-class,
deep-linkable, per-tab dimension and removes cross-tab interference. There is no imperative
"set active space" — to switch Space you navigate to its URL. `preferredSpaceId`
(active → last visited → default → personal) is the Space targeted when following a space link
from a user-scoped surface. `localStorage` only remembers the last visited Space and the Home
write target. Logical in-space paths are composed with `spacePath()` / `useSpaceNavigate` /
`SpaceLink` (`src/core/spaceNav.tsx`); the API client's space header is synced from the URL
before page effects run.

Rules enforced by the frontend:

- **Home is user-scoped, not a Space.** `/home` shows the cross-space command center and is
  **never** filtered by the active Space. `activeSpaceId` is null on Home and only governs
  `/spaces/:spaceId/*` routes.
- **Home is not a Space Switcher option.** The switcher lists only real Spaces
  (Personal / Family / Team). Selecting one navigates to `/spaces/:spaceId/today`; it never
  mutates Home.
- **Personal Space is a real data container, not the cross-space overview.** It uses the same
  Space UI as any other Space and does not aggregate other spaces.
- **Home writes show their target.** The floating Quick Capture always shows `Save to: <Space>`
  (default Personal Space) — Home never writes silently.

### Home (`/home`) — user-level Today Command Center

Prioritizes, all cross-space with source-Space badges:
- **Personal Assistant entry** — a space-aware entry point (memory, projects, notes, wiki,
  captures, runs, proposals). Opening expands into the Assistant surface; chat execution is not wired yet,
  so it never fabricates a reply. It is labelled **Personal Assistant**, never "DirectChat".
- **Needs attention** — pending proposals, assigned tasks, failed runs.
- **Review packets** — pending proposals grouped/labelled by source Space; opening enters the
  owning Space.
- **Continue working** — recent runs and participation across spaces.
- **Suggested actions** — derived from the real aggregate (never fabricated).
- **Recent timeline** — cross-space pointers.
- **Right panel** — pending review, active runs, your tasks (useful empty states).

There is **no module gallery** on Home.

### Space Today (`/spaces/:spaceId/today`) — space-scoped dashboard

Mirrors Home's structure but limited to the active Space (`homeApi.summary`): today stats, the
product-loop strip (recent runs / open tasks / pending proposals), pending review with quick
accept/reject, intake, projects, providers, runtime, recent. Writes default to the active Space.

---

## 3a. Navigation Model

Two stable tiers plus per-scene context (`src/core/navigation.tsx`, `src/components/shell/`):

- **Global Rail** (`RAIL_ITEMS`) — narrow, icon-only desktop rail of major destinations, Home
  first and stable: Home · Inbox · Review · Knowledge · Tasks · Agents · Workspaces · Settings.
  Collapsible/expandable. On mobile this becomes the bottom tab bar (`MOBILE_TAB_ITEMS`).
- **Scene Sidebar** (`SCENES`) — second-level navigation for the current scene, changes by
  scene (Inbox / Review / Agents / Workspaces). Collapsible; when collapsed the expand
  handle is shown in the main header next to the scene title (e.g. "☰ Agents"). Home needs no
  scene sidebar. On mobile it becomes a horizontal tab strip. Filter scenes (Inbox)
  drive a single real, API-backed query param the page reads — no fabricated views; route
  scenes (Review / Agents / Workspaces) link real sibling routes. Review links the real
  `Proposals` and `Memory` surfaces; proposal-type filters (All / Memory / Knowledge / Code /
  Tasks) live inside the Proposals page because they are filters, not routes.
- **Knowledge has no scene.** It switches sub-areas via a lightweight in-header breadcrumb
  switcher (`Knowledge / Notes ▼`, `KnowledgeSectionHeader`) so each workspace owns its own
  layout — notably the backend-driven Notes collection tree, which would collide with a
  persistent section sidebar or tab strip. The Notes tree is local to the Notes workspace
  and is never a global nav tier; PARA is only the default initialization template.
- **Right Inspector** — scene/object-specific and owned by individual pages, never an
  app-level feature menu.

The old single mixed sidebar, the "perspective" (personal-as-Space) model, the
PersonalView-as-Space switcher entry, the module-gallery Home, the imperative
`setActiveSpace`/`activeOperationalSpace*` context API, and `location.state` navigation handoffs
(now `?open=` / `?draft=` URL params) have been removed. All navigation is URL-based.

---

## 4. Module Visibility Policy

Implemented modules with backend support appear in the navigation (Global Rail and, where
applicable, the scene sidebar). There is no module gallery.

Unimplemented modules must not appear as clickable primary modules. Modules are hidden using
`enabled: false, visible: false` in the frontend module registry
(`apps/web/src/modules/registry.ts`). A module with backend prerequisites not yet met must
not be navigable.

**Current module visibility state:**

| Module | Status | Notes |
|---|---|---|
| Capture | Enabled | Functional |
| Activity Inbox | Enabled | Functional |
| Sessions | Enabled | Functional |
| Tasks | Enabled | Functional |
| Runs | Enabled | Functional |
| Proposals | Enabled | Functional |
| Artifacts | Enabled | Functional |
| Memory | Enabled | Functional |
| Context Preview | Enabled | Developer tool |
| Job Queue | Enabled | Infrastructure debug tool |
| Workspaces | Enabled | Functional |
| Workspace Console | Enabled | Functional |
| Settings | Enabled | Functional |
| Capabilities | Enabled | Developer tool |
| Providers | Enabled | Functional |
| Runtime (CLI Adapters) | Enabled | Functional |
| **Home** (user-scoped) | Enabled | Cross-space command center at `/home`; **not** a Space, not in the switcher |
| **Today** (Space) | Enabled | Space-scoped dashboard at `/spaces/:spaceId/today` for the active Space |
| **Inbox** (Activity) | Enabled | Capture intake (rail label "Inbox"; route `/activity`) |
| **Review** (Proposals + Memory) | Enabled | Governance area (rail label "Review"; routes `/proposals` and `/memory`). The scene sidebar links real surfaces; proposal-type filters live inside `/proposals`. |
| **Knowledge** | Enabled | First-level unified module (rail label "Knowledge"; route `/knowledge`). `/knowledge` redirects to the last-used workspace (default `/knowledge/notes`); `/knowledge/home` is an optional overview hub, never the forced landing. Sub-areas switch via an in-header breadcrumb (no scene sidebar): **Notes** (working-knowledge workspace — configurable collection tree + open-note tabs), **Wiki** (canonical, KnowledgeItem-backed, `/knowledge/wiki`), **Sources**, **Cards** |
| **Cards** | `enabled: false, visible: false` | Standalone module hidden; surfaced as the Knowledge › Cards placeholder until the spaced-repetition model exists |
| Time | `planned: true` | Shows "soon" badge |

Future modules (Editor, Calendar, Automation, Knowledge Graph) should only be enabled when
backend support exists. Do not add them to the registry as clickable modules before that.

---

## 5. Error and Empty-State Policy

### Authentication

- 401 dispatches the `auth:required` event → `RequireAuth` redirects to `/login`.
- Per-page auth errors should show "Session expired — sign in again" before redirect.

### 404 / Not Accessible

- 404 for any durable object must render as: **"Not found or not accessible"**
- Do not reveal whether the object exists in another space.
- Do not show raw server error text.
- Show a contextual empty state with a back link, not a toast.

Affected pages: Sessions detail, Task detail, Activity detail, Run detail.

### Empty States

| Surface | Empty-state guidance |
|---|---|
| Activity Inbox (raw) | "Nothing to process. Use Quick Capture to save a thought." → link to Capture |
| Proposal Inbox | "No pending proposals. Process activity or ask an agent to generate some." |
| No runtime configured | "No runtime adapter configured." → link to Runtime settings |
| No recent sessions | "Start by asking an agent or capturing a thought." |
| Unsupported proposal type | "This proposal type cannot be applied yet. Reject to dismiss it." |
| Hidden task (404) | "This task is not accessible in your current space or visibility level." |
| Board with filtered tasks | Note: "Tasks filtered by your visibility in this space. Some board items may not be shown." |

### Proposal Accept/Reject

Errors on proposal accept/reject must distinguish:
- Unsupported proposal type → friendly explanation, not raw 422
- Egress approval required → handled by the `EgressReviewNotice` component

---

## 6. Current Frontend Status

The frontend is ready for personal dogfooding. The core product loop is usable:
- Capture → Activity Inbox → Consolidate → Proposals → Accept/Reject → Memory/Task
- Sessions, Runs, Artifacts, Memory, Workspaces, Settings are functional.
- Auth, space context, and RequireAuth wrapper are correctly wired.

**Non-blocking follow-ups (discovered during use):**

- ✅ **Done:** Space-scoped routes are now URL-scoped (`/spaces/:spaceId/*`) and deep-linkable;
  the active Space is read from the route, and all in-app navigation is URL-based (no
  `location.state` handoffs). Accessing a Space the user can't see falls back to the preferred
  Space. (Backend access control is the source of truth — a shared-Space URL is only viewable by
  its members; non-members get the standard authz error, not silent space-switching.)
- Cross-space Home aggregates are limited to what `/me/*` exposes (proposals, tasks, runs,
  participation, timeline). "Captures waiting" / "review packets ready" / "cards due" per Space
  need cross-space aggregate endpoints before they can appear on Home.
- Quick Capture supports text and links; file/image drag-drop and voice are shown as
  coming-soon (no upload endpoint yet).
- Assistant chat execution is not wired; the Home Assistant is an entry point only.
- Activity / Run / Artifact cross-linking can be improved (e.g., post-consolidate navigation
  to generated proposals; post-accept link to created memory record).
- Board visibility notice can be added before heavier shared-space use.

These are improvements to collect from real use, not pre-conditions for dogfooding.

---

## 7. Backend Security Boundaries the Frontend Must Respect

| Backend rule | Frontend implication |
|---|---|
| All data routes require `get_identity` | Every data call inside `RequireAuth`; 401 event dispatched by `client.ts` |
| Sessions are user-owned within a space; cross-space access → 404 | Sessions detail must treat 404 as "not accessible" |
| Task visibility: private/restricted tasks return 404 on direct access | Task detail shows "not accessible" empty state |
| Board task list is filtered by visibility | Board view should indicate filtered content is possible |
| Activity process/consolidate enforces visibility | Same 404 handling in Activity detail |
| Proposals: accept/reject → 422 for unsupported types | Proposals page distinguishes unsupported-type errors |
| Egress approval is a cross-space exception | Handled by `EgressReviewNotice` component |
| Raw activity is not memory — it is input awaiting processing | Labels reflect this: Activity Inbox = captured input |

---

## 8. Future Modules — Prerequisites Before Enabling

| Module | Backend prerequisite |
|---|---|
| Cards | Spaced-repetition card model + review API |
| Time | Time entry model + activity linkage |
| Editor | File editor backend + save API |
| Calendar | Calendar/scheduling model |
| Automation | Trigger/workflow model |
| Knowledge Graph | Graph query API |
