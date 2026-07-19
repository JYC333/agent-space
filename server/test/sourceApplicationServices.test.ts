import { describe, expect, it, vi } from "vitest";
import { loadConfig } from "../src/config";
import type { Queryable } from "../src/modules/routeUtils/common";
import { SourceRecipeService } from "../src/modules/sources/sourceRecipeService";
import { ProjectSourceBindingService } from "../src/modules/projects/projectSourceBindingService";

const identity = { spaceId: "space-1", userId: "user-1" };

describe("Source application-service boundaries", () => {
  it("exposes recipe discovery through the formal recipe service", () => {
    const service = new SourceRecipeService({} as never, loadConfig({}));
    const result = service.listPrimitives();

    expect(result.primitives.length).toBeGreaterThan(0);
  });

  it("rejects malformed project binding commands before persistence", async () => {
    const query = vi.fn();
    const service = new ProjectSourceBindingService({ query } as Queryable);

    expect(() => service.createBinding(identity, {
      project_id: "project-1",
      source_channel_id: "channel-1",
      delivery_scope: "everyone",
    })).toThrow(expect.objectContaining({ statusCode: 422 }));
    await expect(service.updateBinding(identity, "binding-1", { status: "deleted" }))
      .rejects.toMatchObject({ statusCode: 422 });
    expect(query).not.toHaveBeenCalled();
  });
});
