import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const repoRoot = join(__dirname, "..", "..");

function readRepoFile(path: string) {
  return readFileSync(join(repoRoot, path), "utf8");
}

describe("server database ownership cutover", () => {
  it("does not provision a separate per-table server database role", () => {
    const files = [
      "ops/scripts/lib/local-compose.sh",
      "ops/scripts/start.sh",
      "ops/scripts/db/migrate.sh",
      "ops/scripts/db/reset-postgres.sh",
      "ops/env/.env.dev.example",
      "ops/env/.env.test.example",
      "ops/env/.env.prod.example",
    ];

    const combined = files.map((path) => readRepoFile(path)).join("\n");
    const forbidden = [
      ["SERVER_DB", "_RW"].join(""),
      ["agent_space", "_cp"].join(""),
      ["local_compose_provision", "_server_db_role"].join(""),
      ["GRANT SELECT ON TABLE public.", "participation_records"].join(""),
      ["least", "-privilege"].join(""),
    ];

    for (const value of forbidden) {
      expect(combined).not.toContain(value);
    }
    expect(readRepoFile("ops/scripts/lib/local-compose.sh")).toContain(
      "local_compose_server_owner_database_url",
    );
    expect(readRepoFile("ops/scripts/lib/local-compose.sh")).toContain(
      "env -u DEBUG docker compose",
    );
  });
});
