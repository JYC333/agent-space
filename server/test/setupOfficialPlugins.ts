import { execFileSync } from "node:child_process";
import { existsSync, readdirSync } from "node:fs";
import { join } from "node:path";

export default function setupOfficialPlugins(): void {
  const serverRoot = join(__dirname, "..");
  const repoRoot = join(serverRoot, "..");
  const officialPluginsRoot = join(repoRoot, "plugins", "official");
  const pluginIds = existsSync(officialPluginsRoot)
    ? readdirSync(officialPluginsRoot, { withFileTypes: true })
        .filter((entry) => entry.isDirectory())
        .map((entry) => entry.name)
        .filter((id) => existsSync(join(officialPluginsRoot, id, "plugin.json")))
    : [];

  const missingRuntime = pluginIds.some((id) =>
    !existsSync(join(serverRoot, "dist", "official-plugins", id, "server", "index.js")),
  );
  if (!missingRuntime) return;

  execFileSync(process.execPath, ["scripts/build-official-plugins.mjs"], {
    cwd: serverRoot,
    stdio: "inherit",
  });
}
