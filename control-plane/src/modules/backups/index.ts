import type { ControlPlaneModule } from "../../gateway/routeRegistry";
import { registerRoutes } from "./routes";

export const backupsModule: ControlPlaneModule = {
  name: "backups",
  registerRoutes,
};

export { BackupService, runScheduledBackup } from "./service";
export { enforceBackupPolicy, BackupPolicyError } from "./guard";
