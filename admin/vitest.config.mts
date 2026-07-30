import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";

export default defineConfig({
  // Cast works around the vite/vitest dual-version Plugin type mismatch, exactly as in
  // storefront/vitest.config.mts: @vitejs/plugin-react returns a rolldown-typed Plugin
  // but vitest bundles its own rollup-typed vite. Runtime is fine; only the types differ.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  plugins: [react() as any],
  test: {
    environment: "jsdom",
    setupFiles: ["./vitest.setup.ts"],
    globals: true,
    env: { TZ: "UTC" },
  },
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
});
