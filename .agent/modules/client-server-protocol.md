# Module: Client-Server Protocol

## Status
**PLANNED** — REST API exists. WebSocket / real-time layer not yet built.

## Purpose
Define how the frontend and mobile clients communicate with the FastAPI backend. Covers the REST API conventions already in place, the planned real-time event layer (WebSocket or SSE), and streaming agent output. This module is the contract between frontend and backend — changes here affect both sides.

## Owns
- REST API conventions (request/response shape, error format, pagination)
- WebSocket event protocol (planned)
- Server-Sent Events for streaming agent output (planned)
- API versioning strategy

## Does Not Own
- Auth token generation (auth module)
- Business logic behind any endpoint (owning feature module)
- Transport security (deployment / infra layer)

## REST Conventions (Current)

**Base URL:** `GET /api/v1/...`

**Auth:** API key via `X-API-Key` header (dev mode: key printed at startup). Bearer token (future).

**Request body:** JSON with snake_case fields.

**Response shape:**
```json
// Single resource
{ "id": "...", "field": "...", ... }

// Collection
{ "items": [...], "total": 42, "page": 1, "page_size": 20 }

// Error
{ "detail": "human-readable message" }
```

**HTTP status codes:**
- 200 OK — success (GET, PUT, PATCH)
- 201 Created — new resource created (POST)
- 204 No Content — delete success
- 400 Bad Request — validation error (Pydantic detail in `detail`)
- 401 Unauthorized — missing or invalid API key
- 403 Forbidden — authenticated but not allowed (wrong space)
- 404 Not Found — resource not found
- 422 Unprocessable Entity — body parse error (FastAPI default)
- 500 Internal Server Error — unexpected error

**Pagination:** query params `?page=1&page_size=20` (default page_size=20, max=100).

**Filtering:** query params matching model field names (e.g., `?scope=user&type=preference`).

**Ordering:** `?order_by=created_at&desc=true`

## Planned: Real-time Event Layer

**Transport:** WebSocket at `ws://host/api/v1/ws?space_id=...`

**Event envelope:**
```json
{
  "event": "event_type",
  "space_id": "personal",
  "payload": { ... }
}
```

**Event types:**

| Event | Payload | When |
|---|---|---|
| `agent_run.started` | `{run_id, agent_id}` | Run begins |
| `agent_run.output` | `{run_id, chunk}` | Streaming output chunk |
| `agent_run.completed` | `{run_id, status, exit_code}` | Run finishes |
| `proposal.created` | `{proposal_id, type}` | New proposal pending |
| `proposal.resolved` | `{proposal_id, status}` | Proposal accepted/rejected |
| `memory.updated` | `{memory_id}` | Memory record changed |
| `status.changed` | `{component, status}` | Runtime status change |
| `sync.conflict` | `{record_type, record_id}` | Sync conflict detected |

**Client → server messages:**
```json
{ "action": "subscribe", "channels": ["agent_runs", "proposals"] }
{ "action": "ping" }
```

## Planned: SSE for Agent Output

For agent run streaming without a persistent WebSocket:

```
GET /api/v1/runs/{id}/stream
Accept: text/event-stream

data: {"chunk": "...", "run_id": "..."}
data: {"done": true, "exit_code": 0}
```

## API Versioning

- Current: `v1` prefix on all routes
- Breaking changes → increment to `v2`; maintain `v1` for one release cycle
- Non-breaking additions (new fields, new endpoints) do not require version bump
- Frontend must gracefully handle unknown event types and extra JSON fields

## Invariants
- All API endpoints require `space_id` in the path, query params, or request body — no global routes that ignore space
- Clients must send `X-API-Key` on every request (no cookie-based session state in v1)
- WebSocket connection is per-space — one connection per space_id per client
- Streaming output uses SSE (not WebSocket) so it works without persistent connections
- Error responses always include `detail` string — never return empty 500

## Related Files
- `core/backend/app/api/` — all REST routers
- `core/backend/app/main.py` — app entry, CORS config
- `core/backend/app/auth/` — API key validation middleware
- `frontend/src/` — TODO: API client layer, WebSocket hook

## Related Modules
- [product-shell.md](product-shell.md) — shell connects to WebSocket for live proposal badges
- [server-status.md](server-status.md) — status events pushed over WebSocket
- [agents.md](agents.md) — agent run output streamed via SSE
- [sync-and-conflicts.md](sync-and-conflicts.md) — sync conflict events over WebSocket
