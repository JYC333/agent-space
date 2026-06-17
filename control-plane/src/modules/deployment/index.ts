import type { ControlPlaneModule } from "../../gateway/routeRegistry";
import { registerRoutes } from "./routes";

export const deploymentModule: ControlPlaneModule = {
  name: "deployment",
  registerRoutes,
};

export { ALLOWED_DEPLOYER_JOB_TYPES, DeployerSocketClient } from "./client";
