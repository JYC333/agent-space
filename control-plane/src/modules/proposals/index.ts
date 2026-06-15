import type { ControlPlaneModule } from "../../gateway/routeRegistry";
import { registerRoutes } from "./routes";

export const proposalsModule: ControlPlaneModule = {
  name: "proposals",
  registerRoutes,
};

export {
  __setProposalIdentityForTests,
  __setProposalServicesFactoryForTests,
} from "./routes";
