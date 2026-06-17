import type { ControlPlaneModule } from "../../gateway/routeRegistry";
import { registerRoutes } from "./routes";
export { __setSpaceRepositoryForTests, type SpaceRepository } from "./repository";

export const spacesModule: ControlPlaneModule = { name: "spaces", registerRoutes };
