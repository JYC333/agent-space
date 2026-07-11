import { createHash } from "node:crypto";
import { Pool } from "pg";
import { inject } from "vitest";

export interface SharedPostgresContext {
  available: boolean;
  adminUri?: string;
  templateDatabase?: string;
  runId?: string;
  error?: string;
}

declare module "vitest" {
  export interface ProvidedContext {
    sharedPostgres: SharedPostgresContext;
  }
}

export interface TestPostgresDatabase {
  getConnectionUri(): string;
  stop(): Promise<void>;
}

function databaseUri(adminUri: string, database: string): string {
  const uri = new URL(adminUri);
  uri.pathname = `/${database}`;
  return uri.toString();
}

function quoteIdentifier(identifier: string): string {
  return `"${identifier.replaceAll('"', '""')}"`;
}

export async function getTestPostgres(
  fileUrl: string,
  options: { empty?: boolean } = {},
): Promise<TestPostgresDatabase> {
  const context = inject("sharedPostgres");
  if (
    !context.available ||
    !context.adminUri ||
    !context.templateDatabase ||
    !context.runId
  ) {
    throw new Error(context.error ?? "Shared Postgres test container is unavailable");
  }

  const fileHash = createHash("sha256").update(fileUrl).digest("hex").slice(0, 12);
  const database = `aspace_test_${context.runId}_${fileHash}`;
  const template = options.empty ? "template0" : context.templateDatabase;
  const admin = new Pool({ connectionString: context.adminUri, max: 1 });

  try {
    await admin.query(
      `CREATE DATABASE ${quoteIdentifier(database)} TEMPLATE ${quoteIdentifier(template)}`,
    );
  } finally {
    await admin.end();
  }

  let stopped = false;
  return {
    getConnectionUri: () => databaseUri(context.adminUri!, database),
    stop: async () => {
      if (stopped) return;
      stopped = true;
      const cleanup = new Pool({ connectionString: context.adminUri, max: 1 });
      try {
        await cleanup.query(
          `SELECT pg_terminate_backend(pid)
             FROM pg_stat_activity
            WHERE datname = $1 AND pid <> pg_backend_pid()`,
          [database],
        );
        await cleanup.query(`DROP DATABASE IF EXISTS ${quoteIdentifier(database)}`);
      } finally {
        await cleanup.end();
      }
    },
  };
}
