import { afterAll, beforeAll, beforeEach, describe, expect, inject, it } from "vitest";
import { randomUUID } from "node:crypto";
import { Pool } from "pg";
import { getTestPostgres, type TestPostgresDatabase } from "./support/sharedPostgres";
import { migrate } from "../src/db/migrator";
import { loadConfig } from "../src/config";
import { PgPlanRepository } from "../src/modules/plans/repository";
import { PgProposalApplyService } from "../src/modules/proposals/applyService";
import { PgRunRepository } from "../src/modules/runs/repository";
import { PgTaskRepository } from "../src/modules/tasks/repository";
import { PgAutomationRepository } from "../src/modules/automations/repository";
import { WorkflowExecutionService } from "../src/modules/automations/workflowExecutionService";
import type { SpaceUserIdentity } from "../src/modules/routeUtils/common";

const MIGRATIONS_DIR = `${process.cwd()}/migrations`;
const SPACE = "11111111-1111-4111-8111-111111111111";
const USER = "22222222-2222-4222-8222-222222222222";
const AGENT = "33333333-3333-4333-8333-333333333333";
const AGENT_VERSION = "44444444-4444-4444-8444-444444444444";
const TASK = "77777777-7777-4777-8777-777777777777";
const AUTOMATION = "88888888-8888-4888-8888-888888888888";
const WORKFLOW_ASSET = "99999999-9999-4999-8999-999999999999";
const FIXED_WORKFLOW_VERSION = "workflow-version-fixed-1";
const BINDING_WORKFLOW_VERSION = "workflow-version-bindings";

let container: TestPostgresDatabase | undefined;
let pool: Pool | undefined;
let available = false;
const identity: SpaceUserIdentity = { spaceId: SPACE, userId: USER };
const sharedPostgres = inject("sharedPostgres");
const describeWithPostgres = describe.skipIf(
  !sharedPostgres.available || !sharedPostgres.adminUri || !sharedPostgres.templateDatabase || !sharedPostgres.runId,
);

beforeAll(async () => {
  try {
    container = await getTestPostgres(__filename);
    pool = new Pool({ connectionString: container.getConnectionUri(), max: 4 });
    await migrate(pool, MIGRATIONS_DIR);
    available = true;
  } catch (error) {
    console.warn(`[plan-graph-execution-db] skipped — shared PostgreSQL unavailable: ${error instanceof Error ? error.message : String(error)}`);
  }
}, 180_000);

afterAll(async () => {
  await pool?.end();
  await container?.stop();
});

beforeEach(async () => {
  if (!available || !pool) return;
  await pool.query("TRUNCATE spaces, users CASCADE");
  const now = new Date().toISOString();
  await pool.query(
    `INSERT INTO users (id, display_name, status, created_at, updated_at)
     VALUES ($1, 'Plan Test User', 'active', $2, $2)`,
    [USER, now],
  );
  await pool.query(
    `INSERT INTO spaces (id, name, type, created_by_user_id, created_at, updated_at)
     VALUES ($1, 'Plan Test Space', 'team', $2, $3, $3)`,
    [SPACE, USER, now],
  );
  await pool.query(
    `INSERT INTO space_memberships (id, space_id, user_id, role, status, created_at, updated_at)
     VALUES ($1, $2, $3, 'owner', 'active', $4, $4)`,
    ["66666666-6666-4666-8666-666666666666", SPACE, USER, now],
  );
  await pool.query(
    `INSERT INTO evolvable_assets (
       id, space_id, asset_type, asset_key, display_name, owner_scope_type,
       owner_scope_id, status, metadata_json, created_at, updated_at
     ) VALUES ($1, $2, 'workflow_template', 'plan-graph-test', 'Plan graph test',
               'space', $2, 'active', '{}'::jsonb, $3, $3)`,
    [WORKFLOW_ASSET, SPACE, now],
  );
  await pool.query(
    `INSERT INTO evolvable_asset_versions (
       id, asset_id, space_id, scope_type, scope_id, version, status, source,
       content_json, created_at, updated_at
     ) VALUES
       ($1, $3, $4, 'space', $4, 1, 'approved', 'user_authored', '{}'::jsonb, $5, $5),
       ($2, $3, $4, 'space', $4, 2, 'approved', 'user_authored', '{}'::jsonb, $5, $5)`,
    [FIXED_WORKFLOW_VERSION, BINDING_WORKFLOW_VERSION, WORKFLOW_ASSET, SPACE, now],
  );
  await pool.query(
    `INSERT INTO agents (id, space_id, owner_user_id, name, status, current_version_id,
                         created_at, updated_at, visibility)
     VALUES ($1, $2, $3, 'Plan Test Agent', 'active', NULL, $4, $4, 'space_shared')`,
    [AGENT, SPACE, USER, now],
  );
  await pool.query(
    `INSERT INTO agent_versions (
       id, agent_id, space_id, version_label, system_prompt,
       model_config_json, runtime_config_json, context_policy_json,
       memory_policy_json, capabilities_json, tool_permissions_json,
       runtime_policy_json, created_at
     ) VALUES ($1, $2, $3, 'v1', 'You are a test agent.',
               '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, '{}'::jsonb,
               '[]'::jsonb, '{"allowed_tools":["task.plan.propose"]}'::jsonb,
               '{}'::jsonb, $4)`,
    [AGENT_VERSION, AGENT, SPACE, now],
  );
  await pool.query(
    `INSERT INTO agent_runtime_profiles (
       id, space_id, agent_id, name, adapter_type, runtime_config_json,
       runtime_policy_json, enabled, is_default, created_at, updated_at
     ) VALUES ($1, $2, $3, 'Default', 'model_api', '{"adapter_type":"model_api"}'::jsonb,
       '{}'::jsonb, true, true, $4, $4)`,
    [randomUUID(), SPACE, AGENT, now],
  );
  await pool.query(`UPDATE agents SET current_version_id = $2 WHERE id = $1 AND space_id = $3`, [AGENT, AGENT_VERSION, SPACE]);
});

function agentPlanDefinition() {
  return {
    schema_version: "workflow_definition.v1",
    workflow_id: "agent-plan-db-test",
    name: "Agent generated plan",
    description: "A plan produced from a planning Run.",
    input_schema_json: {},
    output_artifact_types: [],
    metadata_json: {
      primary_objective: "Complete the source task.",
      scope_json: { inputs: ["source task contract"] },
    },
    nodes: [{
      id: "work",
      title: "Complete the task",
      depends_on: [],
      capability_id: "task-work",
      verification_recipe_refs: ["output-check"],
      contract_json: { risk_level: "high", max_attempts: 2 },
      metadata_json: { runtime_delegation_allowed: false },
    }],
  };
}

describeWithPostgres("Task to Agent Plan real PostgreSQL lifecycle", () => {
  it("does not create a Plan for a source Task until an Agent planning Run proposes it", async () => {
    if (!available || !pool || !container) return;
    const now = new Date().toISOString();
    await pool.query(
      `INSERT INTO tasks (
         id, space_id, task_role, title, description, task_type, status, priority,
         risk_level, owner_user_id, visibility, access_level, created_by_user_id,
         created_at, updated_at
       ) VALUES ($1, $2, 'source', 'Source task', 'Task requiring a plan.', 'general',
                 'inbox', 'normal', 'medium', $3, 'space_shared', 'full', $3, $4, $4)`,
      [TASK, SPACE, USER, now],
    );

    expect((await pool.query(`SELECT count(*)::int AS count FROM plans WHERE space_id = $1`, [SPACE])).rows[0]?.count).toBe(0);

    const taskRepository = new PgTaskRepository(pool);
    const planningRun = await taskRepository.requestPlanningRun(identity, TASK, {
      agent_id: AGENT,
      prompt: "Plan this source task.",
    }) as { id: string; run_type: string };
    expect(planningRun.run_type).toBe("planning");
    expect((await pool.query(
      `SELECT role FROM task_runs WHERE space_id = $1 AND task_id = $2 AND run_id = $3`,
      [SPACE, TASK, planningRun.id],
    )).rows[0]?.role).toBe("planning");

    const plans = new PgPlanRepository(pool);
    const first = await plans.createPlanFromAgent(identity, {
      sourceTaskId: TASK,
      planningRunId: planningRun.id,
      planningToolCallId: "tool-call-1",
      agentId: AGENT,
      definitionJson: agentPlanDefinition(),
      budgetCap: 100,
    });
    expect(first).toMatchObject({ source_task_id: TASK, created_by_agent_id: AGENT, status: "pending_review" });
    const firstVersion = first.current_version as { id: string; status: string; approval_proposal_id: string | null; nodes: unknown[] };
    expect(firstVersion.status).toBe("pending_review");
    expect(firstVersion.approval_proposal_id).toBeTruthy();
    expect(firstVersion.nodes).toHaveLength(1);

    const replay = await plans.createPlanFromAgent(identity, {
      sourceTaskId: TASK,
      planId: String(first.id),
      planningRunId: planningRun.id,
      planningToolCallId: "tool-call-1",
      agentId: AGENT,
      definitionJson: agentPlanDefinition(),
      budgetCap: 100,
    });
    expect(replay.id).toBe(first.id);
    expect((await pool.query(`SELECT count(*)::int AS count FROM plan_versions WHERE plan_id = $1`, [first.id])).rows[0]?.count).toBe(1);

    const apply = PgProposalApplyService.fromConfig(loadConfig({
      SERVER_DATABASE_URL: container.getConnectionUri(),
      SERVER_INTERNAL_TOKEN: "test-internal-token",
    }));
    const reviewed = await apply.accept(firstVersion.approval_proposal_id!, identity);
    expect(reviewed?.proposal.status).toBe("accepted");

    const executed = await plans.executePlan(identity, String(first.id), { agentId: AGENT });
    expect(executed.scheduled_node_ids).toHaveLength(1);
    const nodeRun = (await pool.query<{ node_id: string; run_id: string }>(
      `SELECT pnr.plan_node_id AS node_id, pnr.run_id
         FROM plan_node_runs pnr JOIN plan_nodes n ON n.id = pnr.plan_node_id
        WHERE pnr.space_id = $1 AND n.plan_version_id = $2`,
      [SPACE, firstVersion.id],
    )).rows[0];
    expect(nodeRun).toBeTruthy();
    expect((await pool.query(`SELECT count(*)::int AS count FROM tasks WHERE space_id = $1 AND id <> $2`, [SPACE, TASK])).rows[0]?.count).toBe(0);

    const runs = new PgRunRepository(pool);
    const planArtifactId = randomUUID();
    await pool.query(
      `INSERT INTO artifacts (
         id, space_id, run_id, artifact_type, title, export_formats_json,
         created_at, updated_at
       ) VALUES ($1, $2, $3, 'result', 'Plan result', '[]'::jsonb, $4, $4)`,
      [planArtifactId, SPACE, nodeRun!.run_id, now],
    );
    await runs.markRunRunning({ run_id: nodeRun!.run_id, space_id: SPACE, started_at: new Date().toISOString() });
    await runs.markRunTerminal({
      run_id: nodeRun!.run_id,
      space_id: SPACE,
      status: "succeeded",
      output_json: {
        result: "done",
        materialization: [{ kind: "artifact", status: "succeeded", artifact_id: planArtifactId }],
      },
      completed_at: new Date().toISOString(),
    });
    await runs.insertRunEvaluation({
      space_id: SPACE,
      run_id: nodeRun!.run_id,
      outcome_status: "passed",
      trajectory_status: "acceptable",
      evaluated_at: new Date().toISOString(),
    });
    const reconciled = await plans.reconcilePlan(identity, String(first.id));
    expect(reconciled.status).toBe("completed");
    expect((await pool.query<{ status: string }>(`SELECT status FROM plan_nodes WHERE id = $1`, [nodeRun!.node_id])).rows[0]?.status).toBe("done");
  });

  it("executes a fixed Workflow through Workflow Execution without creating a Plan", async () => {
    if (!available || !pool || !container) return;
    const now = new Date().toISOString();
    await pool.query(
      `INSERT INTO automations (
         id, space_id, owner_user_id, agent_id, name, trigger_type, status,
         config_json, created_at, updated_at
       ) VALUES ($1, $2, $3, $4, 'Fixed workflow automation', 'manual', 'active', $5::jsonb, $6, $6)`,
      [AUTOMATION, SPACE, USER, AGENT, JSON.stringify({ target_type: "workflow" }), now],
    );
    const service = new WorkflowExecutionService();
    const execution = await service.start({
      db: pool,
      identity,
      automation: {
        id: AUTOMATION,
        space_id: SPACE,
        owner_user_id: USER,
        agent_id: AGENT,
        workspace_id: null,
        project_id: null,
        name: "Fixed workflow automation",
        description: null,
        trigger_type: "manual",
        status: "active",
        preflight_snapshot_json: null,
        config_json: { target_type: "workflow" },
        next_run_at: null,
        last_fired_at: null,
        created_at: now,
        updated_at: now,
      },
      target: {
        versionId: FIXED_WORKFLOW_VERSION,
        resolutionTrace: [`pin:${FIXED_WORKFLOW_VERSION}`],
        contentJson: {
          schema_version: "workflow_definition.v1",
          workflow_id: "fixed-workflow-db-test",
          name: "Fixed workflow",
          description: "A workflow execution independent of Plans.",
          input_schema_json: {},
          output_artifact_types: [],
          metadata_json: {},
          nodes: [
            { id: "work", title: "Run workflow work", depends_on: [], capability_id: "workflow-work", contract_json: {}, metadata_json: {} },
            {
              id: "consume",
              title: "Consume workflow output",
              depends_on: ["work"],
              capability_id: "workflow-consume",
              input_bindings: [
                { name: "summary", from_node: "work", source: "output_text" },
                { name: "answer", from_node: "work", source: "output_json", json_pointer: "/result/answer" },
                { name: "report", from_node: "work", source: "artifact", artifact_type: "report" },
              ],
              contract_json: {},
              metadata_json: {},
            },
            { id: "checkpoint", title: "Approve workflow result", depends_on: ["consume"], approval_checkpoint: { required: true, proposal_type: "workflow_execution_checkpoint" }, contract_json: {}, metadata_json: {} },
          ],
        },
      },
      triggerType: "manual",
      inputJson: {},
      preflightSnapshot: { executable: true },
      budgetSources: [],
    });
    expect((await pool.query(`SELECT count(*)::int AS count FROM plans WHERE space_id = $1`, [SPACE])).rows[0]?.count).toBe(0);
    expect((await pool.query<{
      run_role: string;
      runtime_profile_id: string | null;
      adapter_type: string | null;
      attempt_count: number;
    }>(
      `SELECT root.run_role, root.runtime_profile_id, root.adapter_type,
              count(attempt.id)::int AS attempt_count
         FROM runs root
         LEFT JOIN run_attempts attempt ON attempt.run_id = root.id AND attempt.space_id = root.space_id
        WHERE root.space_id = $1 AND root.id = $2
        GROUP BY root.id`,
      [SPACE, execution.rootRunId],
    )).rows[0]).toEqual({
      run_role: "coordinator",
      runtime_profile_id: null,
      adapter_type: null,
      attempt_count: 0,
    });
    await new PgAutomationRepository(pool).createAutomationRun({
      automationId: AUTOMATION,
      runId: execution.rootRunId,
      workflowExecutionId: execution.workflowExecutionId,
      triggeredByUserId: USER,
      triggerType: "manual",
      preflightSnapshot: { executable: true },
    });

    const work = (await pool.query<{ node_id: string; run_id: string }>(
      `SELECT wr.node_id, wr.run_id FROM workflow_execution_node_runs wr
        JOIN workflow_execution_nodes n ON n.id = wr.node_id
       WHERE wr.space_id = $1 AND n.execution_id = $2 AND n.node_key = 'work'`,
      [SPACE, execution.workflowExecutionId],
    )).rows[0];
    expect(work).toBeTruthy();
    const runs = new PgRunRepository(pool);
    const artifactId = randomUUID();
    await pool.query(
      `INSERT INTO artifacts (
         id, space_id, run_id, artifact_type, title, export_formats_json,
         created_at, updated_at
       ) VALUES ($1, $2, $3, 'report', 'Workflow report', '[]'::jsonb, $4, $4)`,
      [artifactId, SPACE, work!.run_id, now],
    );
    await runs.markRunRunning({ run_id: work!.run_id, space_id: SPACE, started_at: new Date().toISOString() });
    await runs.markRunTerminal({
      run_id: work!.run_id,
      space_id: SPACE,
      status: "succeeded",
      output_text: "workflow done",
      output_json: { result: { answer: 42 } },
      completed_at: new Date().toISOString(),
    });
    await runs.insertRunEvaluation({ space_id: SPACE, run_id: work!.run_id, outcome_status: "passed", trajectory_status: "acceptable", evaluated_at: new Date().toISOString() });
    await Promise.all([
      service.reconcileForRun(pool, SPACE, work!.run_id, USER),
      service.reconcileForRun(pool, SPACE, work!.run_id, USER),
    ]);

    const consume = (await pool.query<{
      run_id: string;
      resolved_inputs_json: { values: Record<string, unknown>; contextArtifactIds: string[] };
      contract_snapshot_json: { upstream_inputs_json: { values: Record<string, unknown> } };
      request_json: { context_artifact_ids: string[] };
    }>(
      `SELECT wr.run_id, wr.resolved_inputs_json, r.contract_snapshot_json, snapshot.request_json
         FROM workflow_execution_node_runs wr
         JOIN workflow_execution_nodes n ON n.id = wr.node_id AND n.space_id = wr.space_id
         JOIN runs r ON r.id = wr.run_id AND r.space_id = wr.space_id
         JOIN context_snapshots snapshot ON snapshot.id = r.context_snapshot_id AND snapshot.space_id = r.space_id
        WHERE wr.space_id = $1 AND n.execution_id = $2 AND n.node_key = 'consume'`,
      [SPACE, execution.workflowExecutionId],
    )).rows[0];
    expect(consume).toBeTruthy();
    expect((await pool.query<{ count: number }>(
      `SELECT count(*)::int AS count
         FROM workflow_execution_node_runs wr
         JOIN workflow_execution_nodes n ON n.id = wr.node_id AND n.space_id = wr.space_id
        WHERE wr.space_id = $1 AND n.execution_id = $2 AND n.node_key = 'consume'`,
      [SPACE, execution.workflowExecutionId],
    )).rows[0]?.count).toBe(1);
    expect(consume!.resolved_inputs_json.values).toEqual({
      summary: "workflow done",
      answer: 42,
      report: { artifact_id: artifactId, artifact_type: "report" },
    });
    expect(consume!.contract_snapshot_json.upstream_inputs_json.values).toEqual(consume!.resolved_inputs_json.values);
    expect(consume!.request_json.context_artifact_ids).toContain(artifactId);

    await runs.markRunRunning({ run_id: consume!.run_id, space_id: SPACE, started_at: new Date().toISOString() });
    await runs.markRunTerminal({ run_id: consume!.run_id, space_id: SPACE, status: "succeeded", output_json: { result: "consumed" }, completed_at: new Date().toISOString() });
    await runs.insertRunEvaluation({ space_id: SPACE, run_id: consume!.run_id, outcome_status: "passed", trajectory_status: "acceptable", evaluated_at: new Date().toISOString() });
    await service.reconcileForRun(pool, SPACE, consume!.run_id, USER);

    const checkpoint = (await pool.query<{ proposal_id: string }>(
      `SELECT approval_proposal_id AS proposal_id FROM workflow_execution_nodes WHERE space_id = $1 AND execution_id = $2 AND node_key = 'checkpoint'`,
      [SPACE, execution.workflowExecutionId],
    )).rows[0];
    expect(checkpoint?.proposal_id).toBeTruthy();
    const apply = PgProposalApplyService.fromConfig(loadConfig({ SERVER_DATABASE_URL: container.getConnectionUri(), SERVER_INTERNAL_TOKEN: "test-internal-token" }));
    const accepted = await apply.accept(checkpoint!.proposal_id, identity);
    expect(accepted?.proposal.status).toBe("accepted");
    const finalState = (await pool.query<{ execution_status: string; root_status: string; linked_execution_id: string }>(
      `SELECT e.status AS execution_status, root.status AS root_status, ar.workflow_execution_id AS linked_execution_id
         FROM workflow_executions e JOIN runs root ON root.id = e.root_run_id
         JOIN automation_runs ar ON ar.workflow_execution_id = e.id
        WHERE e.space_id = $1 AND e.id = $2`,
      [SPACE, execution.workflowExecutionId],
    )).rows[0];
    expect(finalState).toEqual({ execution_status: "completed", root_status: "succeeded", linked_execution_id: execution.workflowExecutionId });
  });

  it("fails closed for a missing required binding while an optional sibling continues", async () => {
    if (!available || !pool) return;
    const now = new Date().toISOString();
    await pool.query(
      `INSERT INTO automations (
         id, space_id, owner_user_id, agent_id, name, trigger_type, status,
         config_json, created_at, updated_at
       ) VALUES ($1, $2, $3, $4, 'Binding workflow', 'manual', 'active',
                 '{"target_type":"workflow"}'::jsonb, $5, $5)`,
      [AUTOMATION, SPACE, USER, AGENT, now],
    );
    const automation = {
      id: AUTOMATION, space_id: SPACE, owner_user_id: USER, agent_id: AGENT,
      workspace_id: null, project_id: null, name: "Binding workflow", description: null,
      trigger_type: "manual", status: "active", preflight_snapshot_json: null,
      config_json: { target_type: "workflow" }, next_run_at: null, last_fired_at: null,
      created_at: now, updated_at: now,
    };
    const service = new WorkflowExecutionService();
    const execution = await service.start({
      db: pool,
      identity,
      automation,
      target: {
        versionId: BINDING_WORKFLOW_VERSION,
        resolutionTrace: [],
        contentJson: {
          schema_version: "workflow_definition.v1",
          workflow_id: "binding-failure-workflow",
          name: "Binding failure workflow",
          description: "Checks required and optional inputs.",
          input_schema_json: {}, output_artifact_types: [], metadata_json: {},
          nodes: [
            { id: "source", title: "Source", depends_on: [], capability_id: "source", contract_json: {}, metadata_json: {} },
            { id: "required", title: "Required", depends_on: ["source"], capability_id: "required", input_bindings: [{ name: "missing", from_node: "source", source: "output_text" }], contract_json: {}, metadata_json: {} },
            { id: "optional", title: "Optional", depends_on: ["source"], capability_id: "optional", input_bindings: [{ name: "missing", from_node: "source", source: "output_text", required: false }], contract_json: {}, metadata_json: {} },
          ],
        },
      },
      triggerType: "manual", inputJson: {}, preflightSnapshot: { executable: true }, budgetSources: [],
    });
    const sourceRun = (await pool.query<{ run_id: string }>(
      `SELECT link.run_id FROM workflow_execution_node_runs link
       JOIN workflow_execution_nodes node ON node.id = link.node_id AND node.space_id = link.space_id
       WHERE node.execution_id = $1 AND node.node_key = 'source'`,
      [execution.workflowExecutionId],
    )).rows[0]!.run_id;
    const runs = new PgRunRepository(pool);
    await runs.markRunRunning({ run_id: sourceRun, space_id: SPACE, started_at: now });
    await runs.markRunTerminal({ run_id: sourceRun, space_id: SPACE, status: "succeeded", output_json: {}, completed_at: now });
    await runs.insertRunEvaluation({ space_id: SPACE, run_id: sourceRun, outcome_status: "passed", trajectory_status: "acceptable", evaluated_at: now });
    await service.reconcileForRun(pool, SPACE, sourceRun, USER);

    const states = (await pool.query<{
      node_key: string; status: string; blocked_reason: string | null;
      run_count: number; resolved_inputs_json: { values: Record<string, unknown>; bindings: Array<{ missing_reason: string | null }> } | null;
    }>(
      `SELECT node.node_key, node.status, node.blocked_reason,
              count(link.id)::int AS run_count,
              max(link.resolved_inputs_json::text)::jsonb AS resolved_inputs_json
         FROM workflow_execution_nodes node
         LEFT JOIN workflow_execution_node_runs link ON link.node_id = node.id AND link.space_id = node.space_id
        WHERE node.execution_id = $1 AND node.node_key IN ('required', 'optional')
        GROUP BY node.id ORDER BY node.node_key`,
      [execution.workflowExecutionId],
    )).rows;
    expect(states[0]).toMatchObject({ node_key: "optional", status: "in_progress", run_count: 1 });
    expect(states[0]!.resolved_inputs_json?.values).toEqual({ missing: null });
    expect(states[0]!.resolved_inputs_json?.bindings[0]?.missing_reason).toBe("output_text_missing");
    expect(states[1]).toMatchObject({ node_key: "required", status: "failed", run_count: 0 });
    expect(states[1]!.blocked_reason).toBe("input_binding_unresolved:missing:output_text_missing");
  });
});
