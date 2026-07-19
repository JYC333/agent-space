import { describe, expect, it, vi } from "vitest";
import { loadConfig } from "../src/config";
import { SourceChannelService } from "../src/modules/sources/channels/sourceChannelService";
import type { Queryable } from "../src/modules/routeUtils/common";

describe("Source Channel boundary", () => {
  it("requires a Provider instead of an implementation connector key", async () => {
    const query = vi.fn();
    const service = new SourceChannelService({ query } as Queryable, loadConfig({}));
    await expect(service.create({ spaceId: "space-1", userId: "user-1" }, {
      connector_key: "custom_source",
      name: "Bypass attempt",
    })).rejects.toMatchObject({ statusCode: 422 });
    expect(query).not.toHaveBeenCalled();
  });
});
