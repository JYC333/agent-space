import type { ServerModule } from "../../gateway/routeRegistry";
import { registerRoutes } from "./routes";

export const memoryModule: ServerModule = {
  name: "memory",
  registerRoutes,
};

export {
  __setMemoryIdentityForTests,
  __setMemoryServicesFactoryForTests,
} from "./routes";

export { MemoryMaintenanceService } from "./maintenance";
export {
  MEMORY_MAINTENANCE_PACKET_PROPOSAL_TYPE,
  MEMORY_MAINTENANCE_REPORT_ARTIFACT_TYPE,
  createMemoryMaintenanceProposalPacket,
  persistMemoryMaintenanceReportArtifact,
  registerMemoryMaintenanceProposalAppliers,
} from "./maintenanceArtifacts";
