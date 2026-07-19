import { describe, expect, it } from "vitest";
import { researchQuestionDrift } from "../src/modules/projectResearch/questionDrift";

describe("researchQuestionDrift", () => {
  it("detects a changed non-empty project question", () => {
    expect(researchQuestionDrift("New question", "Old question")).toBe(true);
  });

  it("ignores surrounding whitespace", () => {
    expect(researchQuestionDrift("  Same question ", "Same question")).toBe(false);
  });

  it("does not report drift before a workflow has a question", () => {
    expect(researchQuestionDrift("New question", null)).toBe(false);
  });
});
