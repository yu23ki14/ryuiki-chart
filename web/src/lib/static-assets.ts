import { getCloudflareContext } from "@opennextjs/cloudflare";

/**
 * 静的アセット（`public/` 配下 = ビルドで `.open-next/assets` に入るもの）の JSON 読み出し口（1か所）。
 * `geo.ts`（GeoJSON）と `mcp/datapackage.ts`（配布物の目録）が共有する。
 *
 * Workers にファイルシステムは無いので、本番は ASSETS バインディング（ワーカー内部の呼び出し。egress なし）。
 * `next dev` では ASSETS の実体が前回ビルドの成果物で `public/` の修正が反映されないので、開発時だけ `public/` を直接読む。
 */

/** 見つからなければ null（読み出し側が「無い」を扱う）。`urlPath` は `/geo/x.geojson` のようなサイトルート相対。 */
export async function readStaticJson(urlPath: string): Promise<unknown | null> {
  if (process.env.NODE_ENV === "development") {
    const [fs, path] = await Promise.all([import("node:fs/promises"), import("node:path")]);
    try {
      return JSON.parse(await fs.readFile(path.join(process.cwd(), "public", urlPath), "utf8"));
    } catch {
      return null;
    }
  }
  const { env } = await getCloudflareContext({ async: true });
  if (!env.ASSETS) return null;
  // ASSETS.fetch は絶対 URL を要求するが、ホスト名は使われない
  const res = await env.ASSETS.fetch(new URL(urlPath, "https://assets.local"));
  return res.ok ? await res.json() : null;
}
