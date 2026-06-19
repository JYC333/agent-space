import { defineConfig } from "vitest/config";

// Plain Node environment — the gateway has no DOM or framework UI; tests exercise
// config parsing, server-owned routes, and the proxy against a mock upstream.
export default defineConfig({
  test: {
    environment: "node",
    include: ["test/**/*.test.ts"],
    globalSetup: ["./test/setupOfficialPlugins.ts"],
  },
});
