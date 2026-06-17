import type { ServerModule } from "../../gateway/routeRegistry";
import { registerRoutes } from "./routes";

export const artifactsModule: ServerModule = {
  name: "artifacts",
  registerRoutes,
};

export {
  __setArtifactIdentityForTests,
  __setArtifactRepositoryFactoryForTests,
} from "./routes";
