import { describe, expect, it } from "vitest";
import {
  intakeCursorWatermark,
  intakeDeltaConfig,
  renderIntakeDeltaInstruction,
} from "../src/modules/automations/intakeDelta";

describe("intakeDeltaConfig", () => {
  it("defaults to limit 25, no skip, no connection allowlist", () => {
    expect(intakeDeltaConfig(null)).toEqual({
      limit: 25,
      skipWhenNoNewItems: false,
      sourceConnectionIds: [],
    });
  });

  it("caps intake_delta_limit at 100 and keeps only string connection ids", () => {
    const config = intakeDeltaConfig({
      intake_delta_limit: 500,
      skip_when_no_new_items: true,
      intake_source_connection_ids: ["conn-1", 7, "", "conn-2"],
    });
    expect(config).toEqual({
      limit: 100,
      skipWhenNoNewItems: true,
      sourceConnectionIds: ["conn-1", "conn-2"],
    });
  });

  it("ignores non-integer limits", () => {
    expect(intakeDeltaConfig({ intake_delta_limit: "10" }).limit).toBe(25);
    expect(intakeDeltaConfig({ intake_delta_limit: 0 }).limit).toBe(25);
  });
});

describe("intakeCursorWatermark", () => {
  it("returns the stored watermark", () => {
    expect(
      intakeCursorWatermark({ intake_watermark: { created_at: "2026-07-01T00:00:00.000Z", id: "item-1" } }),
    ).toEqual({ created_at: "2026-07-01T00:00:00.000Z", id: "item-1" });
  });

  it("returns null for missing or malformed cursors", () => {
    expect(intakeCursorWatermark(null)).toBeNull();
    expect(intakeCursorWatermark({})).toBeNull();
    expect(intakeCursorWatermark({ intake_watermark: { created_at: 5 } })).toBeNull();
  });
});

describe("renderIntakeDeltaInstruction", () => {
  it("lists each item with title, source, id, and truncated excerpt", () => {
    const rendered = renderIntakeDeltaInstruction([
      {
        id: "item-1",
        title: "Attention Is All You Need",
        source_uri: "https://arxiv.org/abs/1706.03762",
        excerpt: "x".repeat(600),
        created_at: "2026-07-01T00:00:00.000Z",
      },
      {
        id: "item-2",
        title: "No source",
        source_uri: null,
        excerpt: null,
        created_at: "2026-07-02T00:00:00.000Z",
      },
    ]);
    expect(rendered).toContain("## New intake items since the last successful run (2)");
    expect(rendered).toContain("1. Attention Is All You Need — https://arxiv.org/abs/1706.03762 (intake_item_id: item-1)");
    expect(rendered).toContain("2. No source (intake_item_id: item-2)");
    expect(rendered).toContain("x".repeat(500));
    expect(rendered).not.toContain("x".repeat(501));
  });
});
