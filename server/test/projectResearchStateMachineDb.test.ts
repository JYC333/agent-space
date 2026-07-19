import { join } from "node:path";
import { randomUUID } from "node:crypto";
import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { Pool } from "pg";
import { getTestPostgres, type TestPostgresDatabase } from "./support/sharedPostgres";
import { migrate } from "../src/db/migrator";
import { transition, type ResearchOperationState } from "../src/modules/projectResearch/stateMachine";

const MIGRATIONS_DIR = join(process.cwd(), "migrations");
const SPACE = "11111111-1111-4111-8111-111111111111";
const OWNER = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const PROJECT = "55555555-5555-4555-8555-555555555555";
const WORKFLOW = "66666666-6666-4666-8666-666666666666";
const OPERATION = "77777777-7777-4777-8777-777777777777";

let container: TestPostgresDatabase | undefined;
let pool: Pool | undefined;
let available = false;

beforeAll(async () => {
  try {
    container = await getTestPostgres(__filename);
    pool = new Pool({ connectionString: container.getConnectionUri(), max: 3 });
    await migrate(pool, MIGRATIONS_DIR);
    available = true;
  } catch (error) {
    console.warn(`[project-research-state-machine-db] skipped — Docker/Postgres unavailable: ${error instanceof Error ? error.message : String(error)}`);
  }
}, 180_000);

afterAll(async () => {
  await pool?.end();
  await container?.stop();
});

function operationState(): ResearchOperationState {
  return {
    schema_version: "project_research_operation.v1",
    run_kind: "baseline",
    workflow_id: WORKFLOW,
    research_question: "Question",
    research_question_version: 1,
    channel_ids: [],
    project_source_binding_ids: [],
    source_post_processing_rule_ids: [],
    project_source_binding_id: null,
    source_post_processing_rule_id: null,
    source_backfill_plan_id: null,
    source_backfill_plan_ids: [],
    query: { source_channel_ids: [], fingerprint: "", sort_by: "submittedDate", history_mode: null, from: null, to: null },
    history: { mode: null, from: null, to: null, max_items: null },
    watermark: { before: null, after: null, overlap_hours: 48 },
    source_item_ids: [],
    current_stage: "monitor_setup",
    stage_state: "running",
    agent_id: "agent-1",
    runtime_profile_id: "profile-1",
    checkpoint_ids: [],
    synthesis_run_id: null,
    artifact_ids: [],
    partial: false,
    monitoring_active: false,
    idempotency: { key: "key", fingerprint: "fingerprint" },
  };
}

async function seed(): Promise<void> {
  await pool!.query(`TRUNCATE project_operations, project_research_workflows, projects, space_memberships, users, spaces CASCADE`);
  const now = new Date().toISOString();
  await pool!.query(`INSERT INTO spaces (id, name, type, created_at, updated_at) VALUES ($1,'Main','personal',$2,$2)`, [SPACE, now]);
  await pool!.query(`INSERT INTO users (id, display_name, status, created_at, updated_at) VALUES ($1,'Owner','active',$2,$2)`, [OWNER, now]);
  await pool!.query(`INSERT INTO projects (id, space_id, owner_user_id, name, status, created_at, updated_at) VALUES ($1,$2,$3,'Research','active',$4,$4)`, [PROJECT, SPACE, OWNER, now]);
  await pool!.query(
    `INSERT INTO project_research_workflows (id, space_id, project_id, workflow_type, current_stage, status, mode, state_json, created_at, updated_at)
     VALUES ($1,$2,$3,'literature_review','initial_intake_setup','active','autonomous','{}'::jsonb,$4,$4)`,
    [WORKFLOW, SPACE, PROJECT, now],
  );
  await pool!.query(
    `INSERT INTO project_operations (id, space_id, project_id, kind, title, status, created_by_user_id, progress_json, created_at, updated_at)
     VALUES ($1,$2,$3,'research','Research','active',$4,$5::jsonb,$6,$6)`,
    [OPERATION, SPACE, PROJECT, OWNER, JSON.stringify(operationState()), now],
  );
}

describe("project research state machine (real Postgres)", () => {
  beforeEach(async () => {
    if (available) await seed();
  });

  it("serializes concurrent transitions and lets the loser observe the new stage", async () => {
    if (!available || !pool) return;
    const transitionSpec = {
      from: ["monitor_setup"] as const,
      to: "backfill" as const,
      mutate: ({ state }: { state: ResearchOperationState }) => {
        state.stage_state = "running";
      },
      onIllegal: "throw" as const,
    };
    const results = await Promise.allSettled([
      transition(pool, SPACE, OPERATION, transitionSpec),
      transition(pool, SPACE, OPERATION, transitionSpec),
    ]);

    expect(results.filter((result) => result.status === "fulfilled")).toHaveLength(1);
    expect(results.filter((result) => result.status === "rejected")).toHaveLength(1);
    const row = await pool.query<{ current_stage: string; status: string }>(
      `SELECT progress_json->>'current_stage' AS current_stage, status FROM project_operations WHERE id=$1`,
      [OPERATION],
    );
    expect(row.rows[0]).toEqual({ current_stage: "backfill", status: "active" });
  });

  it("enforces one active research operation per workflow in the database", async () => {
    if (!available || !pool) return;
    await expect(pool.query(
      `INSERT INTO project_operations (id, space_id, project_id, kind, title, status, created_by_user_id, progress_json, created_at, updated_at)
       VALUES ($1,$2,$3,'research','Duplicate','waiting_review',$4,$5::jsonb,now(),now())`,
      [randomUUID(), SPACE, PROJECT, OWNER, JSON.stringify(operationState())],
    )).rejects.toMatchObject({ code: "23505", constraint: "uq_project_operations_active_research_workflow" });
  });
});
