# Runs And Outputs

Date: 2026-05-14

Runs are the durable execution record for agent work. A run must be auditable: request metadata, selected runtime, status, output, errors, activities, artifacts, and proposals must be inspectable after execution.

## Durable Outputs

- A run may produce an `Artifact`.
- A run produces a `Proposal` only for durable mutation requests.
- `output_text` alone is display output and does not create a proposal.
- Durable mutations are review-gated; run execution does not auto-apply proposals.

## Materialization

Run output materialization supports:

- `output_json.artifacts` for content-backed artifacts.
- `output_json.activities` for run-event activity records.
- `output_json.proposed_changes` for proposal creation.
- `produced_artifact_paths` from the runtime result for file-backed artifacts.

Materialization records errors in `run.output_json.materialization_errors` when structured output cannot be safely converted into durable records. Safe records are still created when possible.

## Boundaries

- Runtime/provider execution is outside the core product boundary and should be represented through adapter results.
- Managed artifacts and proposals are durable product records.
- Capability execution uses the same Run and adapter result path as other runtimes: `adapter_type="capability"` resolves an enabled local capability, stores its normalized result in `Run.output_json`, and materializes returned artifacts and activities.
- External workspace capabilities default **disabled**; enable state persists in `$AGENT_SPACE_HOME/config/settings.yaml` (`capabilities.enabled_external_capabilities`) and survives registry reload.
- Disabled external capabilities fail at adapter resolution with `capability_disabled` before execution.

## Run model config (resolved_model)

Each Run may snapshot model provider + model name at creation. `RunOut.resolved_model` exposes a safe summary:

- `provider_id`, `provider_name`, `provider_type`, `model`, `source` (`request` | `agent_default` | `space_default` | `none`)
- `used_by_adapter` — whether the selected runtime adapter consumes model config
- `adapter_model_support` — `uses_model` | `not_applicable` | `unsupported` | `unknown`
- `disclosure_note` — user-facing text when a model was recorded but not used (e.g. echo/capability adapters)

Adapters that consume model config today: **`anthropic_messages` only**. `echo` and `capability` record model config but do not call an LLM.

## ModelProvider secrets

Provider API keys are write-only on the API. Storage uses `Credential.secret_ref` with scheme `model_provider_api_key:v1:` (encrypted payload + nonce). Runtime credential resolution decrypts via `Credential.secret_ref` through the canonical `runtimes.credentials` boundary. `ModelProvider.credential_id` is the single source of truth for provider API keys.

