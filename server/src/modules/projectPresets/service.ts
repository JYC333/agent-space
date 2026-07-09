import type { ServerConfig } from "../../config";
import { dbPool, HttpError, type SpaceUserIdentity } from "../routeUtils/common";
import { listBuiltInProjectPresets } from "./registry";
import { ProjectPresetsRepository } from "./repository";
import type { ProjectPresetDescriptor } from "./types";

export class ProjectPresetsService {
  static fromConfig(config: ServerConfig): ProjectPresetsService {
    const pool = dbPool(config);
    return new ProjectPresetsService(new ProjectPresetsRepository(pool));
  }

  constructor(private readonly repository: ProjectPresetsRepository) {}

  listAvailablePresets(): ProjectPresetDescriptor[] {
    return listBuiltInProjectPresets();
  }

  async getProjectPreset(identity: SpaceUserIdentity, projectId: string): Promise<string | null> {
    const row = await this.repository.getProjectPresetKey(identity.spaceId, projectId);
    if (!row) throw new HttpError(404, "Project not found");
    return row.preset_key;
  }
}
