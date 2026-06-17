import type { ServerModule } from "../../gateway/routeRegistry";
import { registerRoutes } from "./routes";

export const runsModule: ServerModule = {
  name: "runs",
  registerRoutes,
};

export {
  __setRunsCommandServicesFactoryForTests,
  __setRunsIdentityForTests,
  __setRunsReadResponseForTests,
} from "./routes";
