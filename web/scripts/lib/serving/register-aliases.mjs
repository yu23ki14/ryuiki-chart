// serving-diff（web/scripts/serving-diff.mts）が v1 アダプタ（web/scripts/lib/serving/adapters-v1.ts）
// 経由で `web/src/lib/queries.ts` を **無変更で** 呼ぶための、CommonJS require の解決を
// 差し替えるプリロードスクリプト。
//
//   npx tsx --import ./scripts/lib/serving/register-aliases.mjs ./scripts/serving-diff.mts
//
// 何を差し替えるか（2つだけ）:
//   1. bare specifier "server-only" -> 空モジュール（本物は index.js が常に throw する。
//      Next.js の "react-server" 条件下だけ empty.js に切り替わるが、tsx で素の Node
//      として走らせるとその条件が付かないため、放っておくと queries.ts の
//      `import "server-only"` で即死ぬ）。
//   2. `web/src/lib/db.ts` の絶対パス -> この隣の `v1-db-shim.ts`（better-sqlite3 で
//      ryuiki/cells/derived を ATTACH し、`query`/`queryOne`/`queryChunked`/`ph` を
//      同じシグネチャで実装したもの）。
//
// なぜ tsconfig の `paths`（設計書 §9-2 で「未検証」としていたもの）ではなく
// この方式か: `queries.ts` は `import { query, ... } from "./db"` と **相対** specifier
// で db.ts を読んでいる。TypeScript/tsx の `paths` は非相対（bare）specifier しか
// 書き換えない仕様なので、"@/lib/db" を書き換えても "./db" は素通りする（実機で確認
// 済み——tsx --tsconfig で "./db" 相対import は無視されることを実験して確認した）。
// 加えて、この web/package.json には `"type": "module"` が無く、tsx は無印の .ts を
// CommonJS の require() 経路で読み込む（`node --import tsx/esm` を素で使うと
// ERR_REQUIRE_CYCLE_MODULE で落ちることも確認済み。tsx 自身の CLI はこの経路を
// うまく吸収する）。CommonJS の require() は Node の ESM ローダーフック
// （`module.register`/`resolve`/`load`）の対象外なので、`Module._resolveFilename`
// を直接パッチする（tsconfig-paths 等の既存ツールも同じ手を使う、広く使われている
// 手法）。解決後の絶対パスで比較するので、呼び出し側が相対・絶対どちらの specifier
// で書いていても効く。
import Module from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REAL_DB_ABS = path.resolve(HERE, "../../../src/lib/db.ts");
const SHIM_DB_ABS = path.resolve(HERE, "../v1-db-shim.ts");
const SHIM_SERVER_ONLY_ABS = path.resolve(HERE, "server-only-shim.ts");

const originalResolveFilename = Module._resolveFilename;

Module._resolveFilename = function servingDiffResolveFilename(request, parent, isMain, options) {
  if (request === "server-only") {
    return SHIM_SERVER_ONLY_ABS;
  }
  const resolved = originalResolveFilename.call(this, request, parent, isMain, options);
  if (resolved === REAL_DB_ABS) {
    return SHIM_DB_ABS;
  }
  return resolved;
};
