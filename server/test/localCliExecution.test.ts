import { describe, expect, it } from "vitest";
import { LocalCliCommandExecutor, LocalCliProcessRegistry } from "../src/modules/runs/localCliExecution";

describe("local CLI execution supervision", () => {
  it("fails a command that produces no output before the overall timeout", async () => {
    const result = await new LocalCliCommandExecutor().runCommand({
      command: [process.execPath, "-e", "setTimeout(() => {}, 5000)"],
      cwd: null,
      timeout_seconds: 10,
      stall_timeout_seconds: 0.05,
      env: cleanEnv(),
      run_id: "stall-test",
      stdin: null,
    });

    expect(result).toMatchObject({
      timed_out: true,
      failure_code: "stall_timeout",
    });
  });

  it("deregisters a process after the watchdog terminates it", async () => {
    const registry = new LocalCliProcessRegistry();
    const result = await new LocalCliCommandExecutor().runCommand({
      command: [process.execPath, "-e", "setTimeout(() => {}, 5000)"],
      cwd: null,
      timeout_seconds: 10,
      stall_timeout_seconds: 0.05,
      env: cleanEnv(),
      run_id: "registry-stall-test",
      stdin: null,
      process_registry: registry,
    });

    expect(result.failure_code).toBe("stall_timeout");
    expect(await registry.waitForExit("registry-stall-test", 1)).toBe(true);
  });
});

function cleanEnv(): Record<string, string> {
  return Object.fromEntries(
    Object.entries(process.env).filter((entry): entry is [string, string] => entry[1] !== undefined),
  );
}
