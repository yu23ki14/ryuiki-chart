/**
 * 流域の属性と境界の問い合わせ（MCP の `get_watersheds`。ADR-0014: 画面・API・MCP・AI は同じ問い合わせ層を共有）。
 *
 * 属性（名前・面積・unit_kind・主な河川・重心）は D1 の `place`／`place_watershed`（registry 由来）を正とする。
 * 静的アセット `/geo/watersheds.geojson` からは、D1 に無い境界（geometry）と河口の座標（outlet_lat/outlet_lon。
 * 奄美の DEM 流域だけが持つ）だけを取る。GeoJSON の `properties.watershed_id` と place_id の対応は
 * `placeIdOfWatershedId`／`watershedIdOfPlaceId`（`cube/grid.ts`）が唯一の規則:
 * `common:place:watershed.nlni.<id>` ⇔ `<id>`、`common:place:watershed.dem.<key>` ⇔ `dem-<key>`。
 */
import type { CubeDb, SqlParam } from "@/lib/cube/db";
import { placeIdOfWatershedId } from "@/lib/cube/grid";
import { jsonEachParam, uniq } from "@/lib/cube/sql";
import type { RegionId } from "@/lib/region";

export const WATERSHED_GEOJSON_PATH = "/geo/watersheds.geojson";
export const WATERSHED_ID_RULE =
  "GeoJSON の properties.watershed_id から place_id へは、数字だけの ID（例 83030-0001）は 'common:place:watershed.nlni.' + ID、" +
  "'dem-' で始まる ID（例 dem-amami-039）は 'common:place:watershed.dem.' + 'dem-' を除いた残り（amami-039）";

export interface WatershedRow {
  place_id: string;
  region: string | null;
  name: string | null;
  area_km2: number | null;
  unit_kind: string | null;
  merged_share: number | null;
  own_drainage_km2: number | null;
  main_rivers: string | null;
  outlet_lat: number | null;
  outlet_lon: number | null;
  centroid_lat: number | null;
  centroid_lon: number | null;
  source_id: string | null;
  /** include_geometry のときだけ。GeoJSON の geometry のまま。 */
  geometry?: unknown;
}

export interface GeoFeatureLike {
  geometry: unknown;
  properties: Record<string, unknown>;
}
export type GeoLoader = () => Promise<{ features: GeoFeatureLike[] }>;

export interface WatershedsOpt {
  region?: RegionId;
  placeIds?: readonly string[];
  includeGeometry?: boolean;
  /** 取得する最大行数（打ち切りの判定用に呼び出し側が +1 を渡す）。 */
  limit?: number;
}

type R = Record<string, string | number | null>;

const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);

/** 既定の GeoJSON 読み出し口（静的アセット）。`geo.ts` は server-only なので、使うときに読み込む。 */
const defaultGeoLoader: GeoLoader = async () => (await import("@/lib/geo")).loadGeoJson("watersheds.geojson");

export async function watersheds(db: CubeDb, opt: WatershedsOpt = {}, loadGeo: GeoLoader = defaultGeoLoader): Promise<WatershedRow[]> {
  const params: SqlParam[] = [];
  let where = "p.place_kind = 'watershed'";
  if (opt.region !== undefined) {
    where += " AND pr.region_id = ?";
    params.push(opt.region);
  }
  if (opt.placeIds?.length) {
    where += " AND p.place_id IN (SELECT value FROM json_each(?))";
    params.push(jsonEachParam(uniq(opt.placeIds)));
  }
  params.push(opt.limit ?? 1000);
  const rows = await db.all<R>(
    `SELECT p.place_id AS place_id, pr.region_id AS region_id, p.name_ja AS name, p.area_km2 AS area_km2,
            p.lat AS lat, p.lon AS lon,
            w.unit_kind AS unit_kind, w.merged_share AS merged_share, w.own_drainage_km2 AS own_drainage_km2,
            w.main_rivers AS main_rivers, e.source_id AS source_id
     FROM place p
     LEFT JOIN place_watershed w ON w.place_id = p.place_id
     LEFT JOIN place_region pr ON pr.place_id = p.place_id
     LEFT JOIN place_source_ref sr ON sr.place_id = p.place_id AND sr.key_space = 'watershed_id'
     LEFT JOIN source_edition e ON e.edition_id = sr.source_edition_id
     WHERE ${where}
     ORDER BY p.place_id LIMIT ?`,
    params,
  );

  // 境界と河口は静的アセットから。全面を読むのは geometry か outlet が要るときで、いまは outlet が常に要る。
  const features = new Map<string, GeoFeatureLike>();
  for (const f of (await loadGeo()).features) {
    const wid = f.properties.watershed_id;
    if (typeof wid === "string") features.set(placeIdOfWatershedId(wid), f);
  }

  return rows.map((r) => {
    const f = features.get(r.place_id as string);
    const out: WatershedRow = {
      place_id: r.place_id as string,
      region: (r.region_id as string | null) ?? null,
      name: (r.name as string | null) ?? null,
      area_km2: num(r.area_km2),
      unit_kind: (r.unit_kind as string | null) ?? null,
      merged_share: num(r.merged_share),
      own_drainage_km2: num(r.own_drainage_km2),
      // 主要河川が無い流域は空文字列のまま持つ（NULL に丸めない。place_watershed の規約）
      main_rivers: (r.main_rivers as string | null) ?? null,
      outlet_lat: num(f?.properties.outlet_lat),
      outlet_lon: num(f?.properties.outlet_lon),
      centroid_lat: num(r.lat),
      centroid_lon: num(r.lon),
      source_id: (r.source_id as string | null) ?? null,
    };
    if (opt.includeGeometry) out.geometry = f?.geometry ?? null;
    return out;
  });
}
