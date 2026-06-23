# Object Kind Registry And Object Schema

Status: implemented core object-schema runtime slices; optional hardening remains
Date: 2026-06-27

This document records the Agent Space-native answer to gbrain-style schema
packs. The governed object-kind registry, retrieval projection/filtering, Space
Settings UI, relation hints, object-schema export/import, and deterministic
schema suggestions are implemented.

Current code keeps `RetrievalObjectTypeSchema` closed in
`packages/protocol/src/knowledgeRetrieval.ts`, and the baseline schema keeps
`retrieval_objects.object_type` behind a SQL `CHECK` with the same fixed values.
`space_object_kinds` stores governed per-space state under those fixed values.
Retrieval projection keeps a nullable `object_kind` slot populated by domain
adapters from subtype fields such as `knowledge_kind`, `source_type`,
`claim_kind`, and `memory_type`; search/brief APIs can filter by active governed
object kinds and surface kind labels only after normal read/source-policy
revalidation.

Upstream gbrain is a reference only. Its schema pack is an always-consulted
runtime artifact with bundled/user packs, a multi-tier active-pack resolver,
path/type inference, pack-aware link verbs, pack-aware search cache identity,
detect/suggest tooling, and dream-cycle phases. Agent Space borrows the
constraint discipline, not the runtime shape. It does not adopt gbrain's
schema-pack terminology: the active configuration for a space is called an
`object_schema`, which is the governed collection of `object_kind` definitions.
Export/import is serialization of `object_schema`; it is not a separate concept.

## Decision Summary

- Do not copy gbrain's full schema-pack runtime.
- Keep physical/canonical `object_type` fixed and owned by Agent Space.
- Use the per-space `object_kind` registry under each fixed `object_type`.
- Treat `object_schema` as the active, proposal-gated configuration view for one
  space. Export/import is serialization of `object_schema`; it is not a
  separate runtime concept.
- Keep export/import as a serialization wrapper over `object_schema`, not the
  runtime source of truth.

The core split is:

```text
object_type   = closed product/domain boundary
object_kind   = space-defined subtype label under that boundary
object_schema = active registry view: full set of object_kinds and config for one space
                (export/import serializes object_schema; no separate pack concept)
```

This preserves Agent Space's stronger Space/User/Agent/Run/Proposal/Artifact
governance while still allowing each space to describe its own working language.

## Terminology

`object_type`

The fixed domain boundary used by protocol, retrieval adapters, SQL checks,
read gates, and cross-domain ownership. Current retrieval values are
`knowledge_item`, `note`, `source`, `claim`, `memory_entry`, and
`project_public_summary`. Future canonical object domains such as people,
assets, events, or tasks may be added through explicit product/schema work, not
through per-space object schema import.

`object_kind`

A governed label/config layer over the canonical subtype field owned by each
fixed `object_type`. In the current implementation the registry key must match
the domain subtype value that retrieval projects from canonical rows:
Knowledge uses `knowledge_kind` values such as `decision`, `lesson`, or
`procedure`; Claims use `claim_kind` values such as `preference`, `metric`, or
`event`; Sources use `source_type` values such as `paper`, `email`, or `pdf`;
Notes and Project public summaries currently have one projected kind each
(`note` and `project_public_summary`); Memory entries use the governed
`memory_type` values. `object_kind` can affect labels, filters, templates,
validation hints, relation discovery, and explanation. It must not create a new
taxonomy that cannot be projected from canonical rows, and it must not change
which canonical domain owns the row.

`object_schema`

The active set of object kinds, field schemas, relation hints, extraction hints,
retrieval hints, and UI labels/config for one space. It is a view over governed
`space_object_kinds` registry rows and versions. It is not executable code.
Export/import serializes and deserializes `object_schema`; importing creates
draft proposals for review and never activates definitions directly.

`relation_hint`

A declarative hint stored in `space_object_kind_relation_hints`. Each hint
records an expected endpoint `object_type`, an optional endpoint `object_kind`,
a `relation_type`, a direction, a confidence default, and a `required` flag.

Hints have no effect on deterministic wikilink extraction, which remains purely
text-driven. They guide the injectable LLM extraction pass with per-kind relation
type context and drive Brain Ops gap findings when `required` is true and no
matching visible active relation exists. Hints never write a relation directly.

## Load-Bearing Invariants

1. No dynamic replacement of `RetrievalObjectTypeSchema`.
2. No schema-driven canonical writes.
3. All object schema changes are proposal-gated and require owner/admin authority.
4. Source policy and live read gates apply before any schema-driven discovery,
   extraction, relation hinting, provider call, or UI drill-down surfaces
   content.
5. Ranking, salience, backlink, graph, diagnostics, and gap signals remain
   access-safe. They may use only visible rows or access-neutral metadata.
6. Cross-space behavior stays fail-closed. An object schema from space A never
   changes read, write, cache, or discovery behavior in space B.
7. Object schema config must not contain executable code, scripts, shell commands,
   provider tools, SQL, or regex-like constructs that execute without bounded
   validation. Declarative patterns need length, timeout, and ReDoS guardrails.
8. Imported object schemas create draft proposals, not active runtime changes.
9. Schema/kind hints cannot widen source retention, provider egress, connector
   import targets, Memory visibility, Project public-summary scope, or artifact
   attachment policy.
10. Existing rows with no `object_kind` remain valid.

These invariants are direct extensions of `BOUNDARIES.md`: Space isolation,
proposal-gated Memory/Knowledge writes, source consent, policy enforcement, and
adapter-not-source-of-truth rules stay stronger than schema convenience.

## Data Model

The `space_object_kinds` table, `space_object_kind_relation_hints` table,
protocol contracts, proposal routes, and proposal appliers are implemented.
Export/import is a manifest wrapper over registry definitions and does not add a
runtime schema-pack table.

### `space_object_kinds`

Each row defines an `object_kind` under one fixed `base_object_type`.

| Column | Meaning |
|---|---|
| `id` | UUID primary key. |
| `space_id` | Required isolation scope. |
| `key` | Stable canonical subtype key for the `base_object_type`, unique per `(space_id, base_object_type)` including archived rows. Archive retires and reserves the key so historical references never point at a new definition. |
| `label` | Human label shown in UI and citations. |
| `description` | Operator-facing purpose and usage note. |
| `base_object_type` | One value from the fixed canonical object type enum. |
| `status` | `draft`, `active`, `deprecated`, or `archived`. |
| `version` | Monotonic registry-row version used by proposals, artifacts, and eval reports. |
| `field_schema_json` | Declarative field schema for forms/proposal payload validation. |
| `extraction_policy_json` | Declarative extraction eligibility and allowed source classes. |
| `retrieval_policy_json` | Advisory retrieval/ranking/filtering hints. |
| `ui_config_json` | Labels, icons, grouping, form templates, and display options. |
| `created_by_user_id` | User id that created the definition proposal. |
| `created_from_proposal_id` | Proposal that created the row. |
| `updated_from_proposal_id` | Most recent proposal that updated status or config. |
| `created_at` | Creation timestamp. |
| `updated_at` | Last update timestamp. |

The `base_object_type` column is load-bearing: it keeps object schema
customization inside the existing domain adapter and read-gate boundary.
The `(base_object_type, key)` pair is constrained to values the current domain
adapter can actually project, so registry definitions cannot silently become
unreachable labels.

Status lifecycle is proposal-gated. Create proposals may create `draft` or
`active` rows. Update proposals may activate `draft` rows by setting
`status: "active"` and may update labels/config. Deprecate and archive use
explicit status proposals. Archived rows cannot be changed, and their keys stay
reserved.

### `space_object_kind_relation_hints`

Each row is one relation hint for a given `object_kind`. Split from
`space_object_kinds` because each hint carries a FK reference to another kind
row and a CHECK-validated `relation_type`; a JSON blob cannot enforce either.

| Column | Meaning |
|---|---|
| `id` | UUID primary key. |
| `space_id` | Required isolation scope. |
| `object_kind_id` | FK → `space_object_kinds.id`. |
| `endpoint_object_type` | CHECK constraint: one value from the fixed canonical object type enum. |
| `endpoint_object_kind_id` | FK → `space_object_kinds.id`, nullable when only the `object_type` boundary matters. |
| `relation_type` | CHECK constraint: one value from the known `RELATION_TYPES` / `OBJECT_RELATION_TYPES` set. |
| `direction` | `from`, `to`, or `either`. |
| `confidence_default` | Float 0–1. Default confidence for LLM-extracted candidates of this hint type. |
| `required` | Boolean. When true, Brain Ops gap detection flags objects of this kind that have no matching active relation. |
| `created_at` | Creation timestamp. |

Deleting a `space_object_kinds` row should cascade-delete its incoming hint
references via `endpoint_object_kind_id`.

### Optional future tables

`space_object_schemas`

Named active registry views. A schema can group active object kinds and defaults
for a space, for example "research lab" or "household ops". Only one active
schema should drive runtime surfaces unless a later design proves multi-schema
selection is safe.

`space_object_schema_versions`

Immutable snapshots of the active schema. Artifacts, diagnostics, eval reports,
and import/export events can record the version they used without copying private
content.

`space_object_schema_imports`

Optional audit records for imported object schemas if proposal rows and artifacts
become insufficient. Current import creates draft object-kind proposals and
returns proposal ids, skipped entries, and warnings without activating
definitions.

### Relation table routing

Four relation tables exist with distinct domain boundaries.

`knowledge_item_relations` — KI↔KI only. Strong FK constraints to
`knowledge_items`. Has `created_from_assessment_id` for assessment-backed
provenance. The authoritative KI graph.

`claim_relations` — Claim↔Claim only. Strong FK constraints to `claims`.
Carries claim-reasoning relation types (`supersedes`, `refines`, `same_as`).

`object_relations` — Cross-domain edges via `space_objects`. Used for
Note↔KI, Note↔Note, Note↔Source, KI↔Source, and any other cross-type
connection. Although `space_objects` includes `knowledge_item` and `claim`,
`object_relations` must not store KI↔KI or Claim↔Claim edges; those must go
to the domain-specific tables. The application layer enforces this boundary;
there is no DB-level constraint preventing the overlap.

`memory_relations` — Memory-domain polymorphic tracking. Uses type+id string
pairs rather than FK-backed object ids. Has no status lifecycle (append-only)
and is not part of the relation discovery or relation hint flow.

### Canonical rows and retrieval projection

Existing canonical rows should store `object_kind` either in existing domain
metadata or in a safe nullable field added later by that domain. The chosen
storage is domain-owned; it must not bypass proposal flow for governed domains.

`retrieval_objects` may project `object_kind` for filtering, citations,
explainability, and diagnostics. Its current nullable `object_kind` column is
only a projection slot. The fixed `object_type` remains the authoritative
boundary for adapter selection, SQL checks, protocol contracts, and read gates.

## Runtime Integration Plan

UI

- Show `object_kind` labels in citations/results and expose registry management
  in Space Settings.
- Knowledge creation forms can submit `object_kind_fields`; field schemas are
  validated by proposal creation before review work is created.
- Space Settings supports registry proposal creation/status changes plus
  object-schema manifest export/import.
- Future UI work can add richer creation/edit templates selected by object kind.
- Deprecation should warn on use, not break existing rows.

Retrieval

- Allow optional `object_kind` filters only after preserving the existing
  `object_type` boundary.
- Do not expose hidden kind counts, hidden candidate ids, hidden titles, or
  near-miss kind suggestions in traces or diagnostics.
- Treat `retrieval_policy_json` as advisory until a calibrated setting adopts a
  specific ranking/filtering behavior.

Context Brief / Ask Brain

- Surface `object_kind` in citations, provenance, and answer explanations when
  the cited object is already visible.
- Never include kind counts or suggestions derived from hidden rows.

Relation discovery

- The deterministic pass (wikilink extraction) is text-driven and does not
  consult `relation_hints`. It produces `knowledge_relation_create` candidates
  for KI↔KI wikilinks and `object_relation_create` candidates for Note↔KI
  wikilinks, following the relation table routing rules above.
- `relation_hints` activate only in the LLM extraction pass: hints narrow the
  relation type search space per object kind, improving precision without
  expanding source text access beyond the existing visible/source-policy-gated
  source set.
- Required hints also drive Brain Ops review-only gap findings when no matching
  visible active relation exists.
- Hints never write a relation directly. All candidates feed the existing
  `relation_discovery_packet` proposal flow.

Claim loop

- Use `object_kind` and `field_schema_json` to support claim subtypes,
  holder/perspective review, and validity fields.
- Do not convert this into gbrain-style direct fact/take writes. Candidate
  claims, holder/perspective inferences, and contradictions stay packetized.

Memory maintenance

- Use `object_kind` to guide review/update proposals and explain why a finding
  exists.
- It must not enable hot-to-cold direct promotion from Memory into Knowledge or
  Claims.

Brain Ops

- Brain Ops exposes deterministic object-schema suggestions from visible data:
  missing registry definitions for used kinds, deprecated kind usage, and active
  kinds with no current visible usage. Reports are artifacts; they do not mutate
  active config.
- Future diagnostics can add invalid field payloads, source policy conflicts,
  relation-hint yield, and richer schema drift analysis.

## Relationship To Current Gaps

Search-quality runtime ranking is eval-gated through
`space_retrieval_settings.ranking_config`. Future `retrieval_policy_json` stays
advisory unless a calibrated runtime setting adopts and ships a mechanic with
access-safety proof, aggregate eval delta, shared evidence refs, and guardrails.
Because ranking config is space-wide, runtime settings must not depend on
operator-private calibration artifacts. Object schema config must not become a
backdoor for ranking changes.

Relation hints do not expand discovery source coverage. Future source-text
classes or hint expansion must reuse the current read/source/egress gates before
content reaches an LLM or review artifact.

Memory maintenance can now generate provenance-backed `memory_update` child
proposals from accepted maintenance packets. Schema-driven update suggestions
must use the same proposal-first path and must mark `requires_operator_edit`
when the system cannot safely produce a complete no-edit update.

Claim/take modeling can use `object_kind` and field schemas, but it must not
become gbrain-style direct fact/take writes. Holder, perspective, validity, and
contradiction signals remain proposal-first.

Brain Ops is now the review surface for deterministic schema suggestions. Future
schema diagnostics should stay aggregate-safe and should point to review reports
or packets rather than mutating active config.

## Implementation Slices

### Implemented Slices

- `server/migrations/0001_baseline.sql` includes `space_object_kinds` scoped by
  `space_id`, plus `space_object_kind_relation_hints` for governed relation
  hint config. Both are constrained to fixed retrieval `object_type` values
  where applicable. `space_object_kinds.key` is also constrained by
  `base_object_type` to the canonical subtype values each domain adapter can
  project.
- `packages/protocol/src/objectSchema.ts` defines object-kind list/output and
  proposal request contracts, relation hints, object-schema manifests, and
  deterministic suggestion reports without adding `object_kind` or schema-pack
  values to `RetrievalObjectTypeSchema`.
- `server/src/modules/knowledge/routes.ts` exposes owner/admin proposal routes
  for create, update, deprecate, and archive, plus member-visible list/get
  reads for registry rows in the current space. It also exposes object-schema
  export/import and deterministic suggestion scans.
- `server/src/modules/knowledge/proposalApplier.ts` applies accepted
  `object_kind_create`, `object_kind_update`, `object_kind_deprecate`, and
  `object_kind_archive` proposals. The appliers write only registry rows and do
  not create canonical Knowledge, Memory, Claim, Project, or retrieval object
  rows. `object_kind_update` is also the activation path for draft definitions;
  only `draft` → `active` is allowed.
- `field_schema_json`, `extraction_policy_json`, `retrieval_policy_json`, and
  `ui_config_json` are bounded JSON objects. They reject executable/script/tool,
  SQL, and regex-like keys; they remain declarative config only.
- Retrieval search/brief accepts `object_kinds` filters under fixed
  `object_types` and surfaces active kind key/label metadata only for visible
  results after source-policy revalidation.
- Relation discovery passes relation hints to the injectable LLM extraction hook
  and emits review-only required-hint gap findings. Deterministic wikilink
  extraction remains unchanged.
- Object-schema export returns `agent_space.object_schema.v1` manifests with
  definitions only. Import creates draft object-kind proposals and never
  activates definitions.
- Deterministic object-schema suggestion scans use only visible aggregate usage
  and registry rows, persist optional Brain Ops artifacts, and perform no
  provider calls or canonical writes.

## Non-Goals

- Do not implement gbrain's seven-tier schema resolution.
- Do not add a per-call object schema override.
- Do not make an imported object schema the live source of truth.
- Do not allow object schema config to run code.
- Do not let imported schemas bypass proposal approval.
- Do not add cross-viewer semantic result caching.
- Do not make Memory, Knowledge, and Project collapse into one domain.
- Do not dynamically add retrieval object types through object schema import.
- Do not bypass source consent, provider egress policy, or artifact attachment
  revalidation.

## Architecture Acceptance Criteria

- The design clearly explains why full gbrain schema packs are not copied and
  why Agent Space uses `object_schema` instead of gbrain's `schema_pack`
  terminology.
- It provides an Agent Space-native alternative based on a governed per-space
  `object_kind` registry and `object_schema` active view.
- The implemented foundation keeps the first runtime slice as the registry
  foundation, not object schema export/import.
- It connects schema/kind work to Search Quality Stage 2, relation discovery,
  Memory maintenance, the claim loop, and Brain Ops.
- It preserves `BOUNDARIES.md` and does not weaken proposal, policy, source, or
  cross-space constraints.

## Cross-References

- Current retrieval and brain layer:
  [`RETRIEVAL_AND_BRAIN_LAYER.md`](RETRIEVAL_AND_BRAIN_LAYER.md)
- Brain-layer next work plan:
  [`BRAIN_LAYER_CLOSURE_PLAN.md`](BRAIN_LAYER_CLOSURE_PLAN.md)
- Claim/fact atom model:
  [`CLAIM_FACT_ATOM_MODEL.md`](CLAIM_FACT_ATOM_MODEL.md)
- Source/connector consent:
  [`SOURCE_CONNECTOR_CONSENT.md`](SOURCE_CONNECTOR_CONSENT.md)
- Architecture boundaries:
  [`../BOUNDARIES.md`](../BOUNDARIES.md)
