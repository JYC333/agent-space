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

Home should remain a thin UI over backend aggregate read models. Cross-space
Home data comes from `/api/v1/me/*`; space Today data comes from
`/api/v1/home/summary`. When Home needs another count, queue, or rollup, add or
extend a backend read model instead of reconstructing proposal/activity/runtime
logic by calling every domain API separately from the browser.

### Space Today (`/spaces/:spaceId/today`) — space-scoped dashboard

Mirrors Home's structure but limited to the active Space (`homeApi.summary`): today stats, the
product-loop strip (recent runs / open tasks / pending proposals), pending review with quick
accept/reject, sources, projects, providers, runtime, recent. Writes default to the active Space.

---

## 3a. Navigation Model

Two stable tiers plus per-scene context (`src/core/navigation.tsx`, `src/components/shell/`):

- **Global Rail** (`RAIL_ITEMS`) — narrow, icon-only desktop rail of major destinations, Home
  first and stable: Home · Inbox · Library · Sources · Review · Knowledge · Tasks · Projects · Agents · Workspaces · Settings.
  Collapsible/expandable. On mobile this becomes the bottom tab bar (`MOBILE_TAB_ITEMS`).
- **Scene Sidebar** (`SCENES`) — second-level navigation for the current scene, changes by
  scene (Inbox / Library / Review / Agents / Workspaces). Collapsible; when collapsed the expand
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

## 3b. Interaction State And Refresh Policy

Frontend pages must preserve the user's local navigation context while mutations complete.

- Route-level, detail-page, settings-page, and sidebar tabs must be controlled (`value` +
  `onValueChange`), not `defaultValue`, unless the component is truly static and never
  remounts after data changes.
- A save/create/run action must not reset the active tab, selected panel, open advanced
  section, or current filter. Reset local UI state only when the entity id, route scope, or
  explicit user action changes.
- Prefer local state updates from mutation responses (`setItem`, `upsert`, append/prepend
  returned rows) over full `load()` reloads. Use a background refresh only for secondary
  read models that the mutation response cannot provide.
- Initial skeleton/loading states are for first load or route/entity changes. Refresh buttons
  and post-mutation reloads should keep existing content visible and show only local busy
  indicators.
- Tests for tabbed/detail/settings pages should cover the common regression: perform a
  mutation from a non-default tab and assert the active tab remains selected and the page does
  not re-run the full initial load unless that is intentionally required.

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
| Workspace Snapshot Settings | Enabled | Space-admin-only UI for snapshot retention policy (`/workspace-snapshot-settings`); configures `snapshot_retention_days` / `snapshot_max_count` at space and per-workspace level |
| Retrieval Settings | Enabled | Space-scoped UI for the `retrieval.space.settings` scoped setting, `space_retrieval_prompts`, and retrieval `provider_task_policies` (`/retrieval-settings`); members can view retrieval models and the advanced collapsed rewrite prompt, while owner/admin users can edit default search mode, retrieval embedding dimensions/models, native rerank model, query-rewrite chat model and prompt, rerank/rewrite availability, rewrite/cache/trace defaults, and default result budget |
| Settings | Enabled | Functional |
| Capabilities | Enabled | Capability/skill control-plane; developer-heavy but user-visible for review |
| Providers | Enabled | Functional; provider cards and create/edit forms show capability labels for Chat, Embeddings, and Native rerank, and creation is split into chat-provider, embedding-provider, and rerank-provider flows so retrieval-only providers are not confused with ordinary chat providers |
| Runtime (CLI Adapters) | Enabled | Functional |
| Agent Rooms | Enabled | Space-scoped room surface at `/agent-groups`; starts on create/list, then opens a chat-style room with conversation history and a Tiptap composer. Creating a room only creates the room and members; goal is optional room metadata that can be added or edited later. The first user message creates the room/root run, with the room goal passed as background instruction only when present rather than inserted as a synthetic chat message. User messages go to the manager agent by default when no structured mention is present. Structured `@agent` mention tokens are parsed into a visible route preview before send: one mention routes that segment directly to that agent, adjacent mentions fan out the same segment in parallel, and separated mention groups create segmented recipient prompts. The user can explicitly switch the turn to Agent coordination, which routes the full message to the manager for decomposition/delegation instead of directly fanning out. Room members are the automatic `agent.delegate` target pool for every active room agent, not only the manager; `agent.wait_for_results` lets any room agent wait for sibling/delegated same-room results when its answer depends on them. Member capability snapshots are included in room tool context. Chat history treats recipient/delegating agent `agent_message` rows as the main conversation and folds child-agent delegation details by user turn by default; advanced lifecycle controls, trace/run links, and policy records live behind room settings / advanced audit rather than the chat first screen. |
| **Home** (user-scoped) | Enabled | Cross-space command center at `/home`; **not** a Space, not in the switcher |
| **Today** (Space) | Enabled | Space-scoped dashboard at `/spaces/:spaceId/today` for the active Space |
| **Inbox** (Activity) | Enabled | Capture inputs (rail label "Inbox"; route `/activity`) |
| **Library** | Enabled | Space-scoped, per-user reading surface at `/library` for Sources-derived items and digests. `/library` is a shell that defaults to `/library/items`; scene-sidebar routes keep `All Items` and `Digests` as siblings, with soft type filters under `All Items` (`/library/items/articles`, `/library/items/emails`, `/library/items/videos`, `/library/items/podcasts`, `/library/items/pdfs`). It only shows items/digests from sources the current user follows, plus that user's manual unconnected URLs. Source digest detail routes live under `/library/digests/:connectionId/:date`; single-item readers live under `/library/items/:itemId` or the day-scoped `/library/digests/:connectionId/:date/items/:itemId`. |
| **Sources** | Enabled | Space-scoped information stream control plane at `/sources`; owns RSS/Atom/web page connections, owner/visibility metadata, opt-in delivery subscriptions, source-level health, scan state, and source governance. Pending source recommendations show source metadata and Follow/Dismiss/Mute actions without exposing the item stream until the user follows. Project item feeds do not live here. |
| **Project Sources** | Enabled | Project workflow surface at `/projects/:projectId/sources`; binds existing Sources directly to a Project, shows project source health, runs scans/backfills, pauses/removes bindings, renders the materialized project source item collection from `/sources/project-items`, syncs the Project corpus from source links/evidence/decisions, and links to the project graph lens. Academic projects open Graph with `lens_id=academic_citation_v1`. |
| **Project Presets** | Enabled | Creation-time Project shape selector for code-owned workflow packs. The optional `academic_research` preset is selected when creating a Project and then drives the Project-specific shell, visual treatment, and primary operations; it is not a post-create enable toggle. It reuses Project Sources, Project Corpus, and Project Graph for literature monitoring, paper screening, corpus triage, and citation/relation visualization. |
| **Review** (Proposals + Memory) | Enabled | Governance area (rail label "Review"; routes `/proposals` and `/memory`). The scene sidebar links real surfaces; proposal-type filters live inside `/proposals`. |
| **Knowledge** | Enabled | First-level unified module (rail label "Knowledge"; route `/knowledge`). `/knowledge` redirects to the last-used workspace (default `/knowledge/notes`); `/knowledge/home` is an optional overview hub, never the forced landing. Sub-areas switch via an in-header breadcrumb (no scene sidebar): **Notes** (working-knowledge workspace — configurable collection tree + open-note tabs), **Wiki** (canonical, KnowledgeItem-backed, `/knowledge/wiki`), **Sources** (backend source CRUD exists; current frontend is list-only evidence browsing), **Cards** |
| **Graph** | Enabled | Space-scoped relationship projection at `/graph`; renders the shared `GraphProjection` contract through `apps/web/src/components/graph/`, reads core `/api/v1/graph/*`, persists per-user view state under `scope_key='core:graph'`, `core:graph:<lens_id>`, `project:graph:<project_id>`, or `project:graph:<project_id>:<lens_id>`, and remains read-only over visible `space_objects` / `object_relations`. `?project_id=` narrows the graph to active object-backed Project corpus rows; `?lens_id=academic_citation_v1` applies the academic citation/authorship lens. |
| **Cards** | `enabled: false, visible: false` | Standalone module hidden; surfaced as the Knowledge › Cards placeholder until the spaced-repetition model exists |
| Time | `planned: true` | Shows "soon" badge |

Future modules (Editor, Calendar, Automation, and domain-specific graph surfaces beyond the
core Graph page) should only be enabled when backend support exists. Do not add them to the
registry as clickable modules before that.

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
- Project creation includes a Project type selector. Selecting Academic Research
  stores `settings_json.preset = "academic_research"` and routes the resulting
  Project into an Academic Research shell with literature monitoring, paper
  screening/corpus, arXiv source setup, and citation graph actions. The preset
  is not exposed as a post-create enable/use/clear toggle. Project detail pages
  include a Research workflow panel that creates
  optional project-scoped saved workflow presets, builds run drafts directly
  from templates or saved presets, and queues normal agent runs. Runtime profile
  selection is hidden when an Agent has only one enabled default runtime.
  Project pages show compact Sources summaries and recent Sources
  recommendations, then hand off project collection work to
  `/projects/:projectId/sources`; global source-level management remains
  `/sources`. The
  Capabilities page is the imported skill/package review surface. Library (`/library`)
  is the shell for per-user Sources-derived reading, with scene-sidebar routes
  for All Items and Digests; item type filters live under All Items rather than
  becoming top-level Library categories. Activity Inbox daily source rows point
  into `/library/digests/:connectionId/:date`, source recommendation rows point
  into `/sources?view=pending`, and project source collection rows point into
  `/projects/:projectId/sources`; Inbox does not render source item or digest
  bodies.
  Artifacts render structured Research outputs when possible.

**Non-blocking follow-ups (discovered during use):**

- ✅ **Done:** Space-scoped routes are now URL-scoped (`/spaces/:spaceId/*`) and deep-linkable;
  the active Space is read from the route, and all in-app navigation is URL-based (no
  `location.state` handoffs). Accessing a Space the user can't see falls back to the preferred
  Space. (Backend access control is the source of truth — a shared-Space URL is only viewable by
  its members; non-members get the standard authz error, not silent space-switching.)
- Cross-space Home aggregates are limited to what `/me/*` exposes (proposals, tasks, runs,
  participation, timeline). "Captures waiting" / "review packets ready" / "cards due" per Space
  need backend aggregate endpoints before they can appear on Home; the frontend should not fan
  out across raw domain APIs to reconstruct those counts.
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
