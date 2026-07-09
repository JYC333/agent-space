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
    expect(migrate.lastIndexOf("run_drizzle_schema_check_docker")).toBeLessThan(
      migrate.lastIndexOf("ensure_docker_database_exists"),
    );
    expect(migrate).toContain("ensure_docker_database_exists");
    expect(migrate).toContain("run_drizzle_schema_check_host");

    expect(reset).not.toContain('CREATE DATABASE "$PGDB";');
    expect(reset).toContain('"$REPO_ROOT/ops/scripts/db/migrate.sh" --mode "$MODE"');

    expect(start).toContain("generate_schema_migrations()");
    expect(start).toContain("npm run schema:generate");
    expect(start.lastIndexOf("generate_schema_migrations")).toBeLessThan(
      start.lastIndexOf("ensure_server_image_for_migrations"),
    );
    expect(start).toContain("run_database_migrations()");
    expect(start).toContain('"$REPO_ROOT/ops/scripts/db/migrate.sh" --mode "$MODE"');
    expect(start).toContain("ensure_server_image_for_migrations");
  });

  it("waits for stable postgres SQL readiness during compose bootstrap", () => {
    const localCompose = readRepoFile("ops/scripts/lib/local-compose.sh");

    expect(localCompose).toContain("required_successes=3");
    expect(localCompose).toContain('psql -X -q -U "$pguser" -d "$db"');
    expect(localCompose).toContain("-tAc \"SELECT 1;\"");
    expect(localCompose).toContain("consecutive_successes=0");
  });
});
