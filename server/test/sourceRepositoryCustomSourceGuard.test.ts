import { describe, expect, it, vi } from "vitest";
import { loadConfig } from "../src/config";
import { PgSourcesRepository } from "../src/modules/sources/repository";
import { HttpError, type Queryable } from "../src/modules/routeUtils/common";

describe("PgSourcesRepository Custom Source guard", () => {
  it("rejects generic custom_source connection creation before touching the database", async () => {
    const query = vi.fn(async () => ({ rows: [], rowCount: 0 }));
    const repository = new PgSourcesRepository({ query } as Queryable, loadConfig({}));

    await expect(
      repository.createConnection({ spaceId: "space-1", userId: "user-1" }, {
        connector_key: "custom_source",
        name: "Bypass attempt",
        endpoint_url: "https://example.com/list",
      }),
    ).rejects.toThrow(HttpError);
    expect(query).not.toHaveBeenCalled();
  });

  it("allows the Custom Source draft flow to opt into the seeded custom_source connector", async () => {
    const query = vi.fn(async () => ({ rows: [], rowCount: 0 }));
    const repository = new PgSourcesRepository({ query } as Queryable, loadConfig({}));

    await expect(
      repository.createConnection({ spaceId: "space-1", userId: "user-1" }, {
        connector_key: "custom_source",
        name: "Draft flow",
        endpoint_url: "https://example.com/list",
      }, { allowCustomSourceConnector: true }),
    ).rejects.toThrow("Source connector not found");
    expect(query).toHaveBeenCalledTimes(1);
  });
});
