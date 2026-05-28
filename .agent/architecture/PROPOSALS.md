# Proposals

Date: 2026-05-14

Proposals are the product review and application boundary for durable mutations.

## Product API

- `/api/v1/proposals` is the only product API for proposal review and application.
- `GET /api/v1/proposals` defaults to pending proposals.
- `status=all` is explicit and returns proposals across statuses.
- Supported apply types are `memory_create`, `memory_update`,
  `memory_archive`, `policy_change`, `code_patch`, `egress_review`,
  `follow_up_task`, `agent_config_update`, `knowledge_create`,
  `knowledge_update`, `knowledge_archive`, `knowledge_relation_create`, and
  `knowledge_relation_delete`.
- Accept returns the general `ProposalAcceptOut` response shape.
- A proposal is never auto-applied.

## Application Rules

- `memory_create`, `memory_update`, and `memory_archive` mutate durable memory
  only when accepted.
- Knowledge writes mutate durable Knowledge only when accepted:
  `knowledge_create` creates an active KnowledgeItem; `knowledge_update`
  creates a new version rather than overwriting in place; `knowledge_archive`
  archives an item; `knowledge_relation_create` creates a same-space relation;
  `knowledge_relation_delete` removes or archives a relation.
- Knowledge read and proposal creation endpoints are viewer-aware. Private and
  restricted Knowledge is owner-readable for the MVP; unauthorized same-space
  users receive 404 for item reads and cannot create update/archive/relation
  proposals involving hidden endpoints.
- Knowledge proposal apply repeats domain-specific authorization after
  `proposal.apply` allows acceptance. Malformed or internally seeded proposals
  cannot mutate another user's private/restricted Knowledge or relations that
  include private/restricted endpoints.
- `policy_change` creates or supersedes Policy rows only when accepted.
- `code_patch` updates workspace files only when accepted.
- `agent_config_update` creates a new immutable `AgentVersion`, advances
  `Agent.current_version_id`, records version provenance back to the accepted
  Proposal and ActivityRecord, and marks the agent context digest dirty.
- Public post-create execution config changes for Agents must use
  `POST /api/v1/agents/{agent_id}/config-proposals`; direct
  `POST /agents/{agent_id}/versions` does not advance the current version.
- Rejected, accepted, expired, or superseded proposals cannot be applied again.
- Cross-space or unauthorized access must not reveal proposal details.

## Audit Rules

- Proposal creation, acceptance, and rejection must be durable.
- User-created memory proposals use the `proposal.create` policy gate.
- Agent execution config proposals use the `agent.config_update` policy gate
  at proposal creation and `proposal.apply` at acceptance.
- Agent-generated Knowledge proposals use the same review boundary:
  Activity, Run, or Artifact source -> `knowledge_*` proposal -> human
  acceptance -> active Knowledge record. They must not auto-activate and must
  not auto-enter Memory or ContextBuilder.
- Knowledge proposal apply currently relies on proposal approval plus
  `proposal.apply`. Source monitoring has an explicit code boundary for
  Knowledge but the full evaluator for external or untrusted Activity/Artifact
  derived Knowledge remains future work.
- Accepted proposals keep enough result detail for callers to identify the applied product effect.
- Proposal application must be idempotence-safe at the API boundary: repeated accept attempts must not repeat the mutation.
