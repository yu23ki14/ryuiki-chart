import "server-only";
import { readStaticJson } from "./static-assets";

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
  const fc = (await readStaticJson(`/geo/${name}`)) as FeatureCollection | null;
  if (!fc) {
    throw new Error(
      `静的アセット /geo/${name} が無い。ビルド前に npm run prepare:geo が通っているか、wrangler.jsonc の assets を確認する。`,
    );
  }
  cache.set(name, fc);
  return fc;
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
