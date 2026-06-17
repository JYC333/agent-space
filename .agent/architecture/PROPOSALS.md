# Proposals

Date: 2026-06-16

Proposals are the product review and application boundary for durable mutations.

## Product API

- `/api/v1/proposals` is the only product API for proposal review and application.
- In the current control-plane stack, external proposal review routes are
  fixed TS-owned. List/get are served by the control-plane DB read model.
  Accept/reject/egress approval run in the TS proposal apply service and share
  the TS transaction boundary with the applier registry. Proposal creation
  entrypoints remain in their source product modules.
- `GET /api/v1/proposals` defaults to pending proposals.
- `status=all` is explicit and returns proposals across statuses.
- Product-recognized proposal types are `memory_create`, `memory_update`,
  `memory_archive`, `policy_change`, `code_patch`, `egress_review`,
  `follow_up_task`, `agent_config_update`, `knowledge_create`,
  `knowledge_update`, `knowledge_archive`, `knowledge_relation_create`, and
  `knowledge_relation_delete`.
- The currently registered TS apply types are `memory_create`,
  `memory_update`, and `memory_archive`. Unregistered proposal types fail closed
  on accept until their owning domain migrates and registers a TS applier.
- Accept returns the general `ProposalAcceptOut` response shape.
- A proposal is never auto-applied.

## Application Rules

- The TS apply service must run the `proposal.apply` policy gate before
  dispatching any registered applier.
- `memory_create`, `memory_update`, and `memory_archive` mutate durable memory
  only when accepted.
- Knowledge proposal records are still reviewable through the proposal API, but
  Knowledge apply is not registered in the TS applier registry yet. It must fail
  closed until the Knowledge domain migrates and registers its appliers:
  `knowledge_create`, `knowledge_update`, `knowledge_archive`,
  `knowledge_relation_create`, and `knowledge_relation_delete`.
- Knowledge read and proposal creation endpoints are viewer-aware. Private and
  restricted Knowledge is owner-readable for the MVP; unauthorized same-space
  users receive 404 for item reads and cannot create update/archive/relation
  proposals involving hidden endpoints.
- Knowledge proposal apply must repeat domain-specific authorization after
  `proposal.apply` allows acceptance when that applier is registered. Malformed
  or internally seeded proposals must not mutate another user's private or
  restricted Knowledge or relations that include private or restricted endpoints.
- `policy_change`, `follow_up_task`, `agent_config_update`, and other
  non-memory target mutations are not currently registered TS appliers. They
  fail closed until their owning domain registers a TS applier.
- `code_patch` remains fail-closed until workspace patch governance migrates.
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
- Knowledge proposal apply is currently deferred with the Knowledge migration.
  Source monitoring has an explicit code boundary for Knowledge but the full
  evaluator for external or untrusted Activity/Artifact derived Knowledge
  remains future work.
- Accepted proposals keep enough result detail for callers to identify the applied product effect.
- Proposal application must be idempotence-safe at the API boundary: repeated accept attempts must not repeat the mutation.
