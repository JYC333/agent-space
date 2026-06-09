# Module: Knowledge Base

## Status
**BACKEND + FRONTEND MVP IMPLEMENTED** — Knowledge is the first-level product module
(it replaced the old first-level "Wiki"). Backend has the canonical schema,
`/api/v1/knowledge` API, and proposal apply handlers. Frontend: `/knowledge` is a thin
entry that redirects to the last-used workspace (default `/knowledge/notes`);
`/knowledge/home` is an **optional** overview hub, never the forced landing. Sub-areas
(Notes / Wiki / Sources / Cards) switch via an in-header breadcrumb switcher
(`Knowledge / Notes ▼`) — there is **no** Knowledge scene sidebar or tab strip, so each
workspace owns its own layout. Notes is a working-knowledge workspace (configurable
collection tree + open-note tabs, create / edit + links/backlinks); Wiki is the KnowledgeItem browser under
`/knowledge/wiki`; Sources lists evidence; Cards is a clean placeholder. Automatic
generation, assessments, card generation, and richer search remain future work.

### Frontend information architecture
- **Knowledge** is first-level; **Notes** are working knowledge; **Wiki** is powered by
  `KnowledgeItem`; **Sources** and **Cards** are Knowledge sub-areas.
- `/knowledge` opens the last-used workspace by default (Notes on a fresh client); the
  overview is reached intentionally at `/knowledge/home`, not forced on every visit.
- Cross-section navigation is the breadcrumb switcher in `KnowledgeSectionHeader`
  (last-used section persisted via `rememberKnowledgeSection`, excluding `home`).
- The Notes collection tree is **local to the Notes workspace** and loaded from the backend,
  never a third-level global nav tier. PARA (Inbox / Projects / Areas / Resources / Archive)
  is only the default initialization template for a space. The open note nests at
  `/knowledge/notes/:noteId` so the tree + tabs stay mounted while switching notes.

## Purpose
**Knowledge** is the unified, human-browsable long-term content module. It is split
into subdomains by *lifecycle*, not just by view:

- **Notes** — *working knowledge*: evolving meeting/design/research/thinking notes,
  edited freely via direct CRUD (no proposal gate). Table `notes`.
- **Wiki** — *canonical knowledge*: stable concepts, definitions, structured pages,
  graph relations and evidence. Review-gated and versioned. Table `knowledge_items`.
- **Sources** — external references / evidence. Table `sources`.
- **Cards** — review/learning artifacts derived from Notes/Wiki/Sources.
  Space-scoped content (`cards`); user-specific scheduling state (`card_review_states`);
  append-only review history (`card_reviews`). FSRS algorithm implementation deferred.

Notes and Wiki are **related but not the same**: Wiki is not merely a different view
of Notes. The working/canonical split is the reason they are separate models — folding
freely-editable notes into the proposal-governed `knowledge_items` table would break
its "everything here was reviewed" guarantee, so Notes get their own lightweight model.

Capture / Activity is *raw material* upstream of all of this and is not Knowledge.

Backend and API naming uses `knowledge`; space-specific product labels (e.g. "Second
Brain") are presentation concerns. Knowledge is distinct from Memory: Memory is agent
context; Knowledge is durable content for people to inspect, revise, relate, and reuse.

No legacy route or compatibility alias exists. The API path is `/api/v1/knowledge`;
canonical table names are `notes`, `note_collections`, `note_collection_items`,
`knowledge_items`, `knowledge_item_relations`, `sources`, `knowledge_item_sources`,
and the generic `entity_links`; wiki proposal types use `knowledge_*` (notes are not proposal-gated).

## Layers

| Layer | Table | Write path | Role |
|---|---|---|---|
| **Note** | `notes` | direct CRUD | working knowledge that evolves freely |
| **NoteCollection** | `note_collections` | direct CRUD | space-scoped folder tree for organizing notes |
| **KnowledgeItem** (Wiki) | `knowledge_items` | proposal → approval | canonical, versioned knowledge |
| **Source** | `sources` | direct CRUD | provenance / evidence |
| **KnowledgeItemRelation** | `knowledge_item_relations` | proposal → approval | wiki item ↔ item semantic graph |
| **KnowledgeItemSource** | `knowledge_item_sources` | direct CRUD | wiki item ↔ source evidence |
| **EntityLink** | `entity_links` | direct CRUD | generic cross-object relation layer (notes ↔ anything) |
| **Card** | `cards` | direct CRUD (future) | space-scoped review card derived from knowledge objects |
| **CardReviewState** | `card_review_states` | scheduler-written (future) | per-user FSRS scheduling state; one row per (card, user) |
| **CardReview** | `card_reviews` | append-only (future) | per-user review history with rating + state snapshot |

Notes on the wiki layers: `source` is **not** a KnowledgeItem type — it is the `sources`
table. `answer` **is** a canonical KnowledgeItem type (a `question` item and its `answer`
item are linked with a generic `related_to` relation; there is no dedicated `answers`
relation type). `KnowledgeItemRelation` is the governed item↔item graph; `KnowledgeItemSource`
is item↔source evidence; the two must not be conflated.

### EntityLink — generic cross-object relations

`entity_links` is the user-facing working relation layer (direct CRUD), primarily for
Notes: it connects a note to another note, a wiki KnowledgeItem, a Source, a Project, a
Workspace, an ActivityRecord, a Run, or a Proposal without a join table per pair.
`source_id` / `target_id` are polymorphic (keyed by `source_type` / `target_type`) and
are intentionally not foreign keys (allowlisted in `test_postgres_ddl_semantics.py`).
Endpoints are validated to exist in the same space. Link types: `references`,
`related_to`, `belongs_to`, `captured_from`, `source_for`, `derived_from`; status:
`suggested | accepted | rejected`. It **complements** — does not replace —
`KnowledgeItemRelation` (governed wiki graph), `KnowledgeItemSource` (evidence), and
`ProvenanceLink` (provenance into memory/policy/knowledge targets).

Wiki pages read their generic backlinks (from Notes, Activities, Sources, Runs,
Proposals, …) via `GET /api/v1/knowledge/items/{id}/backlinks` (EntityLinks targeting the
item). A generic read endpoint `GET /api/v1/knowledge/entity-links?source_type=&source_id=
&target_type=&target_id=` filters the layer by any endpoint combination. Item↔item
semantic relations stay on the separate `/items/{id}/relations` (KnowledgeItemRelation).

### Notes vs Collections

Collections/folders are organization *views*, not sole ownership, and a note may appear
in many. The `note_collections` tree is space-scoped and user-configurable; PARA is seeded
only as the initial folder template. A note still belongs to global Knowledge, never to a
separate per-project note system.

## Owns
- `Note` model (working-knowledge layer; direct CRUD via `NoteService`)
- `NoteCollection` / `NoteCollectionItem` models (space-scoped Notes folder tree)
- `KnowledgeItem` model (canonical wiki layer)
- `KnowledgeItemRelation` model (item↔item semantic relations)
- `Source` model (independent provenance/evidence layer)
- `KnowledgeItemSource` model (item↔source evidence links)
- `EntityLink` model + `EntityLinkService` (generic cross-object relation layer)
- `KnowledgeSummaryService` (Overview counts)
- `/api/v1/knowledge` read and proposal API for wiki items; `/api/v1/knowledge/notes`
  + `/api/v1/knowledge/notes/{id}/links|backlinks` direct CRUD for notes;
  `/api/v1/notes/collections` direct CRUD for the Notes collection tree;
  `/api/v1/knowledge/sources` direct CRUD; `/api/v1/knowledge/summary`
- Knowledge proposal apply handlers (wiki only)
- Frontend Knowledge module (breadcrumb switcher, Notes workspace, Wiki/Sources/Cards, overview hub) under `frontend/src/modules/knowledge/`
- Relation and evidence-link records backed by database rows, not only Markdown links

## Does Not Own
- Raw capture (activity module)
- Agent runtime output storage (runs/artifacts modules)
- Long-term agent context injection (memory module)
- Project taxonomy or workspace structure
- Spaced repetition scheduling
- Feynman or Reflection assessment dialogue flows

## Knowledge vs Memory

| Aspect | Memory | Knowledge |
|---|---|---|
| Primary audience | Agent context | Human browsing and review |
| Runtime use | Eligible for ContextBuilder | Must not automatically enter ContextBuilder |
| Shape | Scoped context entry | Typed item with versioning and relations |
| Write path | Proposal -> approval -> active memory | Proposal -> approval -> active KnowledgeItem |
| Promotion | N/A | Future separate proposal, e.g. `knowledge_promote_to_memory` |

Knowledge items must not be auto-injected into runtime context. Promoting Knowledge into Memory is a separate future flow and is not part of the Knowledge MVP scaffold.

## Activity-First Input Boundary

Raw user input, session content, file imports, web captures, and run outputs enter Activity, Run, or Artifact first. Future Knowledge generation normally follows:

```
Activity / Run / Artifact
-> knowledge proposal
-> proposal acceptance
-> active KnowledgeItem / KnowledgeItemRelation
```

Agent-generated knowledge never becomes active without proposal approval.

## Item Types

`KnowledgeItem.item_type` is restricted to these canonical Wiki types:

| Type | Purpose |
|---|---|
| `concept` | A definition, idea, or named concept |
| `claim` | An assertion or position that can be supported/contradicted |
| `lesson` | Learned principle or takeaway |
| `procedure` | Repeatable steps or operating procedure |
| `decision` | Decision record or rationale |
| `question` | Open question |
| `answer` | An answer to a `question` item (linked via `related_to`) |
| `summary` | Digest of an Activity, Run, Artifact, or Source |

`source`, `idea`, `experience`, and `reflection` are **not** canonical Wiki item types.
`source` is the `sources` table (provenance/evidence). Ideas, experiences, and
reflections are working-note / activity concepts and belong in **Notes** or **Activity**,
not the proposal-governed `knowledge_items` table. (Daily-capture "experience"
candidates land as canonical `summary` KnowledgeItems.)

The default `item_type` for the create proposal is `concept`. Some item types may later
gate on assessment flows (e.g. a Feynman/Reflection gate); these are future and must not
block the MVP persistence/API slice.

## Proposal Types

- `knowledge_create` creates an active KnowledgeItem.
- `knowledge_update` creates a new version, not an in-place overwrite.
- `knowledge_archive` archives an item.
- `knowledge_relation_create` creates a relation only within the same space.
- `knowledge_relation_delete` removes or archives a relation.

These proposal types are supported by `ProposalApplyService`. They remain review-gated and are not direct-write API operations.

`knowledge_create` sets `owner_user_id` to the proposal creator for the MVP. The API does not expose selected owner/user assignment yet, so one user cannot create private or restricted Knowledge owned by another user.

Proposal creation is viewer-aware, and proposal apply performs defense-in-depth
authorization again. Malformed, internally seeded, or future system-created
proposals cannot update, archive, relate, or archive relations involving another
user's private or restricted Knowledge. Agent/run provenance is not treated as
human ownership authority for private or restricted Knowledge in the MVP.

## Read Visibility

Knowledge reads are viewer-aware:

- `space_shared` is readable by any authenticated member of the current space.
- `workspace_shared` is readable by any authenticated member of the current space for now. Workspace-role narrowing is future work.
- `private` is readable only by `owner_user_id`, or by `created_by_user_id` when no owner is set.
- `restricted` follows the same owner-only MVP rule as `private`.

Private or restricted rows with neither `owner_user_id` nor `created_by_user_id` fail closed for normal reads. Unauthorized reads return 404 and must not reveal existence.

`GET /api/v1/knowledge/items` returns summary rows with `content_preview`; `GET /api/v1/knowledge/items/{id}` returns full content.

Relation reads first require the requested item to be visible to the viewer, then omit any relation where either endpoint is not visible to the viewer.

Relation apply uses the same endpoint visibility authority: private or restricted
endpoints can only be used by their owner/creator, while shared endpoints remain
collaborative within the current space.

## Source Monitoring

Knowledge proposal apply currently relies on proposal approval and the `proposal.apply` policy gate. `ProposalApplyService._enforce_source_monitoring()` has an explicit Knowledge branch documenting that full Knowledge source monitoring is future work. External or untrusted Activity/Artifact-derived Knowledge requires a future evaluator and must not be treated as safe merely because the current branch does not block.

## Policy Actions

- `knowledge.create`
- `knowledge.update`
- `knowledge.archive`
- `knowledge.relation_create`
- `knowledge.relation_delete`

These actions are `WIRED_VIA_PROPOSAL`: durable mutation is protected by `proposal.apply` and `ProposalApplyService`, not direct `PolicyGateway.enforce()` call sites. Unknown or not-yet-implemented Knowledge actions must fail closed.

## Project And Workspace Association

Project is not a Knowledge type. Workspace is not a Knowledge type. They are contextual associations.

KnowledgeItem rows may carry `project_id` and/or `workspace_id`, but the primary content model must not be a project tree taxonomy.

## Models

```text
Note:                                 # working-knowledge layer (direct CRUD)
  id, space_id
  title
  content_json                    # ProseMirror JSON once a rich editor is wired
  content_format                  # markdown|plain|prosemirror_json (ships markdown)
  content_schema_version          # int, default 1
  plain_text, excerpt             # derived projections for preview / future search
  status                          # draft|active|archived
  primary_project_id              # optional association (FK projects)
  created_from_activity_id        # optional capture provenance (FK activity_records)
  created_by_user_id
  created_at, updated_at, archived_at

EntityLink:                           # generic cross-object relation layer (direct CRUD)
  id, space_id
  source_type, source_id          # polymorphic (note|knowledge_item|source|project|
  target_type, target_id          #   workspace|activity|run|proposal); not FKs
  link_type                       # references|related_to|belongs_to|captured_from|
                                  #   source_for|derived_from
  confidence
  status                          # suggested|accepted|rejected
  created_by_user_id, created_at

KnowledgeItem:
  id, space_id
  project_id, workspace_id        # optional associations
  root_item_id, supersedes_item_id
  redirect_to_item_id             # self-FK; readiness for future merge/rename/deprecate
  item_type                       # canonical Wiki types above
  slug                            # readable-URL slug; indexed (space_id, slug), NOT unique
  aliases_json                    # alternate names for future search/linking
  title, content
  content_json                    # ProseMirror/Tiptap JSON once a rich editor is wired
  content_format                  # markdown|plain|prosemirror_json
  content_schema_version          # int, default 1
  plain_text, excerpt             # derived projections for search/preview/LLM context
  status                          # draft|active|superseded|archived
  visibility                      # private|space_shared|workspace_shared|restricted
  verification_status, reflection_status
  tags_json, confidence, source_url, source_refs_json
  owner_user_id, created_by_user_id, created_by_agent_id, created_by_run_id
  source_activity_id, source_artifact_id, created_from_proposal_id
  approved_by_user_id
  version, created_at, updated_at, archived_at, deprecated_at

KnowledgeItemRelation:                # item <-> item semantic graph
  id, space_id
  from_item_id, to_item_id
  relation_type                   # related_to|explains|depends_on|prerequisite_of|
                                  #   part_of|example_of|applies_to|supports|
                                  #   contradicts|derived_from|summarizes|updates
  status                          # candidate|active|rejected|archived
  confidence, evidence_summary
  source_proposal_id
  created_by_user_id, created_by_agent_id
  created_at, updated_at

Source:                               # independent provenance / evidence layer
  id, space_id
  source_type                     # activity_record|chat_capture|webpage|article|
                                  #   paper|pdf|file|email|manual_reference|external_note
  title, uri, content_ref, raw_text, summary, metadata_json
  status                          # raw|processing|processed|archived|error
  source_activity_id              # optional FK back to the raw ActivityRecord
  created_by_user_id
  created_at, updated_at

KnowledgeItemSource:                  # item <-> source evidence link
  id, space_id
  knowledge_item_id, source_id
  relation_type                   # derived_from|supported_by|cites|summarizes|mentions
  locator, quote, note, confidence
  created_by_user_id
  created_at
```

Relation creation must enforce same-space endpoints. `KnowledgeItemRelation` is the
item↔item semantic layer; `KnowledgeItemSource` is the item↔source evidence layer —
the two must not be conflated. Sources are evidence/raw material, so Source and
KnowledgeItemSource use direct CRUD (`/api/v1/knowledge/sources`,
`/api/v1/knowledge/items/{id}/sources`) rather than the proposal workflow that gates
semantic KnowledgeItem and KnowledgeItemRelation writes. A Source may point back to an
existing ActivityRecord via `source_activity_id` (or any other origin via
`content_ref` / `metadata_json`); ActivityRecord remains the raw capture layer and is
not replaced by Source.

> Frontend follow-up: Sources should surface as a Wiki sub-tab / evidence panel, not
> as ordinary wiki items.

## Invariants

- **Wiki** (canonical KnowledgeItem) durable writes go through proposals; agent-generated
  wiki knowledge never directly becomes active.
- **Notes** (working knowledge) are direct-CRUD and **not** proposal-gated; they are
  space-scoped and never auto-injected into Memory/ContextBuilder. Notes are not wiki:
  they do not version, carry verification/reflection status, or share the proposal path.
- `entity_links.source_id` / `target_id` are polymorphic (no FK); every link endpoint
  must resolve to an existing row in the same space, and an entity cannot link to itself.
- **Card content** (`cards`) is space-scoped; any member of the space can see cards
  in that space. **Card review state** (`card_review_states`) and **review history**
  (`card_reviews`) are user-specific. `cards.source_id` is polymorphic (no FK;
  allowlisted in `test_postgres_ddl_semantics.py`). The FSRS scheduling fields on
  `card_review_states` are nullable — a state row can be created before first review.
- Durable Knowledge writes go through proposals.
- Agent-generated Knowledge never directly becomes active.
- Private and restricted Knowledge reads are owner-only for the MVP.
- Knowledge does not automatically enter Memory or ContextBuilder.
- Knowledge promotion into Memory is a future explicit proposal flow.
- Activity, Run, and Artifact are raw/source inputs, not active Knowledge.
- Project and workspace are associations, not Knowledge content categories.
- Updates are versioned; active content is not overwritten in place.
- Relation rows are database-backed and same-space only.
- Backend/domain/API naming uses `knowledge`; frontend-specific labels are presentation-only.
- No legacy route compatibility is provided.
- No historical data migration compatibility is required.

**Enforced by tests:**
- `test_knowledge_ingestion_boundary.py` — raw/article/file captures create no KnowledgeItem; agent-generated proposals stay pending; rejecting a proposal creates no KnowledgeItem or KnowledgeItemRelation; accepted KnowledgeItem creates no MemoryEntry; KnowledgeItemRelation creation requires proposal accept.
- `test_knowledge_api.py` — accepting a proposal creates active KnowledgeItem; KnowledgeItem does not auto-inject as Memory; KnowledgeItemRelation requires proposal accept; cross-space relation rejected; ownership and visibility enforcement.
- Payload validation is enforced at apply time in `KnowledgeProposalApplier`: `item_type`, `content_format`, `visibility`, `verification_status`, `reflection_status`, and `confidence` for items; `relation_type`, `status`, and `confidence` for relations.

## Related Files
- `core/backend/app/knowledge/` - API, service (Knowledge/Note/EntityLink/SourceService), schemas, read models
- `core/backend/app/models.py` - `Note`, `EntityLink`, `Card`, `CardReviewState`, `CardReview`, `KnowledgeItem`, `KnowledgeItemRelation`, `Source`, `KnowledgeItemSource`
- `core/backend/migrations/versions/0001_canonical_initial_schema.py` - canonical schema tables (incl. `notes`, `entity_links`, `cards`, `card_review_states`, `card_reviews`)
- `core/backend/tests/unit/test_cards_schema.py` - ORM metadata + live schema tests for Cards layer
- `core/backend/app/policy/actions.py` - Knowledge policy actions wired via proposal
- `core/backend/app/policy/proposal_apply.py` - supported Knowledge proposal type names
- `core/backend/app/modules/registry.py` - active backend module registry entry
- `frontend/src/modules/knowledge/` - `KnowledgeModule` (index redirect + routes), `KnowledgeSectionHeader` (breadcrumb switcher), `utils.ts` (last-used section storage + canonical vocabularies), `KnowledgeOverviewPage` (`/knowledge/home`), `NotesPage` workspace + `NoteEditor`, `KnowledgePage`/`KnowledgeDetailPage` (Wiki), `SourcesPage`, `KnowledgeCardsPanel`
- `frontend/src/core/navigation.tsx` - first-level "Knowledge" rail item only (Knowledge has **no** scene; sections switch via the in-header breadcrumb)
- `core/backend/tests/invariants/test_knowledge_ingestion_boundary.py` - ingestion/review boundary invariant tests
- `core/backend/tests/contracts/test_knowledge_api.py` - wiki API contract tests (accept, versioning, visibility, relations)
- `core/backend/tests/contracts/test_notes_api.py` - notes/links/backlinks/summary contract tests

## Related Modules
- [../architecture/INTAKE_EVIDENCE_FOUNDATION.md](../architecture/INTAKE_EVIDENCE_FOUNDATION.md) - the two evidence stacks (intake candidate vs curated wiki `Source`/`KnowledgeItemSource`), their hard separation, and the intake→wiki promotion rule spec
- [memory.md](memory.md) - Memory is agent context, not the Knowledge browser
- [activity.md](activity.md) - raw input and source events
- [spaced-repetition.md](spaced-repetition.md) - future card generation from approved Knowledge
- [proposals.md](proposals.md) - proposal review and apply boundary

## TODO
- Notes: ProseMirror/Tiptap rich editor (schema already ProseMirror-ready), full link
  picker across all entity types, and richer collection management
- Note → Wiki promotion flow (create a `knowledge_create` proposal from a note, linked
  via `entity_links` `source_for`/`derived_from`)
- Plain-text/excerpt + search projection regeneration from `content_json`
- Later Feynman and Reflection assessments
- Automatic Activity/Artifact to Knowledge proposal generation
- Source monitoring evaluator for Knowledge proposals
- **Cards — next slice**: card generation workflow (from Notes/Wiki/Sources → Card rows),
  direct CRUD API under `/api/v1/knowledge/cards`, FSRS review scheduler, and the
  frontend review UI. Schema (cards / card_review_states / card_reviews) is in place.
