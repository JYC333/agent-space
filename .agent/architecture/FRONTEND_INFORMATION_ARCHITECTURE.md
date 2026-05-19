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

## 3. Home Page Direction

Home acts as the command center, not a module gallery.

Home prioritizes:
- **Needs attention** — pending proposals, unprocessed activity, failed runs, blocked tasks
- **Quick input** — QuickCapture composer with mode tabs
- **Continue working** — recent sessions and recent runs with status
- **Pending review** — proposal inbox summary in the right sidebar
- **Runtime status** — adapter health in the right sidebar
- **Recent sessions / runs / captures** — recent items panel

The module gallery (all enabled modules grouped by category) is secondary. It should not
occupy the primary viewport on first load.

---

## 4. Module Visibility Policy

Implemented modules with backend support appear in the primary navigation and gallery.

Unimplemented modules must not appear as clickable primary modules. Modules are hidden using
`enabled: false, visible: false` in the frontend module registry
(`frontend/src/modules/registry.js`). A module with backend prerequisites not yet met must
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
| Personal View | Enabled | Cross-space aggregation |
| **Today** | `planned: true` | Home serves the command-center role; Today shows "soon" badge |
| **Wiki** | `enabled: false, visible: false` | Hidden until backend Wiki model exists |
| **Cards** | `enabled: false, visible: false` | Hidden until backend spaced-repetition model exists |
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

- Home gallery can be collapsed or demoted further so the command-center content is primary.
- Home can add stronger Needs Attention and Continue Working sections.
- Activity / Run / Artifact cross-linking can be improved (e.g., post-consolidate navigation
  to generated proposals; post-accept link to created memory record).
- Sessions UI is functional but not a polished chat interface.
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
| Wiki | Wiki entity model + CRUD API |
| Cards | Spaced-repetition card model + review API |
| Time | Time entry model + activity linkage |
| Editor | File editor backend + save API |
| Calendar | Calendar/scheduling model |
| Automation | Trigger/workflow model |
| Knowledge Graph | Graph query API |
