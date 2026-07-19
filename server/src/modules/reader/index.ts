import type { ServerModule } from "../../gateway/routeRegistry";
import { registerRoutes } from "./routes";

export const readerModule: ServerModule = { name: "reader", registerRoutes };
export * from "./repository";
