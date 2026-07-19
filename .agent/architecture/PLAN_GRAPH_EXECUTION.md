# Task-first Agent Planning and Workflow Execution

## Boundary

`Task` is a product goal. `Plan` is an Agent-generated dynamic execution path
for one source Task. A fixed Workflow Automation is a separate execution
domain and never creates a Plan.

```text
source Task → planning Run → task.plan.propose → PlanVersion → review → Plan execution
Automation → resolved Workflow Version → WorkflowExecution → node Runs
```

The server is the authority for graph validation, permissions, budgets,
approval, scheduling, evaluation, and reconciliation. The UI can request
planning and review results, but cannot create or revise a PlanVersion directly.

## Durable models

- `tasks.task_role` is `source` or `subtask`. A source Task may own one logical
  Plan through `plans.source_task_id`. Plan nodes are not Tasks.
- `plans` stores the aggregate and `plan_versions` stores immutable Agent
  revisions. `planner_mode` is always `agent`; an optional
  `reference_workflow_version_id` is context for the Agent, never the Plan's
  execution source.
- `plan_nodes`, `plan_node_dependencies`, and `plan_node_runs` store the
  bounded graph and its physical Run links. A node carries its A1 contract,
  risk, budget, assigned Agent, verification recipe, content hash, and explicit
  `input_bindings`. Bindings can read `output_text`, a JSON Pointer in
  `output_json`, or a durable Artifact from a direct dependency only.
- `workflow_executions`, `workflow_execution_nodes`,
  `workflow_execution_dependencies`, and `workflow_execution_node_runs` store
  an immutable Workflow definition snapshot, resolution trace, checkpoints,
  dependencies, and child Runs for one Automation fire.
- `automation_runs.workflow_execution_id` is the audit link for Workflow
  Automation fires. Automation does not write `plans` or `plan_review`
  proposals.

The schema is authored under `server/src/db/schema/` and the only generated
migration artifact is `server/migrations/0001_baseline.sql`.

## Agent planning lifecycle

`POST /api/v1/tasks/:taskId/plan-requests` creates only a queued `planning`
Run. It links that Run to the source Task with `task_runs.role='planning'`,
copies the Task contract and optional Workflow reference into the Run context,
and grants only the Agent planning action. It does not create a Plan.

During that Run, the Agent-only `task.plan.propose` action submits a structured
`workflow_definition.v1` through `PgPlanRepository.createPlanFromAgent`. The
service derives Agent and planning Run identity from the current Run, checks
Task/Space ownership, validates the graph and budget sources, and uses the
planning Run plus tool-call id as an idempotency key. A repeated tool call
returns the existing PlanVersion.

The first proposal creates the Plan and Version; later Agent planning Runs add
the next Version. A source Task cannot have two logical Plans. Safe low-risk
graphs may be auto-approved; all other graphs create a `plan_review` Proposal
and keep their nodes blocked. Proposal application approves the Version and
unblocks nodes in the same transaction. Human revision is a new planning Run,
not a direct `POST /plans/:id/revise` operation.

## Plan execution

The retained Plan API is read/operate only:

- `GET /api/v1/plans`
- `GET /api/v1/plans/:planId`
- `POST /api/v1/plans/:planId/execute` for an approved Version
- `POST /api/v1/plans/:planId/reconcile` for owner/admin recovery

Execution creates a parked coordinator Run and `plan_node_runs` for ready
nodes. It never inserts graph nodes into `tasks` or `task_runs`. The scheduler
waits for dependency completion, creates checkpoint Proposals when required,
and consumes the latest `RunEvaluation`: a terminal adapter success without a
passed evaluation does not complete a node. Finalization discovers the graph
from `plan_node_runs`, so route hints are evidence only, not the primary link.

Before creating a ready child Run, the scheduler resolves every declared input
from the latest dependency Run whose evaluation passed. A missing required
input fails the node with `input_binding_unresolved`; optional missing input is
recorded as null. Resolved values and provenance are snapshotted on the
node-run link and Run contract. Artifact inputs use durable context attachments,
never another Run's sandbox path. This extends `workflow_definition.v1`
without changing its version because there is no deployed compatibility boundary.

Plan reconciliation schedules newly-ready nodes, verifies integration nodes,
and completes the coordinator only after dependency and output checks pass.
Retries are represented by new Run attempts/finalizations while preserving the
same node-to-Run relation.

## Fixed Workflow Automation lifecycle

Workflow Automation resolves `pin` or `follow` to one approved Workflow
Version, snapshots the definition and resolution trace, then creates a
`WorkflowExecution`. Scheduled Workflow Automation must be pinned. Materialized
nodes and dependencies live only in the Workflow Execution tables. Workflow
checkpoint approval uses `workflow_execution_checkpoint`; it never uses
`plan_checkpoint` and never creates a Plan.

The shared execution behavior is exposed through `PlanExecutionService` and
`WorkflowExecutionService`; both use durable node-run
links and post-finalization reconciliation. The Automation fire transaction
commits the Workflow Execution, coordinator Run, child scheduling, and
`automation_runs` audit link together.

Post-finalization reconciliation is the immediate path, not the only recovery
path. `ExecutionGraphRecoveryService` scans active Plan and Workflow executions
at startup and periodically, then idempotently reconciles each graph under its
aggregate row lock. Per-graph failures are isolated and emit deduplicated
operational alerts.

AgentRunGroup owns interactive, policy-gated dynamic delegation inside an
Agent Room. Plan and Workflow Execution own persistent, reviewable DAG nodes.
Neither mechanism creates, adopts, or reschedules the other's nodes.

## UI boundary

- Task Detail is the planning entry point: **Ask Agent to plan**, planning Run
  status, current Plan, review link, history, nodes, and node Runs.
- `/plans` is an Agent Plan review/index surface. It has no New Plan, raw
  definition, LLM prompt, or direct revision form. Plan Detail provides source
  Task, review, Execute, Reconcile, version, node, and root Run links.
- `/automations` manages fixed Workflow targets and shows recent Workflow
  Executions, root Runs, node progress, and checkpoints.
- Workflow asset/version pages manage version lifecycle, evaluation, promotion,
  and Automation references; they do not create Plans.

There is no Workflow Canvas in this scope. D2.1 still selects existing
candidate Runs rather than starting a candidate Run automatically. Runtime
session checkpoint/resume remains A3.1.
