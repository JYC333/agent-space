import { describe, expect, it } from "vitest";
import { parseFeed } from "../src/modules/intake/feedParser";
import { computeNextCheckAt } from "../src/modules/intake/scanSchedule";

describe("intake feed parser", () => {
  it("parses RSS items into normalized feed entries", () => {
    const items = parseFeed(
      `<?xml version="1.0"?>
       <rss version="2.0">
         <channel>
           <item>
             <title>Release notes</title>
             <link>https://example.test/releases/1</link>
             <guid>guid-1</guid>
             <pubDate>Tue, 30 Jun 2026 09:00:00 GMT</pubDate>
             <description><![CDATA[<p>Important changes shipped today.</p>]]></description>
             <dc:creator>Ada</dc:creator>
           </item>
         </channel>
       </rss>`,
      "rss",
    );

    expect(items).toHaveLength(1);
    expect(items[0]).toMatchObject({
      title: "Release notes",
      url: "https://example.test/releases/1",
      externalId: "guid-1",
      author: "Ada",
      occurredAt: "2026-06-30T09:00:00.000Z",
      excerpt: "Important changes shipped today.",
      metadata: { feed_type: "rss" },
    });
  });

  it("parses Atom entries with alternate links and author names", () => {
    const items = parseFeed(
      `<?xml version="1.0"?>
       <feed>
         <entry>
           <id>tag:example.test,2026:item-1</id>
           <title>Atom update</title>
           <link rel="alternate" href="https://example.test/atom/1" />
           <published>2026-06-30T10:15:00Z</published>
           <updated>2026-06-30T10:20:00Z</updated>
           <author><name>Grace</name></author>
           <summary>Short atom summary.</summary>
         </entry>
       </feed>`,
      "atom",
    );

    expect(items).toHaveLength(1);
    expect(items[0]).toMatchObject({
      title: "Atom update",
      url: "https://example.test/atom/1",
      externalId: "tag:example.test,2026:item-1",
      author: "Grace",
      occurredAt: "2026-06-30T10:15:00.000Z",
      excerpt: "Short atom summary.",
      metadata: {
        feed_type: "atom",
        updated_at: "2026-06-30T10:20:00.000Z",
      },
    });
  });
});

describe("intake scan schedule", () => {
  it("computes next checks for manual, hourly, daily, and weekly frequencies", () => {
    const completedAt = "2026-06-30T12:00:00.000Z";

    expect(computeNextCheckAt("manual", completedAt)).toBeNull();
    expect(computeNextCheckAt("hourly", completedAt)).toBe("2026-06-30T13:00:00.000Z");
    expect(computeNextCheckAt("daily", completedAt)).toBe("2026-07-01T12:00:00.000Z");
    expect(computeNextCheckAt("weekly", completedAt)).toBe("2026-07-07T12:00:00.000Z");
  });

  it("preserves a future scheduled check when a manual scan runs", () => {
    expect(computeNextCheckAt("daily", "2026-06-30T12:00:00.000Z", {
      manualRun: true,
      existingNextCheckAt: "2026-07-03T12:00:00.000Z",
    })).toBe("2026-07-03T12:00:00.000Z");
  });
});
