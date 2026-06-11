import { describe, it, expect, afterEach } from "vitest";
import type { FastifyInstance } from "fastify";
import { buildServer } from "../src/server";
import { loadConfig } from "../src/config";
import {
  computeFeatures,
  isProtocolPackageDetected,
} from "../src/modules/system";

let app: FastifyInstance;

afterEach(async () => {
  await app?.close();
});

describe("TS-owned features route", () => {
  it("advertises control_plane_health, legacy_python_proxy and protocol detection", async () => {
    app = buildServer(loadConfig({}), { logger: false });
    const res = await app.inject({ method: "GET", url: "/api/v1/control-plane/features" });
    expect(res.statusCode).toBe(200);
    const body = res.json() as { service: string; features: string[] };
    expect(body.service).toBe("control-plane");
    expect(body.features).toContain("control_plane_health");
    expect(body.features).toContain("legacy_python_proxy");
  });

  it("detects the @agent-space/protocol package (declared file dependency)", () => {
    expect(isProtocolPackageDetected()).toBe(true);
    expect(computeFeatures(loadConfig({}))).toContain("protocol_package_detected");
  });

  it("omits legacy_python_proxy when the proxy is disabled", () => {
    const features = computeFeatures(
      loadConfig({ CONTROL_PLANE_ENABLE_LEGACY_PROXY: "false" }),
    );
    expect(features).not.toContain("legacy_python_proxy");
    expect(features).toContain("control_plane_health");
  });
});
