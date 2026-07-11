import { join } from "node:path";
import { randomUUID } from "node:crypto";
import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { Pool } from "pg";
import {
  PostgreSqlContainer,
  type StartedPostgreSqlContainer,
} from "@testcontainers/postgresql";
import { migrate } from "../src/db/migrator";
import {
  linkEvidenceToBoundProjects,
  recomputeProjectSourceBindingLinks,
} from "../src/modules/projects/projectSourceRoutingService";
import { PgRunContextRepository } from "../src/modules/context/repository";

// Real-PostgreSQL tests for evidence→project auto-linking on materialization:
// bound sources produce active `context_candidate` project links, re-runs are
// idempotent (partial unique index), unbound/paused bindings produce nothing,
// and the context evidence selector actually returns the auto-linked evidence
// for a project-scoped selection. Skips when Docker is unavailable.

const MIGRATIONS_DIR = join(process.cwd(), "migrations");
const SPACE = "11111111-1111-4111-8111-111111111111";
const OWNER = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const PROJECT = "55555555-5555-4555-8555-555555555555";
const PROJECT_B = "66666666-6666-4666-8666-666666666666";
const CONNECTOR = "33333333-3333-4333-8333-333333333333";
const CONNECTION = "44444444-4444-4444-8444-444444444444";

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
    console.warn(
      `[source-evidence-project-link-db] skipped — Docker/Postgres unavailable: ${
        err instanceof Error ? err.message : String(err)
      }`,
    );
  }
}, 180_000);

afterAll(async () => {
  await pool?.end();
  await container?.stop();
});

beforeEach(async () => {
  if (!available || !pool) return;
  await pool.query(
    `TRUNCATE evidence_links, extracted_evidence, source_snapshots, source_items, project_source_item_links,
       project_source_bindings, source_connections, source_connectors, project_members, projects,
       space_memberships, users, spaces CASCADE`,
  );
  const now = new Date().toISOString();
  await pool.query(
    `INSERT INTO spaces (id, name, type, created_at, updated_at) VALUES ($1,'Main','personal',$2,$2)`,
    [SPACE, now],
  );
  await pool.query(
    `INSERT INTO users (id, display_name, status, created_at, updated_at) VALUES ($1,$1,'active',$2,$2)`,
    [OWNER, now],
  );
  await pool.query(
    `INSERT INTO space_memberships (id, space_id, user_id, role, status, created_at, updated_at)
     VALUES ($1,$2,$3,'owner','active',$4,$4)`,
    [randomUUID(), SPACE, OWNER, now],
  );
  await pool.query(
    `INSERT INTO projects (id, space_id, owner_user_id, name, status, created_at, updated_at)
     VALUES ($1,$2,$3,'Research','active',$4,$4), ($5,$2,$3,'Second','active',$4,$4)`,
    [PROJECT, SPACE, OWNER, now, PROJECT_B],
  );
  await pool.query(
    `INSERT INTO source_connectors (
       id, connector_key, display_name, connector_type, ingestion_mode, status,
       capabilities_json, created_at, updated_at
     ) VALUES ($1,'rss','RSS','external_feed','pull','active','{}'::jsonb,$2,$2)`,
    [CONNECTOR, now],
  );
  await pool.query(
    `INSERT INTO source_connections (
       id, space_id, connector_id, owner_user_id, name, endpoint_url, status,
       fetch_frequency, capture_policy, trust_level, consent_json, policy_json,
       config_json, created_at, updated_at
     ) VALUES ($1,$2,$3,$4,'arXiv feed','https://example.org/rss','active',
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

async function seedBinding(projectId: string, status = "active", bindingKey = "default"): Promise<string> {
  const id = randomUUID();
  const now = new Date().toISOString();
  await pool!.query(
    `INSERT INTO project_source_bindings (
       id, space_id, project_id, source_connection_id, binding_key,
       status, priority, delivery_scope, collection_notifications_enabled,
       filters_json, routing_policy_json, extraction_policy_json,
       created_at, updated_at
     ) VALUES ($1,$2,$3,$4,$5,$6,0,'project_members',true,'{}'::jsonb,'{}'::jsonb,'{}'::jsonb,$7,$7)`,
    [id, SPACE, projectId, CONNECTION, bindingKey, status, now],
  );
  return id;
}

async function seedItemWithEvidence(connectionId: string | null = CONNECTION): Promise<{ itemId: string; evidenceId: string }> {
  const itemId = randomUUID();
  const evidenceId = randomUUID();
  const now = new Date().toISOString();
  await pool!.query(
    `INSERT INTO source_items (
       id, space_id, owner_user_id, visibility, connection_id, item_type, title, first_seen_at, last_seen_at,
       content_state, retention_policy, created_at, updated_at
     ) VALUES ($1,$2,$3,'space_shared',$4,'external_url','New paper',$5,$5,'excerpt_saved','summary_only',$5,$5)`,
    [itemId, SPACE, OWNER, connectionId, now],
  );
  await pool!.query(
    `INSERT INTO extracted_evidence (
       id, space_id, owner_user_id, visibility, source_item_id, source_object_type, source_object_id,
       evidence_type, title, content_excerpt, extraction_method, trust_level,
       confidence, status, metadata_json, created_at, updated_at
     ) VALUES ($1,$2,$3,'space_shared',$4,'source_item',$4,'excerpt','New paper','Abstract text','connection_scan','normal',
       0.55,'candidate','{}'::jsonb,$5,$5)`,
    [evidenceId, SPACE, OWNER, itemId, now],
  );
  return { itemId, evidenceId };
}

async function seedSourceSnapshot(itemId: string, connectionId: string): Promise<void> {
  const now = new Date().toISOString();
  await pool!.query(
    `INSERT INTO source_snapshots (
       id, space_id, owner_user_id, visibility, source_item_id, connection_id, snapshot_type, content_hash,
       source_uri, capture_method, trust_level, metadata_json, captured_at, created_at, updated_at
     ) VALUES ($1,$2,$3,'space_shared',$4,$5,'metadata','hash','https://example.org/paper',
       'connection_scan','normal','{}'::jsonb,$6,$6,$6)`,
    [randomUUID(), SPACE, OWNER, itemId, connectionId, now],
  );
}

describe("Evidence→project auto-link (real Postgres)", () => {
  it("links new evidence to the bound project and is idempotent on re-run", async () => {
    if (!available) return;
    const bindingId = await seedBinding(PROJECT);
    const { itemId, evidenceId } = await seedItemWithEvidence();

    const created = await linkEvidenceToBoundProjects(pool!, { spaceId: SPACE, sourceItemId: itemId });
    expect(created).toBe(1);

    const links = await pool!.query(
      `SELECT target_type, target_id, link_type, status, reason FROM evidence_links WHERE evidence_id = $1`,
      [evidenceId],
    );
    expect(links.rows).toEqual([
      {
        target_type: "project",
        target_id: PROJECT,
        link_type: "context_candidate",
        status: "active",
        reason: `project_source_binding:${bindingId}`,
      },
    ]);

    const again = await linkEvidenceToBoundProjects(pool!, { spaceId: SPACE, sourceItemId: itemId });
    expect(again).toBe(0);
  });

  it("backfills historical evidence after a source binding is created", async () => {
    if (!available) return;
    const { evidenceId } = await seedItemWithEvidence();
    const bindingId = await seedBinding(PROJECT);

    const result = await recomputeProjectSourceBindingLinks(pool!, { spaceId: SPACE, bindingId });
    expect(result.created_links).toBe(1);
    expect(result.evidence_links).toBe(1);

    const links = await pool!.query(
      `SELECT target_type, target_id, link_type, status, reason FROM evidence_links WHERE evidence_id = $1`,
      [evidenceId],
    );
    expect(links.rows).toEqual([
      {
        target_type: "project",
        target_id: PROJECT,
        link_type: "context_candidate",
        status: "active",
        reason: `project_source_binding:${bindingId}`,
      },
    ]);

    const again = await recomputeProjectSourceBindingLinks(pool!, { spaceId: SPACE, bindingId });
    expect(again.created_links).toBe(0);
    expect(again.evidence_links).toBe(0);
  });

  it("two bindings to the same project produce one link; distinct projects each get one", async () => {
    if (!available) return;
    await seedBinding(PROJECT, "active", "default");
    await seedBinding(PROJECT, "active", "secondary");
    await seedBinding(PROJECT_B, "active", "default");
    const { itemId, evidenceId } = await seedItemWithEvidence();

    const created = await linkEvidenceToBoundProjects(pool!, { spaceId: SPACE, sourceItemId: itemId });
    expect(created).toBe(2);

    const targets = await pool!.query<{ target_id: string }>(
      `SELECT target_id FROM evidence_links WHERE evidence_id = $1 ORDER BY target_id`,
      [evidenceId],
    );
    expect(targets.rows.map((r) => r.target_id)).toEqual([PROJECT, PROJECT_B].sort());
  });

  it("creates nothing for paused bindings", async () => {
    if (!available) return;
    await seedBinding(PROJECT, "paused");
    const { itemId, evidenceId } = await seedItemWithEvidence();

    const created = await linkEvidenceToBoundProjects(pool!, { spaceId: SPACE, sourceItemId: itemId });
    expect(created).toBe(0);
    const links = await pool!.query(`SELECT id FROM evidence_links WHERE evidence_id = $1`, [evidenceId]);
    expect(links.rows).toHaveLength(0);
  });

  it("links evidence through source snapshot provenance when the item belongs to another source", async () => {
    if (!available) return;
    const bindingId = await seedBinding(PROJECT);
    const { itemId, evidenceId } = await seedItemWithEvidence(null);
    await seedSourceSnapshot(itemId, CONNECTION);

    const created = await linkEvidenceToBoundProjects(pool!, { spaceId: SPACE, sourceItemId: itemId });
    expect(created).toBe(1);

    const links = await pool!.query(
      `SELECT target_id, reason FROM evidence_links WHERE evidence_id = $1`,
      [evidenceId],
    );
    expect(links.rows).toEqual([{ target_id: PROJECT, reason: `project_source_binding:${bindingId}` }]);
  });

  it("auto-linked evidence is returned by context evidence selection for the project", async () => {
    if (!available) return;
    await seedBinding(PROJECT);
    const { itemId, evidenceId } = await seedItemWithEvidence();
    await linkEvidenceToBoundProjects(pool!, { spaceId: SPACE, sourceItemId: itemId });

    const repo = new PgRunContextRepository(pool!);
    const selections = await repo.selectEvidenceForContext({
      spaceId: SPACE,
      userId: OWNER,
      workspaceId: null,
      projectId: PROJECT,
      runId: null,
      limit: 8,
    });
    expect(selections.map((s) => (s.item as { id?: string }).id)).toContain(evidenceId);
  });
});
