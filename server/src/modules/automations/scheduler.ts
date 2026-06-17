import type { ServerConfig } from "../../config";
import { getDbPool } from "../../db/pool";
import { AutomationService } from "./service";
import { PgAutomationRepository } from "./repository";

export async function scanAutomationsAndFire(config: ServerConfig): Promise<number> {
  if (!config.databaseUrl) return 0;
  const db = getDbPool(config.databaseUrl);
  const service = new AutomationService(config, new PgAutomationRepository(db));
  return service.scanAndFire();
}
