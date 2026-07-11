import { join } from "node:path";
import { randomUUID } from "node:crypto";
import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { Pool } from "pg";
import { getTestPostgres, type TestPostgresDatabase } from "./support/sharedPostgres";
import { migrate } from "../src/db/migrator";
import { ProjectResearchRepository } from "../src/modules/projectResearch/repository";
import type { SpaceUserIdentity } from "../src/modules/routeUtils/common";

// Real-Postgres coverage for the Academic Research project-scoped research
// profile/workflow/checkpoint/artifact-link/
// literature-matrix/integrity API surface backing
// /api/v1/projects/:projectId/research/*.

const MIGRATIONS_DIR = join(process.cwd(), "migrations");
const SPACE = "11111111-1111-4111-8111-111111111111";
const OWNER = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const SAME_SPACE_MEMBER = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const PROJECT_VIEWER = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";
const PROJECT = "55555555-5555-4555-8555-555555555555";
const OTHER_PROJECT = "66666666-6666-4666-8666-666666666666";

let container: TestPostgresDatabase | undefined;
let pool: Pool | undefined;
let available = false;

beforeAll(async () => {
  try {
    container = await getTestPostgres(__filename);
    pool = new Pool({ connectionString: container.getConnectionUri(), max: 3 });
    await migrate(pool, MIGRATIONS_DIR);
    available = true;
  } catch (err) {
    console.warn(`[project-research-db] skipped — Docker/Postgres unavailable: ${err instanceof Error ? err.message : String(err)}`);
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
       project_research_profiles, artifacts, project_members, projects, space_memberships, users, spaces CASCADE`,
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

function repo(): ProjectResearchRepository {
  return new ProjectResearchRepository(pool!);
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

async function addProjectMember(userId: string, role = "viewer"): Promise<void> {
  const now = new Date().toISOString();
  await pool!.query(
    `INSERT INTO project_members (id, space_id, project_id, user_id, role, status, created_at, updated_at)
     VALUES ($1,$2,$3,$4,$5,'active',$6,$6)`,
    [randomUUID(), SPACE, PROJECT, userId, role, now],
  );
}

describe("ProjectResearchRepository (real Postgres)", () => {
  it("upserts a draft profile, then approves it", async () => {
    if (!available) return;
    const created = await repo().upsertProfile(identity, PROJECT, {
      research_question: "Does X improve Y?",
      output_type: "paper",
      paper_type: "empirical",
    });
    expect(created).toMatchObject({ status: "draft", research_question: "Does X improve Y?" });

    const approved = await repo().approveProfile(identity, PROJECT);
    expect(approved).toMatchObject({ status: "approved" });
    expect(approved.approved_by_user_id).toBe(OWNER);
    expect(approved.approved_at).toBeTruthy();
  });

  it("returns an approved profile to draft when edited, requiring a fresh approval before workflow start", async () => {
    if (!available) return;
    await repo().upsertProfile(identity, PROJECT, { research_question: "Initial question" });
    await repo().approveProfile(identity, PROJECT);

    const edited = await repo().upsertProfile(identity, PROJECT, { research_question: "Revised question" });
    expect(edited).toMatchObject({
      status: "draft",
      research_question: "Revised question",
      approved_by_user_id: null,
      approved_at: null,
    });
    await expect(repo().startWorkflow(identity, PROJECT, { workflow_type: "literature_review" })).rejects.toMatchObject({
      statusCode: 422,
    });
  });

  it("rejects an invalid output_type", async () => {
    if (!available) return;
    await expect(repo().upsertProfile(identity, PROJECT, { output_type: "not_a_type" })).rejects.toMatchObject({ statusCode: 422 });
  });

  it("blocks starting a workflow before the profile is approved", async () => {
    if (!available) return;
    await repo().upsertProfile(identity, PROJECT, {});
    await expect(repo().startWorkflow(identity, PROJECT, { workflow_type: "literature_review" })).rejects.toMatchObject({
      statusCode: 422,
    });
  });

  it("starts a workflow after profile approval, runs a stage, and lists checkpoints via a decided checkpoint", async () => {
    if (!available) return;
    await repo().upsertProfile(identity, PROJECT, {});
    await repo().approveProfile(identity, PROJECT);

    const workflow = await repo().startWorkflow(identity, PROJECT, { workflow_type: "literature_review" });
    expect(workflow).toMatchObject({ workflow_type: "literature_review", status: "active", current_stage: null });

    const afterRun = await repo().runStage(identity, PROJECT, workflow.id as string, "research_setup", { run_id: "run-123" });
    expect(afterRun.current_stage).toBe("research_setup");
    expect((afterRun.state_json as { stages: Record<string, unknown> }).stages.research_setup).toMatchObject({
      status: "running",
      run_id: "run-123",
    });

    const checkpoint = await repo().createCheckpoint(identity, PROJECT, workflow.id as string, {
      stageKey: "research_setup",
      checkpointType: "profile_approval",
      machineResult: { ok: true },
    });
    expect(checkpoint.status).toBe("pending");

    const decided = await repo().decideCheckpoint(identity, PROJECT, workflow.id as string, checkpoint.id as string, {
      decision: "approved",
      reason: "looks good",
    });
    expect(decided).toMatchObject({ status: "approved", user_decision: "approved", decision_reason: "looks good" });

    const checkpoints = await repo().listCheckpoints(identity, PROJECT, workflow.id as string);
    expect(checkpoints).toHaveLength(1);
    expect(checkpoints[0]!.id).toBe(checkpoint.id);
  });

  it("links an artifact to a workflow stage and lists it back", async () => {
    if (!available) return;
    await repo().upsertProfile(identity, PROJECT, {});
    await repo().approveProfile(identity, PROJECT);
    const workflow = await repo().startWorkflow(identity, PROJECT, { workflow_type: "literature_review" });

    const now = new Date().toISOString();
    const artifactId = randomUUID();
    await pool!.query(
      `INSERT INTO artifacts (
         id, space_id, artifact_type, title, content, exportable, export_formats_json, created_at, updated_at
       ) VALUES ($1,$2,'research_artifact','RQ Brief','Body text',true,'[]'::jsonb,$3,$3)`,
      [artifactId, SPACE, now],
    );

    const link = await repo().linkArtifact(identity, PROJECT, {
      workflow_id: workflow.id,
      stage_key: "research_setup",
      artifact_id: artifactId,
      artifact_type: "rq_brief",
    });
    expect(link).toMatchObject({ artifact_type: "rq_brief", stage_key: "research_setup" });

    const links = await repo().listArtifactLinks(identity, PROJECT, { workflowId: workflow.id as string });
    expect(links).toHaveLength(1);
    expect((links[0]!.artifact as { title: string }).title).toBe("RQ Brief");
  });

  it("does not expose research read models to a same-space non-project member", async () => {
    if (!available) return;
    await makeSharedSpace();
    await addSpaceMember(SAME_SPACE_MEMBER);
    const nonProjectIdentity: SpaceUserIdentity = { spaceId: SPACE, userId: SAME_SPACE_MEMBER };

    await repo().upsertProfile(identity, PROJECT, {});
    await repo().approveProfile(identity, PROJECT);
    const workflow = await repo().startWorkflow(identity, PROJECT, { workflow_type: "literature_review" });
    await repo().createCheckpoint(identity, PROJECT, workflow.id as string, {
      stageKey: "research_setup",
      checkpointType: "profile_approval",
      machineResult: { ok: true },
    });
    const artifactId = randomUUID();
    await pool!.query(
      `INSERT INTO artifacts (
         id, space_id, artifact_type, title, content, exportable, export_formats_json, created_at, updated_at
       ) VALUES ($1,$2,'research_artifact','Synthesis','Body',true,'[]'::jsonb,now(),now())`,
      [artifactId, SPACE],
    );
    await repo().linkArtifact(identity, PROJECT, { artifact_id: artifactId, artifact_type: "synthesis_report" });
    await repo().upsertScreeningCriteria(identity, PROJECT, { include_keywords: ["llm"] });

    await expect(repo().getProfile(nonProjectIdentity, PROJECT)).rejects.toMatchObject({ statusCode: 404 });
    await expect(repo().listWorkflows(nonProjectIdentity, PROJECT)).rejects.toMatchObject({ statusCode: 404 });
    await expect(repo().listCheckpoints(nonProjectIdentity, PROJECT, workflow.id as string)).rejects.toMatchObject({ statusCode: 404 });
    await expect(repo().listArtifactLinks(nonProjectIdentity, PROJECT, {})).rejects.toMatchObject({ statusCode: 404 });
    await expect(repo().getLiteratureMatrix(nonProjectIdentity, PROJECT)).rejects.toMatchObject({ statusCode: 404 });
    await expect(repo().getScreeningCriteria(nonProjectIdentity, PROJECT)).rejects.toMatchObject({ statusCode: 404 });
  });

  it("applies artifact visibility when linking and reading research artifact links", async () => {
    if (!available) return;
    await makeSharedSpace();
    await addSpaceMember(SAME_SPACE_MEMBER);
    await addSpaceMember(PROJECT_VIEWER);
    await addProjectMember(PROJECT_VIEWER);
    const viewerIdentity: SpaceUserIdentity = { spaceId: SPACE, userId: PROJECT_VIEWER };
    const now = new Date().toISOString();

    const otherPrivateArtifactId = randomUUID();
    await pool!.query(
      `INSERT INTO artifacts (
         id, space_id, artifact_type, title, content, exportable, export_formats_json,
         visibility, owner_user_id, created_at, updated_at
       ) VALUES ($1,$2,'research_artifact','Other private','Secret',true,'[]'::jsonb,'private',$3,$4,$4)`,
      [otherPrivateArtifactId, SPACE, SAME_SPACE_MEMBER, now],
    );
    await expect(
      repo().linkArtifact(identity, PROJECT, { artifact_type: "draft", artifact_id: otherPrivateArtifactId }),
    ).rejects.toMatchObject({ statusCode: 422 });

    const ownerPrivateArtifactId = randomUUID();
    await pool!.query(
      `INSERT INTO artifacts (
         id, space_id, artifact_type, title, content, exportable, export_formats_json,
         visibility, owner_user_id, created_at, updated_at
       ) VALUES ($1,$2,'research_artifact','Owner private','Owner-only',true,'[]'::jsonb,'private',$3,$4,$4)`,
      [ownerPrivateArtifactId, SPACE, OWNER, now],
    );
    await repo().linkArtifact(identity, PROJECT, { artifact_type: "draft", artifact_id: ownerPrivateArtifactId });

    expect(await repo().listArtifactLinks(identity, PROJECT, {})).toHaveLength(1);
    expect(await repo().listArtifactLinks(viewerIdentity, PROJECT, {})).toHaveLength(0);
  });

  it("rejects linking an artifact from another space", async () => {
    if (!available) return;
    await pool!.query(`INSERT INTO spaces (id, name, type, created_at, updated_at) VALUES ($1,'Other','personal',now(),now())`, [
      "22222222-2222-4222-8222-222222222222",
    ]);
    const otherArtifactId = randomUUID();
    const now = new Date().toISOString();
    await pool!.query(
      `INSERT INTO artifacts (
         id, space_id, artifact_type, title, exportable, export_formats_json, created_at, updated_at
       ) VALUES ($1,$2,'research_artifact','Other space artifact',true,'[]'::jsonb,$3,$3)`,
      [otherArtifactId, "22222222-2222-4222-8222-222222222222", now],
    );

    await expect(
      repo().linkArtifact(identity, PROJECT, { artifact_type: "draft", artifact_id: otherArtifactId }),
    ).rejects.toMatchObject({ statusCode: 422 });
  });

  it("rejects linking an artifact that belongs to another project in the same space", async () => {
    if (!available) return;
    const now = new Date().toISOString();
    await pool!.query(
      `INSERT INTO projects (id, space_id, owner_user_id, name, status, created_at, updated_at)
       VALUES ($1,$2,$3,'Other project','active',$4,$4)`,
      [OTHER_PROJECT, SPACE, OWNER, now],
    );
    const artifactId = randomUUID();
    await pool!.query(
      `INSERT INTO artifacts (
         id, space_id, project_id, artifact_type, title, exportable, export_formats_json, created_at, updated_at
       ) VALUES ($1,$2,$3,'research_artifact','Other project artifact',true,'[]'::jsonb,$4,$4)`,
      [artifactId, SPACE, OTHER_PROJECT, now],
    );

    await expect(
      repo().linkArtifact(identity, PROJECT, { artifact_type: "draft", artifact_id: artifactId }),
    ).rejects.toMatchObject({ statusCode: 422 });
  });

  it("literature matrix includes only included/maybe corpus items, and rebuild backfills from source links", async () => {
    if (!available) return;
    const now = new Date().toISOString();
    const objectId = randomUUID();
    await pool!.query(
      `INSERT INTO space_objects (id, space_id, object_type, title, status, created_at, updated_at)
       VALUES ($1,$2,'source','Paper A','processed',$3,$3)`,
      [objectId, SPACE, now],
    );
    const corpusItemId = randomUUID();
    await pool!.query(
      `INSERT INTO project_corpus_items (
         id, space_id, project_id, object_id, role, status, triage_status, read_status,
         metadata_json, created_at, updated_at
       ) VALUES ($1,$2,$3,$4,'candidate','active','included','unread','{}'::jsonb,$5,$5)`,
      [corpusItemId, SPACE, PROJECT, objectId, now],
    );
    const excludedCorpusItemId = randomUUID();
    const excludedObjectId = randomUUID();
    await pool!.query(
      `INSERT INTO space_objects (id, space_id, object_type, title, status, created_at, updated_at)
       VALUES ($1,$2,'source','Paper B','processed',$3,$3)`,
      [excludedObjectId, SPACE, now],
    );
    await pool!.query(
      `INSERT INTO project_corpus_items (
         id, space_id, project_id, object_id, role, status, triage_status, read_status,
         metadata_json, created_at, updated_at
       ) VALUES ($1,$2,$3,$4,'candidate','active','excluded','unread','{}'::jsonb,$5,$5)`,
      [excludedCorpusItemId, SPACE, PROJECT, excludedObjectId, now],
    );

    const matrix = await repo().getLiteratureMatrix(identity, PROJECT);
    expect(matrix).toHaveLength(1);
    expect(matrix[0]).toMatchObject({ object_id: objectId, title: "Paper A", triage_status: "included" });

    const rebuilt = await repo().rebuildLiteratureMatrix(identity, PROJECT);
    expect(rebuilt).toHaveLength(1);
  });

  it("records a pending integrity checkpoint with a real (non-fabricated) machine result", async () => {
    if (!available) return;
    await repo().upsertProfile(identity, PROJECT, {});
    await repo().approveProfile(identity, PROJECT);
    const workflow = await repo().startWorkflow(identity, PROJECT, { workflow_type: "literature_review" });

    // No claim links yet, so the integrity gate has nothing to check
    // and passes cleanly — see projectResearchIntegrityDb.test.ts for the
    // full citation/evidence/gap-finding coverage.
    const checkpoint = await repo().runIntegrityCheck(identity, PROJECT, { workflow_id: workflow.id });
    expect(checkpoint).toMatchObject({ checkpoint_type: "integrity_gate", status: "pending" });
    expect(checkpoint.machine_result_json).toMatchObject({ checked_claim_links: 0, blocking: false });
  });

  it("returns an empty default before screening criteria are saved, then upserts and rejects a bad date range", async () => {
    if (!available) return;
    const empty = await repo().getScreeningCriteria(identity, PROJECT);
    expect(empty).toMatchObject({ include_keywords: [], exclude_keywords: [], project_id: PROJECT });

    const saved = await repo().upsertScreeningCriteria(identity, PROJECT, {
      include_keywords: ["transformer", "attention"],
      exclude_keywords: ["survey"],
      methods: ["ablation"],
      venues: ["NeurIPS"],
      date_range_start: "2020-01-01T00:00:00.000Z",
      date_range_end: "2024-01-01T00:00:00.000Z",
    });
    expect(saved).toMatchObject({ include_keywords: ["transformer", "attention"], venues: ["NeurIPS"] });

    const fetched = await repo().getScreeningCriteria(identity, PROJECT);
    expect(fetched).toMatchObject({ exclude_keywords: ["survey"], methods: ["ablation"] });

    await expect(
      repo().upsertScreeningCriteria(identity, PROJECT, {
        date_range_start: "2024-01-01T00:00:00.000Z",
        date_range_end: "2020-01-01T00:00:00.000Z",
      }),
    ).rejects.toMatchObject({ statusCode: 422 });
  });

  it("enriches the literature matrix with academic metadata and evidence/annotation counts", async () => {
    if (!available) return;
    const now = new Date().toISOString();
    const sourceItemId = randomUUID();
    await pool!.query(
      `INSERT INTO source_items (
         id, space_id, owner_user_id, visibility, item_type, title, first_seen_at, last_seen_at, content_state, retention_policy, created_at, updated_at
       ) VALUES ($1,$2,$3,'space_shared','feed_entry','Paper A',$4,$4,'excerpt_saved','summary_only',$4,$4)`,
      [sourceItemId, SPACE, OWNER, now],
    );
    const objectId = randomUUID();
    await pool!.query(
      `INSERT INTO space_objects (id, space_id, object_type, title, status, created_at, updated_at)
       VALUES ($1,$2,'source','Paper A','processed',$3,$3)`,
      [objectId, SPACE, now],
    );
    await pool!.query(
      `INSERT INTO sources (object_id, space_id, source_type, uri, metadata_json)
       VALUES ($1,$2,'paper','https://arxiv.org/abs/2401.00009',$3::jsonb)`,
      [objectId, SPACE, JSON.stringify({ authors: ["A. Author"], categories: ["cs.CL"] })],
    );
    await pool!.query(
      `INSERT INTO academic_papers (object_id, space_id, arxiv_id, paper_type, created_at, updated_at)
       VALUES ($1,$2,'2401.00009','preprint',$3,$3)`,
      [objectId, SPACE, now],
    );
    await pool!.query(
      `INSERT INTO project_corpus_items (
         id, space_id, project_id, object_id, source_item_id, role, status, triage_status, read_status,
         metadata_json, created_at, updated_at
       ) VALUES ($1,$2,$3,$4,$5,'candidate','active','included','unread','{}'::jsonb,$6,$6)`,
      [randomUUID(), SPACE, PROJECT, objectId, sourceItemId, now],
    );
    await pool!.query(
      `INSERT INTO extracted_evidence (
         id, space_id, owner_user_id, visibility, source_item_id, source_object_type, source_object_id, evidence_type, title,
         extraction_method, trust_level, status, created_at, updated_at
       ) VALUES ($1,$2,$3,'space_shared',$4,'source_item',$4,'excerpt','Key finding','full_text','normal','candidate',$5,$5)`,
      [randomUUID(), SPACE, OWNER, sourceItemId, now],
    );

    const matrix = await repo().getLiteratureMatrix(identity, PROJECT);
    expect(matrix).toHaveLength(1);
    expect(matrix[0]).toMatchObject({
      object_id: objectId,
      evidence_count: 1,
      annotation_count: 0,
      academic: { arxiv_id: "2401.00009", paper_type: "preprint", authors: ["A. Author"], categories: ["cs.CL"] },
    });
  });
});
