import { describe, expect, it, vi } from "vitest";
import { loadConfig } from "../src/config";
import { getDbPool } from "../src/db/pool";
import { registerContextDigestRefreshHandler } from "../src/modules/context/digestJob";
import { JobHandlerRegistry } from "../src/modules/jobs/handlerRegistry";

vi.mock("../src/db/pool", () => ({
  getDbPool: vi.fn(),
}));

function config() {
  return loadConfig({
    SERVER_DATABASE_URL: "postgresql://server@db:5432/agent_space",
    SERVER_INTERNAL_TOKEN: "internal-token",
  });
}

describe("context digest refresh job", () => {
  it("rejects payload space_id that does not match the job envelope", async () => {
    const query = vi.fn();
    vi.mocked(getDbPool).mockReturnValue({ query } as never);
    const registry = new JobHandlerRegistry();
    registerContextDigestRefreshHandler(registry, config());

    await expect(
      registry.dispatch({
        job_id: "job-1",
        space_id: "space-1",
        user_id: "user-1",
        job_type: "context_digest_refresh",
        attempts: 1,
        max_attempts: 3,
        worker_id: "worker-1",
        payload: { space_id: "space-2", digest_type: "policy_bundle" },
      }),
    ).rejects.toThrow(/payload space_id does not match envelope space_id/);
    expect(query).not.toHaveBeenCalled();
  });
});
