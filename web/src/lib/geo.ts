import "server-only";
import { getCloudflareContext } from "@opennextjs/cloudflare";

/**
 * GeoJSON の読み込み。
 *
 * Workers にファイルシステムは無いので、GeoJSON は静的アセットとして配る。
 * `scripts/copy-geo-assets.mjs` が data/processed から public/geo へ写し、
 * ビルドで .open-next/assets に入る。ここは ASSETS バインディング経由で読む
 * （公開 URL への外向き HTTP ではなく、ワーカー内部の呼び出し。egress も掛からない）。
 *
 * `next dev` でも ASSETS バインディング自体は生えているが、その実体は
 * wrangler.jsonc が指す .open-next/assets（前回ビルドの成果物）で、
 * public/ を直しても反映されない。開発時だけ public/geo を直接読む。
 *
 * ブラウザへ素通しするだけの GeoJSON（河川）はここを通さない。
 * MapPage が /geo/*.geojson を直接 fetch する（Worker の CPU もメモリも使わない）。
 */

export type FeatureCollection = {
  type: "FeatureCollection";
  features: { type: "Feature"; geometry: unknown; properties: Record<string, unknown> }[];
};

declare global {
  var __ryuikiGeo: Map<string, FeatureCollection> | undefined;
}
/** isolate が生きている間だけのキャッシュ。本番では捨てられる前提で、当たればもうけ。 */
const cache = (globalThis.__ryuikiGeo ??= new Map<string, FeatureCollection>());

export async function loadGeoJson(name: string): Promise<FeatureCollection> {
  const hit = cache.get(name);
  if (hit) return hit;
  const fc = process.env.NODE_ENV === "development" ? await fromPublicDir(name) : await fromAssets(name);
  cache.set(name, fc);
  return fc;
}

async function fromAssets(name: string): Promise<FeatureCollection> {
  const { env } = await getCloudflareContext({ async: true });
  if (!env.ASSETS) {
    throw new Error("ASSETS バインディングが無い。wrangler.jsonc の assets を確認する。");
  }
  // ASSETS.fetch は絶対 URL を要求するが、ホスト名は使われない
  const res = await env.ASSETS.fetch(new URL(`/geo/${name}`, "https://assets.local"));
  if (!res.ok) {
    throw new Error(
      `静的アセット /geo/${name} が無い (${res.status})。ビルド前に npm run prepare:geo が通っているか確認する。`,
    );
  }
  return (await res.json()) as FeatureCollection;
}

async function fromPublicDir(name: string): Promise<FeatureCollection> {
  const [fs, path] = await Promise.all([import("node:fs/promises"), import("node:path")]);
  const file = path.join(process.cwd(), "public", "geo", name);
  return JSON.parse(await fs.readFile(file, "utf8")) as FeatureCollection;
}

/** 0.01度メッシュの ID から矩形ポリゴンを作る */
export function meshPolygon(mlat: number, mlon: number): number[][][] {
  const lat0 = mlat / 100;
  const lon0 = mlon / 100;
  const lat1 = lat0 + 0.01;
  const lon1 = lon0 + 0.01;
  return [
    [
      [lon0, lat0],
      [lon1, lat0],
      [lon1, lat1],
      [lon0, lat1],
      [lon0, lat0],
    ],
  ];
}
