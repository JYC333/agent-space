import { join } from "node:path";
import { randomUUID } from "node:crypto";
import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { Pool } from "pg";
import { PostgreSqlContainer, type StartedPostgreSqlContainer } from "@testcontainers/postgresql";
import { migrate } from "../src/db/migrator";
import { ProjectExperimentRepository } from "../src/modules/projectResearch/experimentRepository";
import type { SpaceUserIdentity } from "../src/modules/routeUtils/common";

// Real-Postgres coverage for Academic Research experiment campaigns/runs/
// provenance. Campaign setup requires a workspace
// already linked to the project, a baseline run must be kept before other
// runs are allowed, editable/protected scope may not overlap, and
// keep/discard/crash decisions are durable.

const MIGRATIONS_DIR = join(process.cwd(), "migrations");
const SPACE = "11111111-1111-4111-8111-111111111111";
const OWNER = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const SAME_SPACE_MEMBER = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const PROJECT = "55555555-5555-4555-8555-555555555555";
const WORKSPACE = "88888888-8888-4888-8888-888888888888";
const OTHER_WORKSPACE = "99999999-9999-4999-8999-999999999999";

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
    console.warn(`[project-experiment-db] skipped — Docker/Postgres unavailable: ${err instanceof Error ? err.message : String(err)}`);
  }
}, 180_000);

afterAll(async () => {
  await pool?.end();
  await container?.stop();
});

beforeEach(async () => {
  if (!available || !pool) return;
  await pool.query(
    `TRUNCATE project_experiment_provenance, project_experiment_runs, project_experiment_campaigns,
       project_workspaces, workspaces, projects, space_memberships, users, spaces CASCADE`,
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
  for (const workspaceId of [WORKSPACE, OTHER_WORKSPACE]) {
    await pool.query(
      `INSERT INTO workspaces (
         id, space_id, owner_user_id, name, status, workspace_type, kind, visibility,
         protected, system_managed, created_at, updated_at
       ) VALUES ($1,$2,$3,'Experiment WS','active','project','git','private',false,false,$4,$4)`,
      [workspaceId, SPACE, OWNER, now],
    );
  }
  await pool.query(
    `INSERT INTO project_workspaces (id, space_id, project_id, workspace_id, role, created_at, updated_at)
     VALUES ($1,$2,$3,$4,'primary_codebase',$5,$5)`,
    [randomUUID(), SPACE, PROJECT, WORKSPACE, now],
  );
});

function repo(): ProjectExperimentRepository {
  return new ProjectExperimentRepository(pool!);
}

const identity: SpaceUserIdentity = { spaceId: SPACE, userId: OWNER };

async function makeSharedSpace(): Promise<void> {
  await pool!.query(`UPDATE spaces SET type = 'team' WHERE id = $1`, [SPACE]);
}

async function addSpaceMember(userId: string): Promise<void> {
  const now = new Date().toISOString();
  await pool!.query(`INSERT INTO users (id, display_name, status, created_at, updated_at) VALUES ($1,$1,'active',$2,$2)`, [
    userId,
    now,
  ]);
  await pool!.query(
    `INSERT INTO space_memberships (id, space_id, user_id, role, status, created_at, updated_at)
     VALUES ($1,$2,$3,'member','active',$4,$4)`,
    [randomUUID(), SPACE, userId, now],
  );
}

async function createCampaign(overrides: Record<string, unknown> = {}): Promise<Record<string, unknown>> {
  return repo().createCampaign(identity, PROJECT, {
    workspace_id: WORKSPACE,
    name: "Ablation study",
    editable_scope: ["src/model.py"],
    protected_scope: ["src/eval.py"],
    ...overrides,
  });
}

describe("Project Experiment campaigns/runs/provenance (real Postgres)", () => {
  it("creates a campaign only against a workspace linked to the project", async () => {
    if (!available) return;
    const campaign = await createCampaign();
    expect(campaign).toMatchObject({ status: "draft", workspace_id: WORKSPACE, name: "Ablation study" });

    await expect(
      repo().createCampaign(identity, PROJECT, { workspace_id: OTHER_WORKSPACE, name: "Unlinked" }),
    ).rejects.toMatchObject({ statusCode: 422 });
  });

  it("does not expose experiment read models to a same-space non-project member", async () => {
    if (!available) return;
    await makeSharedSpace();
    await addSpaceMember(SAME_SPACE_MEMBER);
    const nonProjectIdentity: SpaceUserIdentity = { spaceId: SPACE, userId: SAME_SPACE_MEMBER };

    const campaign = await createCampaign();
    const baseline = await repo().createRun(identity, PROJECT, campaign.id as string, { is_baseline: true });
    await repo().decideRun(identity, PROJECT, campaign.id as string, baseline.id as string, { decision: "keep" });
    await repo().createProvenance(identity, PROJECT, { experiment_key: "exp-private" });

    await expect(repo().listCampaigns(nonProjectIdentity, PROJECT)).rejects.toMatchObject({ statusCode: 404 });
    await expect(repo().listRuns(nonProjectIdentity, PROJECT, campaign.id as string)).rejects.toMatchObject({ statusCode: 404 });
    await expect(repo().listProvenance(nonProjectIdentity, PROJECT)).rejects.toMatchObject({ statusCode: 404 });
  });

  it("rejects a campaign whose editable and protected scopes overlap", async () => {
    if (!available) return;
    await expect(
      createCampaign({ editable_scope: ["src/model.py"], protected_scope: ["src/model.py"] }),
    ).rejects.toMatchObject({ statusCode: 422 });
    await expect(
      createCampaign({ editable_scope: ["src"], protected_scope: ["src/eval.py"] }),
    ).rejects.toMatchObject({ statusCode: 422 });
  });

  it("normalizes literal relative experiment scopes and rejects unsafe paths", async () => {
    if (!available) return;
    const campaign = await createCampaign({
      editable_scope: ["src/./model.py", "src/model.py"],
      protected_scope: ["evals"],
    });
    expect(campaign).toMatchObject({ editable_scope: ["src/model.py"], protected_scope: ["evals"] });

    await expect(
      createCampaign({ editable_scope: ["../outside.py"], protected_scope: [] }),
    ).rejects.toMatchObject({ statusCode: 422 });
    await expect(
      createCampaign({ editable_scope: ["/abs/path.py"], protected_scope: [] }),
    ).rejects.toMatchObject({ statusCode: 422 });
    await expect(
      createCampaign({ editable_scope: ["src/*.py"], protected_scope: [] }),
    ).rejects.toMatchObject({ statusCode: 422 });
  });

  it("blocks a non-baseline run before a baseline run exists", async () => {
    if (!available) return;
    const campaign = await createCampaign();
    await expect(
      repo().createRun(identity, PROJECT, campaign.id as string, { hypothesis: "faster convergence" }),
    ).rejects.toMatchObject({ statusCode: 422 });
  });

  it("sets the campaign's baseline_run_id once a baseline run is kept, then allows further runs", async () => {
    if (!available) return;
    const campaign = await createCampaign();
    const baseline = await repo().createRun(identity, PROJECT, campaign.id as string, { is_baseline: true });
    expect(baseline).toMatchObject({ is_baseline: true, status: "queued" });

    await repo().decideRun(identity, PROJECT, campaign.id as string, baseline.id as string, {
      decision: "keep",
      metrics: { accuracy: 0.81 },
      primary_metric_name: "accuracy",
      primary_metric_value: 0.81,
    });

    const campaigns = await repo().listCampaigns(identity, PROJECT);
    expect(campaigns[0]).toMatchObject({ baseline_run_id: baseline.id });

    const followUp = await repo().createRun(identity, PROJECT, campaign.id as string, { hypothesis: "try dropout 0.2" });
    expect(followUp.status).toBe("queued");
  });

  it("records keep/discard/crash decisions and marks a run as best on request", async () => {
    if (!available) return;
    const campaign = await createCampaign();
    const baseline = await repo().createRun(identity, PROJECT, campaign.id as string, { is_baseline: true });
    await repo().decideRun(identity, PROJECT, campaign.id as string, baseline.id as string, { decision: "keep" });

    const candidate = await repo().createRun(identity, PROJECT, campaign.id as string, { hypothesis: "try dropout 0.2" });
    const decided = await repo().decideRun(identity, PROJECT, campaign.id as string, candidate.id as string, {
      decision: "keep",
      metrics: { accuracy: 0.87 },
      mark_as_best: true,
      reason: "best so far",
    });
    expect(decided).toMatchObject({ status: "keep", decision_reason: "best so far" });

    const campaigns = await repo().listCampaigns(identity, PROJECT);
    expect(campaigns[0]).toMatchObject({ best_run_id: candidate.id });

    const crashed = await repo().createRun(identity, PROJECT, campaign.id as string, { hypothesis: "try lr 1.0" });
    const crashDecision = await repo().decideRun(identity, PROJECT, campaign.id as string, crashed.id as string, {
      decision: "crash",
      reason: "OOM",
    });
    expect(crashDecision.status).toBe("crash");
  });

  it("creates a provenance record with a project-unique experiment_key", async () => {
    if (!available) return;
    const campaign = await createCampaign();
    const provenance = await repo().createProvenance(identity, PROJECT, {
      experiment_key: "exp-ablation-1",
      campaign_id: campaign.id,
      planned_summary: "Ablate the attention module",
    });
    expect(provenance).toMatchObject({ experiment_key: "exp-ablation-1", campaign_id: campaign.id });

    await expect(
      repo().createProvenance(identity, PROJECT, { experiment_key: "exp-ablation-1" }),
    ).rejects.toMatchObject({ statusCode: 409 });
  });
});
