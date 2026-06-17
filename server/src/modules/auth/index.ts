import type { ServerModule } from "../../gateway/routeRegistry";
import { registerRoutes } from "./routes";

export const authModule: ServerModule = { name: "auth", registerRoutes };

export {
  __setAuthIdentityForTests,
  __setAuthRepositoryForTests,
  introspectIdentity,
  type AuthFailure,
  type AuthRepository,
} from "./identity";
export { __setGoogleOAuthClientForTests, type GoogleOAuthClient } from "./oauth";
