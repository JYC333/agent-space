import type { ServerModule } from "../../gateway/routeRegistry";
import { registerRoutes } from "./routes";

export const academicModule: ServerModule = {
  name: "academic",
  registerRoutes,
};

export { __setAcademicServiceFactoryForTests } from "./routes";
export { AcademicService } from "./service";
export { materializeAcademicPaperFromSourceItem } from "./paperMaterializer";
export type { MaterializeAcademicPaperResult } from "./paperMaterializer";
