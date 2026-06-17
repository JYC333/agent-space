# Module: Server Status

## Status
**PLANNED** — `/health` endpoint exists. Full runtime status model and UI not built.

## Purpose
Surface the operational health of the agent-space runtime to the user. Users must be able to see at a glance whether the backend, adapters, capabilities, and external integrations are reachable and functioning. This is not monitoring — it is a user-facing status display integrated into the product shell.

## Owns
- Runtime status API endpoint (`GET /api/v1/status`)
- Per-component health checks (db, adapters, capabilities, LLM provider)
- `RuntimeStatusBar` UI component (always visible in shell)
- Status detail modal (expandable from status bar)

## Does Not Own
- Alerting or paging (not in scope)
- External monitoring dashboards (e.g., Grafana)
- Log storage (instance/logs/)

## Status Components

| Component | Check | Green | Yellow | Red |
|---|---|---|---|---|
| Database | PostgreSQL reachable, schema current | OK | schema lag | unreachable |
| LLM Provider | Anthropic API key valid, model reachable | OK | rate-limited | no key / unreachable |
| Claude adapter | active `claude_code` runtime tool found | OK | degraded | not installed |
| Codex adapter | active `codex_cli` runtime tool found | OK | degraded | not installed |
| Capabilities | All registered caps loaded without error | OK | some failed | all failed |
| Sandbox runner | Docker socket reachable (if Docker executor) | OK | partial | unavailable |

## API Endpoint (Planned)

```
GET /api/v1/status

Response:
{
  "overall": "ok" | "degraded" | "error",
  "components": [
    {
      "name": "database",
      "status": "ok" | "degraded" | "error",
      "detail": "string or null"
    },
    ...
  ],
  "version": "...",
  "checked_at": "ISO datetime"
}
```

The existing `/health` returns `{"status": "ok", "version": "..."}` — the new endpoint replaces it as the full status surface while keeping `/health` as the minimal liveness probe.

## UI: RuntimeStatusBar

- Persistent bottom or top bar (see frontend-layout.md — bottom panel)
- Shows: overall dot (green/yellow/red) + short text ("Connected" / "Degraded" / "Error")
- Click → opens status detail modal
- Auto-refreshes every 30 seconds (or on WebSocket event in future)

## UI: Status Detail Modal

- Table of all components with status + detail string
- "Last checked" timestamp
- "Refresh" button (triggers manual re-check)
- Link to logs (if accessible)

## Degraded vs Error

- **Degraded**: system can still function but with reduced capability (e.g., no Docker → Local executor only; Codex adapter missing → Claude only)
- **Error**: a critical component is down (db unreachable, no LLM key) and agent runs will fail

## Invariants
- Status endpoint must respond even when DB is unreachable (check DB as a component, don't depend on it to respond)
- Status must never expose secrets (API keys must not appear in response)
- `overall` is the worst component status — if any component is `error`, overall is `error`
- RuntimeStatusBar is always visible; cannot be hidden by user (collapses to dot icon on mobile)

## Related Files
- `server/src/server.ts` — `/health` endpoint
- `server/src/config.ts` — settings and diagnostics
- `server/src/modules/system/` — status/feature routes
- `apps/web/src/components/` — TODO: RuntimeStatusBar, StatusDetailModal

## Related Modules
- [product-shell.md](product-shell.md) — RuntimeStatusBar lives in the shell
- [frontend-layout.md](frontend-layout.md) — bottom panel / status area
