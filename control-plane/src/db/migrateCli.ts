/**
 * CLI entry for the TS migration runner: `node dist/db/migrateCli.js [up|status]`.
 *
 * Re-platform foundation — this is a parity/ops tool, NOT wired into server startup.
 * Python/Alembic still runs the schema in prod; cutting the control plane over to
 * run migrations on boot is a later phase. Run from `control-plane/` so the
 * default migrations directory resolves, or set `CONTROL_PLANE_MIGRATIONS_DIR`.
 */

import { resolve } from "node:path";
import { loadConfig } from "../config";
import { getDbPool } from "./pool";
import { migrate, status } from "./migrator";

function migrationsDir(): string {
  const override = process.env.CONTROL_PLANE_MIGRATIONS_DIR?.trim();
  if (override) return resolve(override);
  // dist/db/migrateCli.js -> control-plane/migrations
  return resolve(__dirname, "..", "..", "migrations");
}

async function main(): Promise<void> {
  const command = (process.argv[2] ?? "up").toLowerCase();
  const config = loadConfig();
  if (!config.databaseUrl) {
    console.error("CONTROL_PLANE_DATABASE_URL is required to run migrations");
    process.exitCode = 2;
    return;
  }
  const pool = getDbPool(config.databaseUrl);
  const dir = migrationsDir();
  try {
    if (command === "status") {
      const rows = await status(pool, dir);
      for (const r of rows) {
        console.log(`${r.applied ? "[x]" : "[ ]"} ${r.version}_${r.name}`);
      }
      return;
    }
    if (command === "up") {
      const result = await migrate(pool, dir, { log: (m) => console.log(m) });
      console.log(
        result.applied.length === 0
          ? "schema is up to date (no migrations applied)"
          : `applied ${result.applied.length} migration(s): ${result.applied.join(", ")}`,
      );
      return;
    }
    console.error(`unknown command: ${command} (expected "up" or "status")`);
    process.exitCode = 2;
  } finally {
    await pool.end();
  }
}

main().catch((err) => {
  console.error(err instanceof Error ? err.message : String(err));
  process.exitCode = 1;
});
