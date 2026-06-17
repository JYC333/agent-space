# Control-Plane Module Convention

> **Status:** established 2026-06-11. Source of truth is the code under
> `control-plane/src/`. Companions:
> [`TS_CONTROL_PLANE_FOUNDATION.md`](TS_CONTROL_PLANE_FOUNDATION.md) (the service),
> [`TS_MIGRATION_STRATEGY.md`](TS_MIGRATION_STRATEGY.md) (the migration rules).

`control-plane` is the **default client-facing API entrypoint**. This document
defines the internal structure every TS-owned control-plane module follows, so
future TS server features are added consistently — one explicit module at a
time — while **`backend/` remains the Python authority for schema migrations and
unowned business contexts. Native auth/spaces, session-cookie identity,
Google OAuth, and providers/credentials are TS-owned; DB-persisted API-key
storage remains disabled until the canonical schema adds that table.**

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
  pythonFallback/                  # TEMPORARY Python fallback proxy implementation
    pythonProxy.ts         #   catch-all /api/v1/* → Python fallback proxy
```

- **`gateway/` is permanent.** It is the entry/routing layer of the service:
  route registry, request context, error envelope, log hygiene. It is not a
  general plugin system and has no event bus.
- **`modules/` contains TS-owned modules.** A new TS module lives under
  `control-plane/src/modules/<module_name>/` with `routes.ts` + `service.ts` +
  `index.ts`.
- **`pythonFallback/` is temporary.** It holds the Python fallback proxy only. Do not
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
first; the Python fallback proxy is registered **last**, as the catch-all
fallback. Anything the control plane does not explicitly own falls through to
Python. A route becomes TS-owned only by explicit registration, never by
accident — and never by widening the proxy.

## Request context convention

`gateway/requestContext.ts`:

- `resolveRequestId(request)` — preserve an incoming `x-request-id` or generate
  one. The gateway stamps it on every response; the proxy forwards it upstream.
- `buildRequestContext(request)` — `{ requestId, method, path }` for TS-owned
  handlers. `modules/auth` owns session-cookie validation and may attach
  `{ userId, spaceId }` identity for downstream TS-owned modules. OAuth callback
  semantics live in `modules/auth`; API-key persistence is feature-gated off
  while the canonical schema has no `api_keys` table.
- `readHeader(request, name)` — safe header access; refuses to return
  `Authorization`, `Cookie`, `Proxy-Authorization`. Auth resolution reads cookie
  material in `modules/auth`; the fallback proxy also forwards sensitive headers
  verbatim to Python-owned routes.
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
- **Python fallback proxy exemption:** bodies proxied from Python pass through untouched;
  the proxy's own sanitized transport failures keep their established shapes —
  502 `python_backend_unavailable`, 503 `python_fallback_proxy_disabled` (no
  `request_id` field; the id travels in the `x-request-id` header).

## Boundaries (what this convention does NOT change)

- `backend/` (Python) remains the authority for schema migrations and every
  product context not explicitly registered as TS-owned.
- Current TS-owned contexts are listed in
  [`TS_CONTROL_PLANE_OWNERSHIP.md`](TS_CONTROL_PLANE_OWNERSHIP.md); no command
  has dual ownership.
- Python/alembic remains the schema owner.
- The control plane owns the native Phase 2 auth/space routes; it adds no
  gateway caching or rate limiting.
- Routing rule: when a module claims a parametric route
  (`/:id`) under a prefix the Python fallback proxy used to serve, it must claim every
  static sibling path under that prefix too. Parametric routes beat the proxy
  wildcard, so an unclaimed static sibling (e.g. `/providers/catalog`) would be
  swallowed by the parametric handler and mis-validated.
