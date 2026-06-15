import type { ControlPlaneModule } from "../../gateway/routeRegistry";
import { registerRoutes } from "./routes";

export const agentsModule: ControlPlaneModule = {
  name: "agents",
  registerRoutes,
};

export {
  __setAgentChatIdentityForTests,
  __setAgentChatServicesFactoryForTests,
} from "./routes";
