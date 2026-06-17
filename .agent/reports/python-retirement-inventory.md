# Python Retirement Inventory

> **Status:** temporary report (per `.agent/INDEX.md` §7). Not source of truth.
> Produced 2026-06-15 as preparation for a controlled TypeScript backend
> re-platform. Repository facts are grounded in inspection of `backend/app/`,
> `control-plane/src/`, `backend/migrations/`, and `apps/web/src/`. Lines marked
> **(uncertain)** need confirmation before action.
>
> Scope: this catalogs what the Python backend (`backend/`) still owns and what
> must move to or be retired from the TypeScript control plane before `backend/`
> can be deleted. It does not change code. Companion reports:
> [`ts-reuse-in-replatform.md`](ts-reuse-in-replatform.md),
> [`ts-backend-replatform-plan.md`](ts-backend-replatform-plan.md). Target model:
> [`../architecture/TS_BACKEND_TARGET.md`](../architecture/TS_BACKEND_TARGET.md).

## How to read the ownership columns

- **Authority today** — who actually decides the response *right now* under the
  dev/test/prod env templates (which opt every completed `CONTROL_PLANE_*_AUTHORITY`
  into `ts`). "Python (proxied)" means the route falls through
  `control-plane/src/pythonFallback/proxy.ts` to Python unchanged.
- **Action** — `migrate` (must become TS-native), `retain` (intentionally stays
  Python only until its domain migrates; not accidental), `retire` (route/behavior
  should be deleted, not ported), `defer` (future feature, out of re-platform scope).
- **Blocks deletion** — whether this must be resolved before `backend/` can be
  removed. Everything Python-owned blocks deletion by definition; the column flags
  the *hard* blockers (deep dependencies many things rely on).

Authority switches and their dependency order live in
`control-plane/src/config.ts`; current split is in
[`../architecture/TS_CONTROL_PLANE_OWNERSHIP.md`](../architecture/TS_CONTROL_PLANE_OWNERSHIP.md).

---

## 1. Python-owned public `/api/v1` routes

Routes are grouped by Python module (`backend/app/<module>/api.py`). Method/path
are the registered decorators (prefix from `APIRouter(prefix=...)`, all mounted
under `/api/v1`). "Frontend caller" is the `apps/web/src/modules/<x>` feature that
drives the route via the single client `apps/web/src/api/client.ts`.

### 1.1 Identity, spaces, membership — `auth`, `spaces`, `me`, root

| Method | Path | Python file | Domain | Frontend caller | TS equivalent today | Action | Hard blocker |
|---|---|---|---|---|---|---|---|
| GET | `/auth/introspect` | `auth/api.py` | auth | (internal) | **consumed by every TS module** via `providers/identity.ts` | migrate | **YES** |
| POST/GET/DELETE | `/auth/keys[/{id}]` | `auth/api.py` | auth | settings | none | migrate | yes |

> **API-key correction:** `ApiKeyService` (`auth/api_key.py`) methods are
> **feature-gated** — `create`/`list`/`revoke` call `feature_not_implemented("api_keys")`
> unless `feature_gates.API_KEYS_DB_PERSISTED` is on, and there is **no `api_keys`
> table** in the schema. The live auth path is **session-cookie + Google OAuth**
> (`UserSessionService` → `user_sessions`) plus `SpaceMembership`. Port the
> session/OAuth path first; treat DB-persisted API keys as an optional, currently-off
> capability.
| GET | `/auth/google`, `/auth/google/callback` | `auth/api.py` | auth | settings/login | none (proxied verbatim, OAuth-safe) | migrate | yes |
| POST | `/auth/logout` | `auth/api.py` | auth | shell | none | migrate | yes |
| GET | `/auth/google-configured` | `main.py` | auth | login | none | migrate | no |
| GET | `/me`, `/me/spaces` | `auth/api.py` (`me_router`) | auth | shell/space switch | none | migrate | **YES** |
| GET | `/health`, `/api/v1/features` | `main.py` | system | shell/status | `system` module exposes its own `/api/v1/control-plane/*`; `/features` itself still Python | migrate/retire | no |
| POST | `/spaces`, GET `/spaces/{id}`, `/spaces/{id}/members` | `spaces/api.py` | spaces | settings/space | none | migrate | **YES** |
| POST | `/spaces/{id}/invitations`, POST `/invitations/{token}/accept` | `spaces/api.py` | spaces | settings | none | migrate | yes |

> `GET /auth/introspect` and `GET /me`/`/me/spaces` are the **deepest** blockers:
> every TS-owned DB module calls `introspect` for `space_id`/`user_id` before any
> query (`control-plane/src/modules/providers/identity.ts`). Until TS owns identity
> natively, no module can stand alone and the fallback proxy cannot be deleted.

### 1.2 TS-owned-at-edge read models (Python still the read authority)

These are claimed by `frontendSupport` / domain modules as TS *edge* routes but
**forwarded to Python** through `ports/pythonHttp.ts` (not the fallback proxy).

| Method | Path | Python file | Domain | Frontend caller | TS equivalent today | Action | Hard blocker |
|---|---|---|---|---|---|---|---|
| GET | `/home/summary` | `home/api.py` | home/aggregation | home | `frontendSupport` forwards | migrate | no |
| GET | `/me/summary`, `/me/timeline`, `/me/tasks`, `/me/pending` | `me/api.py` | aggregation | today/home | `frontendSupport` forwards | migrate | no |
| GET | `/workspace-console/workspaces[...tree/file/git]`, `/runtimes`, `/sessions[/{id}]` | `workspace_console/api.py` | workspaces | workspace_console | `frontendSupport` forwards (reads only) | migrate | no |

### 1.3 Memory & context — `memory`

| Method | Path | Python file | Domain | Frontend caller | TS equivalent today | Action | Hard blocker |
|---|---|---|---|---|---|---|---|
| GET | `/memory`, `/memory/{id}`, POST `/memory/search` | `memory/api.py` | memory | memory | **TS-owned** (fixed TS) | (done) retain TS | no |
| POST/PATCH/DELETE | `/memory[/{id}]` (proposal create) | `memory/api.py` | memory | memory | **TS-owned** proposal creation | (done) retain TS | no |
| POST | `/memory/consolidation/run` | `memory/api.py` | memory | (manual/job) | none | migrate | yes |
| POST | `/context/build` | `memory/context_api.py` | context | (runtime) | none — TS run path uses native context prepare; Python port retired | retain only digest/job paths | no |
| POST | `/context/digests/refresh` | `memory/context_api.py` | context | (job) | none | migrate | yes |

### 1.4 Sessions, agents, chat — `sessions`, `agents`

| Method | Path | Python file | Domain | Frontend caller | TS equivalent today | Action | Hard blocker |
|---|---|---|---|---|---|---|---|
| POST/GET | `/sessions[/{id}]`, `/sessions/{id}/messages` | `sessions/api.py` | sessions | sessions/chat | **TS-owned** (fixed; no switch) | (done) retain TS | no |
| POST | `/sessions/{id}/reflect` | `sessions/api.py` | sessions | (post-run) | none | migrate | yes |
| POST/GET/PATCH/DELETE | `/agents[...]`, versions, config-proposals, default-assistant, settings | `agents/api.py` | agents | agents | none | migrate | yes |
| GET | `/agents/runs[...]`, `/agents/{id}/runs` | `agents/api.py` | agents/runs | agents/runs | none (run reads Python) | migrate | yes |
| POST | `/agents/{id}/run`, `/agents/{id}/runs` | `agents/api.py` | runs (create) | agents | **TS-owned** in control-plane agents module | done | no |
| POST | `/agents/{id}/chat` | `agents/api.py` | chat | chat | **TS-owned** (fixed TS, native context/run creation) | retain TS | no |

### 1.5 Runs — `runs`

| Method | Path | Python file | Domain | Frontend caller | TS equivalent today | Action | Hard blocker |
|---|---|---|---|---|---|---|---|
| POST | `/runs/{id}/execute` | `runs/api.py` | runs | runs | **TS-owned**; native TS context.prepare | retain TS | no |
| PATCH | `/runs/{id}/stop` | `runs/api.py` | runs | runs | **TS-owned** | (done) retain TS | no |
| POST | `/runs/preflight` | `runs/api.py` | runs | runs | none | migrate | yes |
| GET | `/runs`, `/runs/{id}`, `/{id}/status` | `runs/api.py` | runs | runs | **TS-owned** | done | no |
| GET | `/{id}/trace` | `runs/api.py` | runs | runs | **TS-owned** safe replay spine | done | no |
| GET | `/{id}/activities`, `/artifacts`, `/proposals`, `/steps`, `/events` | `runs/api.py` | runs | runs | child read surfaces still Python except SSE event edge | migrate with activity/artifacts/proposals | yes |
| POST/GET | `/{id}/finalize`, `/finalization(s)`, `/evaluation(s)` | `runs/api.py` | runs | runs | **TS-owned** deterministic finalization/evaluation | done | no |

### 1.6 Proposals & approvals — `proposals`, `personal_memory_grants`

| Method | Path | Python file | Domain | Frontend caller | TS equivalent today | Action | Hard blocker |
|---|---|---|---|---|---|---|---|
| GET | `/proposals`, `/proposals/{id}` | `proposals/api.py` | proposals | review/memory | **TS-owned** fixed route/read model | (done) retain TS | no |
| POST | `/proposals/{id}/accept`, `/reject`, `/approvals/egress-granting-user` | `proposals/api.py` | proposals | review | **TS-owned** fixed route/apply orchestration; memory appliers registered; unregistered types fail closed | migrate non-memory target appliers with owning domains | yes |
| POST/GET | `/personal-memory-grants[...]` preview/create/list/revoke/audit | `personal_memory_grants/api.py` | memory/policy | settings | none | migrate | yes |

### 1.7 Providers & credentials — `providers`, `credentials` (TS-owned)

| Method | Path | Python file | Domain | Frontend caller | TS equivalent today | Action | Hard blocker |
|---|---|---|---|---|---|---|---|
| GET/POST/PATCH/DELETE | `/providers[...]`, `/catalog`, `/litellm-providers`, `/{id}/models`, `/{id}/test`, `/chat` | `providers/api.py` | providers | providers | **TS-owned** (fixed; no switch) | (done) retain TS | no |
| GET/POST | `/credentials/cli/*` profiles/detect/methods/login(stream/input)/status | `credentials/api.py` | credentials | providers/settings | **TS-owned** (fixed; no switch) | (done) retain TS | no |

> Provider/credential routes are the most complete TS migration. Python still
> hosts the route *files* but the fallback proxy never serves them under the TS
> authority templates. They are a retirement candidate once Python is deleted, not
> a migration target.

### 1.8 Activity, intake, knowledge — `activity`, `intake`, `knowledge`

| Method | Path | Python file | Domain | Frontend caller | TS equivalent today | Action | Hard blocker |
|---|---|---|---|---|---|---|---|
| POST/GET/PATCH | `/activity[...]` create/upload/list/get/review/archive/consolidate/summary-runs | `activity/api.py` | activity | activity/capture | none | migrate | yes |
| GET/POST/PATCH | `/intake/*` connectors/connections/items/jobs/evidence/evidence-links/workspace-profiles/summary-runs | `intake/api.py` | intake | intake | none | migrate | yes |
| GET/POST/PATCH/DELETE | `/knowledge/*` items/relations/sources/summary/entity-links | `knowledge/api.py` | knowledge | knowledge | none | migrate | yes |
| GET/POST/PATCH/DELETE | `/notes/*`, `/notes/collections/*` | `knowledge/api.py` (`notes_router`) | knowledge | knowledge | none | migrate | yes |

### 1.9 Workspaces, artifacts, tasks, projects — operator/work surfaces

| Method | Path | Python file | Domain | Frontend caller | TS equivalent today | Action | Hard blocker |
|---|---|---|---|---|---|---|---|
| GET/POST/PATCH/DELETE | `/workspaces[...]`, `/scan` | `workspaces/api.py` | workspaces | workspaces | none | migrate | yes |
| GET/PATCH | `/workspace-profiles/{id}` | `workspace_profiles/api.py` | workspaces | workspaces | none | migrate | no |
| GET | `/workspace-console/sessions[/{id}]` (read) | `workspace_console/api.py` | workspaces | workspace_console | `frontendSupport` forwards reads | migrate | no |
| POST | `/workspace-console/sessions`, `/sessions/{id}/run`, `/stop` (writes) | `workspace_console/api.py` | workspaces | workspace_console | **stub: `feature_not_implemented("workspace_console_sessions")`** | retire/defer | no |
| GET | `/artifacts`, `/artifacts/{id}`, `/{id}/export` | `artifacts/api.py` | artifacts | artifacts/runs | none | migrate | yes |
| POST/GET/PATCH | `/tasks[...]` + `/{id}/runs`, `/artifacts`, `/proposals`, `/evaluations` | `tasks/api.py` | tasks | tasks | none | migrate | yes |
| GET/POST/PATCH | `/boards[...]`, `/{id}/tasks` | `tasks/board_api.py` | tasks | tasks | none | migrate | no |
| GET/POST/PATCH/DELETE | `/projects[...]`, `/{id}/workspaces`, `/summary` | `projects/api.py` | projects | projects | none | migrate | no |

### 1.10 Automation, jobs, deployment, ops — control surfaces

| Method | Path | Python file | Domain | Frontend caller | TS equivalent today | Action | Hard blocker |
|---|---|---|---|---|---|---|---|
| POST/GET/PATCH | `/spaces/{id}/automations[...]`, `/{id}/fire` | `automation/api.py` | automations | automations | none | migrate | yes |
| GET/POST | `/jobs`, `/jobs/handlers`, `/jobs/{id}[/events]`, `/{id}/cancel` | `jobs/api.py` | jobs | job_queue | none (durable queue is Python) | migrate | **YES** |
| GET/PUT/PATCH/POST | `/daily-capture-report/*` settings/run/reports | `daily_reports/api.py` | automations/reports | daily_reports | none | migrate | no |
| POST/GET | `/deployments/jobs`, `/jobs/{id}` | `deployment/api.py` | deployment | settings | none — **create/get are stubs: `feature_not_implemented("deployment_jobs")`**; `DeployerClient` socket exists | retire/defer | no |
| GET/POST | `/system/backups`, `/manual` | `backups/api.py` | jobs/ops | settings | none | migrate | yes |
| GET/POST | `/evolution/*` summary/targets/signals/runs/proposals/validation | `evolution/api.py` | (future) | evolution | none | defer/migrate | no |

### 1.11 Catalog/registry surfaces (read = TS, write/lifecycle = Python)

| Method | Path | Python file | Domain | Frontend caller | TS equivalent today | Action | Hard blocker |
|---|---|---|---|---|---|---|---|
| GET/POST | `/capabilities[...]`, `/reload` | `capabilities/api.py` | capabilities | capabilities | catalog *reads* via `catalog` module; DB registry Python | migrate | no |
| GET/POST | `/agent-templates[...]`, versions, `/{id}/agents` | `agent_templates/api.py` | agents/templates | agents | catalog *reads* via `catalog` module | migrate | no |
| GET | `/runtime-tool-bindings[...]` | `runtime_tool_bindings/api.py` | runtimeAdapters | runtime_tools | binding read only; `runtimeTools` module owns install/status | migrate | no |
| GET | `/execution-planes[...]` | `execution_planes/api.py` | spaces/infra | settings | none | migrate | no |
| GET/POST/DELETE | `/source-pointers[...]` | `source_pointers/api.py` | activity/provenance | (internal) | none | migrate | no |

---

## 2. Python internal ports (cross-language seams)

These are explicit service-to-service ports (not the fallback proxy). A TS module
owns the client-facing command but calls into Python for the underlying
transaction/read. They are authenticated with `CONTROL_PLANE_INTERNAL_TOKEN`
(`x-agent-space-internal-token`, validated in both directions). **These ports are
the true migration glue: each must be replaced by a TS-native implementation, then
the port deleted.**

| Port route | Operations | TS caller | Owner domain | Writes performed | TS-native replacement needed |
|---|---|---|---|---|---|
| `GET /api/v1/auth/introspect` | identity introspection (space_id/user_id from token/cookie) | `modules/providers/identity.ts` (all TS DB modules) | auth | none (read) | **Native TS identity middleware** (Phase 2). Highest priority. |
| `/internal/runs-context` (`runs/internal_api.py`) | `policy.enforce`, ~~`context.prepare`~~ (retired), `artifact.persist`, `proposal.create`, `workspace.prepare`, `workspace.cleanup`, `finalization.finalize` | `modules/runs/pythonContextPorts.ts` | runs/workspace/artifacts/proposals | `runs.sandbox_path`, artifacts, proposals, run finalization rows, policy decision records | context.prepare is TS-native; retire remaining operations with Phases 6/9 |
| `/internal/stage6-context` (`sessions/internal_api.py`) | `session_summary.get_latest`, `context.build`, `memory.read`, `memory.proposal_create` | ~~`modules/memory/pythonStage6Ports.ts`~~ (deleted, was unused) | sessions/context/memory | proposals (memory_create), memory read traces | TS context build + memory read/proposal-create complete |
| `/internal/agents-chat` (`agents/internal_api.py`) | ~~`prepare-run`~~ (retired), `context-candidates`, `create-run` | ~~`pythonChatTurnPrep.ts`~~ (deleted) | agents/chat/runs | `runs` rows (legacy create-run) | TS-native chat context/run creation; combined prepare-run fails closed |
| `/internal/proposals-context` (`proposals/internal_api.py`) | `proposal.accept`, `proposal.reject`, `proposal.egress_approval`, `memory.apply_gate` | none in the current TS proposal route | proposals/policy | legacy Python compatibility writes | **Phase 6 done:** TS apply service + applier registry replaced the TS caller; delete backend port with Python |
| `POST /internal/runs/execute` | TS-owned internal execute port (called by Python run-create path / job) | `modules/runs/routes.ts` | runs | run execution evidence | already TS — retire Python caller side (Phase 4) |
| `runtimeHost` internal route (Python → TS) | provider-backed in-process host turn (`ts_agent_host`) | Python `runtimes/runtime_host_client.py` → TS `modules/runtimeHost` | runtimeAdapters | none (returns adapter result) | already TS; Python client retires with run-create (Phase 3–4) |

> Directionality note: most ports are **TS → Python** (TS owns the edge, Python
> owns the transaction). The `runtimeHost` port is the one **Python → TS** seam
> (Python `runs` invokes the TS in-process model runtime). The re-platform flips
> the remaining TS → Python ports to TS-native and deletes both the port route and
> its TS client.

---

## 3. Python jobs, workers, schedulers, hooks

There are **two distinct job systems** in the Python backend.

### 3.1 Generic durable job queue

`PostgresQueueService` (`jobs/queue.py`) + `JobHandlerRegistry` (`jobs/registry.py`)
+ background worker (`jobs/worker.py`, started in `main.py` lifespan). Handlers are
registered per-module via `register_job_handlers` hooks.

| Job type | Handler file | Scheduler/source | Tables touched | TS equivalent? | Migration priority |
|---|---|---|---|---|---|
| `agent_run` | `jobs/handlers.py` | enqueue from run/task create; automation | `runs`, `run_steps`, `run_events`, artifacts | **YES** — TS `modules/runs/jobWorker.ts`; Python handler fails closed via `runs.authority` | done (close Python path) |
| `memory_consolidation` | `jobs/handlers.py` | `activity` consolidate; manual | `proposals`, `activity_records` | no | high |
| `daily_capture_report` | `daily_reports/handlers.py` | `daily_report_scheduler` | `runs`, artifacts, `proposals`, `daily_capture_report_settings` | no | medium |

### 3.2 Intake `ExtractionJob` system (separate)

`ExtractionJob` (table `extraction_jobs`) is a **domain-specific** job model, not on
the generic queue. Rows are created pending and executed by `intake/service.py`
methods (`run_pending_job`, `_execute_text_extraction`, `_execute_internal_normalization`,
`_execute_snapshot`) **invoked from intake API routes** (`POST /intake/connections/{id}/scan`,
`POST /intake/jobs/{id}/run`). **(uncertain)** No dedicated background worker or
scheduler drives these in `main.py`; they appear to run synchronously on request.
Confirm before assuming auto-processing.

| Job type | Handler | Trigger | Tables touched | TS equivalent? | Priority |
|---|---|---|---|---|---|
| `connection_scan` | `intake/service.py` | `/intake/connections/{id}/scan` | `extraction_jobs`, `intake_items`, `source_connections` | no | medium |
| `manual_url` | `intake/service.py` | `/intake/items/manual-url` | `extraction_jobs`, `intake_items` | no | medium |
| `extract_text` | `intake/service.py` | item action / scan | `extraction_jobs`, `intake_items`, `extracted_evidence` | no | medium |
| `snapshot` | `intake/service.py` | item action | `extraction_jobs`, `source_snapshots` | no | low |
| `normalize_activity` / `normalize_artifact` / `normalize_run_event` | `intake/service.py` | activity/artifact/run-event normalization | `extraction_jobs`, `activity_records`/`artifacts`/`run_events`, `extracted_evidence` | no | medium |

### 3.3 Schedulers (`SchedulerRegistry`, started in `main.py` lifespan)

| Scheduler | Source file | Cadence (config) | Effect | TS equivalent? | Priority |
|---|---|---|---|---|---|
| `daily_report_scheduler` | `daily_reports/scheduler.py` | `daily_report_scheduler_interval_seconds` | scans + enqueues `daily_capture_report` jobs | no | medium |
| `automation_scheduler` | `automation/scheduler.py` | `automation_scheduler_interval_seconds` | `AutomationScheduler.scan_and_fire` → enqueues jobs / fires automations | no | high |
| `memory_access_log_retention` | `memory/access_log.py` | `memory_access_log_prune_interval_seconds` | prunes `memory_access_logs` | no | low |
| backup scheduler | `backups/scheduler.py` | `backup_interval_hours` | snapshot of data root → `backup_root` | no | low |

### 3.4 Lifecycle hooks (module-registered registries)

| Hook registry | Built in | Registered by modules | Purpose |
|---|---|---|---|
| `SpaceCreatedHookRegistry` | `spaces/hooks.py` | `memory`, `knowledge`, `execution_planes` (`space_hooks`) | per-space default rows on Space create |
| `RunFinalizedHookRegistry` | `runs/lifecycle_hooks.py` | `tasks` (`run_lifecycle`) | post-run side effects on terminal Run |
| `ProposalApplierRegistry` | `proposals/applier_registry.py` | see §4 | dispatch proposal apply to owning module |
| `JobHandlerRegistry` | `jobs/registry.py` | `jobs`, `daily_reports` | durable job dispatch |

> These four registries are the **module-extension contract** of the Python
> backend. The TS target must reproduce the *registry pattern* (so domains own
> their own jobs/hooks/appliers), not the specific Python wiring. This is the
> single most reusable architectural idea to carry across.

---

## 4. Python proposal appliers

Registered via `register_proposal_appliers(registry)` per module (see
`backend/app/modules/registry.py` `proposal_appliers` column). The proposal review
routes and apply orchestration are TS-owned. TS registers the three memory
appliers and fails closed for unregistered proposal types. Non-memory target
mutations move with their owning domains.

| Proposal type | Applier module | Target tables/resources | Safety / policy checks | TS replacement needed |
|---|---|---|---|---|
| `memory_create` | `memory/proposal_appliers.py` | `memory_entries`, `memory_relations`, provenance | policy apply gate; egress guard | **done for TS route** — registered TS memory applier; egress/workspace/agent-scope exceptions still fail closed |
| `memory_update` | `memory/proposal_appliers.py` | `memory_entries` | apply gate | done for TS route (as above) |
| `memory_archive` | `memory/proposal_appliers.py` | `memory_entries` | apply gate | done for TS route (as above) |
| `policy_change` | `memory/proposal_appliers.py` | `policies` | policy apply gate | owning-domain follow-up; fail closed until registered |
| `code_patch` | `memory/proposal_appliers.py` | workspace files via patch; `runs` provenance | incomplete-patch confirmation; risk-level validation | yes (Phase 6/9 — needs workspace apply) |
| `follow_up_task` | `memory/proposal_appliers.py` | `tasks` | apply gate | yes (Phase 6/7) |
| `egress_review` | `memory/proposal_appliers.py` | `proposal_approvals`, grants | egress-granting-user approval | yes (Phase 6) |
| `agent_config_update` | `agents/proposal_appliers.py` | `agent_versions`, `activity_records` | version immutability invariant | yes (Phase 6) |
| `knowledge_create` / `knowledge_update` / `knowledge_archive` | `knowledge/proposal_appliers.py` | `knowledge_items` | apply gate | yes (Phase 6/7) |
| `knowledge_relation_create` / `knowledge_relation_delete` | `knowledge/proposal_appliers.py` | `knowledge_item_relations` | apply gate | yes (Phase 6/7) |
| `prompt_update` | `evolution/proposal_appliers.py` | agent/template prompts | evaluation gate | defer (evolution is future) |

> The proposal-apply boundary is a **security invariant** (`.agent/BOUNDARIES.md`
> B10, B24): agents/runtimes never write active memory/knowledge directly. The TS
> re-platform must keep the proposal → approval → apply path and **fail closed**
> for any proposal type without a registered TS applier — never silently no-op.

---

## 5. Schema / migration ownership

| Item | Current state | Implication for deletion |
|---|---|---|
| **Alembic** | `backend/migrations/` with a single consolidated baseline `versions/0001_canonical_initial_schema.py`. `init_db` runs `alembic upgrade` synchronously in `main.py` lifespan. | Python/Alembic is the **sole schema owner** (confirmed in every TS doc). A TS migration runner + baselined current schema must exist and be authoritative before `backend/` is removed. |
| **Model source** | `backend/app/models.py` (~231 KB, **91 tables**) is the canonical data model; `schemas.py` (~57 KB) the API contracts. | TS has no ORM/model layer — it uses `pg` (`db/pool.ts`) with raw SQL against the Python-owned schema. The TS backend needs a typed schema/repository layer over the same tables (not a re-modeling). |
| **TS DB access** | `control-plane/src/db/pool.ts` (single `pg` Pool), least-privilege role provisioned by `ops/scripts/lib/local-compose.sh` per active authority switch. | The role grants currently track TS-owned slices. As more domains migrate, grants widen; eventually the TS role becomes the primary application role. |
| **Scripts depending on Python migration** | `init_db` (startup), `ops/scripts/lib/local-compose.sh` (role grants), compose files (`backend` service runs migrations on boot), test harness (empty-DB → alembic upgrade). **(uncertain)** Confirm exact ops scripts in `ops/`. | Baseline parity + an empty-DB CI migration test on the TS runner must pass before the Python migration entrypoint is removed. |

**What must move to TS before `backend/` can be deleted (schema layer):**

1. A TS migration runner with a migration lock and transaction helper.
2. A baseline migration capturing the current PostgreSQL schema (the `0001`
   canonical schema), verified by drift check against a live DB.
3. CI test: empty DB → TS migrations → schema matches expected.
4. The TS DB role promoted from least-privilege-per-slice to full app role.
5. Compose/ops updated so the **control-plane** (not `backend`) runs migrations.

---

## 6. Deletion-blocking summary

The 91-table schema, the four internal ports, and the identity introspection
dependency are the structural blockers. The single hardest blocker is **identity**
(`/auth/introspect`, `/me`): every TS module currently cannot answer a request
without asking Python "who is this caller and which space." Closing that is the
prerequisite that unlocks standalone operation. See
[`ts-backend-replatform-plan.md`](ts-backend-replatform-plan.md) §"Top 10 blockers".
