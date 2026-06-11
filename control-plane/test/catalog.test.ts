/**
 * Tests for the catalog module — the first TS-owned read surface beyond the
 * system descriptors. Uses a temp-dir catalog fixture; never reads the repo's
 * real catalog so assertions stay stable as built-in definitions evolve.
 */

import { describe, it, expect, beforeAll, afterAll, afterEach } from "vitest";
import { mkdtemp, mkdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { FastifyInstance } from "fastify";
import { buildServer } from "../src/server";
import { loadConfig } from "../src/config";
import { catalogModule } from "../src/modules/catalog";
import { TS_OWNED_MODULES } from "../src/gateway/routeRegistry";

let fixtureRoot: string;
let app: FastifyInstance;

beforeAll(async () => {
  fixtureRoot = await mkdtemp(join(tmpdir(), "cp-catalog-"));

  const capDir = join(fixtureRoot, "capabilities", "alpha-cap");
  await mkdir(capDir, { recursive: true });
  await writeFile(
    join(capDir, "capability.yaml"),
    [
      "id: alpha-cap",
      "name: Alpha Capability",
      'version: "0.1.0"',
      "description: >",
      "  Extracts things.",
      "enabled: true",
    ].join("\n"),
  );

  const brokenDir = join(fixtureRoot, "capabilities", "broken-cap");
  await mkdir(brokenDir, { recursive: true });
  await writeFile(join(brokenDir, "capability.yaml"), "{{{ not yaml ::::");

  // Noise that must be skipped: a plain file and a dir without a manifest.
  await writeFile(join(fixtureRoot, "capabilities", "__init__.py"), "");
  await mkdir(join(fixtureRoot, "capabilities", "__pycache__"), { recursive: true });

  const tmplDir = join(fixtureRoot, "agent_templates", "beta_tmpl");
  await mkdir(tmplDir, { recursive: true });
  await writeFile(
    join(tmplDir, "template.yaml"),
    [
      "key: beta_tmpl",
      "name: Beta Template",
      "category: assistant",
      "visibility: system_internal",
      "description: A template.",
    ].join("\n"),
  );
});

afterAll(async () => {
  await rm(fixtureRoot, { recursive: true, force: true });
});

afterEach(async () => {
  await app?.close();
});

function buildApp(catalogRoot: string): FastifyInstance {
  return buildServer(loadConfig({ CONTROL_PLANE_CATALOG_ROOT: catalogRoot }), {
    logger: false,
  });
}

describe("catalog module registration", () => {
  it("is a TS-owned module advertised through features", async () => {
    expect(catalogModule.name).toBe("catalog");
    expect(TS_OWNED_MODULES).toContain(catalogModule);

    app = buildApp(fixtureRoot);
    const res = await app.inject({ method: "GET", url: "/api/v1/control-plane/features" });
    expect((res.json() as { features: string[] }).features).toContain("catalog_read");
  });
});

describe("catalog summary", () => {
  it("reports availability and entry counts", async () => {
    app = buildApp(fixtureRoot);
    const res = await app.inject({ method: "GET", url: "/api/v1/control-plane/catalog" });
    expect(res.statusCode).toBe(200);
    expect(res.json()).toEqual({
      catalog_available: true,
      capabilities_count: 2,
      agent_templates_count: 1,
    });
  });

  it("degrades to catalog_available=false (HTTP 200) when the root is missing", async () => {
    app = buildApp(join(fixtureRoot, "does-not-exist"));
    const res = await app.inject({ method: "GET", url: "/api/v1/control-plane/catalog" });
    expect(res.statusCode).toBe(200);
    expect(res.json()).toEqual({
      catalog_available: false,
      capabilities_count: 0,
      agent_templates_count: 0,
    });

    const list = await app.inject({
      method: "GET",
      url: "/api/v1/control-plane/catalog/capabilities",
    });
    expect(list.statusCode).toBe(200);
    expect(list.json()).toEqual({ catalog_available: false, items: [] });
  });
});

describe("catalog capabilities listing", () => {
  it("lists manifest summaries sorted by directory, flags parse errors, skips noise", async () => {
    app = buildApp(fixtureRoot);
    const res = await app.inject({
      method: "GET",
      url: "/api/v1/control-plane/catalog/capabilities",
    });
    expect(res.statusCode).toBe(200);
    const body = res.json() as {
      catalog_available: boolean;
      items: Array<Record<string, unknown>>;
    };
    expect(body.catalog_available).toBe(true);
    expect(body.items).toHaveLength(2);
    expect(body.items[0]).toEqual({
      id: "alpha-cap",
      name: "Alpha Capability",
      version: "0.1.0",
      description: "Extracts things.",
      enabled: true,
    });
    expect(body.items[1]).toMatchObject({ id: "broken-cap", parse_error: true });
  });
});

describe("catalog agent templates listing", () => {
  it("lists template summaries with declared visibility passed through verbatim", async () => {
    app = buildApp(fixtureRoot);
    const res = await app.inject({
      method: "GET",
      url: "/api/v1/control-plane/catalog/agent-templates",
    });
    expect(res.statusCode).toBe(200);
    const body = res.json() as { items: Array<Record<string, unknown>> };
    expect(body.items).toEqual([
      {
        key: "beta_tmpl",
        name: "Beta Template",
        category: "assistant",
        visibility: "system_internal",
        description: "A template.",
      },
    ]);
  });
});
