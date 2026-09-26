import path from "node:path";
import { defineConfig } from "vitest/config";

/**
 * このリポジトリで最初に入れる vitest 設定（Phase A, docs/plans/PHASE_A.md §A-1）。
 * `@` エイリアスは tsconfig.json の paths（"@/*": ["./src/*"]）に合わせてある。
 *
 *   pnpm run test  -> vitest run
 *
 * `server-only` エイリアス（Issue #48 PR-1a, design §7）: `server-only` パッケージは
 * デフォルト（"default" 条件）で import すると例外を投げる（"react-server" 条件でだけ
 * 空の `empty.js` になる）。vitest は Node 環境（"react-server" 条件を持たない）なので、
 * 何もしないとサーバ専用のマーカーを付けたモジュール（`@/lib/db` 等）を import した
 * 時点で落ちる。`lib/cube` は `@/lib/db` の `D1_MAX_BOUND_PARAMS`/`getD1` に依存するため
 * （`lib/cube/db.ts`/`db-d1.ts`）、このエイリアスで `server-only` を空モジュールに
 * 差し替える（`server-only` パッケージ自体が `react-server` 条件向けに同梱している
 * `empty.js` を使う）。`getD1()` を実行時に呼べば（Cloudflare コンテキストが無いので）
 * 落ちるが、`lib/cube` は `CubeDb` を引数で受ける設計にしてあるので、テストは
 * `db-sqlite.ts`/インメモリだけで動く（`getD1()` 自体は呼ばない）。
 *
 * `scripts/**\/*.test.ts` は Issue #48 PR-1（serving-diff、1c）が足した。
 * `web/scripts/lib/serving/{classify,mutations,normalize,report}.test.ts` は
 * フィクスチャだけで完結し DB を読まないので、`src/**` と同じ node 環境でそのまま動く。
 * `adapters-v1.ts` は `web/src/lib/queries.ts`（`server-only` マーカー付き）を import
 * するので、これを import するテストが将来足されたときも同じ `server-only` alias に
 * 乗って空モジュールへ逃げる（1a と 1c は同じエイリアスを共有する）。
 */
export default defineConfig({
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
      "server-only": path.resolve(__dirname, "node_modules/server-only/empty.js"),
    },
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts", "src/**/*.test.tsx", "scripts/**/*.test.ts"],
  },
});
