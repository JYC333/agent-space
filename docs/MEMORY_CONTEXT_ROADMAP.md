# Memory and Context Roadmap

## Purpose

This document records future extension directions for the current memory/context architecture.
It is not a history of past changes. All paths below are optional and can be prioritised
independently of one another.

The current foundation provides:

- Activity as the raw event layer
- Proposal-only durable Memory and Policy writes
- Provenance links and source monitoring
- Activity consolidation into reviewable MemoryCandidates
- MemoryRetriever with hard space/user/workspace filters
- ContextSnapshot audit before run execution
- ContextDigest as a derived stable-prefix cache

---

## Current Stable Foundation

The current system forms a clean, unidirectional chain:

```
ActivityRecord
  → MemoryCandidate
  → MemoryCandidateValidator
  → MemoryProposalProducer
  → Proposal
  → ProposalApplyService
  → MemoryEntry / Policy
  → MemoryRetriever
  → ContextDigest
  → ContextSnapshot
  → Run
```

Agents do not write directly to MemoryEntry or Policy.
Every durable write goes through a Proposal that requires explicit approval.

---

## Extension Path A — Context Digest Maturity

Improvements to the ContextDigest layer:

- Dirty tracking refinement: mark digest stale on specific source changes, not all writes
- Configurable regeneration thresholds (token staleness, time-based, manual)
- Manual refresh endpoint for user-triggered regeneration
- `source_hash` and `content_hash` observability for audit
- Stable-prefix token savings metrics (track actual tokens avoided per run)
- Digest quality templates (structured vs free-form vs domain-specific)
- Digest freshness policy per space or workspace
- Optional LLM-assisted digest generation using only approved Memory sources

**Constraints:**

- Digest remains a derived cache, not durable Memory.
- Digest must not create a Proposal unless explicitly promoted to known fact.
- Digest must not ingest external sources directly — it reflects approved Memory only.

---

## Extension Path B — Personal Radius / Source Horizon

A future Personal Radius layer for tracking external information sources:

- External source profiles (RSS feeds, browser capture, article feeds, GitHub watches, paper feeds)
- Private search index over followed sources
- Source trust level, source role (informational vs authoritative), and source weighting
- Radius search runs before falling back to public web search
- Radius results can become ActivityRecord entries or context candidates

**Constraints:**

- Radius content is not confirmed Memory; it is candidate input only.
- Following a source does not mean agreeing with it.
- Radius results cannot bypass Activity → Proposal → Provenance.
- Radius should be implemented as a ContextSource adapter, not embedded in MemoryEntry.

**Suggested objects:**

- `SourceProfile` — user-registered external source
- `SourceDocument` — captured document from a source
- `RadiusIndex` — local search index over source documents
- `RadiusSearchService` — ranked retrieval over the radius index
- `ContextSourceAdapter` — pluggable source for ContextSnapshot assembly

> **Note:** "ContextSource adapter" here is a future design-pattern name for a pluggable
> retrieval adapter. It is unrelated to the historical `context_sources` database table,
> which was removed from the schema.

---

## Extension Path C — Wiki / Knowledge Synthesis

A structured knowledge layer synthesised from approved sources:

- Approved Memory entries and Artifacts can be synthesised into Wiki pages
- Wiki pages are readable long-form knowledge (distinct from raw Activity)
- Wiki updates go through Proposal if the change is durable
- Wiki preserves provenance back to the originating Memory / Activity / Artifact

**Constraints:**

- Wiki is not raw Activity — it represents synthesised, reviewed knowledge.
- Wiki is not an ephemeral ContextSnapshot — it is persistent structured content.
- Wiki derives only from approved sources; agents cannot write Wiki pages directly.

---

## Extension Path D — Cards / Learning / Review

A spaced-repetition and review layer built on approved knowledge:

- Cards created from approved Memory, Wiki pages, or Artifacts
- Spaced repetition scheduling or user-configured review workflows
- Card creation goes through Proposal if the card represents a durable fact
- Cards preserve provenance back to their source Memory or Artifact

**Constraints:**

- Cards are user-facing study and review units, not hidden memory facts.
- Cards must not become silent memory writes; approval is required for durable cards.

---

## Extension Path E — Advanced Consolidation

Improvements to the activity → candidate pipeline:

- Multi-activity semantic synthesis (grouping related events into a single candidate)
- Conflict detection between incoming candidate and existing Memory
- Contradiction proposals: surfacing when a new candidate disagrees with active Memory
- Stale memory review scheduling (`reconsolidation_due` field)
- Candidate clustering before promotion to reduce proposal noise
- Case memory synthesis (grouping a session or run into a single structured candidate)
- User feedback loops to tune consolidation quality

**Constraints:**

- Classifier output remains candidate-only; it never writes MemoryEntry directly.
- Validator must remain deterministic for hard space/user/workspace boundaries.
- No direct active Memory writes from the consolidation pipeline.

---

## Extension Path F — Retrieval and Context Intelligence

Improvements to MemoryRetriever and ContextSnapshot assembly:

- Better symbol and entity extraction from queries
- Relation graph ranking (surface connected Memory, not just keyword matches)
- Controlled embedding backend (opt-in; embeddings must not reintroduce forbidden Memory)
- Hybrid lexical + semantic retrieval modes
- Retrieval evaluation metrics (precision, recall over known test cases)
- Context budget optimizer (rank-order entries to fit token budget)
- Stable-prefix / dynamic-tail split tuning
- Explainable retrieval traces (log why each entry was included)

**Constraints:**

- Hard filters (space, user, workspace, policy) must always run before ranking or embeddings.
- Embeddings must not circumvent scope boundaries.
- ContextSnapshot must remain auditable and reproducible.

---

## Extension Path G — Policy and Permission Maturity

Richer enforcement and administration of the Policy layer:

- Policy conflict detection (flag when two active policies contradict)
- Approval routing rules (route proposals to specific reviewers by type or scope)
- Agent/capability-specific permissions (restrict which agents can do what)
- Policy simulation: preview the effect of a new policy before applying it
- Admin review UX for policy management

**Constraints:**

- Policy remains a separate model from Memory.
- `policy_change` proposals remain required; agents cannot infer or write Policy silently.
- Policy simulation output is read-only and does not auto-apply.

---

## Extension Path H — Memory Review UX

Improved surfaces for users to understand and govern their memory:

- Inbox view for raw Activity (capture what has been recorded)
- Review queue for pending Memory, Policy, Wiki, and Card proposals
- Explanation view per proposal: what it is, where it came from, what it would change
- Advanced provenance view (trace a MemoryEntry back through Proposal → Activity)
- Risk labels for `untrusted_external` and `agent_inferred` provenance
- Version history and superseded-memory view

**Constraints:**

- Users should not need to understand internal pipeline stages to use the review UI.
- UI should expose: Capture / Review / Remembered / Rules / Source / Effect.

---

## Extension Path I — Evaluation and Observability

Metrics and tooling for understanding system health:

- Memory precision and recall checks (are retrieved memories actually relevant?)
- Proposal acceptance and rejection rates by source type
- Source trust distribution across the active Memory corpus
- ContextSnapshot audit review surface
- Token budget trends over time
- Digest usage and fallback rates (how often does the digest miss and force full retrieval?)
- Retrieval trace sampling for qualitative review
- Run failure explainability (which context entries were present when a run failed?)

---

## Extension Path J — Automation and Scheduling

Reducing manual overhead through scheduled background work:

- Scheduled consolidation runs (batch process accumulated Activity into candidates)
- Scheduled digest refresh (regenerate stale digests during off-peak hours)
- Stale memory review reminders (surface MemoryEntry records past `reconsolidation_due`)
- Intake source refresh (pull new candidate items from configured source connections on a schedule)
- Review queue batching (group related proposals for a single review session)
- User-configurable automation policies (set thresholds for when automation runs)

**Constraints:**

- Automation creates proposals or updates derived cache only.
- Automation must not silently mutate durable MemoryEntry or Policy records.

---

## Near-Term Recommended Order

A conservative sequencing that builds on real usage before adding complexity:

1. Complete any remaining cleanup and documentation sync.
2. Use the current system in real workflows for several weeks.
3. Observe ContextSnapshot and digest traces under actual load.
4. Improve ContextDigest dirty tracking and regeneration policy (Path A).
5. Improve Memory Review UX — inbox, review queue, explanation view (Path H).
6. Add Personal Radius as a separate ContextSource adapter layer (Path B).
7. Add advanced consolidation only after enough real Activity data exists (Path E).

---

## Non-Goals for Now

The following should not be built until the above foundation is stable and well-exercised:

- Full ontology editor or knowledge graph UI
- Broad vector database migration
- Automatic user profile generation from Memory
- Cross-workspace free association
- Personal Radius ingestion before review boundaries are fully stable
- Auto-accept for high-risk proposals (agent_inferred, untrusted_external)
- Digest promoted as a new source of truth for Memory
- Agents self-modifying Policy without approval
