/**
 * 流域の属性と境界の問い合わせ（MCP の `get_watersheds`。ADR-0014: 画面・API・MCP・AI は同じ問い合わせ層を共有）。
 *
 * 属性（名前・面積・unit_kind・主な河川・重心）は D1 の `place`／`place_watershed`（registry 由来）を正とする。
 * 静的アセット `/geo/watersheds.geojson` からは、D1 に無い境界（geometry）と河口の座標（outlet_lat/outlet_lon。
 * 奄美の DEM 流域だけが持つ）だけを取る。GeoJSON の `properties.watershed_id` と place_id の対応は
 * `cube/grid.ts` の `placeIdOfWatershedId`／`watershedIdOfPlaceId` が唯一の規則（`WATERSHED_ID_RULE` がその説明）。
 */
import type { CubeDb, SqlParam } from "@/lib/cube/db";
import { placeIdOfWatershedId, WATERSHED_ID_RULE } from "@/lib/cube/grid";
import { jsonEachParam, uniq } from "@/lib/cube/sql";
import type { RegionId } from "@/lib/region";

export { WATERSHED_ID_RULE };
export const WATERSHED_GEOJSON_PATH = "/geo/watersheds.geojson";

/** 流域単位の集計（watershed_years・placeId を付けた species_catalog）に入らない記録の説明。get_occurrences と get_watersheds の説明が共有する。 */
export const OUTSIDE_WATERSHED_NOTE =
  "流域に入らない記録（海上・流域の外）は流域の集計（watershed_years、placeId を付けた species_catalog）に入らないので、" +
  "流域ごとの合計は地域の全記録より少ない。測点が流域に入っているかは get_records（record_set=sites）の watershed 列で取れる。";

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
  /** 取得する最大行数。 */
  limit: number;
}

export interface WatershedsResult {
  rows: WatershedRow[];
  /** limit で切る前の、条件に合う流域の総数。 */
  nTotal: number;
  /** `placeIds` のうち、条件（地域）に合う流域が無かったもの（limit とは無関係に判定する）。 */
  notFound: string[];
}

type R = Record<string, string | number | null>;

const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);

/** 既定の GeoJSON 読み出し口（静的アセット）。`geo.ts` は server-only なので、使うときに読み込む。 */
const defaultGeoLoader: GeoLoader = async () => (await import("@/lib/geo")).loadGeoJson("watersheds.geojson");

function filters(opt: Pick<WatershedsOpt, "region" | "placeIds">): { where: string; params: SqlParam[] } {
  const params: SqlParam[] = [];
  let where = "p.place_kind = 'watershed'";
  if (opt.region !== undefined) {
    where += " AND EXISTS (SELECT 1 FROM place_region pr WHERE pr.place_id = p.place_id AND pr.region_id = ?)";
    params.push(opt.region);
  }
  if (opt.placeIds?.length) {
    where += " AND p.place_id IN (SELECT value FROM json_each(?))";
    params.push(jsonEachParam(uniq(opt.placeIds)));
  }
  return { where, params };
}

export async function watersheds(db: CubeDb, opt: WatershedsOpt, loadGeo: GeoLoader = defaultGeoLoader): Promise<WatershedsResult> {
  const f = filters(opt);
  // 行が重複しない理由: place_region は 1 place につき 1 地域（b13 が 2 地域に出たら止める）。place_source_ref は
  // 1 place に版違いの watershed_id 行が複数ありうるので、最新（id 最大）の 1 行に決めて出典を引く。
  const rows = await db.all<R>(
    `SELECT p.place_id AS place_id,
            (SELECT pr.region_id FROM place_region pr WHERE pr.place_id = p.place_id) AS region_id,
            p.name_ja AS name, p.area_km2 AS area_km2, p.lat AS lat, p.lon AS lon,
            w.unit_kind AS unit_kind, w.merged_share AS merged_share, w.own_drainage_km2 AS own_drainage_km2,
            w.main_rivers AS main_rivers,
            (SELECT e.source_id FROM place_source_ref sr JOIN source_edition e ON e.edition_id = sr.source_edition_id
              WHERE sr.place_id = p.place_id AND sr.key_space = 'watershed_id' ORDER BY sr.id DESC LIMIT 1) AS source_id
     FROM place p
     LEFT JOIN place_watershed w ON w.place_id = p.place_id
     WHERE ${f.where}
     ORDER BY p.place_id LIMIT ?`,
    [...f.params, opt.limit],
  );
  const total = (await db.all<R>(`SELECT COUNT(*) AS n FROM place p WHERE ${f.where}`, f.params))[0].n as number;

  let notFound: string[] = [];
  if (opt.placeIds?.length) {
    // limit で切る前の存在確認（place_ids は最大 20 なので軽い）。
    const hit = new Set((await db.all<R>(`SELECT p.place_id AS place_id FROM place p WHERE ${f.where}`, f.params)).map((r) => r.place_id as string));
    notFound = uniq(opt.placeIds).filter((id) => !hit.has(id));
  }

  // 境界と河口は静的アセットから。河口を持つのは DEM 流域（unit_kind がある行）だけなので、境界も要らず
  // DEM 流域も無ければアセットを読まない。読んでも、必要な watershed_id の feature だけを拾う。
  const wanted = new Set(rows.filter((r) => opt.includeGeometry || r.unit_kind !== null).map((r) => r.place_id as string));
  const features = new Map<string, GeoFeatureLike>();
  if (wanted.size > 0) {
    for (const feat of (await loadGeo()).features) {
      const wid = feat.properties.watershed_id;
      if (typeof wid !== "string") continue;
      const pid = placeIdOfWatershedId(wid);
      if (wanted.has(pid)) features.set(pid, feat);
    }
  }

  return {
    nTotal: total,
    notFound,
    rows: rows.map((r) => {
      const feat = features.get(r.place_id as string);
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
        outlet_lat: num(feat?.properties.outlet_lat),
        outlet_lon: num(feat?.properties.outlet_lon),
        centroid_lat: num(r.lat),
        centroid_lon: num(r.lon),
        source_id: (r.source_id as string | null) ?? null,
      };
      if (opt.includeGeometry) out.geometry = feat?.geometry ?? null;
      return out;
    }),
  };
}
