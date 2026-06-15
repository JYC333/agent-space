import { describe, expect, it } from "vitest";
import { loadConfig } from "../src/config";
import { startRunsJobWorker } from "../src/modules/runs/workerRuntime";

describe("startRunsJobWorker", () => {
  it("does not start when the runs authority is python", () => {
    const config = loadConfig({
      CONTROL_PLANE_PYTHON_API_BASE_URL: "http://python.test",
    });
    expect(startRunsJobWorker(config)).toBeNull();
  });
});
