/**
 * チャンク数・キャッシュ・マニフェストの件数を出す。--remote を付けると Vectorize 側の件数（wrangler vectorize info。読み取りのみ）も出し、
 * マニフェストと一致するまで待つ（--wait 秒。既定 0 = 待たない）。一致しなければ非ゼロで終わる。
 *   node scripts/vector/status.mjs --cells <cells.sqlite> [--remote [--wait 300]]
 */
import fs from "node:fs";
import path from "node:path";
import { CONFIG, REPO, VECTOR_DIR, allChunks, openCache, parseArgs, readArticles, wrangler } from "./lib.mjs";

/** wrangler の出力（警告やバナーが前後に付くことがある）から最初の JSON オブジェクトを取り出す。 */
export function extractJson(out) {
  try {
    return JSON.parse(out);
  } catch {
    const a = out.indexOf("{");
    const b = out.lastIndexOf("}");
    if (a < 0 || b <= a) throw new Error(`wrangler の出力に JSON が無い: ${out.slice(0, 200)}`);
    return JSON.parse(out.slice(a, b + 1));
  }
}

const args = parseArgs(process.argv.slice(2));
const cells = args.cells || path.join(REPO, "data/db/cells.sqlite");
const index = CONFIG.index_name;
const chunks = allChunks(readArticles(cells), CONFIG.model);
const cache = openCache();
const cached = cache.prepare("SELECT count(*) AS n FROM embedding WHERE model = ?").get(CONFIG.model).n;
const mp = path.join(VECTOR_DIR, index, "manifest.jsonl");
const manifestN = fs.existsSync(mp) ? fs.readFileSync(mp, "utf8").split("\n").filter(Boolean).length : 0;
console.log(`index=${index} model=${CONFIG.model} チャンク ${chunks.length}・キャッシュ ${cached}・マニフェスト ${manifestN}`);
if (args.remote) {
  const deadline = Date.now() + Number(args.wait || 0) * 1000;
  for (;;) {
    const info = extractJson(wrangler(["vectorize", "info", index, "--json"]));
    const n = info.vectorCount ?? info.vectorsCount ?? info.vector_count;
    if (typeof n !== "number") throw new Error(`info に件数が無い（項目名が違う？）: ${Object.keys(info).join(",")}`);
    console.log(`Vectorize: ${JSON.stringify(info)}`);
    if (n === manifestN) break;
    if (Date.now() > deadline) {
      console.error(`件数が合わない: Vectorize ${n} ≠ マニフェスト ${manifestN}`);
      process.exit(1);
    }
    await new Promise((r) => setTimeout(r, 10000));
  }
}
