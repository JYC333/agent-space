import type { ServerModule } from "../../gateway/routeRegistry";
import { registerRoutes } from "./routes";

export const agentsModule: ServerModule = {
  name: "agents",
  registerRoutes,
};

export {
  __setAgentChatIdentityForTests,
  __setAgentChatServicesFactoryForTests,
} from "./routes";
export { PgAgentRepository } from "./repository";
