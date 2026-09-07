import path from "node:path";
import { defineConfig } from "vitest/config";

/**
 * このリポジトリで最初に入れる vitest 設定（Phase A, docs/plans/PHASE_A.md §A-1）。
 * `@` エイリアスは tsconfig.json の paths（"@/*": ["./src/*"]）に合わせてある。
 *
 *   pnpm run test  -> vitest run
 */
export default defineConfig({
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
  },
});
