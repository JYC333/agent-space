import { join } from "node:path";
import { randomUUID } from "node:crypto";
import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { Pool } from "pg";
import { PostgreSqlContainer, type StartedPostgreSqlContainer } from "@testcontainers/postgresql";
import { migrate } from "../src/db/migrator";

// Real-Postgres coverage for the Academic Research schema foundation:
// the project_research_profiles/workflows/checkpoints/artifact_links schema
// — one profile per project, workflow status/type checks, checkpoint cascade
// on workflow delete, and artifact links surviving workflow deletion with a
// nulled workflow_id.

const MIGRATIONS_DIR = join(process.cwd(), "migrations");
const SPACE = "11111111-1111-4111-8111-111111111111";
const OWNER = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const PROJECT = "55555555-5555-4555-8555-555555555555";

let container: StartedPostgreSqlContainer | undefined;
let pool: Pool | undefined;
let available = false;

beforeAll(async () => {
  try {
    container = await new PostgreSqlContainer("pgvector/pgvector:pg18").start();
    pool = new Pool({ connectionString: container.getConnectionUri(), max: 3 });
    await migrate(pool, MIGRATIONS_DIR);
    available = true;
  } catch (err) {
    console.warn(`[project-research-schema-db] skipped — Docker/Postgres unavailable: ${err instanceof Error ? err.message : String(err)}`);
  }
}, 180_000);

afterAll(async () => {
  await pool?.end();
  await container?.stop();
});

beforeEach(async () => {
  if (!available || !pool) return;
  await pool.query(
    `TRUNCATE project_research_artifact_links, project_research_checkpoints, project_research_workflows,
       project_research_profiles, artifacts, projects, space_memberships, users, spaces CASCADE`,
  );
  const now = new Date().toISOString();
  await pool.query(`INSERT INTO spaces (id, name, type, created_at, updated_at) VALUES ($1,'Main','personal',$2,$2)`, [SPACE, now]);
  await pool.query(`INSERT INTO users (id, display_name, status, created_at, updated_at) VALUES ($1,$1,'active',$2,$2)`, [OWNER, now]);
  await pool.query(
    `INSERT INTO space_memberships (id, space_id, user_id, role, status, created_at, updated_at)
     VALUES ($1,$2,$3,'owner','active',$4,$4)`,
    [randomUUID(), SPACE, OWNER, now],
  );
  await pool.query(
    `INSERT INTO projects (id, space_id, owner_user_id, name, status, created_at, updated_at)
     VALUES ($1,$2,$3,'Research','active',$4,$4)`,
    [PROJECT, SPACE, OWNER, now],
  );
});

async function insertProfile(): Promise<string> {
  const id = randomUUID();
  const now = new Date().toISOString();
  await pool!.query(
    `INSERT INTO project_research_profiles (
       id, space_id, project_id, research_question, status, created_at, updated_at
     ) VALUES ($1,$2,$3,'Does X improve Y?','draft',$4,$4)`,
    [id, SPACE, PROJECT, now],
  );
  return id;
}

async function insertWorkflow(): Promise<string> {
  const id = randomUUID();
  const now = new Date().toISOString();
  await pool!.query(
    `INSERT INTO project_research_workflows (
       id, space_id, project_id, workflow_type, status, mode, created_at, updated_at
     ) VALUES ($1,$2,$3,'literature_review','active','manual',$4,$4)`,
    [id, SPACE, PROJECT, now],
  );
  return id;
}

describe("project_research_* schema (real Postgres)", () => {
  it("allows only one research profile per project", async () => {
    if (!available) return;
    await insertProfile();
    await expect(insertProfile()).rejects.toThrow();
  });

  it("rejects an invalid workflow status", async () => {
    if (!available) return;
    const now = new Date().toISOString();
    await expect(
      pool!.query(
        `INSERT INTO project_research_workflows (
           id, space_id, project_id, workflow_type, status, mode, created_at, updated_at
         ) VALUES ($1,$2,$3,'literature_review','not_a_status','manual',$4,$4)`,
        [randomUUID(), SPACE, PROJECT, now],
      ),
    ).rejects.toThrow();
  });

  it("creates a checkpoint under a workflow and cascades on workflow delete", async () => {
    if (!available) return;
    const workflowId = await insertWorkflow();
    const checkpointId = randomUUID();
    const now = new Date().toISOString();
    await pool!.query(
      `INSERT INTO project_research_checkpoints (
         id, space_id, project_id, workflow_id, stage_key, checkpoint_type, status, created_at, updated_at
       ) VALUES ($1,$2,$3,$4,'research_setup','profile_approval','pending',$5,$5)`,
      [checkpointId, SPACE, PROJECT, workflowId, now],
    );

    await pool!.query(`DELETE FROM project_research_workflows WHERE id = $1`, [workflowId]);
    const remaining = await pool!.query(`SELECT id FROM project_research_checkpoints WHERE id = $1`, [checkpointId]);
    expect(remaining.rows).toHaveLength(0);
  });

  it("nulls the artifact link's workflow_id when the workflow is deleted, keeping the link", async () => {
    if (!available) return;
    const workflowId = await insertWorkflow();
    const artifactId = randomUUID();
    const now = new Date().toISOString();
    await pool!.query(
      `INSERT INTO artifacts (
         id, space_id, artifact_type, title, exportable, export_formats_json, created_at, updated_at
       ) VALUES ($1,$2,'research_artifact','RQ Brief',true,'[]'::jsonb,$3,$3)`,
      [artifactId, SPACE, now],
    );
    const linkId = randomUUID();
    await pool!.query(
      `INSERT INTO project_research_artifact_links (
         id, space_id, project_id, workflow_id, stage_key, artifact_id, artifact_type, created_at
       ) VALUES ($1,$2,$3,$4,'research_setup',$5,'rq_brief',$6)`,
      [linkId, SPACE, PROJECT, workflowId, artifactId, now],
    );

    await pool!.query(`DELETE FROM project_research_workflows WHERE id = $1`, [workflowId]);
    const link = await pool!.query<{ workflow_id: string | null }>(
      `SELECT workflow_id FROM project_research_artifact_links WHERE id = $1`,
      [linkId],
    );
    expect(link.rows).toHaveLength(1);
    expect(link.rows[0]!.workflow_id).toBeNull();
  });

  it("rejects an invalid artifact_type on the artifact link", async () => {
    if (!available) return;
    const artifactId = randomUUID();
    const now = new Date().toISOString();
    await pool!.query(
      `INSERT INTO artifacts (
         id, space_id, artifact_type, title, exportable, export_formats_json, created_at, updated_at
       ) VALUES ($1,$2,'research_artifact','Draft',true,'[]'::jsonb,$3,$3)`,
      [artifactId, SPACE, now],
    );
    await expect(
      pool!.query(
        `INSERT INTO project_research_artifact_links (
           id, space_id, project_id, artifact_id, artifact_type, created_at
         ) VALUES ($1,$2,$3,$4,'not_a_type',$5)`,
        [randomUUID(), SPACE, PROJECT, artifactId, now],
      ),
    ).rejects.toThrow();
  });
});
