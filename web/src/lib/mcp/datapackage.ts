/**
 * `dist/datapackage.json`（配布物の目録。担当 P が作る）の読み出し。MCP の `export_dataset` が使う。
 *
 * 配布物の置き場・配信は Phase D のスコープ外（R2 は未実施）。静的アセットとして
 * `/dist/datapackage.json` が配られているときだけ読み、無ければ null（呼び出し側が
 * `available: false` を返す。黙って空のパッケージを作らない）。
 * geo.ts と同じく、Workers は ASSETS バインディング、`next dev` は public/ を直接読む。
 */
export async function loadDatapackage(): Promise<unknown | null> {
  if (process.env.NODE_ENV === "development") {
    const [fs, path] = await Promise.all([import("node:fs/promises"), import("node:path")]);
    try {
      return JSON.parse(await fs.readFile(path.join(process.cwd(), "public", "dist", "datapackage.json"), "utf8"));
    } catch {
      return null;
    }
  }
  const { getCloudflareContext } = await import("@opennextjs/cloudflare");
  const { env } = await getCloudflareContext({ async: true });
  if (!env.ASSETS) return null;
  const res = await env.ASSETS.fetch(new URL("/dist/datapackage.json", "https://assets.local"));
  return res.ok ? await res.json() : null;
}
