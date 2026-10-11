/**
 * 地図の重ね合わせ層 API（土砂災害警戒区域・保護区ポリゴン）の共通部品。Issue #105。
 * bbox の解釈、出典の注意書き（`sources[].note`。registry/source/access.yaml が正）、GeoJSON の組み立て。
 */
import { sourceAccess, sourceCitation } from "@/lib/cube/source-meta";

export interface Bbox {
  w: number;
  s: number;
  e: number;
  n: number;
}

/** `bbox=w,s,e,n`。無い・数でない・w>=e・s>=n・範囲外は null（呼び出し側が 400 にする）。 */
export function parseBbox(v: string | null): Bbox | null {
  if (!v) return null;
  const p = v.split(",");
  if (p.length !== 4 || p.some((x) => x.trim() === "")) return null;
  const [w, s, e, n] = p.map(Number);
  if (![w, s, e, n].every(Number.isFinite)) return null;
  if (w >= e || s >= n || w < -180 || e > 180 || s < -90 || n > 90) return null;
  return { w, s, e, n };
}

/** bbox を `margin` 度だけ広げ、`range` 条件（緯度・経度の列名を渡す）にする。 */
export function bboxRange(b: Bbox, lat: string, lon: string, margin: number) {
  return [
    { col: lat, min: b.s - margin, max: b.n + margin },
    { col: lon, min: b.w - margin, max: b.e + margin },
  ];
}

export interface OverlaySource {
  source_id: string;
  note: string | null;
  license: string | null;
}

/** 応答の `sources`。note は access.yaml の note（取れる出典の補足）、license は現行の版のライセンス表示名。 */
export function overlaySources(ids: readonly string[]): OverlaySource[] {
  return ids.map((id) => {
    const a = sourceAccess(id);
    return { source_id: id, note: a && a.state === "queryable" ? a.reasonNote : null, license: sourceCitation(id).license };
  });
}

/** `geometry_geojson`（文字列）を Feature に。壊れた値・欠けた値の行は落とす。 */
export function polygonFeature(geom: unknown, properties: Record<string, unknown>) {
  if (typeof geom !== "string" || !geom) return [];
  try {
    return [{ type: "Feature" as const, geometry: JSON.parse(geom) as unknown, properties }];
  } catch {
    return [];
  }
}

export const OVERLAY_CACHE = { "Cache-Control": "public, max-age=300" } as const;

/* 土砂災害警戒区域 */
export const HAZARD_SOURCE_ID = "bodik_kagoshima_dosha_amami";
/** 上限（これを超えたら truncated）。1 件約 0.8KB なので 2,500 件で約 2MB。 */
export const HAZARD_MAX = 2500;
/**
 * bbox を広げる度数。代表点（centroid）で絞るので、画面に掛かるポリゴンの取りこぼしを防ぐ余白。
 * 奄美 6,038 区域の外接幅の最大は 0.0112 度（緯度方向。代表点から縁まで最大 0.0074 度）。
 */
export const HAZARD_BBOX_MARGIN = 0.012;

/* 保護区ポリゴン */
/** 奄美の国土数値情報（A10 自然公園・A15 鳥獣保護区・A45 国有林）。神奈川の保護区は点だけでポリゴンが無い。 */
export const POLYGON_SOURCE_IDS = ["nlni_a10_natparks_amami", "nlni_a15_wildlife_amami", "nlni_a45_forest_amami"] as const;
/**
 * A45 の bbox を広げる度数。代表点（lat/lon）で絞る。小班 940 件の外接幅の最大は 0.0275 度
 * （代表点から縁まで最大 0.0137 度）なので 0.05 度で取りこぼさない。
 */
export const A45_BBOX_MARGIN = 0.05;
export const POLYGON_MAX = 1000;

