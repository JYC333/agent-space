import { describe, expect, it } from "vitest";
import { ProjectPresetsRepository } from "../src/modules/projectPresets/repository";
import { ProjectPresetsService } from "../src/modules/projectPresets/service";

class FakeProjectPresetsRepository {
  constructor(private readonly rows: Map<string, { preset_key: string | null } | null>) {}

  async getProjectPresetKey(_spaceId: string, projectId: string): Promise<{ preset_key: string | null } | null> {
    return this.rows.get(projectId) ?? null;
  }
}

function service(rows: Map<string, { preset_key: string | null } | null>): ProjectPresetsService {
  return new ProjectPresetsService(new FakeProjectPresetsRepository(rows) as unknown as ProjectPresetsRepository);
}

describe("ProjectPresetsService", () => {
  it("reads the project preset key through the dedicated preset repository path", async () => {
    await expect(
      service(new Map([["project-1", { preset_key: "academic_research" }]])).getProjectPreset(
        { spaceId: "space-1", userId: "viewer-1" },
        "project-1",
      ),
    ).resolves.toBe("academic_research");
  });

  it("returns 404 when the project does not exist in the current space", async () => {
    await expect(
      service(new Map()).getProjectPreset({ spaceId: "space-1", userId: "viewer-1" }, "project-missing"),
    ).rejects.toMatchObject({ statusCode: 404 });
  });
});
