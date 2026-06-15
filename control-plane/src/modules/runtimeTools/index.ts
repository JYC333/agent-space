import type { ControlPlaneModule } from "../../gateway/routeRegistry";
import { registerRoutes } from "./routes";

export const runtimeToolsModule: ControlPlaneModule = {
  name: "runtimeTools",
  registerRoutes,
};

export {
  RUNTIME_TOOL_DEFINITIONS,
  RuntimeToolError,
  RuntimeToolRegistry,
  type ResolvedRuntimeTool,
  type RuntimeToolDefinition,
  type RuntimeToolInstallInput,
  type RuntimeToolInstallRunner,
  type RuntimeToolInstallResult,
  type RuntimeToolManifest,
  type RuntimeToolResolverPort,
  type RuntimeToolStatus,
} from "./service";
