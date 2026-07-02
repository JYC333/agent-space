import { describe, expect, it } from "vitest";
import { seedSpaceDefaults } from "../src/modules/spaces/spaceSeeds";
import type { PoolClient } from "../src/db/pool";

class SeedClient {
  readonly queries: Array<{ sql: string; params: readonly unknown[] }> = [];

  async query<Row = Record<string, unknown>>(sql: string, params: readonly unknown[] = []) {
    this.queries.push({ sql, params });
    if (sql.includes("SELECT count(*)::text AS count FROM note_collections")) {
      return { rows: [{ count: "1" }] as Row[], rowCount: 1 };
    }
    return { rows: [] as Row[], rowCount: 0 };
  }
}

describe("space default seeds", () => {
  it("uses the current memory_entries schema without retired scope_id", async () => {
    const client = new SeedClient();

    await seedSpaceDefaults(client as unknown as PoolClient, "space-1");

    const memoryInserts = client.queries.filter(call => call.sql.includes("INSERT INTO memory_entries"));
    expect(memoryInserts).toHaveLength(3);
    for (const insert of memoryInserts) {
      expect(insert.sql).toContain("scope_type");
      expect(insert.sql).not.toContain("scope_id");
      expect(insert.sql).toContain("'system', 'semantic'");
    }
  });
});
