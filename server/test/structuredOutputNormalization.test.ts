import { describe, expect, it } from "vitest";
import { structuredOutputFromText, type ProviderStructuredOutput } from "../src/modules/providers/invocation/invocation";
import { RESEARCH_SYNTHESIS_OUTPUT_CONTRACT } from "../src/modules/projectResearch/outputSchemas";

// Reasoning models wrap the contractual JSON in combinable transport noise:
// a <think> envelope, a markdown fence, and/or surrounding prose. Extraction
// must peel all of them; schema validation stays the real contract gate.

const format: ProviderStructuredOutput = {
  type: "json_schema",
  schema_id: "test.schema.v1",
  schema: {
    type: "object",
    properties: { answer: { type: "string" } },
    required: ["answer"],
    additionalProperties: false,
  },
};

const payload = '{"answer":"ok"}';

describe("structured output text normalization", () => {
  it("parses bare JSON", () => {
    expect(structuredOutputFromText(payload, format)).toEqual({ answer: "ok" });
  });

  it("strips a reasoning envelope", () => {
    expect(structuredOutputFromText(`<think>reasoning here</think>\n${payload}`, format)).toEqual({ answer: "ok" });
  });

  it("unwraps a json fence that follows a reasoning envelope", () => {
    expect(structuredOutputFromText("<think>hm</think>\n```json\n" + payload + "\n```", format)).toEqual({ answer: "ok" });
  });

  it("extracts JSON surrounded by prose after a reasoning envelope (MiniMax-style failure)", () => {
    const text = `<think>long reasoning</think>\nHere is the final result:\n${payload}\nLet me know if you need anything else.`;
    expect(structuredOutputFromText(text, format)).toEqual({ answer: "ok" });
  });

  it("extracts a balanced JSON object without being confused by later prose braces", () => {
    const text = `The final result is ${payload}. The notation {not JSON} is only explanatory.`;
    expect(structuredOutputFromText(text, format)).toEqual({ answer: "ok" });
  });

  it("peels a single-key tool-name wrapper around the payload (MiniMax forced tool call)", () => {
    expect(structuredOutputFromText(`{"test_schema_v1": ${payload}}`, format)).toEqual({ answer: "ok" })
  });

  it("peels nested single-key wrappers", () => {
    expect(structuredOutputFromText(`{"tool": {"arguments": ${payload}}}`, format)).toEqual({ answer: "ok" })
  });

  it("undoes XML-gateway artifacts: stringified scalars and item-wrapped arrays", () => {
    const gatewayFormat: ProviderStructuredOutput = {
      type: "json_schema",
      schema_id: "gateway.v1",
      schema: {
        type: "object",
        properties: {
          count: { type: "integer" },
          ok: { type: "boolean" },
          tags: { type: "array", items: { type: "string" } },
          nested: { type: "object", properties: { score: { type: "number" } }, required: ["score"], additionalProperties: false },
        },
        required: ["count", "ok", "tags", "nested"],
        additionalProperties: false,
      },
    };
    expect(structuredOutputFromText('{"count":"4","ok":"true","tags":{"item":["a","b"]},"nested":{"score":"3.5"}}', gatewayFormat))
      .toEqual({ count: 4, ok: true, tags: ["a", "b"], nested: { score: 3.5 } });
    expect(structuredOutputFromText('{"count":"2","ok":"false","tags":{"item":"solo"},"nested":{"score":"1"}}', gatewayFormat))
      .toEqual({ count: 2, ok: false, tags: ["solo"], nested: { score: 1 } });
    // A string wrapped in a one-field object (issues: [{"issue": "text"}]).
    expect(structuredOutputFromText('{"count":4,"ok":true,"tags":[{"tag":"a"},"b"],"nested":{"score":2}}', gatewayFormat))
      .toEqual({ count: 4, ok: true, tags: ["a", "b"], nested: { score: 2 } });
  });

  it("keeps schema key names and closed-object fields strict", () => {
    const nestedFormat: ProviderStructuredOutput = {
      type: "json_schema",
      schema_id: "nested.v1",
      schema: {
        type: "object",
        properties: {
          assessment: {
            type: "object",
            properties: { answerable: { type: "boolean" }, finer: { type: "object", properties: { feasible: { type: "integer" } }, required: ["feasible"], additionalProperties: false } },
            required: ["answerable", "finer"],
            additionalProperties: false,
          },
        },
        required: ["assessment"],
        additionalProperties: false,
      },
    };
    const text = '{"assessment":{"answerable":false,"rationale":"extra commentary","FINER":{"feasible":1}}}';
    expect(() => structuredOutputFromText(text, nestedFormat)).toThrow(/failed schema/);
  });

  it("names the top-level keys it saw when the shape still fails the schema", () => {
    expect(() => structuredOutputFromText('{"assessments": {}, "extra": 1}', format))
      .toThrow(/json_top_level_keys=assessments\|extra/)
  });

  it("chooses a later schema-valid JSON object after an earlier JSON object", () => {
    const text = `Metadata: {"wrong":"shape"}\nResult: ${payload}`;
    expect(structuredOutputFromText(text, format)).toEqual({ answer: "ok" });
  });

  it("extracts a fenced block embedded in prose", () => {
    const text = "Sure! The output is:\n```json\n" + payload + "\n```\nDone.";
    expect(structuredOutputFromText(text, format)).toEqual({ answer: "ok" });
  });

  it("still enforces the schema on the extracted payload", () => {
    expect(() => structuredOutputFromText('prose {"wrong":"shape"} prose.', format)).toThrow(/failed schema/);
  });

  it("reports invalid_json with the attempted normalizations when nothing parses", () => {
    expect(() => structuredOutputFromText("no json anywhere.", format)).toThrow(/invalid structured output/);
  });

  it("accepts a semantic rejection envelope extracted from surrounding model prose", () => {
    const rejection = {
      status: "rejected",
      artifacts: [],
      rejection: {
        code: "research_question_not_actionable",
        message: "The research question does not define an actionable synthesis target.",
        reason: "The value `test` is too vague to connect the approved papers into a defensible synthesis.",
        suggestions: [
          "Provide a specific research question or thematic lens.",
          "Select the source items that should be synthesized together.",
        ],
      },
    };
    const text = `<think>the question is not actionable</think>\nHere is the result:\n${JSON.stringify(rejection)}\n`;
    expect(structuredOutputFromText(text, RESEARCH_SYNTHESIS_OUTPUT_CONTRACT)).toEqual(rejection);
  });

  it("accepts direct JSON objects inside synthesis artifacts", () => {
    const output = {
      status: "succeeded",
      artifacts: [{
        title: "Brief",
        artifact_type: "research_report.archive.v1",
        mime_type: "application/json",
        content: {
          schema_version: "research_report.v1",
          research_question: "Does X improve Y?",
          summary: "A bounded summary.",
          findings: [],
          limitations: [],
          sources: [],
          ideas: [],
        },
      }],
      rejection: null,
    };
    expect(structuredOutputFromText(JSON.stringify(output), RESEARCH_SYNTHESIS_OUTPUT_CONTRACT)).toEqual(output);
  });

  it("rejects string artifact content at the run contract", () => {
    // A string content slot let arbitrary prose (e.g. a Markdown brief) pass
    // run-level validation and fail only at the post-materialization parse,
    // poisoning the stored artifact. The contract now requires the object.
    const inner = JSON.stringify({
      schema_version: "research_report.v1",
      research_question: "Does X improve Y?",
      summary: "A bounded summary.",
      findings: [],
      limitations: [],
      sources: [],
      ideas: [],
    });
    const output = {
      status: "succeeded",
      artifacts: [{
        title: "Brief",
        artifact_type: "research_report.archive.v1",
        mime_type: "application/json",
        content: inner,
      }],
      rejection: null,
    };
    expect(() => structuredOutputFromText(JSON.stringify(output), RESEARCH_SYNTHESIS_OUTPUT_CONTRACT)).toThrow(/failed schema/);
  });

  it("unwraps {\"$text\": \"<json>\"} text nodes from XML-to-JSON tool-call gateways (MiniMax-style)", () => {
    const brief = {
      schema_version: "research_report.v1",
      research_question: "Does X improve Y?",
      summary: "A bounded summary.",
      findings: [],
      limitations: [],
      sources: [],
      ideas: [],
    };
    const output = {
      status: "succeeded",
      artifacts: [{
        title: "Brief",
        artifact_type: "research_report.archive.v1",
        mime_type: "application/json",
        content: { $text: JSON.stringify(brief) },
      }],
      rejection: null,
    };
    expect(structuredOutputFromText(JSON.stringify(output), RESEARCH_SYNTHESIS_OUTPUT_CONTRACT)).toEqual({
      ...output,
      artifacts: [{ ...output.artifacts[0], content: brief }],
    });
  });

  it("still rejects a $text payload whose parsed value does not match the schema", () => {
    const output = {
      status: "succeeded",
      artifacts: [{
        title: "Brief",
        artifact_type: "research_report.archive.v1",
        mime_type: "application/json",
        content: { $text: JSON.stringify({ schema_version: "research_report.v1" }) },
      }],
      rejection: null,
    };
    expect(() => structuredOutputFromText(JSON.stringify(output), RESEARCH_SYNTHESIS_OUTPUT_CONTRACT)).toThrow(/failed schema/);
  });

  it("never unwraps objects where $text is one key among others", () => {
    const output = {
      status: "succeeded",
      artifacts: [{
        title: "Brief",
        artifact_type: "research_report.archive.v1",
        mime_type: "application/json",
        content: { $text: "{}", extra: 1 },
      }],
      rejection: null,
    };
    expect(() => structuredOutputFromText(JSON.stringify(output), RESEARCH_SYNTHESIS_OUTPUT_CONTRACT)).toThrow(/failed schema/);
  });

  // Providers without constrained decoding (observed with MiniMax-M3 tool
  // calls) fill the required nullable `rejection` slot with a near-miss
  // instead of the literal null. The transport layer coerces those; the
  // orchestrator's semantic gate still enforces status/rejection coherence.
  const succeededOutput = (rejection: unknown) => ({
    status: "succeeded",
    artifacts: [{
      title: "Brief",
      artifact_type: "research_report.archive.v1",
      mime_type: "application/json",
      content: {
        schema_version: "research_report.v1",
        research_question: "Does X improve Y?",
        summary: "A bounded summary.",
        findings: [],
        limitations: [],
        sources: [],
        ideas: [],
      },
    }],
    rejection,
  });

  it("coerces an empty-object rejection to null", () => {
    expect(structuredOutputFromText(JSON.stringify(succeededOutput({})), RESEARCH_SYNTHESIS_OUTPUT_CONTRACT))
      .toEqual(succeededOutput(null));
  });

  it("coerces an all-null rejection object to null", () => {
    const rejection = { code: null, message: null, reason: null, suggestions: null };
    expect(structuredOutputFromText(JSON.stringify(succeededOutput(rejection)), RESEARCH_SYNTHESIS_OUTPUT_CONTRACT))
      .toEqual(succeededOutput(null));
  });

  it("coerces a \"null\" string rejection to null", () => {
    expect(structuredOutputFromText(JSON.stringify(succeededOutput("null")), RESEARCH_SYNTHESIS_OUTPUT_CONTRACT))
      .toEqual(succeededOutput(null));
  });

  it("never coerces a schema-valid rejection object", () => {
    const rejection = {
      code: "insufficient_approved_corpus",
      message: "Not enough approved sources.",
      reason: "Only one source was approved.",
      suggestions: ["Approve more sources."],
    };
    const output = { status: "rejected", artifacts: [], rejection };
    expect(structuredOutputFromText(JSON.stringify(output), RESEARCH_SYNTHESIS_OUTPUT_CONTRACT)).toEqual(output);
  });

  it("reports per-branch failures when a rejection matches no anyOf branch", () => {
    const rejection = { code: "bogus_code", message: "m", reason: "r", suggestions: ["s"] };
    const output = { status: "rejected", artifacts: [], rejection };
    expect(() => structuredOutputFromText(JSON.stringify(output), RESEARCH_SYNTHESIS_OUTPUT_CONTRACT))
      .toThrow(/\$\.rejection:anyOf\(0=\$\.rejection:type:null; 1=\$\.rejection\.code:enum\)/);
  });

  it("rejects a direct artifact object that does not match its artifact type", () => {
    const output = {
      status: "succeeded",
      artifacts: [{
        title: "Brief",
        artifact_type: "research_report.archive.v1",
        mime_type: "application/json",
        content: { schema_version: "research_report.v1" },
      }],
      rejection: null,
    };
    expect(() => structuredOutputFromText(JSON.stringify(output), RESEARCH_SYNTHESIS_OUTPUT_CONTRACT)).toThrow(/failed schema/);
  });
});
