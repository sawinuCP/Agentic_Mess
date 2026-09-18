import { defineConfig } from "vitest/config";

// Node environment: the tested units (reducer, SSE parser) are DOM-free on
// purpose. jsdom would slow the suite without adding coverage.
export default defineConfig({
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});