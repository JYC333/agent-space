// Bridges drizzle-kit's generator output (server/drizzle/) to the applied
// migrations directory (server/migrations/) that src/db/migrator.ts reads.
//
// drizzle-kit's own numbering (index or timestamp prefixes inside
// server/drizzle/) is never applied directly — its counter starts at 0000
// and would collide with 0001_baseline's version prefix in the migrator's
// tracking table. Instead, every drizzle-generated migration (every
// meta/_journal.json entry after the neutralized bootstrap at idx 0) must
// have exactly one copy in server/migrations/ under the next free
// sequential 4-digit prefix. This script is that bridge:
//
//   node scripts/db/schema-sync.mjs copy   -- copy any uncopied entries
//   node scripts/db/schema-sync.mjs check  -- fail if any entry is uncopied
//
// Correspondence between a drizzle/*.sql file and its server/migrations/
// copy is content-based (comment lines stripped, SQL body compared), not
// name-based, since a copied file may carry an explanatory header the raw
// generated file doesn't have.
import { readFileSync, readdirSync, writeFileSync, existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const serverRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const drizzleDir = join(serverRoot, "drizzle");
const migrationsDir = join(serverRoot, "migrations");
const migrationFileRe = /^(\d+)_.+\.sql$/;

function sqlBody(text) {
  return text
    .replaceAll("--> statement-breakpoint", "")
    .split("\n")
    .map((line) => {
      // Strip line comments. Good enough for generated/authored DDL in this
      // repo, which doesn't put "--" inside string literals.
      const idx = line.indexOf("--");
      return idx === -1 ? line : line.slice(0, idx);
    })
    .join(" ")
    .replace(/\s+/g, " ")
    .trim();
}

function journalEntries() {
  const journalPath = join(drizzleDir, "meta", "_journal.json");
  const journal = JSON.parse(readFileSync(journalPath, "utf8"));
  // idx 0 is the neutralized bootstrap (schema already provisioned by
  // 0001_baseline.sql) and is never copied.
  return journal.entries.filter((e) => e.idx > 0);
}

function migrationFiles() {
  const seenVersions = new Map();
  return readdirSync(migrationsDir)
    .filter((f) => migrationFileRe.test(f))
    .sort()
    .map((f) => {
      const version = migrationFileRe.exec(f)[1];
      const previous = seenVersions.get(version);
      if (previous) {
        throw new Error(
          `duplicate migration version ${version}: ${previous} and ${f}. ` +
            "Migration version prefixes must be unique.",
        );
      }
      seenVersions.set(version, f);
      return {
        file: f,
        version,
        body: sqlBody(readFileSync(join(migrationsDir, f), "utf8")),
      };
    });
}

function nextPrefix(existing) {
  const max = existing.reduce((acc, f) => {
    return Math.max(acc, parseInt(f.version, 10));
  }, 0);
  return String(max + 1).padStart(4, "0");
}

function findUncopied() {
  const existing = migrationFiles();
  const uncopied = [];
  for (const entry of journalEntries()) {
    const sourcePath = join(drizzleDir, `${entry.tag}.sql`);
    const sourceBody = sqlBody(readFileSync(sourcePath, "utf8"));
    const matches = existing.filter((f) => f.body === sourceBody);
    if (matches.length === 0) uncopied.push({ entry, sourcePath, sourceBody });
    if (matches.length > 1) {
      throw new Error(
        `drizzle migration '${entry.tag}' matches ${matches.length} files in server/migrations/ ` +
          `(${matches.map((m) => m.file).join(", ")}) — expected exactly one copy`,
      );
    }
  }
  return { uncopied, existing };
}

function copy() {
  const { uncopied, existing } = findUncopied();
  if (uncopied.length === 0) {
    console.log("schema-sync: server/migrations/ already has every drizzle-generated migration");
    return;
  }
  let known = existing;
  for (const { entry, sourcePath } of uncopied) {
    const prefix = nextPrefix(known);
    // drizzle-kit's own tag already carries its internal index prefix
    // (e.g. "0002_absurd_blonde_phantom") — strip it so our sequential
    // prefix isn't doubled up in the copied filename.
    const slug = entry.tag.replace(/^\d+_/, "");
    const targetName = `${prefix}_${slug}.sql`;
    const targetPath = join(migrationsDir, targetName);
    if (existsSync(targetPath)) {
      throw new Error(`refusing to overwrite existing migration file ${targetName}`);
    }
    const content = readFileSync(sourcePath, "utf8");
    writeFileSync(targetPath, content);
    known = [...known, { file: targetName, body: sqlBody(content) }];
    console.log(`schema-sync: copied ${entry.tag}.sql -> migrations/${targetName}`);
  }
}

function check() {
  const { uncopied } = findUncopied();
  if (uncopied.length > 0) {
    console.error("schema-sync: uncopied drizzle-generated migration(s):");
    for (const { entry } of uncopied) console.error(`  - ${entry.tag}`);
    console.error("Run `npm run schema:generate` to copy them into server/migrations/.");
    process.exitCode = 1;
    return;
  }
  console.log("schema-sync: server/migrations/ is in sync with drizzle/meta/_journal.json");
}

const mode = process.argv[2];
if (mode === "copy") copy();
else if (mode === "check") check();
else {
  console.error("usage: node scripts/db/schema-sync.mjs <copy|check>");
  process.exitCode = 2;
}
