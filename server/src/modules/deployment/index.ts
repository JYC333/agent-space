import type { ServerModule } from "../../gateway/routeRegistry";
import { registerRoutes } from "./routes";

export const deploymentModule: ServerModule = {
  name: "deployment",
  registerRoutes,
};

export { ALLOWED_DEPLOYER_JOB_TYPES, DeployerSocketClient } from "./client";
