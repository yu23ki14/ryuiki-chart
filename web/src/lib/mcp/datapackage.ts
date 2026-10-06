import { readStaticJson } from "@/lib/static-assets";

/**
 * `dist/datapackage.json`（配布物の目録。担当 P が作る）の読み出し。MCP の `export_dataset` が使う。
 *
 * 配布物の置き場・配信は Phase D のスコープ外（R2 は未実施）。静的アセットとして
 * `/dist/datapackage.json` が配られているときだけ読み、無ければ null（呼び出し側が
 * `available: false` を返す。黙って空のパッケージを作らない）。読み出し口は geo.ts と共有（`static-assets.ts`）。
 */
export async function loadDatapackage(): Promise<unknown | null> {
  return readStaticJson("/dist/datapackage.json");
}
