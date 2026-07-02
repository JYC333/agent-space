import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchCustomSourceEndpointHtml } from "../src/modules/intake/customSourceEndpointFetch";
import type { CustomSourceRunnerSettings } from "../src/modules/intake/customSourceRunner";

const ORIGIN = "https://source.example";

const POLICY_ENVELOPE = {
  allowed_network_origins: [ORIGIN],
  capture_policy: "auto_extract_relevant",
  retention_policy: "full_text",
  credential_ref: null,
  language: "typescript_node" as const,
  browser_automation_enabled: false,
  shell_enabled: false,
  dependency_installation_enabled: false,
  log_redaction_enabled: true,
  limits: {
    timeout_ms: 5000,
    max_download_bytes: 1_000_000,
    max_output_bytes: 1_000_000,
    max_files: 5,
    max_items: 20,
    max_evidence_items: 20,
    log_max_bytes: 65536,
  },
};

function instanceSettings(
  overrides: Partial<CustomSourceRunnerSettings> = {},
): CustomSourceRunnerSettings {
  return {
    runner_enabled: true,
    allowed_languages: ["typescript_node"],
    network_hard_deny_rules: [],
    timeout_ms_max: 30_000,
    output_bytes_max: 1_048_576,
    download_bytes_max: 5_242_880,
    log_bytes_max: 65_536,
    max_files: 50,
    browser_automation_available: false,
    shell_available: false,
    dependency_installation_available: false,
    ...overrides,
  };
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("fetchCustomSourceEndpointHtml", () => {
  it("fetches and follows same-origin redirects allowed by the handler envelope", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (url) => {
      if (String(url) === `${ORIGIN}/redirect-same-origin`) {
        return new Response(null, { status: 302, headers: { location: "/ok" } });
      }
      return new Response("hello pi world", { status: 200 });
    });

    const html = await fetchCustomSourceEndpointHtml(`${ORIGIN}/redirect-same-origin`, instanceSettings(), POLICY_ENVELOPE);
    expect(html).toBe("hello pi world");
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[1]?.[0]).toBe(`${ORIGIN}/ok`);
  });

  it("rejects an off-origin redirect before following it", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(null, { status: 302, headers: { location: "https://other.example/off-origin" } }),
    );

    await expect(
      fetchCustomSourceEndpointHtml(`${ORIGIN}/redirect-off-origin`, instanceSettings(), POLICY_ENVELOPE),
    ).rejects.toThrow("not allowed by the handler policy envelope");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("truncates fetched HTML by UTF-8 byte length", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("hello pi world", { status: 200 }));

    const html = await fetchCustomSourceEndpointHtml(
      `${ORIGIN}/ok`,
      instanceSettings({ download_bytes_max: 8 }),
      { ...POLICY_ENVELOPE, limits: { ...POLICY_ENVELOPE.limits, max_download_bytes: 8 } },
    );
    expect(Buffer.byteLength(html, "utf8")).toBeLessThanOrEqual(8);
    expect(html).toBe("hello pi");
  });
});
