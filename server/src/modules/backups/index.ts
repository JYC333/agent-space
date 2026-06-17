import type { ServerModule } from "../../gateway/routeRegistry";
import { registerRoutes } from "./routes";

export const backupsModule: ServerModule = {
  name: "backups",
  registerRoutes,
};

export { BackupService, runScheduledBackup } from "./service";
export { enforceBackupPolicy, BackupPolicyError } from "./guard";
