import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const repoRoot = join(__dirname, "..", "..");

function readRepoFile(path: string) {
  return readFileSync(join(repoRoot, path), "utf8");
}

describe("database migration ops scripts", () => {
  it("lets docker-native migrate initialize a missing target database", () => {
    const migrate = readRepoFile("ops/scripts/db/migrate.sh");
    const reset = readRepoFile("ops/scripts/db/reset-postgres.sh");
    const start = readRepoFile("ops/scripts/start.sh");

    expect(migrate).toContain("ensure_docker_database_exists()");
    expect(migrate).toContain("SELECT 1 FROM pg_database WHERE datname = '$pgdb';");
    expect(migrate).toContain('CREATE DATABASE \\"$pgdb\\";');
    expect(migrate).toContain('if [[ "$RUN_MODE" == "docker" ]]; then');
    expect(migrate).toContain("ensure_docker_database_exists");

    expect(reset).not.toContain('CREATE DATABASE "$PGDB";');
    expect(reset).toContain('"$REPO_ROOT/ops/scripts/db/migrate.sh" --mode "$MODE"');

    expect(start).toContain("run_database_migrations()");
    expect(start).toContain('"$REPO_ROOT/ops/scripts/db/migrate.sh" --mode "$MODE"');
    expect(start).toContain("ensure_server_image_for_migrations");
  });
});
