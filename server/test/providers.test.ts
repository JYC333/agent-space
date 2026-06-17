import { describe, it, expect, afterEach } from "vitest";
import type { FastifyInstance } from "fastify";
import { buildServer } from "../src/server";
import { loadConfig } from "../src/config";
import { SERVER_MODULES } from "../src/gateway/routeRegistry";
import { providersModule } from "../src/modules/providers";

let app: FastifyInstance;

afterEach(async () => {
  await app?.close();
});

describe("providers module", () => {
  it("registers as a server-owned module and advertises fixed server provider authority", async () => {
    expect(providersModule.name).toBe("providers");
    expect(SERVER_MODULES).toContain(providersModule);

    app = buildServer(loadConfig({}), { logger: false });
    const res = await app.inject({
      method: "GET",
      url: "/api/v1/server/features",
    });
    expect(res.statusCode).toBe(200);
    expect(res.json().features).toContain("providers_read_server_authority");
    expect(res.json().features).toContain("providers_credentials_server_authority");
  });
});
