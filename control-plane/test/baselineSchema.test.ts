import { join } from "node:path";
import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { Pool } from "pg";
import {
  PostgreSqlContainer,
  type StartedPostgreSqlContainer,
} from "@testcontainers/postgresql";
import { migrate } from "../src/db/migrator";

// Empty-DB migration test. Applies the committed, frozen baseline
// (control-plane/migrations/*.sql) to a fresh Postgres via the TS migration
// runner and asserts it applies cleanly, completely, and idempotently.
//
// The schema is frozen for the re-platform, so this does NOT diff against an
// Alembic-derived fingerprint — it verifies the runner reproduces the full
// canonical table set from the baseline. Skips gracefully without Docker.

const MIGRATIONS_DIR = join(process.cwd(), "migrations");
const RUNNER_TABLE = "control_plane_schema_migrations";

// The canonical schema has 92 base tables (91 application tables + alembic_version).
const EXPECTED_BASELINE_TABLE_COUNT = 92;
// A representative spread across domains; a missing one means an incomplete apply.
const REPRESENTATIVE_TABLES = [
  "spaces",
  "users",
  "memory_entries",
  "runs",
  "proposals",
  "knowledge_items",
  "model_providers",
  "policy_decision_records",
  "alembic_version",
];

let container: StartedPostgreSqlContainer | undefined;
let pool: Pool | undefined;
let available = false;

beforeAll(async () => {
  try {
    container = await new PostgreSqlContainer("postgres:18").start();
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

describe("TS runner applies the frozen baseline schema", () => {
  it("applies the baseline and creates the full canonical table set", async () => {
    if (!available || !pool) return;

    const result = await migrate(pool, MIGRATIONS_DIR);
    expect(result.applied).toContain("0001");

    const recorded = await pool.query(
      `SELECT version FROM public.${RUNNER_TABLE} WHERE version = '0001'`,
    );
    expect(recorded.rowCount).toBe(1);

    const tables = await baselineTableNames(pool);
    expect(tables).toHaveLength(EXPECTED_BASELINE_TABLE_COUNT);
    for (const t of REPRESENTATIVE_TABLES) {
      expect(tables).toContain(t);
    }
  });

  it("is idempotent on an already-migrated database", async () => {
    if (!available || !pool) return;
    const first = await migrate(pool, MIGRATIONS_DIR);
    expect(first.applied).toContain("0001");

    const result = await migrate(pool, MIGRATIONS_DIR);
    expect(result.applied).toEqual([]);
    // Still exactly the canonical set — no duplicate/extra application.
    expect(await baselineTableNames(pool)).toHaveLength(EXPECTED_BASELINE_TABLE_COUNT);
  });
});
