import path from "node:path";
import { defineConfig } from "vitest/config";

/**
 * このリポジトリで最初に入れる vitest 設定（Phase A, docs/plans/PHASE_A.md §A-1）。
 * `@` エイリアスは tsconfig.json の paths（"@/*": ["./src/*"]）に合わせてある。
 *
 *   pnpm run test  -> vitest run
 *
 * `scripts/**\/*.test.ts` は Issue #48 PR-1（serving-diff、1c）が足した。
 * `web/scripts/lib/serving/{classify,mutations,normalize,report}.test.ts` は
 * フィクスチャだけで完結し DB を読まないので、`src/**` と同じ node 環境でそのまま動く。
 * `adapters-v1.test.ts` は `web/src/lib/queries.ts` を import するので、
 * `server-only`（Next.js の "react-server" 条件が無い素の vitest/node 実行では
 * 本来 throw する）を空モジュールに逃がす alias が要る（`node_modules/server-only/
 * empty.js` は Next.js が "react-server" 条件下で使うのと同じ空ファイル）。
 */
export default defineConfig({
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
      "server-only": path.resolve(__dirname, "./node_modules/server-only/empty.js"),
    },
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts", "src/**/*.test.tsx", "scripts/**/*.test.ts"],
  },
});
