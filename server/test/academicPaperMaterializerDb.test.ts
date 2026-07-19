import { join } from "node:path";
import { randomUUID } from "node:crypto";
import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { Pool } from "pg";
import { getTestPostgres, type TestPostgresDatabase } from "./support/sharedPostgres";
import { migrate } from "../src/db/migrator";
import { materializeAcademicPaperFromSourceItem } from "../src/modules/academic/paperMaterializer";
import { syncProjectCorpusForSourceItem } from "../src/modules/projects/corpusRepository";
import { materializeProjectSourceItemLinks } from "../src/modules/projects/projectSourceRoutingService";
import { GraphProjectionRepository } from "../src/modules/graph/projectionRepository";

// Real-Postgres coverage for Academic Research arXiv paper materialization:
// arXiv source items materialize into academic_paper_v1 objects (deduped by
// arxiv_id/doi), become visible in Project Corpus, and are graph-visible.

const MIGRATIONS_DIR = join(process.cwd(), "migrations");
const SPACE = "11111111-1111-4111-8111-111111111111";
const OWNER = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const PROJECT = "55555555-5555-4555-8555-555555555555";
const CONNECTOR = "33333333-3333-4333-8333-333333333333";
const CONNECTION = "44444444-4444-4444-8444-444444444444";

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
    console.warn(`[academic-paper-materializer-db] skipped — Docker/Postgres unavailable: ${err instanceof Error ? err.message : String(err)}`);
  }
}, 180_000);

afterAll(async () => {
  await pool?.end();
  await container?.stop();
});

beforeEach(async () => {
  if (!available || !pool) return;
  await pool.query(
    `TRUNCATE academic_papers, sources, space_objects, project_corpus_items, project_source_item_links,
       project_source_bindings, source_channel_item_links, source_channel_user_subscriptions, source_channels,
       source_items, source_connections, source_provider_connectors, source_providers, source_connectors,
       project_members, projects, space_memberships, users, spaces CASCADE`,
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
  const mappingId = randomUUID();
  await pool.query(
    `INSERT INTO source_providers (id, provider_key, display_name, provider_kind, category, status, capabilities_json, created_at, updated_at)
     VALUES ($1,'arxiv','arXiv','named','academic','active','{}'::jsonb,$2,$2)`,
    [CONNECTOR, now],
  );
  await pool.query(
    `INSERT INTO source_provider_connectors (id, provider_id, connector_id, status, priority, capabilities_json, created_at, updated_at)
     VALUES ($1,$2,$3,'active',0,'{}'::jsonb,$4,$4)`,
    [mappingId, CONNECTOR, CONNECTOR, now],
  );
  await pool.query(
    `INSERT INTO source_connections (
       id, space_id, provider_connector_id, owner_user_id, name, status,
       capture_policy, trust_level, consent_json, policy_json, config_json, created_at, updated_at
     ) VALUES ($1,$2,$3,$4,'arXiv feed','active','reference_only','normal',$5::jsonb,$6::jsonb,'{}'::jsonb,$7,$7)`,
    [
      CONNECTION,
      SPACE,
      mappingId,
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
  await pool.query(
    `INSERT INTO source_channels (
       id, space_id, source_connection_id, created_by_user_id, name, channel_type, endpoint_url,
       query_json, provider_query_json, query_fingerprint, status, fetch_frequency, schedule_rule_json, created_at, updated_at
     ) VALUES ($1,$2,$1,$3,'arXiv Channel','search','https://export.arxiv.org/api/query','{}'::jsonb,'{}'::jsonb,$1,'active','daily','{"frequency":"daily","hour":0,"minute":0}'::jsonb,$4,$4)`,
    [CONNECTION, SPACE, OWNER, now],
  );
});

async function seedBinding(profileKey: string | null): Promise<string> {
  const id = randomUUID();
  const now = new Date().toISOString();
  await pool!.query(
    `INSERT INTO project_source_bindings (
       id, space_id, project_id, source_channel_id, binding_key,
       status, priority, delivery_scope, collection_notifications_enabled,
       filters_json, routing_policy_json, extraction_policy_json,
       created_at, updated_at
     ) VALUES ($1,$2,$3,$4,'default','active',0,'project_members',true,'{}'::jsonb,'{}'::jsonb,$5::jsonb,$6,$6)`,
    [id, SPACE, PROJECT, CONNECTION, JSON.stringify(profileKey ? { profile_key: profileKey } : {}), now],
  );
  return id;
}

async function seedArxivItem(arxivId: string, doi: string | null = null): Promise<string> {
  const itemId = randomUUID();
  const now = new Date().toISOString();
  await pool!.query(
    `INSERT INTO source_items (
       id, space_id, owner_user_id, visibility, connection_id, item_type, title, source_uri, first_seen_at, last_seen_at,
       content_state, retention_policy, metadata_json, created_at, updated_at
     ) VALUES ($1,$2,$3,'space_shared',$4,'feed_entry',$5,$6,$7,$7,'excerpt_saved','summary_only',$8::jsonb,$7,$7)`,
    [
      itemId,
      SPACE,
      OWNER,
      CONNECTION,
      `Paper ${arxivId}`,
      `https://arxiv.org/abs/${arxivId}`,
      now,
      JSON.stringify({
        arxiv_id: arxivId,
        doi,
        authors: ["Jane Doe", "John Smith"],
        categories: ["cs.LG", "cs.AI"],
        primary_category: "cs.LG",
        published_at: now,
        updated_at: now,
        abs_url: `https://arxiv.org/abs/${arxivId}`,
        html_url: `https://arxiv.org/html/${arxivId}`,
        pdf_url: `https://arxiv.org/pdf/${arxivId}`,
        journal_ref: null,
        comment: null,
      }),
    ],
  );
  return itemId;
}

async function seedProviderItem(metadata: Record<string, unknown>, title: string): Promise<string> {
  const itemId = randomUUID(); const now = new Date().toISOString();
  await pool!.query(
    `INSERT INTO source_items (id,space_id,owner_user_id,visibility,connection_id,item_type,title,source_uri,first_seen_at,last_seen_at,content_state,retention_policy,metadata_json,created_at,updated_at)
     VALUES ($1,$2,$3,'space_shared',$4,'feed_entry',$5,$6,$7,$7,'metadata_only','metadata_only',$8::jsonb,$7,$7)`,
    [itemId, SPACE, OWNER, CONNECTION, title, String(metadata.source_url ?? "https://example.test/paper"), now, JSON.stringify(metadata)],
  );
  return itemId;
}

describe("Academic paper materialization from arXiv source items (real Postgres)", () => {
  it("materializes a paper object and syncs into Project Corpus + graph", async () => {
    if (!available) return;
    await seedBinding("academic_paper_v1");
    const itemId = await seedArxivItem("2401.00001", "10.1000/example");
    const routeResult = await materializeProjectSourceItemLinks(pool!, { spaceId: SPACE, sourceItemId: itemId });
    expect(routeResult).toMatchObject({ created: 1, reactivated: 0, archived: 0 });

    const item = await pool!.query<{ source_object_id: string; source_object_type: string }>(
      `SELECT source_object_id, source_object_type FROM source_items WHERE id = $1`,
      [itemId],
    );
    const objectId = item.rows[0]!.source_object_id;
    expect(item.rows[0]!.source_object_id).toBe(objectId);
    expect(item.rows[0]!.source_object_type).toBe("source");

    const paper = await pool!.query<{ arxiv_id: string; doi: string | null; paper_type: string }>(
      `SELECT arxiv_id, doi, paper_type FROM academic_papers WHERE object_id = $1`,
      [objectId],
    );
    expect(paper.rows[0]).toMatchObject({ arxiv_id: "2401.00001", doi: "10.1000/example", paper_type: "preprint" });

    const sourceRow = await pool!.query<{ metadata_json: { authors: string[] } }>(
      `SELECT metadata_json FROM sources WHERE object_id = $1`,
      [objectId],
    );
    expect(sourceRow.rows[0]!.metadata_json.authors).toEqual(["Jane Doe", "John Smith"]);

    await syncProjectCorpusForSourceItem(pool!, { spaceId: SPACE, sourceItemId: itemId });
    const corpusItem = await pool!.query<{ object_id: string; triage_status: string }>(
      `SELECT object_id, triage_status FROM project_corpus_items WHERE project_id = $1 AND object_id = $2`,
      [PROJECT, objectId],
    );
    expect(corpusItem.rows).toHaveLength(1);
    expect(corpusItem.rows[0]!.triage_status).toBe("new");

    const graphRepo = new GraphProjectionRepository(pool!);
    const visible = await graphRepo.getVisibleObject({ spaceId: SPACE, userId: OWNER }, objectId, { projectId: PROJECT });
    expect(visible?.id).toBe(objectId);
  });

  it("is idempotent: re-running does not create a duplicate paper", async () => {
    if (!available) return;
    const itemId = await seedArxivItem("2401.00002");

    const first = await materializeAcademicPaperFromSourceItem(pool!, { spaceId: SPACE, sourceItemId: itemId });
    const second = await materializeAcademicPaperFromSourceItem(pool!, { spaceId: SPACE, sourceItemId: itemId });

    expect(second).toMatchObject({ objectId: first!.objectId, created: false });
    const count = await pool!.query(`SELECT count(*)::int AS total FROM academic_papers WHERE arxiv_id = '2401.00002'`);
    expect(count.rows[0]!.total).toBe(1);
  });

  it("dedupes a second arXiv item that shares an existing doi", async () => {
    if (!available) return;
    const firstItemId = await seedArxivItem("2401.00003", "10.1000/shared");
    const first = await materializeAcademicPaperFromSourceItem(pool!, { spaceId: SPACE, sourceItemId: firstItemId });

    const secondItemId = await seedArxivItem("2401.00004", "10.1000/shared");
    const second = await materializeAcademicPaperFromSourceItem(pool!, { spaceId: SPACE, sourceItemId: secondItemId });

    expect(second).toMatchObject({ objectId: first!.objectId, created: false });
    const count = await pool!.query(`SELECT count(*)::int AS total FROM academic_papers WHERE doi = '10.1000/shared'`);
    expect(count.rows[0]!.total).toBe(1);
  });

  it("materializes OpenAlex and links a Semantic Scholar record with the same DOI to one paper", async () => {
    if (!available) return;
    const openAlexItem = await seedProviderItem({ academic_provider: "openalex", openalex_id: "W123", doi: "10.1000/cross-provider", authors: ["Ada"], published_at: "2026-01-01", venue: "Journal", paper_type: "article", cited_by_count: 7, reference_count: 11, source_url: "https://openalex.org/W123" }, "Cross-provider paper");
    const first = await materializeAcademicPaperFromSourceItem(pool!, { spaceId: SPACE, sourceItemId: openAlexItem });
    const semanticItem = await seedProviderItem({ academic_provider: "semantic_scholar", semantic_scholar_id: "s2-123", doi: "10.1000/cross-provider", authors: ["Ada"], published_at: "2026-01-01", source_url: "https://semanticscholar.org/paper/s2-123" }, "Cross-provider paper");
    const second = await materializeAcademicPaperFromSourceItem(pool!, { spaceId: SPACE, sourceItemId: semanticItem });
    expect(second).toEqual({ objectId: first!.objectId, created: false });
    const row = await pool!.query(`SELECT openalex_id,semantic_scholar_id,cited_by_count,reference_count FROM academic_papers WHERE object_id=$1`, [first!.objectId]);
    expect(row.rows[0]).toMatchObject({ openalex_id: "W123", semantic_scholar_id: "s2-123", cited_by_count: 7, reference_count: 11 });
    expect((await pool!.query(`SELECT count(*)::int AS total FROM academic_papers WHERE doi='10.1000/cross-provider'`)).rows[0].total).toBe(1);
  });

  it("returns null for a non-arXiv source item", async () => {
    if (!available) return;
    const itemId = randomUUID();
    const now = new Date().toISOString();
    await pool!.query(
      `INSERT INTO source_items (
         id, space_id, owner_user_id, visibility, connection_id, item_type, title, first_seen_at, last_seen_at,
         content_state, retention_policy, created_at, updated_at
       ) VALUES ($1,$2,$3,'space_shared',$4,'external_url','A web page',$5,$5,'excerpt_saved','summary_only',$5,$5)`,
      [itemId, SPACE, OWNER, CONNECTION, now],
    );
    const result = await materializeAcademicPaperFromSourceItem(pool!, { spaceId: SPACE, sourceItemId: itemId });
    expect(result).toBeNull();
  });
});
