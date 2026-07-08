import { describe, expect, it } from "vitest";
import { extractPdfReaderContent } from "../src/modules/sources/pdfExtract";
import { simplePdfBytes } from "./fixtures/simplePdf";

describe("extractPdfReaderContent", () => {
  it("extracts PDF bytes into the canonical reader document shape", async () => {
    const result = await extractPdfReaderContent(
      simplePdfBytes("Project Research PDF"),
      "https://example.test/paper.pdf",
    );

    expect(result.kind).toBe("reader_document");
    expect(result.extraction_method).toBe("pdf_text_v1");
    expect(result.image_policy).toBe("none");
    expect(result.source_uri).toBe("https://example.test/paper.pdf");
    expect(result.plain_text).toContain("Project Research PDF");
    expect(result.content_json.type).toBe("doc");
    expect(result.content_json.content.length).toBeGreaterThan(0);
  });
});
