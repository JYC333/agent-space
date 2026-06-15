import type { ControlPlaneModule } from "../../gateway/routeRegistry";
import { registerRoutes } from "./routes";

export const memoryModule: ControlPlaneModule = {
  name: "memory",
  registerRoutes,
};

export {
  __setMemoryIdentityForTests,
  __setMemoryServicesFactoryForTests,
} from "./routes";
