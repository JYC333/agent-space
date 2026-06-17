import type { ControlPlaneModule } from "../../gateway/routeRegistry";
import { registerRoutes } from "./routes";

export const artifactsModule: ControlPlaneModule = {
  name: "artifacts",
  registerRoutes,
};

export {
  __setArtifactIdentityForTests,
  __setArtifactRepositoryFactoryForTests,
} from "./routes";
