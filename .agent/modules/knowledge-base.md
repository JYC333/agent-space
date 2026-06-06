# Module: Knowledge Base

## Status
**BACKEND MVP IMPLEMENTED** - core ORM models, canonical schema, `/api/v1/knowledge` read/proposal API, and proposal apply handlers exist. The full frontend browser, automatic generation, assessments, cards, and search remain future work.

## Purpose
The Knowledge Base is the human-browsable, reviewable, relational long-term content layer. Backend and API naming must use `knowledge`; space-specific product labels are presentation concerns for later frontend work.

Knowledge is distinct from Memory. Memory is agent context. Knowledge is durable content for people to inspect, revise, relate, and later use as a source for other review flows.

No legacy route or compatibility alias exists for the replaced planned module. The API path is `/api/v1/knowledge`; canonical table names are `knowledge_items`, `knowledge_item_relations`, `sources`, and `knowledge_item_sources`; proposal types use `knowledge_*`.

## Three-Layer Model

The wiki is split into three explicit layers:

1. **KnowledgeItem** — the semantic wiki content layer. Only the 9 semantic item
   types below. `source` and `answer` are **not** item types.
2. **Source** — an independent provenance / evidence object (table `sources`). Raw
   material/evidence (webpage, paper, chat capture, processed ActivityRecord, …).
   A Source is **not** a wiki item and must never appear in the main KnowledgeItem
   list. `source` is now a table, not a KnowledgeItem type.
3. Two explicit link tables:
   - **KnowledgeItemRelation** (`knowledge_item_relations`) — item↔item semantic
     graph relations. `answer` is now a **relation type** (`answers`), not an item
     type: an answer is any appropriate KnowledgeItem (e.g. `knowledge`) linked to a
     `question` item via `relation_type=answers`.
   - **KnowledgeItemSource** (`knowledge_item_sources`) — item↔source evidence /
     provenance links. This is strictly for evidence, never for item↔item relations.

## Owns
- `KnowledgeItem` model
- `KnowledgeItemRelation` model (item↔item semantic relations)
- `Source` model (independent provenance/evidence layer)
- `KnowledgeItemSource` model (item↔source evidence links)
- `/api/v1/knowledge` read and proposal API, plus `/api/v1/knowledge/sources` direct CRUD
- Knowledge proposal apply handlers
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

`KnowledgeItem.item_type` currently allows:

| Type | Purpose |
|---|---|
| `knowledge` | General durable knowledge item |
| `idea` | Nascent idea or hypothesis |
| `experience` | First-person or observed experience |
| `reflection` | Reflective synthesis |
| `lesson` | Learned principle or takeaway |
| `procedure` | Repeatable steps or operating procedure |
| `decision` | Decision record or rationale |
| `question` | Open question |
| `summary` | Digest of an Activity, Run, Artifact, or Source |

`source` and `answer` are **removed** as item types. Provenance/evidence now lives
in the `Source` table; "answering a question" is expressed with
`KnowledgeItemRelation.relation_type = answers` between two KnowledgeItems
(e.g. `KnowledgeItem(type=knowledge) --answers--> KnowledgeItem(type=question)`).

Knowledge-type items may later use a Feynman Gate. Experience-type items may later use a Reflection Gate. These are future assessment flows and must not block the MVP persistence/API slice.

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
KnowledgeItem:
  id, space_id
  project_id, workspace_id        # optional associations
  root_item_id, supersedes_item_id
  item_type                       # item types above
  title, content, content_format
  status                          # draft|active|superseded|archived
  visibility                      # private|space_shared|workspace_shared|restricted
  verification_status, reflection_status
  tags_json, confidence, source_url, source_refs_json
  owner_user_id, created_by_user_id, created_by_agent_id, created_by_run_id
  source_activity_id, source_artifact_id, created_from_proposal_id
  approved_by_user_id
  version, created_at, updated_at, archived_at

KnowledgeItemRelation:                # item <-> item semantic graph
  id, space_id
  from_item_id, to_item_id
  relation_type                   # related_to|derived_from|supports|contradicts|
                                  #   answers|summarizes|depends_on|updates
  status                          # candidate|active|rejected|archived
  confidence, note
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
- `core/backend/app/knowledge/` - API, service, schemas, read models
- `core/backend/app/models.py` - `KnowledgeItem`, `KnowledgeItemRelation`, `Source`, `KnowledgeItemSource`
- `core/backend/migrations/versions/0001_canonical_initial_schema.py` - canonical schema tables
- `core/backend/app/policy/actions.py` - Knowledge policy actions wired via proposal
- `core/backend/app/policy/proposal_apply.py` - supported Knowledge proposal type names
- `core/backend/app/modules/registry.py` - active backend module registry entry
- `frontend/src/modules/knowledge/KnowledgePage.tsx` - planned frontend stub
- `core/backend/tests/invariants/test_knowledge_ingestion_boundary.py` - ingestion/review boundary invariant tests
- `core/backend/tests/contracts/test_knowledge_api.py` - API contract tests (accept, versioning, visibility, relations)

## Related Modules
- [../architecture/INTAKE_EVIDENCE_FOUNDATION.md](../architecture/INTAKE_EVIDENCE_FOUNDATION.md) - the two evidence stacks (intake candidate vs curated wiki `Source`/`KnowledgeItemSource`), their hard separation, and the intake→wiki promotion rule spec
- [memory.md](memory.md) - Memory is agent context, not the Knowledge browser
- [activity.md](activity.md) - raw input and source events
- [spaced-repetition.md](spaced-repetition.md) - future card generation from approved Knowledge
- [proposals.md](proposals.md) - proposal review and apply boundary

## TODO
- List/detail frontend
- Later Feynman and Reflection assessments
- Automatic Activity/Artifact to Knowledge proposal generation
- Source monitoring evaluator for Knowledge proposals
- Later card generation
