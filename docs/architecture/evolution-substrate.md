# Evolution Substrate Foundation

The evolution substrate is a product/system feature. Runtime evolution data lives
in product tables and artifacts, not in `.agent/`. The `.agent/` tree may contain
architecture notes or developer context only.

## Core Objects

`EvolutionTarget` represents a product object that can be improved over time:
prompt, capability, agent_profile, workflow, or policy. The first default target
is the `capture-memory-extraction` prompt target.

`EvolutionSignal` is queryable, typed evidence that a target may need improvement,
such as rejected memory candidates, repeated corrections, misclassified
exploration, or failed validation. A signal is not a keyword or free-form tag:
`signal_type` is an application-level evidence category, `summary` describes the
observed case, and `payload_json` can carry source-specific details.
Signal types are application constants, not database enums.

Target validation is configuration-driven. A target defines validation metrics in
`metadata_json.validation.metrics`, and each metric selects a supported evaluator
such as `count_signals` or `rate`. Users can configure target definitions and
validation metric parameters, but evaluator implementations are backend-owned:
targets cannot execute arbitrary SQL, Python, or scripts.

## Product Module And API

Evolution is a first-level frontend module at `/evolution`. It shows targets,
signals, evolution runs, evolution-created proposals, and validation results from
backend DTOs. The UI is proposal-first: it can trigger an evolution review for a
target, but it does not directly apply prompt, capability, workflow, policy, file,
or memory changes.

The backend API lives under `/api/v1/evolution` and exposes summary, target
create/update/list/detail, signals, runs, proposals, validation results, signal
creation, and a target run trigger.
Counts for overview cards are aggregated server-side. Empty backend data is
returned as empty arrays or zero counts so the frontend can render empty states
without fake production data.

## Engine Boundary

Evolution engines are adapters. The active adapter is `llm_prompt_review`, which
requires an enabled default ModelProvider in the current space.

Engines do not directly mutate Memory, prompts, capabilities, policies, files,
or code. They receive an `evolution_context` Artifact and emit `evolution_report`
and `prompt_revision` Artifacts. A separate service converts those outputs into a
pending Proposal.

`llm_prompt_review` reads target metadata, recent typed signals, constraints,
validation goals, validation results, and the current target capability prompt from
`prompts/main.md`. It asks the configured model to return strict JSON containing
an `evolution_report` payload and a complete `prompt_revision`. If no model
provider is configured, or if the model cannot produce a valid non-empty prompt
revision, the run is rejected instead of creating an empty pending proposal.

## Validation Evaluators

Supported evaluator types are intentionally small and reusable:

- `count_signals`: counts signals matching a configured `signal_type` or `signal_types`.
- `rate`: divides a configured numerator signal count by a configured denominator signal count.

Each result includes `value`, `status`, `window`, `sample_size`, optional
`numerator_count` and `denominator_count`, and the configured `goal`. New targets
should add validation configuration, not metric-specific code, unless they need a
new evaluator type or a new event/source that the system does not collect yet.

Example target validation configuration:

```yaml
validation:
  window: 14d
  metrics:
    - id: memory_candidate_reject_rate
      label: Memory candidate reject rate
      evaluator: rate
      numerator:
        source: signals
        signal_type: memory_candidate_rejected
      denominator:
        source: signals
        signal_type: memory_candidate_proposed
      goal:
        direction: decrease
        threshold: 0.2
    - id: exploration_misclassified_as_decision_count
      label: Exploration misclassified as decision
      evaluator: count_signals
      source: signals
      signal_type: exploration_misclassified_as_decision
      goal:
        direction: decrease
        threshold: 0
```

## Scoped Versions And Overlays

Approved evolution does not overwrite core capability defaults. Approval creates
scoped `CapabilityVersion` and `CapabilityOverlay` records. Runtime resolution
checks agent, user, space, instance, then core defaults. Existing users and
spaces do not upgrade merely because another scope accepted a new version.

Prompt evolution emits a full revised prompt proposal, not hand-maintained rule
operation schemas. The approved revision is stored as a scoped overlay so review
and rollback remain explicit.

## Future Adapter Migration

Future optimizer integrations should implement the same LLM/evidence-to-revision
boundary and store engine-specific outputs as Artifacts. They should reuse
`EvolutionTarget`, `EvolutionSignal`, `CapabilityVersion`, and
`CapabilityOverlay`; they should not add optimizer-specific tables until a
product need requires that schema.
