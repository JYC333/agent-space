import type { ServerModule } from "../../gateway/routeRegistry";
import { registerRoutes } from "./routes";

export const relationsModule: ServerModule = {
  name: "relations",
  registerRoutes,
};

export { __setRelationsServiceFactoryForTests } from "./routes";
export { RelationsService } from "./service";
