import type { ServerModule } from "../../gateway/routeRegistry";
import { registerRoutes } from "./routes";

export const projectPresetsModule: ServerModule = {
  name: "project_presets",
  registerRoutes,
};

export { __setProjectPresetsServiceFactoryForTests } from "./routes";
export { ProjectPresetsService } from "./service";
export { __setProjectPresetRegistryForTests, listBuiltInProjectPresets, getBuiltInProjectPreset } from "./registry";
export type { ProjectPresetDescriptor } from "./types";
