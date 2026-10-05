// serving-diff（web/scripts/serving-diff.mts）を素の Node（tsx）で走らせるためのプリロード
// スクリプト。
//
//   npx tsx --import ./scripts/lib/serving/register-aliases.mjs ./scripts/serving-diff.mts
//
// 差し替えるのは1つだけ:
//   bare specifier "server-only" -> node_modules/server-only/empty.js（本物の index.js は
//   常に throw する。Next.js の "react-server" 条件下だけ empty.js に切り替わるが、
//   tsx で素の Node として走らせるとその条件が付かないため、`lib/cube` の
//   `import "server-only"` で即死ぬ。vitest.config.ts の `resolve.alias` が使うのと
//   同じファイルを指す——空モジュールを別々に2つ持たない）。
//
// PR-4 までは `web/src/lib/db.ts` の絶対パスを `v1-db-shim.ts` に差し替えて
// `web/src/lib/queries.ts` の v1 関数を無変更で呼んでいたが、v1 の oracle を
// `v1-queries.ts`（このディレクトリ。`../v1-db-shim` を直接 import する）へ移したので
// 差し替えは不要になった。
//
// `Module._resolveFilename` を直接パッチする理由: この web/package.json には
// `"type": "module"` が無く、tsx は無印の .ts を CommonJS の require() 経路で読む。
// CommonJS の require() は Node の ESM ローダーフックの対象外なので、tsconfig-paths 等と
// 同じ手でここを差し替える。
import Module from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
// vitest.config.ts の `resolve.alias["server-only"]` と同じファイル。
const SHIM_SERVER_ONLY_ABS = path.resolve(HERE, "../../../node_modules/server-only/empty.js");

const originalResolveFilename = Module._resolveFilename;

Module._resolveFilename = function servingDiffResolveFilename(request, parent, isMain, options) {
  if (request === "server-only") {
    return SHIM_SERVER_ONLY_ABS;
  }
  return originalResolveFilename.call(this, request, parent, isMain, options);
};
