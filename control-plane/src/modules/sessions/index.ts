import type { ControlPlaneModule } from "../../gateway/routeRegistry";
import { registerRoutes } from "./routes";

export const sessionsModule: ControlPlaneModule = {
  name: "sessions",
  registerRoutes,
};

export {
  __setSessionIdentityForTests,
  __setSessionServicesFactoryForTests,
} from "./routes";
