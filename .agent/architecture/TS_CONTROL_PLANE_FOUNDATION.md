# TS Control Plane Foundation

> **Status:** current repository fact. Source of truth is `control-plane/`.
> Current TS/Python ownership is recorded in
> [`TS_CONTROL_PLANE_OWNERSHIP.md`](TS_CONTROL_PLANE_OWNERSHIP.md).

## Role

`control-plane` is the default client-facing TypeScript API service and the
host for TS-owned backend modules.

It has three distinct parts:

- `control-plane`: the permanent service.
- `gateway`: the permanent entry/routing layer inside the service.
- `pythonFallback`: a temporary catch-all proxy for unowned `/api/v1/*` routes.

Unknown `/api/v1/*` traffic still falls through to Python unchanged. A route
becomes TS-owned only by explicit module registration before the fallback proxy.

## Source Layout

```text
control-plane/src/
  index.ts
  server.ts
  config.ts
  gateway/
  modules/
  ports/
  pythonFallback/
```

Modules use the convention documented in
[`CONTROL_PLANE_MODULE_CONVENTION.md`](CONTROL_PLANE_MODULE_CONVENTION.md).
`server.ts` stays composition-only; route ownership belongs in modules and the
route registry.

## Boundaries

- Control-plane owns native session-cookie identity resolution, Google OAuth
  login/callback/config, the canonical feature-gated API-key endpoints, and the
  Phase 2 space create/member/invitation routes. DB-persisted API-key storage
  remains deferred because the canonical schema has no `api_keys` table.
- Python/Alembic owns schema migrations.
- TS-owned contexts may use the least-privilege control-plane DB role.
- Credential release stays inside provider/CLI broker channels.
- Unowned business contexts stay Python-owned until an explicit migration
  decision is recorded.

## Database Foundation

Control-plane database access is centralized under `control-plane/src/db/`:

- `pool.ts` owns `pg` pool construction from `CONTROL_PLANE_DATABASE_URL`;
- `tx.ts` provides the shared transaction helper for TS-owned write flows;
- `migrator.ts` and `migrateCli.ts` provide a manual migration runner over
  `control-plane/migrations/*.sql`.

The migration runner is a parity/ops foundation, not a startup hook. Normal
runtime schema migration remains Python/Alembic-owned until a later explicit
schema-ownership cutover is recorded.

## Configuration

Configuration is environment-based and parsed in `control-plane/src/config.ts`.
Completed foundations such as providers/credentials, policy, public sessions,
auth/spaces, and runtime adapter catalog are fixed TS authorities. Remaining
migration slices keep explicit `CONTROL_PLANE_*_AUTHORITY` variables; dev/test
templates opt into the completed migrated slices while code fallbacks remain
`python` for slices that have not been finalized.

When adding a new authority switch, update:

- `control-plane/src/config.ts`;
- `ops/env/.env*.example`;
- `ops/compose/docker-compose.{dev,test,prod}.yml` for both backend and
  control-plane when both services need the switch;
- `ops/scripts/lib/local-compose.sh` grants if TS needs DB access;
- [`TS_CONTROL_PLANE_OWNERSHIP.md`](TS_CONTROL_PLANE_OWNERSHIP.md).

## Python Fallback Proxy

The fallback proxy preserves method, path, query, body, safe headers, and
`x-request-id` while forwarding to Python. It is not a plugin system and should
not gain business logic.

Long-term cleanup is to delete or sharply narrow this proxy after unowned routes
are migrated, retired, or documented as intentionally Python-owned.
