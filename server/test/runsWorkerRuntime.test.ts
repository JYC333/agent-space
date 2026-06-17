import { describe, expect, it } from "vitest";
import { loadConfig } from "../src/config";
import { startRunsJobWorker } from "../src/modules/runs/workerRuntime";

describe("startRunsJobWorker", () => {
  it("does not start without a configured database", () => {
    const config = loadConfig({});
    expect(startRunsJobWorker(config)).toBeNull();
  });
});
