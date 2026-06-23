import { join } from "node:path";
import { readFileSync, readdirSync } from "node:fs";
import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { Pool } from "pg";
import {
  PostgreSqlContainer,
  type StartedPostgreSqlContainer,
} from "@testcontainers/postgresql";
import { migrate } from "../src/db/migrator";

// Empty-DB migration test. Applies the committed consolidated baseline
// (server/migrations/*.sql) to a fresh Postgres via the server migration
// runner and asserts it applies cleanly and idempotently.
//
// Verifies the runner creates representative server-owned tables from the
// baseline. Skips gracefully without Docker.

const MIGRATIONS_DIR = join(process.cwd(), "migrations");
const RUNNER_TABLE = "server_schema_migrations";

// A representative spread across domains; a missing one means an incomplete apply.
const REPRESENTATIVE_TABLES = [
  "spaces",
  "space_objects",
  "users",
  "memory_entries",
  "runs",
  "proposals",
  "knowledge_items",
  "claims",
  "claim_sources",
  "claim_relations",
  "object_relations",
  "space_object_kinds",
  "space_object_kind_relation_hints",
  "retrieval_objects",
  "retrieval_aliases",
  "retrieval_chunks",
  "retrieval_edges",
  "retrieval_feedback_events",
  "model_providers",
  "policy_decision_records",
];

let container: StartedPostgreSqlContainer | undefined;
let pool: Pool | undefined;
let available = false;

beforeAll(async () => {
  try {
    container = await new PostgreSqlContainer("pgvector/pgvector:pg18").start();
    pool = new Pool({ connectionString: container.getConnectionUri(), max: 3 });
    available = true;
  } catch (err) {
    console.warn(
      `[baseline-schema] skipped — Docker/Postgres unavailable: ${
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
  await pool.query("DROP SCHEMA public CASCADE; CREATE SCHEMA public; RESET search_path;");
});

async function baselineTableNames(p: Pool): Promise<string[]> {
  const res = await p.query<{ table_name: string }>(
    `SELECT table_name FROM information_schema.tables
       WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
         AND table_name <> $1
       ORDER BY table_name`,
    [RUNNER_TABLE],
  );
  return res.rows.map((r) => r.table_name);
}

describe("server runner applies the baseline schema", () => {
  it("uses the single committed baseline migration", () => {
    const migrationFiles = readdirSync(MIGRATIONS_DIR)
      .filter((name) => /^\d+_.+\.sql$/.test(name))
      .sort();
    expect(migrationFiles).toEqual(["0001_baseline.sql"]);
  });

  it("does not recreate retired context source tables", () => {
    const baseline = readFileSync(join(MIGRATIONS_DIR, "0001_baseline.sql"), "utf8");
    expect(baseline).not.toContain("CREATE TABLE public.context_sources");
  });

  it("keeps space object statuses constrained by concrete object type", () => {
    const baseline = readFileSync(join(MIGRATIONS_DIR, "0001_baseline.sql"), "utf8");
    expect(baseline).toContain("ck_space_objects_status_by_type");
    expect(baseline).toContain("WHEN 'note'::text THEN");
    expect(baseline).toContain("WHEN 'source'::text THEN");
    expect(baseline).toContain("WHEN 'knowledge_item'::text THEN");
    expect(baseline).toContain("WHEN 'claim'::text THEN");
  });

  it("keeps ClaimFact and object relation tables FK-backed and retrievable", () => {
    const baseline = readFileSync(join(MIGRATIONS_DIR, "0001_baseline.sql"), "utf8");
    expect(baseline).toContain("CREATE TABLE public.claims");
    expect(baseline).toContain("CREATE TABLE public.claim_sources");
    expect(baseline).toContain("CREATE TABLE public.claim_relations");
    expect(baseline).toContain("CREATE TABLE public.object_relations");
    expect(baseline).toContain("ck_claim_sources_source_ref_connection");
    expect(baseline).toContain("FOREIGN KEY (object_id, space_id) REFERENCES public.space_objects(id, space_id)");
    expect(baseline).toContain("FOREIGN KEY (claim_id, space_id) REFERENCES public.claims(object_id, space_id)");
    expect(baseline).toContain("FOREIGN KEY (from_object_id, space_id) REFERENCES public.space_objects(id, space_id)");
    expect(baseline).toContain("'claim'::character varying, 'memory_entry'::character varying");
  });

  it("adds object kind registry without changing retrieval object types", () => {
    const baseline = readFileSync(join(MIGRATIONS_DIR, "0001_baseline.sql"), "utf8");
    expect(baseline).toContain("CREATE TABLE public.space_object_kinds");
    expect(baseline).toContain("CREATE TABLE public.space_object_kind_relation_hints");
    expect(baseline).toContain("ck_space_object_kinds_base_object_type");
    expect(baseline).toContain("ck_space_object_kind_relation_hints_relation_type");
    expect(baseline).toContain("'project_public_summary'::character varying");
    expect(baseline).toContain("ck_retrieval_objects_object_type");
    expect(baseline).toContain("'knowledge_item'::character varying, 'note'::character varying, 'source'::character varying, 'claim'::character varying, 'memory_entry'::character varying, 'project_public_summary'::character varying");
    expect(baseline).not.toContain("ALTER TABLE public.retrieval_objects");
  });

  it("keeps note collection trees and memberships space-scoped in the baseline", () => {
    const baseline = readFileSync(join(MIGRATIONS_DIR, "0001_baseline.sql"), "utf8");
    expect(baseline).toContain("CREATE TABLE public.note_collection_items");
    expect(baseline).toContain("space_id character varying(36) NOT NULL,\n    collection_id character varying(36) NOT NULL");
    expect(baseline).toContain("FOREIGN KEY (collection_id, space_id) REFERENCES public.note_collections(id, space_id)");
    expect(baseline).toContain("FOREIGN KEY (note_id, space_id) REFERENCES public.notes(object_id, space_id)");
    expect(baseline).toContain("FOREIGN KEY (parent_id, space_id) REFERENCES public.note_collections(id, space_id)");
  });

  it("applies the baseline and creates representative server-owned tables", async () => {
    if (!available || !pool) return;

    const result = await migrate(pool, MIGRATIONS_DIR);
    expect(result.all).toEqual(["0001"]);
    expect(result.applied).toContain("0001");

    const recorded = await pool.query(
      `SELECT version FROM public.${RUNNER_TABLE} WHERE version = '0001'`,
    );
    expect(recorded.rowCount).toBe(1);

    const tables = await baselineTableNames(pool);
    for (const t of REPRESENTATIVE_TABLES) {
      expect(tables).toContain(t);
    }
  });

  it("enforces object kind registry constraints in Postgres", async () => {
    if (!available || !pool) return;

    await migrate(pool, MIGRATIONS_DIR);
    await pool.query(
      `INSERT INTO users (id, display_name, status, created_at, updated_at)
       VALUES ('user-1', 'User', 'active', now(), now())`,
    );
    await pool.query(
      `INSERT INTO spaces (id, name, type, created_by_user_id, created_at, updated_at)
       VALUES
         ('space-1', 'Space 1', 'team', 'user-1', now(), now()),
         ('space-2', 'Space 2', 'team', 'user-1', now(), now())`,
    );
    await pool.query(
      `INSERT INTO proposals (
         id, space_id, proposal_type, status, risk_level, urgency, title,
         payload_json, created_by_user_id, created_at, updated_at
       ) VALUES
         ('proposal-1', 'space-1', 'object_kind_create', 'accepted', 'high', 'normal', 'Create kind', '{}'::jsonb, 'user-1', now(), now()),
         ('proposal-2', 'space-2', 'object_kind_create', 'accepted', 'high', 'normal', 'Create kind', '{}'::jsonb, 'user-1', now(), now())`,
    );

    await pool.query(
      `INSERT INTO space_object_kinds (
         id, space_id, key, label, base_object_type, status,
         created_by_user_id, created_from_proposal_id, updated_from_proposal_id,
         created_at, updated_at
       ) VALUES (
         'kind-1', 'space-1', 'question', 'Question', 'knowledge_item', 'active',
         'user-1', 'proposal-1', 'proposal-1', now(), now()
       )`,
    );

    await expect(pool.query(
      `INSERT INTO space_object_kinds (
         id, space_id, key, label, base_object_type, status, created_at, updated_at
       ) VALUES (
         'kind-dup', 'space-1', 'question', 'Duplicate', 'knowledge_item', 'active', now(), now()
       )`,
    )).rejects.toThrow();

    await pool.query(
      `INSERT INTO space_object_kinds (
         id, space_id, key, label, base_object_type, status,
         created_by_user_id, created_from_proposal_id, updated_from_proposal_id,
         created_at, updated_at
       ) VALUES (
         'kind-other-space', 'space-2', 'question', 'Question', 'knowledge_item', 'active',
         'user-1', 'proposal-2', 'proposal-2', now(), now()
       )`,
    );
    await pool.query(
      `INSERT INTO space_object_kinds (
         id, space_id, key, label, base_object_type, status,
         created_by_user_id, created_from_proposal_id, updated_from_proposal_id,
         created_at, updated_at
       ) VALUES (
         'kind-other-base', 'space-1', 'question', 'Question claim', 'claim', 'active',
         'user-1', 'proposal-1', 'proposal-1', now(), now()
       )`,
    );

    await expect(pool.query(
      `INSERT INTO space_object_kinds (
         id, space_id, key, label, base_object_type, status, created_at, updated_at
       ) VALUES (
         'kind-invalid-base', 'space-1', 'person', 'Person', 'person', 'active', now(), now()
       )`,
    )).rejects.toThrow();

    await expect(pool.query(
      `INSERT INTO space_object_kinds (
         id, space_id, key, label, base_object_type, status, created_from_proposal_id, created_at, updated_at
       ) VALUES (
         'kind-bad-fk', 'space-1', 'lesson', 'Bad FK', 'knowledge_item', 'active', 'missing-proposal', now(), now()
       )`,
    )).rejects.toThrow();

    await pool.query(
      `INSERT INTO space_object_kinds (
         id, space_id, key, label, base_object_type, status, created_at, updated_at
       ) VALUES (
         'kind-archived', 'space-1', 'email', 'Email', 'source', 'archived', now(), now()
       )`,
    );
    await expect(pool.query(
      `INSERT INTO space_object_kinds (
         id, space_id, key, label, base_object_type, status, created_at, updated_at
       ) VALUES (
         'kind-archived-reuse', 'space-1', 'email', 'Email replacement', 'source', 'active', now(), now()
       )`,
    )).rejects.toThrow();
  });

  it("is idempotent on an already-migrated database", async () => {
    if (!available || !pool) return;
    const first = await migrate(pool, MIGRATIONS_DIR);
    expect(first.applied).toContain("0001");

    const result = await migrate(pool, MIGRATIONS_DIR);
    expect(result.applied).toEqual([]);
    const tables = await baselineTableNames(pool);
    for (const t of REPRESENTATIVE_TABLES) {
      expect(tables).toContain(t);
    }
  });
});
