import type { ServerModule } from "../../gateway/routeRegistry";
import { registerRoutes } from "./routes";

export const runtimeToolBindingsModule: ServerModule = {
  name: "runtime_tool_bindings",
  registerRoutes,
};
