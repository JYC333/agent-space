# Data Authority Matrix

Date: 2026-06-28

This matrix records the current canonical write/read authority after the
dual-track cleanup. Code and `server/migrations/0001_baseline.sql` remain the
source of truth when this document and implementation disagree.

| Domain | Canonical Authority | Derived / Audit Only | Retired / Non-Authority |
|---|---|---|---|
| Evidence candidates | `extracted_evidence` plus `evidence_links` with `context_candidate`, `supports`, `contradicts`, `derived_from`, or `mentions`; context selection must pass current source read policy before injection. | `evidence_links.link_type='used_in_context'` is best-effort run audit only. | `evidence_links.link_type='provenance'` is retired and is not a source lineage authority. |
| Curated evidence | `sources`, `knowledge_item_sources`, and `claim_sources` after proposal acceptance. | `source_refs_json` snapshots are frozen display/audit context. | Runtime candidate evidence cannot become curated evidence without proposal acceptance. |
| Provenance | `provenance_links` for accepted object/source lineage. | Run/materialization events may mention source ids for audit. | KnowledgeItem shortcut source columns are removed. |
| Relations | `object_relations` is the only canonical FK-backed graph for Knowledge, Claim, and Source relations. | `retrieval_edges` is a projection rebuilt from active `object_relations` and curated source links. `note_links` is direct working-note UI linkage and is not canonical graph authority. | `entity_links`, `knowledge_item_relations`, `claim_relations`, and `knowledge_relation_*` / `claim_relation_*` proposal types are retired. |
| Memory taxonomy | `memory_entries.memory_type` is the public category; `memory_entries.memory_layer` is the hierarchy/layer. `created_from_proposal_id` is the proposal FK. | `memory_access_logs` and provenance rows are audit/read traces. | `memory_kind`, `memory_entries.source_proposal_id`, `memory_entries.scope_id`, and `memory_entries.capability_id` are retired. |
| Context preparation | `ContextPrepareService` is the run/chat authority for conversation window, candidates, snapshots, rendered runtime context, and prompt handoff. | Context snapshots are immutable run read models. | Route-local duplicate context assembly is not authoritative. |
| Run execution | `runs` owns terminal status/output. `run_events` is append-only fact audit. `run_steps` is lifecycle summary. | Step/event writes are best-effort and must not block terminal writes. | Step/event failure must not overwrite or mask terminal run status. |
| Artifacts/proposals from runs | `RunMaterializationService` owns artifact/proposal materialization and applies `artifact.persist` / `proposal.create` policy gates before durable INSERT. | Materialization errors are recorded in `run.output_json.materialization_errors`; successful adapter runs with partial materialization failure are `degraded`. | Adapter output does not directly mutate active Knowledge, Claim, Memory, or relations. |
| Capabilities | Product capability read API is `/api/v1/capability-definitions`; built-ins come from `server/src/modules/capabilities/registry.ts`. | Workflow/catalog compatibility data is internal unless exposed through framework APIs. | Legacy public `/api/v1/capabilities*` product route and frontend `capabilitiesApi` are retired. |
| Identity / space context | User identity comes from auth; active space comes from explicit request context such as `X-Agent-Space-Id` or path scope. | Query `space_id` is legacy fallback on some backend readers only. | The frontend must not globally append `space_id` / `user_id` query params or keep `default_user` client state. |
