import type { ServerModule } from "../../gateway/routeRegistry";
import { registerRoutes } from "./routes";

export const memoryModule: ServerModule = {
  name: "memory",
  registerRoutes,
};

export {
  __setMemoryIdentityForTests,
  __setMemoryServicesFactoryForTests,
} from "./routes";
