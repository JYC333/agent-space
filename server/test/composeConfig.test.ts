import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const repoRoot = join(__dirname, "..", "..");

function serverServiceBlock(mode: "dev" | "test" | "prod"): string {
  const text = readFileSync(
    join(repoRoot, "ops", "compose", `docker-compose.${mode}.yml`),
    "utf8",
  );
  const start = text.indexOf("\n  server:");
  expect(start).toBeGreaterThanOrEqual(0);
  const nextService = text.indexOf("\n  frontend:", start + 1);
  return text.slice(start, nextService === -1 ? undefined : nextService);
}

function composeText(mode: "dev" | "test" | "prod"): string {
  return readFileSync(
    join(repoRoot, "ops", "compose", `docker-compose.${mode}.yml`),
    "utf8",
  );
}

describe("compose server config", () => {
  it("passes only the OAuth/session env needed by native server auth", () => {
    for (const mode of ["dev", "test", "prod"] as const) {
      const block = serverServiceBlock(mode);
      expect(block).not.toContain("env_file:");
      for (const key of [
        "GOOGLE_CLIENT_ID",
        "GOOGLE_CLIENT_SECRET",
        "GOOGLE_REDIRECT_URI",
        "FRONTEND_URL",
        "SESSION_EXPIRE_DAYS",
        "SERVER_DEBUG",
      ]) {
        expect(block).toContain(`- ${key}=`);
      }
      expect(block).toContain("RUNTIME_TOOLS_ROOT=");
      expect(block).not.toContain("8010:8010");
      expect(block).not.toContain("8110:8010");
    }
  });

  it("uses the server compose service as the backend dependency", () => {
    for (const mode of ["dev", "test", "prod"] as const) {
      const text = composeText(mode);
      expect(text).toContain("\n  server:");
      expect(text).toContain("container_name: agent-space-" + mode + "-server");
    }
  });

  it("bind-mounts live server migrations for dev and test one-shot migration runs", () => {
    for (const mode of ["dev", "test"] as const) {
      const block = serverServiceBlock(mode);
      expect(block).toContain(
        "../../server/migrations:/app/server/migrations:ro",
      );
    }
    expect(serverServiceBlock("prod")).not.toContain(
      "../../server/migrations:/app/server/migrations:ro",
    );
    expect(readFileSync(join(repoRoot, "server", "Dockerfile"), "utf8")).toContain(
      "COPY server/migrations ./migrations",
    );
  });
});
