# TS Control Plane Foundation — `control-plane`

> **Status:** describes the official TypeScript control-plane service, established
> 2026-06-10 (renamed/normalized from the initial `gateway-ts` prototype); module
> convention normalized 2026-06-11 (Phase C). Source
> of truth is the code under `control-plane/`. Companions:
> [`TS_PROTOCOL_FOUNDATION.md`](TS_PROTOCOL_FOUNDATION.md) (Phase 1),
> [`TS_MIGRATION_STRATEGY.md`](TS_MIGRATION_STRATEGY.md) (Phase 2),
> [`CONTROL_PLANE_MODULE_CONVENTION.md`](CONTROL_PLANE_MODULE_CONVENTION.md) (Phase C).

## Why the control plane exists

`control-plane` is the **default client-facing TypeScript API entrypoint** and
the permanent home for TS-side server features. It is *not* a temporary gateway.
Today it does little on its own: it serves a few TS-owned control-plane routes
and, through a **temporary** legacy proxy, forwards
everything else to the Python backend. That establishes the seam where TS
features can be added later, one explicit route at a time, without disturbing the
Python system that remains in charge.

Three nested concepts:

- **`control-plane`** — the permanent service.
- **`gateway`** — the permanent entry/routing module *inside* the service
  (`src/gateway/`): request context + route registration.
- **legacy Python proxy** — a **temporary** component (`src/legacy/`). It may be
  deleted in the future once its endpoints are owned by control-plane modules or
  retired. The control-plane service itself remains.

It is **proxy-first**: unknown `/api/v1/*` traffic falls through to Python
unchanged, so introducing the control plane does not change what any existing
endpoint does.

## Ownership model (current)

```
apps/web (browser / frontend dev proxy / nginx)
   │
   ▼
control-plane  ─────────────► TS-owned routes (answered in TS):
   │  gateway (entry module)     GET /health
   │                             GET /api/v1/control-plane/health
   │                             GET /api/v1/control-plane/features
   │  legacy/ proxy (temporary): everything else under /api/v1/* (verbatim)
   ▼
backend (FastAPI / Python)  ◄── the sole authority for every command, write,
   │                            policy check, memory write, proposal apply, run
   ▼                            execution, artifacts, jobs, migrations
PostgreSQL
```

- **Python remains the authority.** The control plane makes **no** business
  decision: it does not authenticate, authorize, write memory, apply proposals,
  run agents, or touch the database. The `x-agent-space-control-plane: ts` header
  it stamps on proxied requests is a trace marker, not trust — Python still
  authenticates and authorizes every request.
- **TS-owned routes** are read-only descriptors of the control plane itself.
- **Legacy fallback routes** are everything else under `/api/v1/*`.

### Control-plane routes vs legacy fallback

| Route | Owner | Notes |
|---|---|---|
| `GET /health` | control-plane (TS) | plain liveness (container/LB probe) |
| `GET /api/v1/control-plane/health` | control-plane (TS) | namespaced liveness |
| `GET /api/v1/control-plane/features` | control-plane (TS) | advertises `control_plane_health`, `legacy_python_proxy`, and `protocol_package_detected` when `@agent-space/protocol` resolves |
| `* /api/v1/*` (all others) | **Python** (legacy proxy) | method, path, query, body, and headers forwarded verbatim |

TS-owned routes are registered **before** the catch-all legacy proxy
(`src/gateway/routeRegistry.ts`), so they always win. The old `/api/v1/gateway/*` routes
were **removed** (no compatibility aliases) — they now fall through to the legacy
proxy like any other unowned path.

## Source layout

```
control-plane/
  package.json            # @agent-space/control-plane — deps: fastify, undici,
                          #   @agent-space/protocol (file:); dev: typescript, vitest, @types/node
  Dockerfile              # multi-stage; prod runs compiled JS (node dist/index.js)
  tsconfig.json / .typecheck.json / vitest.config.ts
  src/
    index.ts              # entrypoint (load config, listen, graceful shutdown)
    server.ts             # composition root only (Fastify build, body passthrough)
    config.ts             # CONTROL_PLANE_* / LEGACY_PYTHON_API_BASE_URL parsing
    gateway/              # permanent entry layer
      routeRegistry.ts    #   module convention; TS modules first, legacy proxy last
      requestContext.ts   #   x-request-id continuity, safe headers, marker
      errorEnvelope.ts    #   {error, message, request_id} + error handler
      logging.ts          #   logger options + secret redaction paths
    modules/
      system/             #   standard module shape (see CONTROL_PLANE_MODULE_CONVENTION.md)
        routes.ts         #   /health, /api/v1/control-plane/{health,features}
        service.ts        #   pure health/features logic
        index.ts          #   exports the ControlPlaneModule object
    legacy/               # TEMPORARY — may be deleted in the future
      pythonProxy.ts      #   catch-all /api/v1/* → Python + sanitized 502/503 bodies
  test/                   # config, health, features, gateway, proxy, import-boundary
```

## Adding future TS features

New TS server features must be added as **explicit control-plane modules**
(`src/modules/<module_name>/` with `routes.ts` + `service.ts` + `index.ts`; see
[`CONTROL_PLANE_MODULE_CONVENTION.md`](CONTROL_PLANE_MODULE_CONVENTION.md))
behind explicit control-plane-owned routes, registered in `TS_OWNED_MODULES`
in `src/gateway/routeRegistry.ts` and advertised in `/api/v1/control-plane/features`. The
default for any path the control plane does not explicitly own is — and must
remain — *proxy to Python via the legacy module*. A feature only becomes TS-owned
by an explicit route registration, never by accident.

The import boundary is enforced by `control-plane/test/boundaries.test.ts`.
`control-plane/` may import `@agent-space/protocol`, Node builtins, and its own
relative modules. It must not import Python backend files, `apps/web` source,
database migrations, `sandbox` internals, `deployer` internals, or `ops` scripts.

**This phase does not migrate any command authority.** Proxying a command does
not move its decision out of Python. Migrating a command to TS is a separate,
explicit, per-command decision (see `TS_MIGRATION_STRATEGY.md` §7 invariants) and
is **not** done here. No command is handled in TS; no command has dual ownership.

**No local-host** (and no desktop / mobile / plugin / MCP / CLI-runner) code is
part of this phase.

## Configuration

All via environment variables, validated at startup (fail-fast on a malformed
`LEGACY_PYTHON_API_BASE_URL`):

| Variable | Default | Meaning |
|---|---|---|
| `CONTROL_PLANE_HOST` | `0.0.0.0` | bind address |
| `CONTROL_PLANE_PORT` | `8010` | listen port |
| `LEGACY_PYTHON_API_BASE_URL` | `http://backend:8000` | legacy Python upstream in the compose network |
| `CONTROL_PLANE_ENABLE_LEGACY_PROXY` | `true` | when `false`, fallback paths return a sanitized `503` |
| `CONTROL_PLANE_LOG_LEVEL` | `info` | pino level |
| `CONTROL_PLANE_REQUEST_TIMEOUT_MS` | `300000` | upstream request timeout |

The Python service is named **`backend`** in this repo, so the default and the
compose files use `LEGACY_PYTHON_API_BASE_URL=http://backend:8000`. No `GATEWAY_*`
variables remain — those were renamed, no deprecated aliases kept.

## Legacy proxy behavior

- Forwards method, path, query string and raw body unchanged.
- Forwards client headers (Authorization, Cookie, Content-Type, Accept, …) minus
  hop-by-hop headers; preserves or generates `x-request-id`; stamps
  `x-agent-space-control-plane: ts`.
- Streams the upstream response body straight through (JSON and
  `text/event-stream`).
- Accepts proxied request bodies up to 32 MiB, enough for the current Python
  25 MiB activity upload contract plus multipart framing. Python remains the
  authority for file type and exact upload limit decisions.
- Does **not** follow redirects and does **not** decompress, so `3xx`/`Location`
  and `content-encoding` pass through untouched (OAuth-safe, transparent). Uses
  `undici.request` (the native client behind `fetch`) — no heavyweight proxy dep.
- **Never logs** secrets, cookies, Authorization values, request bodies, or
  response bodies. Fastify's default request serializer omits headers/bodies; the
  logger additionally redacts `authorization`/`cookie`. Proxy failures log only
  `{ method, path, reason }` (e.g. `ECONNREFUSED`, `timeout`).
- If the Python backend is unreachable, returns a sanitized `502`:
  `{ "error": "python_backend_unavailable", "message": "Python backend is unavailable" }`.

## Docker / Compose behavior (dev / test / prod)

The control plane is wired directly into the base compose files (no separate
optional overlay). Python stays present in all environments as the legacy
authority behind the proxy.

| Env | control-plane | Client entrypoint | Notes |
|---|---|---|---|
| **dev** (`docker-compose.dev.yml`) | published `8010:8010` | browser calls same-origin `/api`; frontend dev proxy `CONTROL_PLANE_API_URL=http://control-plane:8010` | backend `8000` still published for direct debugging |
| **test** (`docker-compose.test.yml`) | published `8110:8010` | browser calls same-origin `/api`; frontend dev proxy `CONTROL_PLANE_API_URL=http://control-plane:8010` | isolated stack; the Python **pytest** suite is independent of compose and unaffected |
| **prod** (`docker-compose.prod.yml`) | internal only (not published) | nginx `/api → control-plane:8010` (see `apps/web/nginx.conf`) | Python **not** exposed directly; all `/api` flows through the control plane → backend |

```bash
# dev
docker compose -f ops/compose/docker-compose.dev.yml up
# test
docker compose -f ops/compose/docker-compose.test.yml up
# prod (requires POSTGRES_PASSWORD)
docker compose -f ops/compose/docker-compose.prod.yml up
```

### Local (no Docker)

```bash
cd control-plane
npm install
npm run typecheck
npm test
npm run build && LEGACY_PYTHON_API_BASE_URL=http://localhost:8000 npm start
```

## How to verify proxy compatibility

With the control plane on `:8010` and the Python backend reachable:

```bash
curl http://localhost:8010/health                          # {"status":"ok","service":"control-plane"}
curl http://localhost:8010/api/v1/control-plane/health      # {"status":"ok","service":"control-plane"}
curl http://localhost:8010/api/v1/control-plane/features     # {"service":"control-plane","features":[...]}

# Proxied — must match direct Python debug access:
curl http://localhost:8010/api/v1/features
curl http://localhost:8000/api/v1/features                  # compare
```

If the Python backend is down, the proxied call returns the sanitized `502` while
the TS-owned `/health` routes keep working.

## Known limitations (follow-ups)

- **No WebSocket proxying.** Not implemented (the backend uses none today).
- **No dedicated SSE handling.** The legacy proxy *streams* response bodies, so
  the one current `text/event-stream` endpoint
  (`/api/v1/credentials/cli/login/stream` progress) passes through; there is no
  SSE-specific heartbeat / flush / reconnect handling. Real-time streaming
  hardening is a follow-up.
- **File/binary proxying is covered for current UI paths.** The active multipart
  upload path (`/api/v1/activity/upload`) and artifact export/download path
  (`/api/v1/artifacts/{id}/export`) pass through the control plane; tests cover
  multipart body preservation and binary response headers/body preservation.
- **No response caching, rate limiting, or auth at the control plane** — by
  design; Python owns all of that.
- The **legacy proxy is temporary**; removing it is a future task once its routes
  are owned by control-plane modules or retired.
