import type { ServerModule } from "../../gateway/routeRegistry";
import { registerRoutes } from "./routes";

export const sessionsModule: ServerModule = {
  name: "sessions",
  registerRoutes,
};

export {
  __setSessionIdentityForTests,
  __setSessionServicesFactoryForTests,
} from "./routes";
