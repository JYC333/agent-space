/**
 * Single owner of the `pg` driver for control-plane database access.
 *
 * Python/alembic remains the exclusive schema owner. The role behind
 * `CONTROL_PLANE_DATABASE_URL` decides which context-scoped table permissions
 * are available to this service.
 */

import { Pool } from "pg";

const pools = new Map<string, Pool>();

export type { Pool, PoolClient } from "pg";

export function getDbPool(databaseUrl: string): Pool {
  let pool = pools.get(databaseUrl);
  if (!pool) {
    pool = new Pool({
      connectionString: databaseUrl,
      max: 4,
      // Surface connectivity problems as request-time errors, not hangs.
      connectionTimeoutMillis: 5_000,
    });
    // A dropped idle connection must not crash the process.
    pool.on("error", () => {});
    pools.set(databaseUrl, pool);
  }
  return pool;
}
