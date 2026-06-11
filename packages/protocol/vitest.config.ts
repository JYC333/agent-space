import { defineConfig } from "vitest/config";

// Plain Node environment — the protocol package has no DOM, framework, or
// backend dependencies; tests only exercise schema parsing and type-level
// contracts.
export default defineConfig({
  test: {
    environment: "node",
    include: ["test/**/*.test.ts"],
  },
});
