import { describe, it, expect } from "vitest";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

const srcDir = join(__dirname, "..", "src");

function tsFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) return tsFiles(full);
    return entry.name.endsWith(".ts") ? [full] : [];
  });
}

/**
 * Bare module specifiers the control plane is allowed to import. Relative imports
 * (`./`, `../`), `node:` builtins, and `@agent-space/protocol` are allowed.
 * Anything else (frontend, Python backend, ORM packages, migration tooling,
 * sandbox/deployer internals, local-host) must not appear.
 */
const ALLOWED_BARE = new Set(["fastify", "undici", "yaml", "@agent-space/protocol"]);

/**
 * Packages allowed only from specific files. `pg` is the providers/credentials
 * DB driver (a raw client, deliberately not an ORM) and must stay confined to
 * the single shared pool module so database access cannot spread
 * module-by-module without showing up here. `node-pty` is the CLI login PTY
 * host and must stay confined to the login engine.
 */
const ALLOWED_BARE_BY_FILE = new Map<string, string>([
  ["pg", join("src", "db", "pool.ts")],
  ["node-pty", join("src", "modules", "providers", "cliLoginEngine.ts")],
]);

/** Substrings that must never appear in any import specifier. */
const FORBIDDEN_SUBSTRINGS = [
  "../backend", // Python backend tree
  "../../backend",
  "../apps/web", // frontend app
  "../../apps/web",
  "../sandbox", // first-level sandbox subsystem internals
  "../../sandbox",
  "../deployer", // first-level deployer subsystem internals
  "../../deployer",
  "../ops", // compose/env/script tree
  "../../ops",
  "backend/app",
  "apps/web/src",
  "sandbox/",
  "deployer/",
  "ops/compose",
  "local-host",
  "src-tauri",
  "alembic",
  "migrations",
  "sqlalchemy",
  "psycopg",
  "drizzle",
  "knex",
  "typeorm",
];

const importRe = /\b(?:from|import)\s+["']([^"']+)["']/g;

describe("control-plane import boundaries", () => {
  it("imports only approved runtime packages, node: builtins and relative modules", () => {
    const offenders: string[] = [];
    for (const file of tsFiles(srcDir)) {
      const text = readFileSync(file, "utf8");
      for (const match of text.matchAll(importRe)) {
        const spec = match[1];
        for (const bad of FORBIDDEN_SUBSTRINGS) {
          if (spec.includes(bad)) offenders.push(`${file}: ${spec} (forbidden: ${bad})`);
        }
        if (spec.startsWith(".")) continue;
        if (spec.startsWith("node:")) continue;
        const pkg = spec.startsWith("@")
          ? spec.split("/").slice(0, 2).join("/")
          : spec.split("/")[0];
        const scopedAllowance = ALLOWED_BARE_BY_FILE.get(pkg);
        if (scopedAllowance) {
          if (!file.endsWith(scopedAllowance)) {
            offenders.push(`${file}: ${spec} (allowed only from ${scopedAllowance})`);
          }
          continue;
        }
        if (!ALLOWED_BARE.has(pkg)) offenders.push(`${file}: ${spec}`);
      }
    }
    expect(offenders, `unexpected imports:\n${offenders.join("\n")}`).toEqual([]);
  });

  it("does not reference backend/web/migration/subsystem internals anywhere in src", () => {
    const offenders: string[] = [];
    for (const file of tsFiles(srcDir)) {
      const text = readFileSync(file, "utf8");
      for (const bad of [
        "../backend",
        "../../backend",
        "backend/app",
        "../apps/web",
        "../../apps/web",
        "apps/web/src",
        "../sandbox",
        "../../sandbox",
        "sandbox/",
        "../deployer",
        "../../deployer",
        "deployer/",
        "alembic.ini",
        "migrations/",
        "local-host",
      ]) {
        if (text.includes(bad)) offenders.push(`${file}: contains "${bad}"`);
      }
    }
    expect(offenders).toEqual([]);
  });
});
