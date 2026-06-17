import type { ServerModule } from "../../gateway/routeRegistry";
import { registerRoutes } from "./routes";
export { __setSpaceRepositoryForTests, type SpaceRepository } from "./repository";

export const spacesModule: ServerModule = { name: "spaces", registerRoutes };
