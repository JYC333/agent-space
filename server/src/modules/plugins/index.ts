import type { ServerModule } from "../../gateway/routeRegistry";
import { registerRoutes } from "./routes";
import { assertPluginRegistryIntegrity } from "./registry";

// Validate descriptor uniqueness at module load time. Throws if violated.
assertPluginRegistryIntegrity();

export const pluginsModule: ServerModule = {
  name: "plugins",
  registerRoutes,
};

// Facade exports for use by other server modules.
export { requireOfficialPluginEnabled } from "./guards";
export { getOfficialPlugin, listOfficialPlugins } from "./registry";
export { pluginService } from "./service";
export type { PluginGuardOptions } from "./guards";
