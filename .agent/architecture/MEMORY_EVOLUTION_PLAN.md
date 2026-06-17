# Memory Evolution Plan (gbrain Absorption)

> **Status:** forward-looking plan, established 2026-06-11. This document
> describes **planned** memory-quality work, not current state; implementation
> lands incrementally and every promotion/consolidation output stays behind the
> proposal gate. Unrelated to the backend `evolution` module (capability/prompt
> evolution). Companions: [`MEMORY_MODEL.md`](MEMORY_MODEL.md),
> [`MEMORY_ACTIVITY_PROVENANCE.md`](MEMORY_ACTIVITY_PROVENANCE.md),
> [`PROPOSALS.md`](PROPOSALS.md),
> [`SERVER_OWNERSHIP.md`](SERVER_OWNERSHIP.md).
>
> External reference: gbrain (<https://github.com/garrytan/gbrain>), reviewed
> 2026-06-11. gbrain is a single-user "brain layer" whose value over a plain
> memory store is a **quality core**: confidence-weighted claims with
> lifecycle, a hybrid retrieval stack, a synthesis layer with gap analysis, and
> an autonomous consolidation cycle. This plan absorbs that quality core into
> agent-space's governance model — never the other way around.

---

## 1. Position

Verified current state (2026-06-11):

- `server/src/modules/context/repository.ts` — hard filter → symbol match → 2-hop typed-relation
  graph expansion → keyword fallback → **embedding fallback stub**.
- `server/src/modules/memory/` consolidation routes/jobs — activity → rule-based trust-aware classifier →
  validator → **proposals only** (single-hop promotion, no clustering, no
  confidence model).
- `MemoryRelation` typed edges exist (`derived_from`, `related_to`,
  `applies_to`, `supports`, `caused_by`); edges are created through governed
  flows, not extracted automatically.
- No confidence weight, no bitemporal validity, no salience/recency ranking,
  no synthesis contract over memory answers.

gbrain's published benchmark (240-page corpus: full stack P@5 49.1 vs ~18 for
vector-only, "+31 points from graph + extraction") independently validates our
typed-relation graph as the load-bearing retrieval signal. The gap is the rest
of the stack around it.

## 2. Guiding principles

1. **The proposal gate is preserved.** gbrain's consolidation writes directly;
   ours never does. Every promotion, supersession, relation, and enrichment
   produced by this plan is a proposal (or a review item), applied only through
   the existing applier registry.
2. **The database remains the system of record.** gbrain treats a git repo as
   SoR with the DB as derived index; that conflicts with our
   server-authoritative model and is rejected.
3. **Zero-LLM-first mechanics.** Clustering, intent classification, and
   auto-link extraction are deterministic (gbrain proves this is enough for the
   pipeline spine). LLM-backed steps are optional and run as auxiliary tasks
   under provider task-policy chains.
4. **Everything lands behind the server memory module boundary.** Memory quality
   work belongs under `server/src/modules/memory/` and its registered
   collaborators. No new cross-module deep imports.
5. **Hard filters cannot be bypassed.** New retrieval arms (vector, BM25,
   salience) re-apply the existing space/visibility/status hard filter exactly
   as the current keyword and graph arms do.

## 3. Absorption map

| # | gbrain concept | What we absorb | Where it lands |
|---|---|---|---|
| G1 | Graduated promotion: atoms → facts → **takes** (weight = avg confidence, `kind=fact\|hunch`, `since_date`); 24h age gate; cosine clustering (≥2 members = corroboration); never delete (`consolidated_at`/`consolidated_into`); bitemporal `valid_until` on superseded facts | Weighted claim model on `MemoryEntry` (`weight`, `claim_kind`, `valid_from`, `valid_until`, consolidation provenance) + clustering-based promotion in `memory/consolidation/` producing **upgrade proposals** | server memory module (schema + consolidation) |
| G2 | Hybrid retrieval: vector (HNSW on pgvector) + BM25 (tsvector) + **RRF fusion** (rank votes, no global weights); per-page max-pool; zero-LLM intent classification (entity/temporal/event/general) with graceful misclassification | Fill the embedding fallback stub with pgvector; add tsvector arm; fuse all arms (incl. existing graph expansion) via RRF; collapse multi-chunk hits; deterministic intent routing of ranking parameters | server context/memory retrieval |
| G3 | Evidence contract: every result labeled `evidence` (alias_hit / exact_title / high_vector / keyword_exact / weak_semantic) + `create_safety` (exists / probable / unknown) | Extend the existing `retrieval_trace` into a per-result evidence contract; surface it in memory-proposal review so the reviewer sees *why* something is judged new-vs-update; agents use `create_safety` to avoid duplicate entries | server memory + proposal review UI |
| G4 | Zero-LLM auto-linking on every write (regex entity-ref extraction, heuristic edge-type inference) | Deterministic relation-candidate extraction at memory/knowledge write time. Whether an edge class may be written as a system-derived edge or must go through a relation proposal is a **policy decision recorded at implementation time** — default is proposal | server memory/knowledge + policy decision |
| G5 | Salience and recency as **orthogonal axes**: salience = importance with *no* time component; recency = per-category decay (evergreen vs volatile half-lives); "current state → on, canonical truth → off" | Memory-kind decay profiles (preference/decision = evergreen; daily capture = volatile); salience recomputed by the consolidation cycle; deterministic axis activation from query intent | server memory ranking |
| G6 | Synthesis contract + gap analysis: strict output of `answer` (every substantive claim cited) + `citations` + `gaps` (what the brain does not know); claims with `weight < 0.5` or `kind=hunch` must be labeled; conflicting claims surfaced, never silently resolved | Memory-grounded assistant answers adopt the same contract; **gaps become a capture driver**: gap → suggested capture/question → activity → proposal → memory, closing the dogfooding loop | server memory/agents chat path |
| G7 | Dream cycle: scheduled 24/7 consolidation with budget meter, phase keepalives, enrich-thin, contradiction detection, drift/anomaly checks, nightly quality probe | Scheduled consolidation tick via `SchedulerRegistry` with an explicit budget meter; phases emit **proposals and review items** (activity inbox), never direct writes; quality probe flags thin/contradictory/stale entries for review | server memory + jobs/scheduler |
| G8 | Three-layer knowledge placement: durable world knowledge vs agent operational state vs ephemeral session ("if the agent loses memory, the brain still has everything"), with routing verification | Routing discipline in reflector/consolidation classification: each proposal explicitly targets memory vs knowledge vs agent settings; contamination checks added to the invariant test layer | server memory/knowledge classifiers + tests |

### Explicitly NOT absorbed

- **Git/markdown as system of record** — conflicts with server authority and
  the proposal gate; the DB stays authoritative (principle 2).
- **Direct autonomous writes from the consolidation cycle** — all outputs are
  proposals/review items here (principle 1).
- **External reranker as hard dependency** (ZeroEntropy) — optional later, as
  a credential-governed auxiliary provider; RRF + graph signals first.
- **Brains/Sources organizational axes** — Space/Workspace already covers
  scoping with stronger governance.

## 4. Implementation order

Phases are sequential by dependency; each ships with tests per
`TESTING_STRATEGY.md`.

1. **Evidence contract + auto-link candidates** (G3, G4) — smallest change,
   immediately improves proposal review; no schema migration.
2. **Hybrid retrieval** (G2) — pgvector + tsvector arms behind the existing
   hard filter, RRF fusion, max-pool, intent routing. A **retrieval eval
   harness** (small labeled corpus, P@k/R@k, gbrain-style hard gates run in CI)
   is introduced in this phase and gates every later ranking change.
3. **Weighted claim model + clustering promotion** (G1) — schema migration
   (`weight`, `claim_kind`, `valid_from`/`valid_until`, consolidation
   provenance) and the corroboration-based upgrade pipeline in consolidation.
4. **Salience/recency ranking axes** (G5) — builds on G1 weights and the G2
   eval harness.
5. **Synthesis contract + gap-driven capture** (G6) — builds on G1 (confidence
   labeling needs weights) and G3 (citations need evidence).
6. **Scheduled consolidation cycle** (G7) + layer-routing checks (G8) — wraps
   the above into a budgeted background loop.

## 5. Relationship to Server Ownership

- All phases are server product capability under the memory/context ownership
  boundaries. They are not migration debt, and no `TODO(ts-migration)` markers
  are needed.
- Distinct from roadmap absorption **P3** (conversation context engine: token
  budgeting/compaction for chat history). P3 manages the *conversation window*;
  this plan manages *long-term memory quality*. They meet only at the chat
  path, where G6 answers are assembled inside P3's budget.
- Embedding/synthesis providers run as auxiliary tasks under per-task provider
  chains once those exist; until then, the single configured provider with
  graceful degradation (skip enrichment, never fail capture).

## 6. Standing risks

- **Schema migrations** (Phase 3) follow `DATABASE_AND_TRANSACTIONS.md` rules;
  bitemporal fields must not break existing `superseded` status semantics —
  supersession becomes time-bounded validity, with a backfill decision recorded
  in the migration.
- **New retrieval arms bypassing hard filters** — the existing invariant
  (fallbacks cannot re-admit forbidden memory) extends to vector/BM25/salience
  arms and is enforced in the invariant test layer.
- **Auto-link governance drift** (G4) — if system-derived edges are allowed for
  any edge class, that decision must be explicit in `policy`, audited, and
  reversible; default remains proposal-gated.
- **Cost creep in the cycle** (G7) — the budget meter is a precondition for
  enabling any LLM-backed phase, not an afterthought.
- **Ranking changes without evals** — after Phase 2, no salience/decay/boost
  change ships without the eval harness passing its hard gates.
