# Brain Layer Next Work Plan

Status: brain shape registry closure complete; guardrail reference for future
brain-layer work
Date: 2026-06-27
Scope: completed gbrain-inspired brain-layer work for Agent Space, including the
Brain Shape Registry implementation path and excluding full gbrain-style dynamic
schema-pack runtime.

This is a planning document, not current-state architecture. It intentionally
does not retain historical lists of shipped work. Implemented behavior lives in
[`RETRIEVAL_AND_BRAIN_LAYER.md`](RETRIEVAL_AND_BRAIN_LAYER.md), with the durable
claim/fact model in
[`CLAIM_FACT_ATOM_MODEL.md`](CLAIM_FACT_ATOM_MODEL.md), source/connector policy
in [`SOURCE_CONNECTOR_CONSENT.md`](SOURCE_CONNECTOR_CONSENT.md), Memory
maintenance state in [`MEMORY_MAINTENANCE.md`](MEMORY_MAINTENANCE.md), and Brain
Shape Registry design in
[`SCHEMA_PACKS_AND_OBJECT_SHAPE.md`](SCHEMA_PACKS_AND_OBJECT_SHAPE.md). Code
remains the source of truth when implementation and docs disagree.

## 1. Guardrails

Future brain-layer work must preserve these constraints:

1. Agent Space DB remains authoritative; gbrain, MCP servers, CLIs, and vendor
   context files are adapters, never source of truth.
2. Knowledge, Memory, Claims, and Project public summaries remain separate
   domains unless a future ADR explicitly changes that boundary.
3. Every surfaced candidate passes live read revalidation before content leaves
   the retrieval engine.
4. LLM stages only see already-visible content and must pass provider policy,
   credential-channel isolation, source policy, external-egress policy, and
   pointer-only audit.
5. Ranking, graph, salience, diagnostics, gaps, maintenance findings, and shape
   diagnostics must not leak unreadable object existence, hidden counts, dropped
   ids, private titles/snippets, or near-miss hints.
6. Cross-space retrieval, shape config, source policy, and cache behavior remain
   fail-closed.
7. Canonical Knowledge, Memory, claim, object-relation, and shape-registry writes
   remain proposal-gated.
8. Review output must be batched, clustered, and confidence-tiered. Do not create
   one proposal per finding.
9. Full gbrain-style dynamic schema packs remain rejected as the runtime model.

## 2. Current Closure State

### A. Brain Shape Registry Implementation

The Brain Shape Registry implementation path is complete in the current code
and documented in
[`SCHEMA_PACKS_AND_OBJECT_SHAPE.md`](SCHEMA_PACKS_AND_OBJECT_SHAPE.md). The
registry uses `space_object_kinds` under the fixed retrieval `object_type` enum,
owner/admin proposal flows, active-kind retrieval projection and filtering,
field-schema-aware proposal validation, relation hints, object-schema
export/import as draft proposals, and deterministic Brain Ops schema-suggestion
reports. It does not add dynamic schema-pack runtime behavior.

## 3. Cross-Cutting Prerequisites

- Brain Ops is the review surface for deterministic shape suggestions and should
  remain the review surface for future schema drift work.
- Future source-text classes or schema-hint expansion must reuse the current
  read/source/egress gates before content reaches an LLM or review artifact.
- Proposal-review UX must support batched review before new maintenance,
  discovery, or shape suggestions produce more candidate work.

## 4. Non-Goals

- Do not import or run the gbrain runtime, or make a gbrain DB/repository
  authoritative for Agent Space.
- Do not expose an external MCP brain server as the default brain interface.
- Do not merge Knowledge, Memory, Claims, and Project public summaries.
- Do not auto-promote Memory to Knowledge, Knowledge to Memory, or hot Memory
  facts to cold claims without a reviewed packet.
- Do not silently inject retrieval/Think results into runtime context.
- Do not let retrieval, context assembly, diagnostics, maintenance, Brain Ops,
  Think, discovery, or shape config write canonical rows directly.
- Do not widen cross-space retrieval.
- Do not add private backlink counts, hidden graph-degree counts, dropped ids,
  hidden titles/snippets, or near-miss hints.
- Do not ship a cross-viewer semantic results cache.
- Do not add a per-call `schema_pack` override, executable packs, or pack-driven
  canonical writes.
- Do not make schema packs the source of truth; registry rows and approved
  shape-profile versions remain Agent Space-owned state.
- Do not build broad connector ingestion without source consent enforcement.
- Do not persist raw private retrieval traces in eval/diagnostic artifacts.
- Do not weaken proposal/approval for canonical writes.

## 5. Success Criteria

The brain-layer phase is successful because:

- Brain Shape Registry reaches retrieval visibility on top of the implemented
  registry foundation without changing canonical `object_type`.
- Agent Space keeps borrowing useful gbrain ideas without depending on the
  gbrain runtime or weakening its stronger governance boundaries.

## Cross-References

- Current-state retrieval and brain layer:
  [`RETRIEVAL_AND_BRAIN_LAYER.md`](RETRIEVAL_AND_BRAIN_LAYER.md)
- Claim/fact atom and core object model:
  [`CLAIM_FACT_ATOM_MODEL.md`](CLAIM_FACT_ATOM_MODEL.md)
- Source/connector consent:
  [`SOURCE_CONNECTOR_CONSENT.md`](SOURCE_CONNECTOR_CONSENT.md)
- Brain Shape Registry / schema-pack design:
  [`SCHEMA_PACKS_AND_OBJECT_SHAPE.md`](SCHEMA_PACKS_AND_OBJECT_SHAPE.md)
- Memory maintenance architecture:
  [`MEMORY_MAINTENANCE.md`](MEMORY_MAINTENANCE.md)
- Knowledge module:
  [`../modules/knowledge-base.md`](../modules/knowledge-base.md)
- Memory module:
  [`../modules/memory.md`](../modules/memory.md)
- Credential/provider channel:
  [`../decisions/0010-credential-channel-isolation.md`](../decisions/0010-credential-channel-isolation.md)
- Engine/domain and runtime adapter boundaries:
  [`../BOUNDARIES.md`](../BOUNDARIES.md)
