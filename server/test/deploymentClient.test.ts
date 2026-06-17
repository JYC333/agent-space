import { describe, expect, it } from "vitest";
import { ALLOWED_DEPLOYER_JOB_TYPES, DeployerSocketClient } from "../src/modules/deployment";

describe("DeployerSocketClient", () => {
  it("limits submitted deployer jobs to the allowlist", async () => {
    expect([...ALLOWED_DEPLOYER_JOB_TYPES].sort()).toEqual([
      "health_check",
      "rebuild_agent_space",
      "restart_agent_space",
    ]);
    const client = new DeployerSocketClient({ deployerSocketPath: "/tmp/missing-deployer.sock" });
    await expect(client.submit("self_evolution_apply" as string)).resolves.toMatchObject({
      status: "failed",
      error: "Unknown deployer job_type: self_evolution_apply",
    });
  });

  it("fails closed when the configured socket is absent", async () => {
    const client = new DeployerSocketClient({ deployerSocketPath: "/tmp/missing-deployer.sock" });
    await expect(client.submit("health_check")).resolves.toMatchObject({
      status: "failed",
      job_id: null,
    });
  });
});
