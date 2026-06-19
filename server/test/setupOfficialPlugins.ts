import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { join } from "node:path";

export default function setupOfficialPlugins(): void {
  const serverRoot = join(__dirname, "..");
  const dairyRuntime = join(
    serverRoot,
    "dist",
    "official-plugins",
    "dairy",
    "server",
    "index.js",
  );
  if (existsSync(dairyRuntime)) return;

  execFileSync(process.execPath, ["scripts/build-official-plugins.mjs"], {
    cwd: serverRoot,
    stdio: "inherit",
  });
}
