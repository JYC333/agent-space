import { describe, expect, it } from "vitest";
import { ExecutionGraphScheduler } from "../src/modules/execution/executionGraphScheduler";

describe("ExecutionGraphScheduler", () => {
  const scheduler = new ExecutionGraphScheduler();

  it("only releases nodes whose dependencies are done", () => {
    expect(scheduler.readyNodes([
      { id: "root", status: "in_progress", dependsOn: [] },
      { id: "next", status: "inbox", dependsOn: ["root"] },
      { id: "independent", status: "inbox", dependsOn: [] },
    ]).map(node => node.id)).toEqual(["independent"]);
  });

  it("requires a passed evaluation after a terminal adapter result", () => {
    expect(scheduler.projectRunOutcome("succeeded", null)).toBeNull();
    expect(scheduler.projectRunOutcome("succeeded", "failed")).toBe("failed");
    expect(scheduler.projectRunOutcome("succeeded", "passed")).toBe("done");
    expect(scheduler.projectRunOutcome("failed", null)).toBe("failed");
  });
});
