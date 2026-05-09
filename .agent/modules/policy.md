# Module: Policy

## Purpose
Central permission engine. Decides allow / deny / require_approval for every sensitive action. Prevents permission logic from being scattered across API routes.

## Owns
- `PolicyEngine` — core allow/deny/require_approval decisions
- Policy rules and rule registry
- Policy decision records (optional audit log)

## Does Not Own
- User authentication (auth module)
- Proposal approval UI (proposals module)
- Agent runtime policy (stored on Agent model, read by runner.py)

## Key Models

```
PolicyDecision: allow | deny | require_approval
PolicyContext:
  space_id, user_id, agent_id
  workspace_id, capability_id
  action, resource_type, resource_id
```

## Main Flows

**Per-request policy check:**
1. API route calls `PolicyEngine.check(context)` before executing action
2. Engine evaluates rules in priority order: system → space → workspace → agent
3. Returns `allow`, `deny`, or `require_approval`
4. `require_approval` → creates a Proposal instead of executing immediately

**Policy rule sources:**
- System defaults (hardcoded in `rules.py`)
- Space-level overrides (stored in Space config)
- Agent-level grants (in `runtime_policy_json`)

## Invariants
- Every destructive or sensitive action must pass through PolicyEngine
- Permission checks must not be duplicated across routes — centralize in engine
- `deny` is never overridable by the calling agent
- Agent runtime policy can only escalate restrictions, never lower system-level deny rules

## Related Files
- `core/backend/app/policy/engine.py` — PolicyEngine
- `core/backend/app/policy/rules.py` — rule definitions
- `core/backend/app/policy/decisions.py` — decision types

## TODO
- PolicyEngine not yet fully wired to all API routes
- Space-level policy overrides not yet implemented
- Audit log for policy decisions not yet implemented
