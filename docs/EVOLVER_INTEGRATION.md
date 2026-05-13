# Memory Evolver Integration

## Goal

Keep the memory store healthy over time. As agents run and memories accumulate,
older/unused/low-confidence memories should fade; frequently-accessed, high-importance
memories should be reinforced; redundant memories should be merged into cleaner facts.

This is treated as an optimization problem over a population of memories using
evolutionary algorithms — specifically the EvoMap evolver mechanism.

---

## EvoMap reference

Repository: https://github.com/EvoMap/evolver

The evolver takes a population of individuals, a fitness function, and evolutionary
operators (selection, mutation, crossover) and returns an evolved population.

Mapping to agent-space:

| EvoMap concept | agent-space equivalent |
|---|---|
| Population | All active `Memory` records in a space |
| Individual | One `Memory` record |
| Fitness function | `fitness(m)` — see below |
| Selection | Keep high-fitness; retire low-fitness |
| Mutation | Adjust `importance`, `confidence`, `status` |
| Crossover | Merge two similar memories into one |
| Synthesis | Generate a new `semantic` memory from episodic cluster |

---

## Fitness function

```
fitness(m) = importance(m) × confidence(m) × recency_decay(m) × access_factor(m)

recency_decay(m) = exp(-λ_scope × days_since_last_access)
access_factor(m) = 0.7 + 0.3 × min(log(1 + access_count) / log(101), 1.0)
```

### Decay constants per scope (λ)

| Scope | λ | Half-life |
|---|---|---|
| `system` | 0.0 | Never decays |
| `space` | 0.02 | ~35 days |
| `user` | 0.05 | ~14 days |
| `workspace` | 0.05 | ~14 days |
| `capability` | 0.03 | ~23 days |
| `agent` | 0.20 | ~3.5 days |

---

## Data collection (already implemented)

`ContextBuilder` records usage on every context build so the evolver has signal:

| Field | Where | Updated by |
|---|---|---|
| `Memory.access_count` | `memories` table | `ContextBuilder.build()` |
| `Memory.last_accessed_at` | `memories` table | `ContextBuilder.build()` |
| `Memory.fitness_score` | `memories` table | `MemoryEvolver.compute_fitness_scores()` |
| `MemoryReadTrace` row | `memory_access_logs` | `ContextBuilder.build()` |

---

## Evolutionary operators

| Operator | LLM required? | Status |
|---|---|---|
| `decay` — reduce confidence on low-fitness | No | Implemented (dry_run default) |
| `archive` — set `status=archived` below threshold | No | Implemented (dry_run default) |
| `promote` — raise importance on high-access | No | Stub |
| `merge` — consolidate semantically duplicate memories | Yes (embedding) | Planned |
| `synthesize` — episodic cluster → semantic summary | Yes (LLM) | Planned |

---

## EvoMap integration steps (TODO)

### Step 1 — Export population

```python
memories = db.query(Memory).filter(Memory.space_id == space_id, Memory.status == "active").all()
population = [
    {
        "id": m.id,
        "genes": {
            "importance": m.importance,
            "confidence": m.confidence,
            "access_count": m.access_count,
            "scope": m.scope,
            "type": m.type,
            "days_old": (now - m.created_at).days,
        }
    }
    for m in memories
]
```

### Step 2 — Run EvoMap

```python
from evolver import Evolver  # pip install evomap-evolver (TBD)

evolved = Evolver(fitness_fn=_fitness, generations=20).evolve(population)
```

### Step 3 — Apply mutations

```python
for individual in evolved:
    mid = individual["id"]
    if individual["action"] == "archive":
        store.update(mid, MemoryUpdate(status="archived"))
    elif individual["action"] == "promote":
        store.update(mid, MemoryUpdate(importance=individual["new_importance"]))
    elif individual["action"] == "merge":
        # create merged Memory, supersede originals
        ...
```

### Step 4 — Log evolution run

Write a `MemoryEvolutionRun` record (table to be added when integration begins):
```python
MemoryEvolutionRun(space_id=space_id, archived=N, promoted=M, merged=K, ...)
```

---

## When to run the evolver

The evolver runs asynchronously — never in the request hot path.

| Trigger | Notes |
|---|---|
| Scheduled (nightly) | APScheduler or cron calling `MemoryEvolver.evolve_space(space_id)` |
| Event-driven | After N new memories created in a space |
| On-demand | `POST /api/v1/memory/evolve` (admin-only endpoint, deferred) |

---

## Current state

`app/memory/evolver.py` — `MemoryEvolver` stub:

| Method | Status |
|---|---|
| `compute_fitness_scores(space_id)` | ✅ writes `fitness_score` to Memory rows |
| `decay_and_archive(space_id, dry_run=True)` | ✅ identifies candidates; applies if `dry_run=False` |
| `evolve_space(space_id)` | Stub — returns dry-run report, EvoMap call pending |

EvoMap library is not yet pinned in `requirements.txt`.
Integration begins when the library export format is confirmed against the evolver API.
