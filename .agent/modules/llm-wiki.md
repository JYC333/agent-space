# Module: LLM Wiki

## Status
**PLANNED** — not yet implemented. This doc defines intended design.

## Purpose
Structured, agent-enhanced knowledge base. Knowledge items are distinct from memories — they are richer, interlinked, and versioned. Agent-generated changes require proposals. The wiki is the long-form, relational layer between raw activity records and lightweight memory entries.

## Owns
- `KnowledgeItem` model (planned)
- `KnowledgeRelation` model (planned)
- Wiki browsing and editing UI (planned)
- Agent-generated wiki proposals
- Wiki → card generation pipeline

## Does Not Own
- Raw capture (activity-inbox module)
- Spaced repetition scheduling (spaced-repetition module)
- Long-term contextual memory (memory module)

## Knowledge vs Memory

| Aspect | Memory | Knowledge Item |
|---|---|---|
| Structure | Free-form text, scoped | Typed: concept/note/claim/source/question |
| Linking | None | KnowledgeRelation graph |
| Audience | Per-user context injection | Shared, browsable |
| Write path | Proposal → approval | Proposal → approval |
| Usage | Agent context (ContextBuilder) | Wiki browsing, card generation |

## Knowledge Item Types

| Type | Description | Example |
|---|---|---|
| `concept` | Definition or explanation of a term | "What is FSRS?" |
| `note` | Freeform structured note | Meeting notes, book highlights |
| `claim` | Assertion with confidence level | "Rust is memory-safe" |
| `source` | Reference to an external resource | Article URL + summary |
| `question` | Open question to be answered | "How does X compare to Y?" |
| `answer` | Answer to a question item | Linked to `question` via KnowledgeRelation |
| `summary` | Agent-generated digest of content | Summary of a long document |

## Knowledge Relation Types

| Relation | Direction | Meaning |
|---|---|---|
| `related` | bidirectional | Loosely connected |
| `supports` | from → to | from supports claim in to |
| `contradicts` | from → to | from disputes claim in to |
| `derived_from` | from → to | from was generated from to |
| `part_of` | from → to | from is a section/component of to |
| `example_of` | from → to | from is a concrete example of to |
| `answers` | from → to | from answers question in to |

## Key Models (Planned)

```
KnowledgeItem:
  id, space_id, workspace_id
  type (concept|note|claim|source|question|answer|summary)
  title, content, content_format (markdown|plain)
  status (draft|active|archived)
  visibility (private|space_shared|workspace_shared)
  tags[]                   — flat string tags
  confidence               — 0.0–1.0 (for claims)
  source_url               — optional for source type
  created_by               — user_id or agent_id
  version                  — increments on content change
  created_at, updated_at

KnowledgeRelation:
  id, space_id
  from_id                  — FK → KnowledgeItem
  to_id                    — FK → KnowledgeItem
  relation_type            — see table above
  created_by, created_at
```

## Main Flow

**Agent-generated wiki item:**
1. Agent analyzes activity or session
2. Proposes new KnowledgeItem or KnowledgeRelation
3. User approves in proposal panel
4. Item becomes active

**Manual wiki editing:**
1. User creates/edits KnowledgeItem directly (status=draft)
2. Auto-approved for self-authored items (configurable per space)
3. Agent edits always require explicit approval

**Wiki → card generation:**
1. Active KnowledgeItem with `type=concept|claim|question` triggers card generation
2. Agent proposes FlashCard(s) from item content
3. User approves; cards enter review queue

## UI Sections

**Wiki browser (center panel):**
- Tree or graph view of KnowledgeItems
- Filter by: type, tags, workspace, status, confidence
- Search: full-text across title + content
- Each item: type badge, title, content preview, relation count

**Knowledge item detail:**
- Full content rendered as Markdown
- Relation graph: linked items with relation types
- Version history
- Source attribution (agent run or user)
- Related cards (if any)
- Actions: edit (opens proposal), archive, generate cards

**Relation editor:**
- Select relation type
- Search and link target item
- Creates KnowledgeRelation (requires approval if agent-generated)

## Invariants
- Agent-generated wiki changes require proposals — never direct writes
- KnowledgeItems are distinct from Memory — they are browsable and linked
- A KnowledgeRelation cannot be created between items in different spaces
- Wiki is not a replacement for Memory — both can coexist for different purposes
- `content` is immutable after creation except via versioned update (new version number)
- `source_url` is stored as-is — never followed or fetched automatically

## Related Files
- `core/backend/app/models.py` — TODO: add KnowledgeItem, KnowledgeRelation
- `core/backend/app/memory/proposals.py` — existing proposal pattern to follow
- `core/backend/app/knowledge/` — TODO: wiki CRUD module
- `frontend/src/pages/` — TODO: wiki browser page

## Related Modules
- [memory.md](memory.md) — memory is shorter-form, not linked; both exist
- [activity-inbox.md](activity-inbox.md) — raw content enters here before becoming wiki items
- [spaced-repetition.md](spaced-repetition.md) — wiki items generate flashcards
- [proposals.md](proposals.md) — wiki writes always go through proposals

## TODO
- KnowledgeItem and KnowledgeRelation models
- Wiki CRUD API
- Wiki-to-card generation pipeline
- Frontend wiki browser
