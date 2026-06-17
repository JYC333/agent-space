import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const repoRoot = join(__dirname, "..", "..");

function controlPlaneServiceBlock(mode: "dev" | "test" | "prod"): string {
  const text = readFileSync(
    join(repoRoot, "ops", "compose", `docker-compose.${mode}.yml`),
    "utf8",
  );
  const start = text.indexOf("\n  control-plane:");
  expect(start).toBeGreaterThanOrEqual(0);
  const nextService = text.indexOf("\n  frontend:", start + 1);
  return text.slice(start, nextService === -1 ? undefined : nextService);
}

describe("compose control-plane config", () => {
  it("passes only the OAuth/session env needed by native TS auth", () => {
    for (const mode of ["dev", "test", "prod"] as const) {
      const block = controlPlaneServiceBlock(mode);
      expect(block).not.toContain("env_file:");
      for (const key of [
        "GOOGLE_CLIENT_ID",
        "GOOGLE_CLIENT_SECRET",
        "GOOGLE_REDIRECT_URI",
        "FRONTEND_URL",
        "SESSION_EXPIRE_DAYS",
        "DEBUG",
      ]) {
        expect(block).toContain(`- ${key}=`);
      }
      for (const removed of [
        "CONTROL_PLANE_PROVIDERS_AUTHORITY",
        "CONTROL_PLANE_PROVIDERS_CREDENTIALS_AUTHORITY",
        "CONTROL_PLANE_POLICY_AUTHORITY",
        "CONTROL_PLANE_SESSIONS_AUTHORITY",
        "CONTROL_PLANE_PROVIDERS_SHADOW",
      ]) {
        expect(block).not.toContain(removed);
      }
    }
  });
});
