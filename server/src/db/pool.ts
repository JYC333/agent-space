/**
 * Single owner of the `pg` driver for server database access.
 *
 * In bundled compose modes, `SERVER_DATABASE_URL` points at the
 * Postgres owner/app role generated from POSTGRES_* because server is
 * the sole backend.
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
