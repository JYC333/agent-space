# Memory Evolution Plan

Status: forward-looking plan, updated 2026-06-21.

This document describes planned Memory-quality work. It is distinct from the
Knowledge retrieval substrate + brain layer in
[`RETRIEVAL_AND_BRAIN_LAYER.md`](RETRIEVAL_AND_BRAIN_LAYER.md).

The original gbrain absorption plan mixed near-term retrieval mechanics with
future Memory evolution. Current direction splits that work into two tracks:

- Track A: the Knowledge retrieval substrate — **implemented and superseded** by
  [`RETRIEVAL_AND_BRAIN_LAYER.md`](RETRIEVAL_AND_BRAIN_LAYER.md); the Phase-1-only
  scope below (no vector/rerank/synthesis) is historical — those have since shipped.
- Track B: later Memory quality and retrieval integration (still forward-looking).

The proposal gate, space boundary, privacy boundary, and ContextBuilder memory
rules remain unchanged.

## Track A: Knowledge Retrieval Substrate (implemented; historical)

> Implemented and superseded — see
> [`RETRIEVAL_AND_BRAIN_LAYER.md`](RETRIEVAL_AND_BRAIN_LAYER.md) for current state.
> The "Track A does not …" list below captured the original Phase-1 (zero-LLM)
> scope; vector search, embeddings, rerankers, query rewrite, and LLM synthesis
> have since been added under their own boundaries. Kept for historical context.

Track A starts with Knowledge-owned objects only:

- `KnowledgeItem`
- `Note`
- `Source`

It absorbs gbrain-style mechanics such as deterministic alias matching,
normalized text search, markdown/wikilink extraction, retrieval graph expansion,
rank fusion, and evidence/create-safety contracts.

Track A does not:

- Add gbrain as a dependency.
- Make gbrain the system of record.
- Index MemoryEntry rows.
- Change Memory write paths.
- Auto-inject Knowledge, Notes, Sources, or retrieval results into
  ContextBuilder.
- Add vector search, pgvector, embeddings, rerankers, or LLM synthesis.
- Turn heuristic links into accepted canonical `KnowledgeItemRelation` rows.
- Revive the removed `context_sources` table.

The Knowledge retrieval projection is derived data. It can be rebuilt from
canonical Knowledge tables and must be live-revalidated before returning results.

## Track B: Later Memory Quality And Retrieval Integration

Memory integration is deferred until the Knowledge substrate proves the
mechanics and until a separate design covers:

- Memory ACL and sensitivity revalidation for every retrieval arm.
- `MemoryReadTrace` logging requirements for candidate reads and context
  injection.
- SourceMonitoring interaction for duplicate/update suggestions.
- Proposal payload shape for retrieval evidence and duplicate detection.
- ContextBuilder hard filters and token-budget behavior.
- Evaluation gates for ranking and leakage.

Any Memory-side implementation must preserve:

- Public Memory writes create proposals, not active `MemoryEntry` rows.
- Accepted Memory changes go through `ProposalApplyService` and the memory
  applier/writer path.
- ContextBuilder remains the only runtime memory context authority.
- Every injected MemoryEntry is logged through MemoryReadTrace.
- Cross-space and private/restricted memory reads remain fail-closed unless a
  documented grant path explicitly applies.

## Future Memory Work

The useful gbrain-style ideas for later Memory work remain:

- Evidence contracts for retrieval results and proposal review.
- Create-safety signals for duplicate Memory proposals.
- Deterministic clustering to batch likely duplicates or thin entries.
- Weighted claims or confidence signals where they do not conflict with current
  status/version semantics.
- Lexical retrieval and graph expansion behind the existing Memory hard filter.
- Salience and recency as separate ranking axes.
- Synthesis/gap contracts for assistant answers, after Memory retrieval and
  citation rules are explicit.
- Scheduled maintenance that emits review candidates or proposals, never direct
  active Memory writes.

The privacy-first backend MVP for this scheduled/manual work is
[`MEMORY_MAINTENANCE.md`](MEMORY_MAINTENANCE.md). Current
implementation supports manual scans, durable full-scan jobs, scheduler
advancement, report artifacts, and review packets. Packet acceptance can
generate child pending `memory_archive` and `memory_update` proposals for
supported findings without writing canonical Memory directly.

Vector search, embeddings, rerankers, and LLM-backed synthesis are not part of
the first Knowledge retrieval implementation and should not be described as
current Memory behavior.

## Standing Risks

- Retrieval arms must never bypass hard filters or source monitoring.
- Derived indexes must never become source of truth.
- Ranking changes need focused evals before they affect runtime context.
- Automated maintenance must batch review pressure instead of creating one
  proposal per finding.
- Knowledge-to-Memory promotion remains a future explicit proposal flow.
