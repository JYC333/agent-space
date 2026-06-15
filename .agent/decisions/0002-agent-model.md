# Decision 0002: Agent is a Separate Model from User

## Status
Accepted

## Context
Early designs conflated "user" and "agent" — treating an AI agent as a type of user. This caused confusion about:
- Who owns what data
- Whose permissions apply
- How to model one user having multiple AI agents

## Decision
**Agent** is a separate model from **User**.

- A User is a human person. Identified by `user_id` string.
- An Agent is an AI runtime entity. Has its own row in the `agents` table.
- One user can create and own multiple agents.
- Agents can be user-owned, space-owned, workspace-owned, or system-owned.

An agent's behaviour is fully configured via its model record:
- `system_prompt` — base instruction
- `model_config_json` — model, temperature, etc.
- `memory_policy_json` — readable/writable scopes, requires_proposal flag
- `capabilities_json` — list of enabled capability IDs
- `tool_permissions_json` — declared allowed tools
- `runtime_policy_json` — sandbox_required, can_delegate, max_delegation_depth, allowed_adapter_types

## Consequences

- Users and agents have independent identity, permissions, and memory policies
- Multiple users may share access to a space-owned or system agent
- An agent's allowed adapter types restrict which CLI tools it can use
- Agent runs carry both `user_id` (the instructing human) and `agent_id` (the executing agent)
- Memory policy on the agent restricts which memory scopes it can read — enforced by ContextBuilder
- No built-in concrete agents are seeded. Built-in behavior comes from system
  AgentTemplates (factories); concrete agents are created on demand via copy-on-create.
  (Superseded the old seeded system agents — removed.)
