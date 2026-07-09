import type { AgentSpacePlugin } from "@agent-space/protocol" with { "resolution-mode": "import" };
import { defaultOfficialPluginArtifactRoot, loadOfficialPluginPackages } from "./packageLoader";
import { listOfficialPlugins } from "./registry";

/**
 * Runtime official plugins bundled with this server build.
 *
 * Source lives under `plugins/official/*`, but the server loads the compiled
 * package artifacts from `dist/official-plugins/*` at startup. This keeps the
 * Level 1 monorepo development flow while matching the Level 2 startup-scan
 * shape for downloaded official plugins.
 */
export const BUILT_IN_PLUGINS: readonly AgentSpacePlugin[] = loadOfficialPluginPackages(
  defaultOfficialPluginArtifactRoot(),
  { allowedPluginIds: listOfficialPlugins().map((descriptor) => descriptor.id) },
);
