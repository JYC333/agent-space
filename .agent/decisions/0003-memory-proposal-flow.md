# Decision 0003: Agents Do Not Directly Write Active Memory

## Status
Accepted

## Context
In early versions, agents could call MemoryStore directly to create or update memories. This caused:
- Unreviewed, low-quality memories accumulating
- No audit trail for how memories were created
- Loss of user control over what the agent "believes" long-term
- Difficulty pruning or correcting bad memories

## Decision
**Agents do not directly write active memory.** All memory changes must go through the proposal → approval workflow.

Flow:
1. Raw input or agent session produces outputs
2. Agent (or reflector) generates a `memory_update` proposal with proposed content and rationale
3. User reviews the proposal and approves or rejects it
4. Only approved proposals call `MemoryStore.create()` / `update()`

This applies to:
- Post-session memory reflection
- Activity-to-memory pipelines
- Agent-initiated memory consolidation
- Any external data import

## Consequences

- `MemoryStore.create()` is never called directly by adapters or agents — only by the proposal executor after approval
- A `requires_proposal` flag on an agent's memory policy enforces this at runtime
- The `MemoryReflector` generates proposals, not memories
- Users retain full control over what becomes permanent memory
- Bad agent reasoning doesn't silently corrupt memory
- Memory has a clear provenance trail (source_session_id, source_run_id, rationale)
- External chat capture must create ActivityRecords first, not memory proposals directly
