// Verifies that the committed Drizzle snapshot matches src/db/schema without
// writing to server/drizzle/ or server/migrations/.
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const serverRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const tmpRoot = mkdtempSync(join(tmpdir(), "agent-space-drizzle-check-"));

function readJson(path) {
  return JSON.parse(readFileSync(path, "utf8"));
}

function normalizeSnapshot(snapshot) {
  const normalized = structuredClone(snapshot);
  delete normalized.id;
  delete normalized.prevId;
  return normalized;
}

try {
  const bin = process.platform === "win32"
    ? join(serverRoot, "node_modules", ".bin", "drizzle-kit.cmd")
    : join(serverRoot, "node_modules", ".bin", "drizzle-kit");
  const result = spawnSync(bin, [
    "generate",
    "--dialect=postgresql",
    "--schema=./src/db/schema/index.ts",
    `--out=${tmpRoot}`,
  ], {
    cwd: serverRoot,
    encoding: "utf8",
    env: { ...process.env, COREPACK_ENABLE_AUTO_PIN: "0" },
  });

  if (result.status !== 0) {
    if (result.stdout) process.stdout.write(result.stdout);
    if (result.stderr) process.stderr.write(result.stderr);
    process.exit(result.status ?? 1);
  }

  // A from-scratch generate against an empty --out (no prior journal) always
  // synthesizes the current full schema as a single "0000_snapshot.json",
  // regardless of how many incremental migrations the real drizzle/ dir has
  // accumulated. The correct comparison target on the committed side is
  // therefore the latest journal entry's snapshot (the cumulative current
  // state), not a hardcoded "0000" — which only happened to be correct
  // before any incremental migration existed beyond the neutralized
  // bootstrap.
  const journal = readJson(join(serverRoot, "drizzle", "meta", "_journal.json"));
  const latestIdx = journal.entries.reduce((max, entry) => Math.max(max, entry.idx), 0);
  const latestSnapshotFile = `${String(latestIdx).padStart(4, "0")}_snapshot.json`;

  const expected = normalizeSnapshot(readJson(join(tmpRoot, "meta", "0000_snapshot.json")));
  const committed = normalizeSnapshot(readJson(join(serverRoot, "drizzle", "meta", latestSnapshotFile)));
  if (JSON.stringify(expected) !== JSON.stringify(committed)) {
    console.error("Drizzle schema snapshot is out of sync with server/src/db/schema/.");
    console.error("Run `cd server && npm run schema:generate`, review the generated SQL, and commit the result.");
    console.error("Do not hand-edit server/migrations/*.sql for schema changes.");
    process.exit(1);
  }

  console.log("drizzle-schema-check: committed snapshot matches server/src/db/schema/");
} finally {
  rmSync(tmpRoot, { recursive: true, force: true });
}
