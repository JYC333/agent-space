import type { ServerModule } from "../../gateway/routeRegistry";
import { registerRoutes } from "./routes";

export const proposalsModule: ServerModule = {
  name: "proposals",
  registerRoutes,
};

export {
  __setProposalIdentityForTests,
  __setProposalServicesFactoryForTests,
} from "./routes";
