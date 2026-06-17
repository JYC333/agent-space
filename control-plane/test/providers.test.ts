import { describe, it, expect, afterEach } from "vitest";
import type { FastifyInstance } from "fastify";
import { buildServer } from "../src/server";
import { loadConfig } from "../src/config";
import { TS_OWNED_MODULES } from "../src/gateway/routeRegistry";
import { providersModule } from "../src/modules/providers";

let app: FastifyInstance;

afterEach(async () => {
  await app?.close();
});

describe("providers module", () => {
  it("registers as a TS-owned module and advertises fixed TS provider authority", async () => {
    expect(providersModule.name).toBe("providers");
    expect(TS_OWNED_MODULES).toContain(providersModule);

    app = buildServer(loadConfig({}), { logger: false });
    const res = await app.inject({
      method: "GET",
      url: "/api/v1/control-plane/features",
    });
    expect(res.statusCode).toBe(200);
    expect(res.json().features).toContain("providers_read_ts_authority");
    expect(res.json().features).toContain("providers_credentials_ts_authority");
    expect(res.json().features).not.toContain("providers_readonly_python_facade");
  });
});
