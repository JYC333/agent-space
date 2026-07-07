import { randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { Pool } from "pg";
import { PostgreSqlContainer, type StartedPostgreSqlContainer } from "@testcontainers/postgresql";
import type { SourcePolicyEnvelope, SourceRecipeDefinition } from "@agent-space/protocol" with { "resolution-mode": "import" };
import { loadConfig, type ServerConfig } from "../src/config";
import { SourceRecipeDryRunService } from "../src/modules/intake/sourceRecipes/recipeDryRunService";
import { insertSourceRecipeVersion } from "../src/modules/intake/sourceRecipes/recipeVersionStore";
import { HttpError } from "../src/modules/routeUtils/common";
import { getDbPool } from "../src/db/pool";

// Real-Postgres integration tests for the Level 2 recipe dry-run: bounded,
// side-effect-free preview of a draft recipe version. Skips without Docker.

const SCHEMA = readFileSync(join(process.cwd(), "test/fixtures/intakeCustomSourceCreateFlowSchema.sql"), "utf8");

const SPACE_A = "space-a";
const IDENTITY = { spaceId: SPACE_A, userId: "user-1" };
const ORIGIN = "https://example.com";

let container: StartedPostgreSqlContainer | undefined;
let pool: Pool | undefined;
let config: ServerConfig | undefined;
let service: SourceRecipeDryRunService | undefined;
let available = false;

beforeAll(async () => {
  try {
    container = await new PostgreSqlContainer("pgvector/pgvector:pg18").start();
    pool = new Pool({ connectionString: container.getConnectionUri() });
    await pool.query(SCHEMA);
    available = true;
  } catch (err) {
    console.warn(
      `[intake-source-recipe-dry-run] skipped — Docker/Postgres unavailable: ${
        err instanceof Error ? err.message : String(err)
      }`,
    );
  }
}, 120_000);

afterAll(async () => {
  if (config?.databaseUrl) await getDbPool(config.databaseUrl).end().catch(() => undefined);
  await pool?.end();
  await container?.stop();
});

beforeEach(async () => {
  if (!available || !pool) return;
  await pool.query(
    `TRUNCATE jobs, retrieval_edges, retrieval_chunks, retrieval_aliases, retrieval_objects,
              policy_decision_records, proposal_approvals, proposals, runs, space_memberships,
              source_handler_runs, source_handler_versions, source_recipe_versions, source_connections,
              source_connectors, scheduler_tasks, settings, artifacts, extraction_jobs, intake_items,
              source_snapshots, extracted_evidence, credentials`,
  );
  await pool.query(
    `INSERT INTO source_connectors (
       id, connector_key, display_name, connector_type, ingestion_mode, status,
       capabilities_json, created_at, updated_at
     ) VALUES ('connector-custom-source', 'custom_source', 'Custom Source', 'external_url', 'pull', 'active', '{}'::jsonb, now(), now())`,
  );
  await pool.query(
    `INSERT INTO space_memberships (id, space_id, user_id, role, status, created_at, updated_at)
     VALUES ($1, $2, $3, 'owner', 'active', now(), now())`,
    [randomUUID(), IDENTITY.spaceId, IDENTITY.userId],
  );
  config = { ...loadConfig({}), databaseUrl: container!.getConnectionUri() };
  service = new SourceRecipeDryRunService(pool, config);
});

const RSS_FIXTURE = `<?xml version="1.0"?>
<rss version="2.0"><channel><title>Feed</title>
  <item><title>One</title><link>${ORIGIN}/one</link><guid>guid-1</guid><description>First body</description></item>
  <item><title>Two</title><link>${ORIGIN}/two</link><guid>guid-2</guid><description>Second body</description></item>
</channel></rss>`;

const FEED_RECIPE: SourceRecipeDefinition = {
  recipe_version: "source.recipe.v1",
  steps: [
    { type: "fetch_page", url: "$source.endpoint_url", bind: "feed" },
    { type: "parse_rss", input: "feed", bind: "items" },
  ],
  output: { items_var: "items" },
};

const ENVELOPE: SourcePolicyEnvelope = {
  allowed_network_origins: [ORIGIN],
  capture_policy: "extract_text",
  retention_policy: "full_text",
  credential_ref: null,
  log_redaction_enabled: true,
  limits: {
    timeout_ms: 5000,
    max_download_bytes: 1_000_000,
    max_output_bytes: 1_000_000,
    max_files: 5,
    max_items: 20,
    max_evidence_items: 20,
    log_max_bytes: 65536,
  },
};

async function seedRecipeConnection(handlerKind = "recipe"): Promise<string> {
  const connectionId = randomUUID();
  await pool!.query(
    `INSERT INTO source_connections (
       id, space_id, connector_id, owner_user_id, name, endpoint_url, status,
       fetch_frequency, capture_policy, trust_level, consent_json, policy_json,
       config_json, handler_kind, created_at, updated_at
     ) VALUES ($1, $2, 'connector-custom-source', $3, 'Feed Source', $4, 'paused',
       'manual', 'extract_text', 'normal', '{}'::jsonb, '{}'::jsonb,
       '{}'::jsonb, $5, now(), now())`,
    [connectionId, SPACE_A, IDENTITY.userId, `${ORIGIN}/feed.xml`, handlerKind],
  );
  return connectionId;
}

async function seedRecipeVersion(connectionId: string, recipe: SourceRecipeDefinition = FEED_RECIPE) {
  return insertSourceRecipeVersion(pool!, {
    spaceId: SPACE_A,
    connectionId,
    recipe,
    policyEnvelope: ENVELOPE,
    primitiveVersions: { fetch_page: 1, parse_rss: 1 },
    createdByUserId: IDENTITY.userId,
  });
}

describe("SourceRecipeDryRunService (real Postgres)", () => {
  it("dry-runs a draft recipe against fixture content without writing any Intake output", async () => {
    if (!available || !service) return;
    const connectionId = await seedRecipeConnection();
    const version = await seedRecipeVersion(connectionId);

    const result = await service.dryRunRecipeVersion(IDENTITY, connectionId, {
      recipe_version_id: version.id,
      fixture_content: RSS_FIXTURE,
    });

    expect(result.dry_run.status).toBe("succeeded");
    expect(result.dry_run.item_count).toBe(2);
    expect(result.dry_run.sample_items[0]).toMatchObject({ external_id: "guid-1", title: "One" });
    expect(result.dry_run.step_traces.map((trace) => trace.primitive)).toEqual(["fetch_page", "parse_rss"]);
    // Network, retention, and output limits are visible in the preview.
    expect(result.dry_run.policy_envelope.allowed_network_origins).toEqual([ORIGIN]);
    expect(result.dry_run.policy_envelope.retention_policy).toBe("full_text");
    expect(result.dry_run.policy_envelope.limits.max_output_bytes).toBe(1_000_000);
    expect(result.recipe_version.status).toBe("draft");

    const stored = await pool!.query<{ test_result_json: { status: string } }>(
      `SELECT test_result_json FROM source_recipe_versions WHERE id = $1`,
      [version.id],
    );
    expect(stored.rows[0]!.test_result_json.status).toBe("succeeded");

    for (const table of ["intake_items", "source_snapshots", "extracted_evidence", "artifacts", "extraction_jobs"]) {
      const rows = await pool!.query<{ n: number }>(`SELECT count(*)::int AS n FROM ${table}`);
      expect(rows.rows[0]!.n).toBe(0);
    }
  });

  it("is deterministic for the same fixture content", async () => {
    if (!available || !service) return;
    const connectionId = await seedRecipeConnection();
    const version = await seedRecipeVersion(connectionId);

    const first = await service.dryRunRecipeVersion(IDENTITY, connectionId, {
      recipe_version_id: version.id,
      fixture_content: RSS_FIXTURE,
    });
    const second = await service.dryRunRecipeVersion(IDENTITY, connectionId, {
      recipe_version_id: version.id,
      fixture_content: RSS_FIXTURE,
    });
    expect(second.dry_run.sample_items).toEqual(first.dry_run.sample_items);
    expect(second.dry_run.item_count).toBe(first.dry_run.item_count);
    expect(second.dry_run.step_traces.map((trace) => [trace.step_path, trace.status])).toEqual(
      first.dry_run.step_traces.map((trace) => [trace.step_path, trace.status]),
    );
  });

  it("marks the version test_failed and captures a failure fixture when the recipe fails", async () => {
    if (!available || !service) return;
    const connectionId = await seedRecipeConnection();
    const version = await seedRecipeVersion(connectionId, {
      recipe_version: "source.recipe.v1",
      steps: [{ type: "extract_list", input: "never_bound", selector: { css_class: "x" }, bind: "items" }],
      output: { items_var: "items" },
    });

    const result = await service.dryRunRecipeVersion(IDENTITY, connectionId, {
      recipe_version_id: version.id,
      fixture_content: RSS_FIXTURE,
    });
    expect(result.dry_run.status).toBe("failed");
    expect(result.recipe_version.status).toBe("test_failed");
    const fixture = (result.dry_run as { failure_fixture?: { content_sha256: string; content_excerpt: string } })
      .failure_fixture;
    expect(fixture?.content_sha256).toHaveLength(64);
    expect(fixture?.content_excerpt).toContain("<rss");
  });

  it("rejects a dry-run against a non-draft version and a non-recipe connection", async () => {
    if (!available || !service) return;
    const connectionId = await seedRecipeConnection();
    const version = await seedRecipeVersion(connectionId);
    await pool!.query(`UPDATE source_recipe_versions SET status = 'active' WHERE id = $1`, [version.id]);
    await expect(
      service.dryRunRecipeVersion(IDENTITY, connectionId, {
        recipe_version_id: version.id,
        fixture_content: RSS_FIXTURE,
      }),
    ).rejects.toMatchObject({ statusCode: 409 });

    const builtInId = await seedRecipeConnection("built_in");
    await expect(
      service.dryRunRecipeVersion(IDENTITY, builtInId, {
        recipe_version_id: version.id,
        fixture_content: RSS_FIXTURE,
      }),
    ).rejects.toBeInstanceOf(HttpError);
  });
});
