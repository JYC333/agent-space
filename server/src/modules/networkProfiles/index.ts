import type { ServerModule } from "../../gateway/routeRegistry";
import { registerRoutes } from "./routes";

export const networkProfilesModule: ServerModule = {
  name: "networkProfiles",
  registerRoutes,
};

export {
  resolveNetworkProfileRepository,
  type NetworkProfileCreateInput,
  type NetworkProfileUpdateInput,
} from "./repository";
export {
  envForNetworkProfile,
  fetchWithNetworkProfile,
  shouldBypassProxy,
  validateNetworkProfileInput,
  type ResolvedNetworkProfile,
} from "./transport";
