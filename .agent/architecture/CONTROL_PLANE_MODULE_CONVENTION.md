# Control-Plane Module Convention (Phase C)

> **Status:** established 2026-06-11 (Phase C). Source of truth is the code under
> `control-plane/src/`. Companions:
> [`TS_CONTROL_PLANE_FOUNDATION.md`](TS_CONTROL_PLANE_FOUNDATION.md) (the service),
> [`TS_MIGRATION_STRATEGY.md`](TS_MIGRATION_STRATEGY.md) (the migration rules).

`control-plane` is the **default client-facing API entrypoint**. This document
defines the internal structure every TS-owned control-plane module follows, so
future TS server features are added consistently — one explicit module at a
time — while **`backend/` remains the Python authority for all existing business
routes and writes. No business authority moved to TypeScript in Phase C.**

## Directory ownership

```
control-plane/src/
  index.ts                 # process entrypoint (config load, listen, shutdown)
  server.ts                # composition root ONLY — no business route logic
  config.ts                # CONTROL_PLANE_* env parsing, fail-fast validation
  gateway/                 # PERMANENT HTTP entry layer
    routeRegistry.ts       #   module convention + registration order
    requestContext.ts      #   request-id continuity, safe header access
    errorEnvelope.ts       #   error shape + app-wide error handler
    logging.ts             #   logger options + secret redaction paths
  modules/                 # TS-OWNED backend modules
    system/                #   health + features descriptors
      routes.ts            #     route registration for this module
      service.ts           #     pure logic (no Fastify types)
      index.ts             #     exports the ControlPlaneModule object
    catalog/               #   read-only surface over top-level catalog/ definitions
  legacy/                  # TEMPORARY migration bridge code
    pythonProxy.ts         #   catch-all /api/v1/* → Python fallback proxy
```

- **`gateway/` is permanent.** It is the entry/routing layer of the service:
  route registry, request context, error envelope, log hygiene. It is not a
  general plugin system and has no event bus.
- **`modules/` contains TS-owned modules.** A new TS module lives under
  `control-plane/src/modules/<module_name>/` with `routes.ts` + `service.ts` +
  `index.ts`.
- **`legacy/` is temporary.** It holds the Python fallback proxy only. Do not
  rename it into `gateway/` or `modules/`; it is deleted when its endpoints are
  owned by control-plane modules or retired.
- **`server.ts` is composition root only.** It builds Fastify (logger, body
  passthrough) and delegates all route registration to
  `gateway/routeRegistry.ts`. Tests enforce that it contains no direct route
  registrations.

## TS-owned module route pattern

Each module exports a `ControlPlaneModule` (defined in
`gateway/routeRegistry.ts`):

```ts
// modules/<module_name>/index.ts
import type { ControlPlaneModule } from "../../gateway/routeRegistry";
import { registerRoutes } from "./routes";

export const myModule: ControlPlaneModule = { name: "<module_name>", registerRoutes };
```

```ts
// modules/<module_name>/routes.ts
import type { FastifyInstance } from "fastify";
import type { ModuleContext } from "../../gateway/routeRegistry";

export function registerRoutes(app: FastifyInstance, context: ModuleContext): void {
  app.get("/api/v1/control-plane/<...>", async () => /* call service.ts */);
}
```

The module is then added to `TS_OWNED_MODULES` in `gateway/routeRegistry.ts` and
advertised in `GET /api/v1/control-plane/features`. `ModuleContext` carries the
validated config plus its immutable `ConfigSnapshot` (schema version + content
hash + load timestamp); future shared deps go there — it is dependency passing,
not a plugin system.

**Registration order is binding:** the registry mounts all TS-owned modules
first; the legacy Python proxy is registered **last**, as the catch-all
fallback. Anything the control plane does not explicitly own falls through to
Python. A route becomes TS-owned only by explicit registration, never by
accident — and never by widening the proxy.

## Request context convention

`gateway/requestContext.ts`:

- `resolveRequestId(request)` — preserve an incoming `x-request-id` or generate
  one. The gateway stamps it on every response; the proxy forwards it upstream.
- `buildRequestContext(request)` — `{ requestId, method, path }` for TS-owned
  handlers. Future identity placeholders (user/space/actor) belong here, but the
  control plane does **not** parse or validate auth tokens — Python owns auth.
- `readHeader(request, name)` — safe header access; refuses to return
  `Authorization`, `Cookie`, `Proxy-Authorization`. Only the legacy proxy's
  forwarding path touches those, verbatim, to Python.
- `x-agent-space-control-plane: ts` is trace metadata, never trust.

Authorization, Cookie, request bodies, and response bodies are never logged
(`gateway/logging.ts` redaction is defense in depth on top of Fastify's default
serializers).

## Error envelope convention

`gateway/errorEnvelope.ts`. TS-owned route errors use one JSON shape:

```json
{ "error": "<machine_code>", "message": "<human text>", "request_id": "<id>" }
```

- 5xx responses use a fixed generic message (`internal_error`) — no stack
  traces, no internal detail, in any environment.
- 4xx responses keep their intentional client-safe message.
- **Legacy proxy exemption:** bodies proxied from Python pass through untouched;
  the proxy's own sanitized transport failures keep their established shapes —
  502 `python_backend_unavailable`, 503 `legacy_proxy_disabled` (no
  `request_id` field; the id travels in the `x-request-id` header).

## Phase C boundaries (what this convention does NOT change)

- `backend/` (Python) remains the authority for every existing business route,
  write, policy decision, proposal apply, run execution, credential brokering,
  job, and migration.
- No business authority moved to TypeScript in Phase C; no command has dual
  ownership (TS_MIGRATION_STRATEGY §8 invariants).
- No database/schema change, no new migration.
- The control plane adds no auth authority, caching, or rate limiting.
- The **catalog module** (`control-plane/src/modules/catalog/`) — named here as
  the first candidate TS-owned read surface — shipped with migration-roadmap
  Stage 1 (2026-06-11): read-only summaries of the top-level `catalog/`
  definitions (`/api/v1/control-plane/catalog`, `/catalog/capabilities`,
  `/catalog/agent-templates`), advertised as `catalog_read`. A missing catalog
  directory degrades to `catalog_available: false`, never an error. Python
  remains the business authority for the DB-backed capability registry and
  Template Library APIs.
