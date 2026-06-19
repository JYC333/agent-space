import { cpSync, existsSync, mkdirSync, readdirSync, readFileSync, rmSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { execFileSync, spawn } from "node:child_process";

const serverRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = resolve(serverRoot, "..");
const officialPluginsRoot = resolve(repoRoot, "plugins", "official");
const artifactRoot = resolve(serverRoot, "dist", "official-plugins");
const tscBin = process.platform === "win32"
  ? resolve(serverRoot, "node_modules", ".bin", "tsc.cmd")
  : resolve(serverRoot, "node_modules", ".bin", "tsc");
const watch = process.argv.includes("--watch");
const protocolTypes = resolve(repoRoot, "packages", "protocol", "dist", "index.d.ts");

if (!existsSync(officialPluginsRoot)) {
  process.exit(0);
}

if (!existsSync(protocolTypes)) {
  execFileSync(tscBin, [
    "-p",
    resolve(repoRoot, "packages", "protocol", "tsconfig.build.json"),
  ], { cwd: repoRoot, stdio: "inherit" });
}

const packages = readdirSync(officialPluginsRoot, { withFileTypes: true })
  .filter((entry) => entry.isDirectory())
  .map((entry) => resolve(officialPluginsRoot, entry.name))
  .filter((dir) => existsSync(resolve(dir, "plugin.json")))
  .sort();

if (!watch) {
  rmSync(artifactRoot, { recursive: true, force: true });
}
mkdirSync(artifactRoot, { recursive: true });

const children = [];
for (const packageRoot of packages) {
  const manifest = readManifest(packageRoot);
  copyPackageAssets(packageRoot, manifest);
  const tsconfig = resolve(packageRoot, "server", "tsconfig.json");
  if (!existsSync(tsconfig)) {
    throw new Error(`Missing server tsconfig for official plugin ${manifest.id}`);
  }

  if (watch) {
    children.push(spawn(tscBin, ["-p", tsconfig, "--watch", "--preserveWatchOutput"], {
      cwd: repoRoot,
      stdio: "inherit",
    }));
  } else {
    execFileSync(tscBin, ["-p", tsconfig], { cwd: repoRoot, stdio: "inherit" });
  }
}

if (watch && children.length > 0) {
  await new Promise((resolveExit, rejectExit) => {
    for (const child of children) {
      child.on("exit", (code) => {
        if (code === 0) resolveExit(undefined);
        else rejectExit(new Error(`official plugin watcher exited with code ${code}`));
      });
      child.on("error", rejectExit);
    }
  });
}

function readManifest(packageRoot) {
  const manifest = JSON.parse(readFileSync(resolve(packageRoot, "plugin.json"), "utf8"));
  if (!manifest || typeof manifest.id !== "string" || manifest.id.trim() === "") {
    throw new Error(`Invalid official plugin manifest at ${packageRoot}`);
  }
  if (!manifest.server || typeof manifest.server.main !== "string") {
    throw new Error(`Official plugin ${manifest.id} must declare server.main`);
  }
  if (manifest.web?.entry !== undefined && typeof manifest.web.entry !== "string") {
    throw new Error(`Official plugin ${manifest.id} web.entry must be a string`);
  }
  if (manifest.web?.entry && !existsSync(resolve(packageRoot, manifest.web.entry))) {
    throw new Error(`Official plugin ${manifest.id} web entry not found: ${manifest.web.entry}`);
  }
  return manifest;
}

function copyPackageAssets(packageRoot, manifest) {
  const target = resolve(artifactRoot, manifest.id);
  mkdirSync(target, { recursive: true });
  cpSync(resolve(packageRoot, "plugin.json"), resolve(target, "plugin.json"));

  const migrationsDir = resolve(packageRoot, manifest.migrations?.dir ?? "migrations");
  if (existsSync(migrationsDir)) {
    cpSync(migrationsDir, resolve(target, "migrations"), { recursive: true });
  }

  const webDir = resolve(packageRoot, "web");
  if (existsSync(webDir)) {
    cpSync(webDir, resolve(target, "web"), { recursive: true });
  }
}
