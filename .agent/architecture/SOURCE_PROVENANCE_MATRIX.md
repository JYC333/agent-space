# Source / Provenance Ownership Matrix

Each table in the source-and-provenance stack has one role. When deciding where
to read or write, pick by role, not by proximity.

---

## Roles

| Role | Definition |
|---|---|
| **Canonical** | Source of truth. Other tables derive from this. |
| **Intake candidate** | Unvalidated ingested content awaiting review. Deleted or promoted, never kept long-term. |
| **Review artifact** | Proposals or packets that an LLM or human must evaluate before anything is written to canonical tables. |
| **Derived index** | Computed for retrieval/embedding. Never authoritative. Re-derivable from canonical. |
| **Audit lineage** | Immutable record of provenance relationships. Written once, never updated. |

---

## Table-by-Table

### `source_connections`
**Role: Canonical**
The user-facing, managed connection to an external data source (URL, file, API,
credential set). Every ingest pipeline starts here. `status = 'active'` means
the connection is live and eligible for re-indexing. `deleted_at` is the
soft-delete gate; hard delete is prohibited once any intake_items reference it.

### `source_snapshots`
**Role: Intake candidate**
A versioned content snapshot fetched from `source_connections` during ingestion.
Contains raw content before extraction. Expires after `extracted_evidence` rows
are promoted or rejected. Do not treat as canonical—`source_connections` is the
authority on what a source *is*; `source_snapshots` is what it *said* at a
point in time.

### `intake_items`
**Role: Intake candidate**
Raw ingested units (one per document, chunk, or API record) before semantic
extraction. Created by `intake_extraction` jobs. Deleted once downstream
proposals are accepted or the item is superseded by a newer snapshot. Not
queryable for knowledge retrieval.

### `extracted_evidence`
**Role: Intake candidate → transitions to Review artifact**
LLM-generated extraction from an `intake_item` (claims, entities, relations).
Created as a review artifact for human inspection; becomes stale once the
downstream `claim_create`/`knowledge_create` proposals are accepted or rejected.
Not a durable record—do not index or expose to agents.

### `evidence_links`
**Role: Review artifact**
Join table between `extracted_evidence` and pending proposal rows
(`claim_candidate_packet`, `relation_discovery_packet`). Deleted with its parent
`extracted_evidence` row after the review cycle completes.

### `sources` (in `space_objects`)
**Role: Canonical**
A knowledge object of type `"source"` — the *processed* artifact after intake
completes. Status `"processed"` (not `"active"`) is the canonical signal that
the source object is ready. This is the object agents see; `source_connections`
is the infrastructure record the system sees.

### `knowledge_item_sources`
**Role: Audit lineage**
Records which `source_connections` contributed to a specific `knowledge_item`.
Written during `knowledge_create` / `knowledge_update` apply. Immutable after
write. Used by source-policy read gating (`loadSourceConnectionIdsForTargets`)
to decide whether a viewer may see a knowledge item.

### `claim_sources`
**Role: Audit lineage**
Same pattern as `knowledge_item_sources` but for `claims`. Written during
`claim_create` / `claim_update` apply. Read by source-policy gating.

### `provenance_links`
**Role: Audit lineage**
Generic many-to-many between a canonical object (`target_type`, `target_id`) and
the intake artifact (`source_type`, `source_id`) that produced it. Covers note,
memory, and other object types that lack a dedicated `*_sources` join table. Read
by `loadSourceConnectionIdsForTargets` to resolve the `connection_id` for each
target.

### `retrieval_objects`
**Role: Derived index**
One row per knowledge object that has been projected into the retrieval engine.
`status` mirrors the canonical object's status at projection time (not the
canonical truth). Can be re-built from canonical tables at any time via a
maintenance job. **Never use as source of truth for object existence or
status—always re-check the canonical table.**

### `retrieval_chunks` / `retrieval_edges`
**Role: Derived index**
Chunked text and semantic edge records produced from `retrieval_objects`.
`retrieval_edges.evidence_json` stores the raw similarity/relation evidence
used to build the edge; it is a snapshot, not a live reference. Re-derivable.

### Proposal `payload_json` and artifact `metadata`
**Role: Review artifact**
`proposals.payload_json` captures the *intent* before any canonical write.
Artifact `metadata` (e.g. `object_schema_suggestion_report`) captures the
*analysis result* before a human decides to act. Neither is authoritative; both
expire once accepted/rejected. The canonical tables (memory_entries, knowledge
items, claims, policies) are authoritative post-accept.

---

## Read-gating authority

Source-policy gating (`sourcePolicyAllowsRead`) consults `source_connections`
for consent and policy fields. It resolves connection IDs via
`loadSourceConnectionIdsForTargets`, which reads both `provenance_links` and the
dedicated `*_sources` join tables. **Never gate reads on `retrieval_objects`
status alone.**

---

## Write authority

| Operation | Correct writer |
|---|---|
| New source connection | `source_connections` INSERT via source routes |
| New intake content | `intake_items` INSERT via extraction job |
| Promote claim/knowledge | `claim_create` / `knowledge_create` proposal apply |
| Update canonical object | `claim_update` / `knowledge_update` proposal apply |
| Index for retrieval | `retrieval_objects` UPSERT via retrieval engine (derived) |
| Record lineage | `provenance_links` / `*_sources` INSERT at proposal apply |
