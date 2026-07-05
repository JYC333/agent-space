# Runs And Outputs

Date: 2026-05-14

Runs are the durable execution record for agent work. A run must be auditable: request metadata, selected runtime, status, output, errors, activities, artifacts, and proposals must be inspectable after execution.

## Trace Read Model

`GET /api/v1/runs/{id}/trace` is the replay-oriented read model for failed and
succeeded runs. It returns one space-scoped aggregate containing:

- `Run`
- safe `Agent` summary
- immutable `AgentVersion` snapshot with system-prompt presence/hash metadata, not raw prompt text
- `RuntimeAdapter` summary
- `ModelProvider` summary without secrets
- `ContextSnapshot` metadata, hashes, retrieval trace, source refs, and redaction metadata without raw rendered context text
- ordered `RunStep`
- ordered `RunEvent`
- linked artifact summaries without artifact content
- linked proposal summaries without raw proposal payload/content
- parent run summary
- child run summaries

The trace endpoint is for reconstruction and debugging. Artifact content,
export, and any raw context/prompt inspection remain separate gated reads.
Cross-space trace reads return not found and must not reveal whether the run
exists.

`GET /api/v1/agent-groups/{group_id}/trace` is the grouped-run companion read
model. It returns the group, members, room messages, delegations, root run id,
child run ids, linked artifact/proposal ids, and `run.spawn_child`
policy-decision ids. It is manager-scoped and must not inline artifact content,
raw rendered context, or secret material. A newly created room may have no root
run yet; the root id is populated by the first user chat message.

## RunStep vs RunEvent — grain rule

`RunStep` and `RunEvent` are intentionally kept as two tables with a strict
division of responsibility. They must not duplicate the same payload:

- **`RunEvent` is the append-only audit source of truth.** It carries the
  detailed phase payload — `summary`, `metadata_json`, exposure/trust levels,
  error codes — and is written through the server runs repository. Rows are never
  updated or deleted. Event writes are best-effort and must not block terminal
  run status writes.
- **`RunStep` is the coarse lifecycle/status projection.** A step carries only
  `step_type`, `status`, `title`, structured FKs (artifact_id,
  proposal_id, …), timing, and `error_type`/`error_message`.
  RunStep writers must **not** receive `metadata_json` or `*_summary`
  detail that already lives on a `RunEvent`. Step writes are best-effort
  lifecycle summaries.

Rule of thumb: rich, queryable phase detail goes on `RunEvent`; a `RunStep` is a
human-/UI-facing lifecycle marker. New orchestration code must not write the same
detail to both.

## Durable Outputs

- A run may produce an `Artifact`.
- A run produces a `Proposal` only for durable mutation requests.
- `output_text` alone is display output and does not create an Artifact or
  Proposal.
- Durable mutations are review-gated; run execution does not auto-apply proposals.
- Future Knowledge generation from run output must follow Run/Artifact -> `knowledge_*`
  proposal -> human acceptance -> active KnowledgeItem. Run output must not
  directly create active Knowledge or Memory.
- Knowledge source monitoring is a future evaluator. Current Knowledge proposal
  apply relies on explicit proposal approval and the `proposal.apply` policy
  gate, not on source-monitoring classification.

## Materialization

Run output materialization supports:

- `output_json.artifacts` for content-backed artifacts.
- `output_json.activities` for run-event activity records.
- `output_json.proposed_changes` for proposal creation.
- `output_json.delegations` for structured agent-group child-run requests.
- `produced_artifact_paths` from the runtime result for file-backed artifacts.

Materialization records errors in `run.output_json.materialization_errors` when structured output cannot be safely converted into durable records. Safe records are still created when possible. If the adapter succeeds but artifact/proposal/finalization materialization partially fails, the run is marked `degraded`.

Artifact INSERTs run the `artifact.persist` policy gate first. Proposal INSERTs
run the `proposal.create` policy gate first.

Delegation materialization is available only for grouped runs. Each
`output_json.delegations[]` entry must be structured (`target_agent_id`,
`instruction`, optional trace-safe `budget` and `context`). The server does not
parse free text to authorize delegation. Materialization calls
`AgentGroupRunService.spawnChildRun`, which performs membership, parent-agent,
authority-envelope, and `run.spawn_child` policy checks before queueing any
child run.

Managed API runs inside an AgentRunGroup expose authorized room tools:
`agent.delegate` and `agent.wait_for_results`. They are available to every
active room agent, not only the manager. Natural-language requests such as
"ask two reviewers" should be handled by the current recipient agent calling
`agent.delegate` for selected room members rather than by the model simulating
their answers. If the current agent needs sibling or delegated results before it
can answer, it calls `agent.wait_for_results`; the run moves to
`waiting_for_dependency`, releases the worker, and is requeued as the same run
after all declared dependency runs are terminal.

Product UI room messages create one manager/root run on the first message, not
at room creation. The room `goal` is optional, can be edited after creation, and
is used as run instruction/background only when present; it is not inserted as a
synthetic chat message. Structured `@agent` mention tokens from the Tiptap room
composer are resolved by the product UI into a visible routing preview and
trace-safe `recipient_segments`: one mention routes that segment directly to
that agent, adjacent mentions fan out the same segment to multiple agents in
parallel, and separated mention groups create separate recipient prompts. The
message content remains the displayed chat text, while each run prompt uses the
segment content with mention tokens removed. The user can explicitly choose
Agent coordination, which routes the full message to the manager instead of
direct fan-out so the manager can decompose/delegate through room tools. Plain
text resembling an `@agent` mention is not trusted for routing. When no
structured mention is present, the message goes to the manager by default.
Direct segmented routing does not contain server-side hard-coded summary
semantics; a manager or other recipient that needs the other segment results
must use `agent.wait_for_results(scope=current_turn)`. Multi-recipient direct
turns include the original user message, recipient segment plan, and current
recipient marker in each recipient run's model context so the agent can decide
whether to wait on sibling runs instead of seeing only its own segment. Internal
agent IDs and run IDs are tool/audit identifiers and should not be included in
user-facing room replies unless the user explicitly asks for debug/audit
identifiers. Each
`agent.delegate` tool call routes through the same
`AgentGroupRunService.spawnChildRun` path and produces normal `run_delegations`
and delegated child `runs`.

Delegated child-run lifecycle is projected back into the group audit surface by
`AgentGroupRunLifecycleProjector`. When the child run starts, the linked
`run_delegations` row moves to `running` and `delegation_started` events are
written on the child run and root run trace spine. When the child reaches a
terminal state, the delegation row moves to `succeeded`, `failed`, or
`cancelled` (`degraded` child runs map to failed delegations), stores a bounded
`result_summary`, appends a `delegation_result` group message, and writes
`delegation_completed` events on the child/root trace spine. Child artifacts and
proposals remain normal run outputs: group trace exposes their IDs for
drill-down and never auto-applies proposals.
The projector does not infer automatic follow-up summaries. Instead, it watches
for runs in `waiting_for_dependency`; when a completed run satisfies one of
their declared dependencies and all declared dependencies are terminal, it
requeues the same waiting run with the dependency result summaries in its
continuation prompt. Non-delegated grouped agent runs project their
`output_text`/summary back into the room as `agent_message` rows linked to the
original user conversation. Product chat surfaces should keep delegation
internals folded by user turn by default and show the recipient/delegating
agent's final `agent_message` as the main reply for that turn.

Claim/ObjectRelation proposal materialization is packet-only: `claim_*` and
`object_relation_*` entries must carry a structured
`payload_json` or `payload` object with a matching `operation`. The materializer
does not infer claims or relations from free text, gap-analysis strings, or flat
proposal-envelope fields.

## Boundaries

- Runtime/provider execution is outside the core product boundary and should be represented through adapter results.
- Managed artifacts and proposals are durable product records.
- Native capability execution is planned, not active. System bookkeeping runs may
  carry `capability_id` / `capabilities_json` provenance, but they do not execute
  `adapter_type="capability"`; that adapter spec remains disabled until a native
  executor exists.
- External workspace capabilities default **disabled**; enable state persists in `$AGENT_SPACE_HOME/config/settings.yaml` (`capabilities.enabled_external_capabilities`) and survives registry reload.
- Disabled external capabilities fail at adapter resolution with `capability_disabled` before execution.

## Run model config (resolved_model)

Each Run may snapshot its selected Agent runtime profile plus model provider
and model name at creation. `RunOut.resolved_model` exposes a safe summary:

- `provider_id`, `provider_name`, `provider_type`, `model`, `source` (`runtime_profile` | `request` | `agent_default` | `runtime_default` | `space_default` | `none`)
- `used_by_adapter` — whether the selected runtime adapter consumes model config
- `adapter_model_support` — `uses_model` | `not_applicable` | `unsupported` | `unknown`
- `disclosure_note` — user-facing text when a model was recorded but not used (e.g. capability adapters)

`runs.runtime_profile_id` records which `AgentRuntimeProfile` was selected.
`runs.runtime_profile_snapshot_json` stores the selected profile's adapter,
provider/model, credential profile, runtime config, and runtime policy at run
creation. Execution uses that snapshot before falling back to the immutable
`AgentVersion`, so later runtime profile edits affect only future runs.

Adapters that consume model config today depend on runtime requirements.
`claude_code` and `codex_cli` may receive model hints only when the underlying
CLI supports them. `capability` records model config but does not call an LLM.
Claude execution must go through the `claude_code`
RuntimeAdapterSpec and `GenericCliRuntimeAdapter`.

## ModelProvider secrets

Provider API keys are write-only on the API. Storage uses `Credential.secret_ref` with scheme `model_provider_api_key:v1:` (encrypted payload + nonce). Runtime credential resolution decrypts via `Credential.secret_ref` through the canonical `runtimes.credentials` boundary. `ModelProvider.credential_id` is the single source of truth for provider API keys.
