import { join } from "node:path";
import { randomUUID } from "node:crypto";
import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { Pool } from "pg";
import { PostgreSqlContainer, type StartedPostgreSqlContainer } from "@testcontainers/postgresql";
import { migrate } from "../src/db/migrator";
import { ProjectCorpusRepository } from "../src/modules/projects/corpusRepository";
import type { SpaceUserIdentity } from "../src/modules/routeUtils/common";

// Real-Postgres coverage for Academic Research project corpus behavior:
// Project Corpus DTOs carry joined academic paper metadata, a human's
// explicit triage decision is durable against AI screening-decision sync
// (triage_confirmed_by_user), and project corpus read state never touches
// the personal Library read state on the same source item.

const MIGRATIONS_DIR = join(process.cwd(), "migrations");
const SPACE = "11111111-1111-4111-8111-111111111111";
const OWNER = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const SAME_SPACE_MEMBER = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const PROJECT = "55555555-5555-4555-8555-555555555555";
const CONNECTOR = "33333333-3333-4333-8333-333333333333";
const CONNECTION = "44444444-4444-4444-8444-444444444444";
const AGENT = "66666666-6666-4666-8666-666666666666";
const PP_RUN = "77777777-7777-4777-8777-777777777777";

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
    console.warn(`[project-corpus-academic-db] skipped — Docker/Postgres unavailable: ${err instanceof Error ? err.message : String(err)}`);
  }
}, 180_000);

afterAll(async () => {
  await pool?.end();
  await container?.stop();
});

beforeEach(async () => {
  if (!available || !pool) return;
  await pool.query(
    `TRUNCATE academic_papers, sources, space_objects, project_corpus_items, source_item_user_states,
       source_post_processing_item_decisions, source_post_processing_runs, agents, project_source_item_links,
       project_source_bindings, source_items, source_connections, source_connectors, project_members, projects,
       space_memberships, users, spaces CASCADE`,
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
  await pool.query(
    `INSERT INTO source_connectors (
       id, connector_key, display_name, connector_type, ingestion_mode, status,
       capabilities_json, created_at, updated_at
     ) VALUES ($1,'arxiv','arXiv','external_feed','pull','active','{}'::jsonb,$2,$2)`,
    [CONNECTOR, now],
  );
  await pool.query(
    `INSERT INTO source_connections (
       id, space_id, connector_id, owner_user_id, name, endpoint_url, status,
       fetch_frequency, capture_policy, trust_level, consent_json, policy_json,
       config_json, created_at, updated_at
     ) VALUES ($1,$2,$3,$4,'arXiv feed','https://export.arxiv.org/api/query','active',
       'daily','reference_only','normal',$5::jsonb,$6::jsonb,'{}'::jsonb,$7,$7)`,
    [
      CONNECTION,
      SPACE,
      CONNECTOR,
      OWNER,
      JSON.stringify({
        schema_version: 1,
        owner_user_id: OWNER,
        allowed_reader_user_ids: [],
        allowed_agent_ids: [],
        allow_space_admins: true,
        allow_local_provider_egress: true,
        allow_external_model_egress: true,
      }),
      JSON.stringify({ schema_version: 1, source_egress_class: "external_provider_allowed" }),
      now,
    ],
  );
});

function repo(): ProjectCorpusRepository {
  return new ProjectCorpusRepository(pool!);
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

async function seedPaperCorpusItem(): Promise<{ objectId: string; sourceItemId: string; corpusItemId: string }> {
  const now = new Date().toISOString();
  const sourceItemId = randomUUID();
  await pool!.query(
    `INSERT INTO source_items (
       id, space_id, connection_id, item_type, title, first_seen_at, last_seen_at,
       content_state, retention_policy, created_at, updated_at
     ) VALUES ($1,$2,$3,'feed_entry','Paper A',$4,$4,'excerpt_saved','summary_only',$4,$4)`,
    [sourceItemId, SPACE, CONNECTION, now],
  );
  const objectId = randomUUID();
  await pool!.query(
    `INSERT INTO space_objects (id, space_id, object_type, title, status, created_at, updated_at)
     VALUES ($1,$2,'source','Paper A','processed',$3,$3)`,
    [objectId, SPACE, now],
  );
  await pool!.query(
    `INSERT INTO sources (object_id, space_id, source_type, uri, metadata_json)
     VALUES ($1,$2,'paper','https://arxiv.org/abs/2401.00001',$3::jsonb)`,
    [objectId, SPACE, JSON.stringify({ authors: ["Jane Doe"], categories: ["cs.LG"] })],
  );
  await pool!.query(
    `INSERT INTO academic_papers (object_id, space_id, arxiv_id, doi, publication_date, paper_type, created_at, updated_at)
     VALUES ($1,$2,'2401.00001','10.1000/example',$3,'preprint',$3,$3)`,
    [objectId, SPACE, now],
  );
  const corpusItemId = randomUUID();
  await pool!.query(
    `INSERT INTO project_corpus_items (
       id, space_id, project_id, object_id, source_item_id, role, status, triage_status, read_status,
       metadata_json, created_at, updated_at
     ) VALUES ($1,$2,$3,$4,$5,'candidate','active','new','unread','{}'::jsonb,$6,$6)`,
    [corpusItemId, SPACE, PROJECT, objectId, sourceItemId, now],
  );
  return { objectId, sourceItemId, corpusItemId };
}

// syncProjectCorpusSourceDecisions() only conflict-targets corpus rows keyed
// by source_item_id with object_id/evidence_id both NULL (the partial index
// `uq_project_corpus_items_project_source_item`) — i.e. items not yet
// materialized into a space_object. Screening-decision tests need that row
// shape, not the object-linked row seedPaperCorpusItem() produces.
async function seedSourceItemOnlyCorpusItem(): Promise<{ sourceItemId: string; corpusItemId: string }> {
  const now = new Date().toISOString();
  const sourceItemId = randomUUID();
  await pool!.query(
    `INSERT INTO source_items (
       id, space_id, connection_id, item_type, title, first_seen_at, last_seen_at,
       content_state, retention_policy, created_at, updated_at
     ) VALUES ($1,$2,$3,'feed_entry','Paper B',$4,$4,'excerpt_saved','summary_only',$4,$4)`,
    [sourceItemId, SPACE, CONNECTION, now],
  );
  // backfillFromSources() archives corpus rows lacking a backing active
  // project_source_item_links row — seed a binding + link so the row this
  // test asserts on survives the backfill's archive-orphans step.
  const bindingId = randomUUID();
  await pool!.query(
    `INSERT INTO project_source_bindings (
       id, space_id, project_id, source_connection_id, binding_key,
       status, priority, delivery_scope, collection_notifications_enabled,
       filters_json, routing_policy_json, extraction_policy_json,
       created_at, updated_at
     ) VALUES ($1,$2,$3,$4,'default','active',0,'project_members',true,'{}'::jsonb,'{}'::jsonb,'{}'::jsonb,$5,$5)`,
    [bindingId, SPACE, PROJECT, CONNECTION, now],
  );
  await pool!.query(
    `INSERT INTO project_source_item_links (
       id, space_id, project_id, project_source_binding_id, source_connection_id,
       source_item_id, status, matched_at, created_at, updated_at
     ) VALUES ($1,$2,$3,$4,$5,$6,'active',$7,$7,$7)`,
    [randomUUID(), SPACE, PROJECT, bindingId, CONNECTION, sourceItemId, now],
  );
  const corpusItemId = randomUUID();
  await pool!.query(
    `INSERT INTO project_corpus_items (
       id, space_id, project_id, source_item_id, role, status, triage_status, read_status,
       metadata_json, created_at, updated_at
     ) VALUES ($1,$2,$3,$4,'candidate','active','new','unread','{}'::jsonb,$5,$5)`,
    [corpusItemId, SPACE, PROJECT, sourceItemId, now],
  );
  return { sourceItemId, corpusItemId };
}

async function seedScreeningDecision(sourceItemId: string, relevance: string): Promise<void> {
  const now = new Date().toISOString();
  await pool!.query(
    `INSERT INTO agents (id, space_id, owner_user_id, name, status, current_version_id, created_at, updated_at, visibility)
     VALUES ($1,$2,$3,'Screening Agent','active',NULL,$4,$4,'space_shared')
     ON CONFLICT (id) DO NOTHING`,
    [AGENT, SPACE, OWNER, now],
  );
  await pool!.query(
    `INSERT INTO source_post_processing_runs (
       id, space_id, source_connection_id, agent_id, project_id, trigger_type, status, created_at
     ) VALUES ($1,$2,$3,$4,$5,'manual','succeeded',$6)
     ON CONFLICT (id) DO NOTHING`,
    [PP_RUN, SPACE, CONNECTION, AGENT, PROJECT, now],
  );
  await pool!.query(
    `INSERT INTO source_post_processing_item_decisions (
       id, space_id, source_connection_id, run_id, project_id, source_item_id, relevance,
       review_status, created_at, updated_at
     ) VALUES ($1,$2,$3,$4,$5,$6,$7,'accepted',$8,$8)`,
    [randomUUID(), SPACE, CONNECTION, PP_RUN, PROJECT, sourceItemId, relevance, now],
  );
}

describe("Project Corpus academic enrichment (real Postgres)", () => {
  it("includes joined academic paper metadata in the corpus list DTO", async () => {
    if (!available) return;
    await seedPaperCorpusItem();

    const page = await repo().list(identity, PROJECT, { limit: 50, offset: 0 });
    const items = page.items as Array<{ object: { academic: Record<string, unknown> | null } }>;
    expect(items).toHaveLength(1);
    expect(items[0]!.object.academic).toMatchObject({
      arxiv_id: "2401.00001",
      doi: "10.1000/example",
      paper_type: "preprint",
      authors: ["Jane Doe"],
      categories: ["cs.LG"],
    });
  });

  it("does not expose project corpus to a same-space non-project member", async () => {
    if (!available) return;
    await makeSharedSpace();
    await addSpaceMember(SAME_SPACE_MEMBER);
    await seedPaperCorpusItem();

    await expect(
      repo().list({ spaceId: SPACE, userId: SAME_SPACE_MEMBER }, PROJECT, { limit: 50, offset: 0 }),
    ).rejects.toMatchObject({ statusCode: 404 });
  });

  it("rejects manually adding corpus targets that the writer cannot read", async () => {
    if (!available) return;
    await makeSharedSpace();
    await addSpaceMember(SAME_SPACE_MEMBER);
    const now = new Date().toISOString();

    const privateObjectId = randomUUID();
    await pool!.query(
      `INSERT INTO space_objects (
         id, space_id, object_type, title, status, visibility, owner_user_id, created_by_user_id, created_at, updated_at
       ) VALUES ($1,$2,'source','Private Paper','processed','private',$3,$3,$4,$4)`,
      [privateObjectId, SPACE, SAME_SPACE_MEMBER, now],
    );
    await expect(repo().upsert(identity, PROJECT, { object_id: privateObjectId })).rejects.toMatchObject({ statusCode: 422 });

    const privateSourceItemId = randomUUID();
    await pool!.query(
      `INSERT INTO source_items (
         id, space_id, created_by_user_id, item_type, title, first_seen_at, last_seen_at,
         content_state, retention_policy, created_at, updated_at
       ) VALUES ($1,$2,$3,'feed_entry','Private source item',$4,$4,'excerpt_saved','summary_only',$4,$4)`,
      [privateSourceItemId, SPACE, SAME_SPACE_MEMBER, now],
    );
    await expect(repo().upsert(identity, PROJECT, { source_item_id: privateSourceItemId })).rejects.toMatchObject({ statusCode: 422 });

    const privateEvidenceId = randomUUID();
    await pool!.query(
      `INSERT INTO extracted_evidence (
         id, space_id, source_item_id, evidence_type, title, content_excerpt,
         extraction_method, trust_level, status, created_by_user_id, created_at, updated_at
       ) VALUES ($1,$2,$3,'excerpt','Private evidence','secret','full_text','normal','candidate',$4,$5,$5)`,
      [privateEvidenceId, SPACE, privateSourceItemId, SAME_SPACE_MEMBER, now],
    );
    await expect(repo().upsert(identity, PROJECT, { evidence_id: privateEvidenceId })).rejects.toMatchObject({ statusCode: 422 });
  });

  it("marks triage_confirmed_by_user when a human explicitly sets triage_status via update", async () => {
    if (!available) return;
    const { corpusItemId } = await seedPaperCorpusItem();

    const updated = await repo().update(identity, PROJECT, corpusItemId, { triage_status: "included" });
    expect(updated).toMatchObject({ triage_status: "included", triage_confirmed_by_user: true });

    const untouched = await repo().update(identity, PROJECT, corpusItemId, { reason: "still relevant" });
    expect(untouched).toMatchObject({ triage_status: "included", triage_confirmed_by_user: true });
  });

  it("does not let a later AI screening decision overwrite a user-confirmed triage_status", async () => {
    if (!available) return;
    const { corpusItemId, sourceItemId } = await seedSourceItemOnlyCorpusItem();
    await repo().update(identity, PROJECT, corpusItemId, { triage_status: "included" });

    await seedScreeningDecision(sourceItemId, "not_relevant");
    await repo().backfillFromSources(identity, PROJECT);

    const page = await repo().list(identity, PROJECT, { limit: 50, offset: 0 });
    const item = (page.items as Array<{ id: string; triage_status: string }>).find((row) => row.id === corpusItemId);
    expect(item?.triage_status).toBe("included");
  });

  it("lets an AI screening decision set triage_status when the item is not yet user-confirmed", async () => {
    if (!available) return;
    const { corpusItemId, sourceItemId } = await seedSourceItemOnlyCorpusItem();

    await seedScreeningDecision(sourceItemId, "relevant");
    await repo().backfillFromSources(identity, PROJECT);

    const page = await repo().list(identity, PROJECT, { limit: 50, offset: 0 });
    const item = (page.items as Array<{ id: string; triage_status: string; triage_confirmed_by_user: boolean }>).find(
      (row) => row.id === corpusItemId,
    );
    expect(item?.triage_status).toBe("relevant");
    expect(item?.triage_confirmed_by_user).toBe(false);
  });

  it("keeps Library personal read state separate from project corpus triage/read state", async () => {
    if (!available) return;
    const { corpusItemId, sourceItemId } = await seedPaperCorpusItem();
    await repo().update(identity, PROJECT, corpusItemId, { triage_status: "included", read_status: "read" });

    const now = new Date().toISOString();
    await pool!.query(
      `INSERT INTO source_item_user_states (
         id, space_id, source_item_id, user_id, library_status, read_status, created_at, updated_at
       ) VALUES ($1,$2,$3,$4,'new','unread',$5,$5)`,
      [randomUUID(), SPACE, sourceItemId, OWNER, now],
    );

    const libraryState = await pool!.query<{ read_status: string; library_status: string }>(
      `SELECT read_status, library_status FROM source_item_user_states WHERE source_item_id = $1`,
      [sourceItemId],
    );
    expect(libraryState.rows[0]).toMatchObject({ read_status: "unread", library_status: "new" });

    const corpusItem = await pool!.query<{ read_status: string; triage_status: string }>(
      `SELECT read_status, triage_status FROM project_corpus_items WHERE id = $1`,
      [corpusItemId],
    );
    expect(corpusItem.rows[0]).toMatchObject({ read_status: "read", triage_status: "included" });
  });
});
