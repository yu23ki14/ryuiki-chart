/**
 * カタログ系の問い合わせ（design §3.4）。PR-1 は問い合わせ時計算（`CatalogSource: "live"`）。
 * PR-2 で事前計算した summary 表（`summary_variable_catalog` 等）に差し替える口を
 * `CatalogSource` として残してある（今はどの関数も `"live"` 固定）。
 *
 * `dataset` の絞り込みは `variable_alias` との JOIN で行う（`registry.sqlite`/D1 の
 * 生テーブルを直接読む。`series.ts`/`generated.ts` の中身が古くても常に最新の状態を反映する）。
 */
import type { CubeDb, SqlParam } from "./db";
import { MAX_ID_LIST } from "./db";
import { jsonEachParam } from "./sql";
import { seriesKeySql, seriesKeyString, type SeriesKey } from "./series";

export type CatalogSource = { kind: "live" } | { kind: "summary" };

const YEAR_GRAINS_SQL = "obs.grain IN ('year','fiscal_year')";
const MEAN_STAT_SQL = "obs.stat = 'mean'";

export interface SeriesCatalogRow {
  series: SeriesKey;
  seriesKey: string;
  inputGrain: string;
  n: number;
  nPlaces: number;
  yFrom: number;
  yTo: number;
  nDaily: number;
  nAnnual: number;
  nCensored: number;
}

interface CatalogRawRow {
  variable_id: string;
  obs_stat: string | null;
  unit_id: string | null;
  value_grain: string | null;
  input_grain: string;
  n: number;
  n_places: number;
  y_from: number;
  y_to: number;
  n_daily: number;
  n_annual: number;
  n_censored: number;
}

function toSeriesCatalogRow(r: CatalogRawRow): SeriesCatalogRow {
  const series: SeriesKey = { variableId: r.variable_id, obsStat: r.obs_stat, unitId: r.unit_id, valueGrain: r.value_grain ?? "" };
  return {
    series,
    seriesKey: seriesKeyString(series),
    inputGrain: r.input_grain,
    n: r.n,
    nPlaces: r.n_places,
    yFrom: r.y_from,
    yTo: r.y_to,
    nDaily: r.n_daily,
    nAnnual: r.n_annual,
    nCensored: r.n_censored,
  };
}

const VARIABLE_CATALOG_SQL = `
  SELECT obs.variable_id, obs.obs_stat, obs.unit_id, obs.value_grain, obs.input_grain,
         SUM(obs.n) AS n, COUNT(DISTINCT obs.place_id) AS n_places,
         MIN(CAST(substr(obs.period_start,1,4) AS INTEGER)) AS y_from,
         MAX(CAST(substr(obs.period_start,1,4) AS INTEGER)) AS y_to,
         SUM(CASE WHEN obs.input_grain = 'day' THEN obs.n ELSE 0 END) AS n_daily,
         SUM(CASE WHEN obs.input_grain = obs.grain THEN obs.n ELSE 0 END) AS n_annual,
         SUM(obs.n_censored) AS n_censored
  FROM observation_agg obs
  WHERE obs.place_kind = 'site' AND ${YEAR_GRAINS_SQL} AND ${MEAN_STAT_SQL}
  GROUP BY obs.variable_id, obs.obs_stat, obs.unit_id, obs.value_grain, obs.input_grain
  ORDER BY n DESC
`;

/**
 * 系列単位の指標カタログ（v1 `var_catalog` の系列版。design §1.1・§3.4）。
 *
 * `dataset` を指定したときは `variable_alias` との JOIN で絞り込む……のを愚直に
 * 「(variable_id, value_grain, obs_stat, unit_id) の組が dataset の組の集合に含まれるか」
 * という等値条件（`COALESCE` で正準化した4列の文字列連結）で書くと、`observation_agg`
 * （200万行超）に索引の効かない結合（SQLite が `dataset` 側を外側ループにして
 * `observation_agg` を毎回全表スキャンする）になり実測 33 秒かかった。
 * `variable_id` 単体は既存索引の先頭列で絞れる（実測 1.5 秒）ので、SQL 側は
 * `variable_id ∈ dataset の distinct variable_id` までに留め、
 * 残り3列（value_grain/obs_stat/unit_id）の厳密一致と集計は JS 側で行う
 * （変換後の行数は高々 12 万行程度で、JS 側の Map 集計は数十 ms）。
 */
export async function variableCatalog(db: CubeDb, opt?: { dataset?: string }): Promise<SeriesCatalogRow[]> {
  if (!opt?.dataset) {
    const rows = await db.all<CatalogRawRow>(VARIABLE_CATALOG_SQL);
    return rows.map(toSeriesCatalogRow);
  }
  return variableCatalogByDataset(db, opt.dataset);
}

interface DatasetTupleRow {
  variable_id: string;
  g: string;
  st: string;
  u: string;
}

async function variableCatalogByDataset(db: CubeDb, dataset: string): Promise<SeriesCatalogRow[]> {
  const dsRows = await db.all<DatasetTupleRow>(
    `SELECT DISTINCT variable_id, COALESCE(grain,'') AS g, COALESCE(stat,'') AS st, COALESCE(unit_id,'') AS u
     FROM variable_alias WHERE dataset = ?`,
    [dataset],
  );
  if (dsRows.length === 0) return [];

  const variableIds = [...new Set(dsRows.map((r) => r.variable_id))];
  const tupleSet = new Set(dsRows.map((r) => `${r.variable_id}|${r.g}|${r.st}|${r.u}`));

  interface RawCell {
    variable_id: string;
    obs_stat: string | null;
    unit_id: string | null;
    value_grain: string | null;
    input_grain: string;
    grain: string;
    place_id: string;
    period_start: string;
    n: number;
    n_censored: number;
  }
  const cells = await db.all<RawCell>(
    `SELECT obs.variable_id, obs.obs_stat, obs.unit_id, obs.value_grain, obs.input_grain, obs.grain,
            obs.place_id, obs.period_start, obs.n, obs.n_censored
     FROM observation_agg obs
     JOIN json_each(?) vid ON vid.value = obs.variable_id
     WHERE obs.place_kind = 'site' AND ${YEAR_GRAINS_SQL} AND ${MEAN_STAT_SQL}`,
    [jsonEachParam(variableIds)],
  );

  interface Group {
    series: SeriesKey;
    inputGrain: string;
    n: number;
    places: Set<string>;
    yFrom: number;
    yTo: number;
    nDaily: number;
    nAnnual: number;
    nCensored: number;
  }
  const groups = new Map<string, Group>();
  for (const c of cells) {
    const g = c.value_grain ?? "";
    const st = c.obs_stat ?? "";
    const u = c.unit_id ?? "";
    if (!tupleSet.has(`${c.variable_id}|${g}|${st}|${u}`)) continue;

    const groupKey = `${c.variable_id}|${g}|${st}|${u}|${c.input_grain}`;
    let group = groups.get(groupKey);
    if (!group) {
      group = {
        series: { variableId: c.variable_id, obsStat: c.obs_stat, unitId: c.unit_id, valueGrain: g },
        inputGrain: c.input_grain,
        n: 0,
        places: new Set(),
        yFrom: Number.POSITIVE_INFINITY,
        yTo: Number.NEGATIVE_INFINITY,
        nDaily: 0,
        nAnnual: 0,
        nCensored: 0,
      };
      groups.set(groupKey, group);
    }
    group.n += c.n;
    group.places.add(c.place_id);
    const year = Number.parseInt(c.period_start.slice(0, 4), 10);
    if (year < group.yFrom) group.yFrom = year;
    if (year > group.yTo) group.yTo = year;
    if (c.input_grain === "day") group.nDaily += c.n;
    if (c.input_grain === c.grain) group.nAnnual += c.n;
    group.nCensored += c.n_censored;
  }

  return [...groups.values()]
    .map((g) => ({
      series: g.series,
      seriesKey: seriesKeyString(g.series),
      inputGrain: g.inputGrain,
      n: g.n,
      nPlaces: g.places.size,
      yFrom: g.yFrom,
      yTo: g.yTo,
      nDaily: g.nDaily,
      nAnnual: g.nAnnual,
      nCensored: g.nCensored,
    }))
    .sort((a, b) => b.n - a.n);
}

export interface SiteSeriesRow {
  series: SeriesKey;
  seriesKey: string;
  grain: string;
  inputGrain: string;
  n: number;
  yFrom: number;
  yTo: number;
  avg: number | null;
}

/** 索引2 (place_id, variable_id, grain) を使う経路。v1 `site_var` 相当（design §3.4）。 */
export async function siteVariables(db: CubeDb, placeId: string): Promise<SiteSeriesRow[]> {
  const sql = `
    SELECT obs.variable_id, obs.obs_stat, obs.unit_id, obs.value_grain, obs.grain, obs.input_grain,
           SUM(obs.n) AS n,
           MIN(CAST(substr(obs.period_start,1,4) AS INTEGER)) AS y_from,
           MAX(CAST(substr(obs.period_start,1,4) AS INTEGER)) AS y_to,
           AVG(obs.value_zero) AS avg
    FROM observation_agg obs
    WHERE obs.place_id = ? AND obs.place_kind = 'site' AND ${YEAR_GRAINS_SQL} AND ${MEAN_STAT_SQL}
    GROUP BY obs.variable_id, obs.obs_stat, obs.unit_id, obs.value_grain, obs.grain, obs.input_grain
    ORDER BY n DESC
  `;
  const rows = await db.all<{
    variable_id: string;
    obs_stat: string | null;
    unit_id: string | null;
    value_grain: string | null;
    grain: string;
    input_grain: string;
    n: number;
    y_from: number;
    y_to: number;
    avg: number | null;
  }>(sql, [placeId]);

  return rows.map((r) => {
    const series: SeriesKey = { variableId: r.variable_id, obsStat: r.obs_stat, unitId: r.unit_id, valueGrain: r.value_grain ?? "" };
    return {
      series,
      seriesKey: seriesKeyString(series),
      grain: r.grain,
      inputGrain: r.input_grain,
      n: r.n,
      yFrom: r.y_from,
      yTo: r.y_to,
      avg: r.avg,
    };
  });
}

export interface SiteRow2 {
  siteId: string;
  name: string | null;
  nameEn: string | null;
  watershed: string | null;
  zone: number | null;
  lat: number | null;
  lon: number | null;
  elevationM: number | null;
  municipality: string | null;
  muniCode: string | null;
  treatment: string | null;
  establishedOn: string | null;
  operator: string | null;
  sourceId: string | null;
  sourceRef: string | null;
  isSynthetic: number | null;
  /** 系列（`(variable_id,obs_stat,unit_id,value_grain)` の組）の distinct 数。 */
  nSeries: number;
  /** variable_id の distinct 数。 */
  nVariables: number;
  nMeas: number;
}

const SITE_ROLLUP_SQL = `
  SELECT psr.external_key AS site_id, SUM(obs.n) AS n_meas,
         COUNT(DISTINCT (${seriesKeySql("obs")})) AS n_series,
         COUNT(DISTINCT obs.variable_id) AS n_variables
  FROM observation_agg obs
  JOIN place_source_ref psr ON psr.place_id = obs.place_id AND psr.source_id = 'sites.site_id'
  WHERE obs.place_kind = 'site' AND ${YEAR_GRAINS_SQL} AND ${MEAN_STAT_SQL}
  GROUP BY psr.external_key
`;

function toSiteRow2(r: {
  site_id: string;
  name: string | null;
  name_en: string | null;
  watershed: string | null;
  zone: number | null;
  lat: number | null;
  lon: number | null;
  elevation_m: number | null;
  municipality: string | null;
  muni_code: string | null;
  treatment: string | null;
  established_on: string | null;
  operator: string | null;
  source_id: string | null;
  source_ref: string | null;
  is_synthetic: number | null;
  n_meas: number | null;
  n_series: number | null;
  n_variables: number | null;
}): SiteRow2 {
  return {
    siteId: r.site_id,
    name: r.name,
    nameEn: r.name_en,
    watershed: r.watershed,
    zone: r.zone,
    lat: r.lat,
    lon: r.lon,
    elevationM: r.elevation_m,
    municipality: r.municipality,
    muniCode: r.muni_code,
    treatment: r.treatment,
    establishedOn: r.established_on,
    operator: r.operator,
    sourceId: r.source_id,
    sourceRef: r.source_ref,
    isSynthetic: r.is_synthetic,
    nMeas: r.n_meas ?? 0,
    nSeries: r.n_series ?? 0,
    nVariables: r.n_variables ?? 0,
  };
}

/** `sites` JOIN `place_source_ref` JOIN 年セル集計（design §3.4）。 */
export async function sites(db: CubeDb): Promise<SiteRow2[]> {
  const sql = `
    SELECT s.site_id, s.name, s.name_en, s.watershed, s.zone, s.lat, s.lon, s.elevation_m,
           s.municipality, s.muni_code, s.treatment, s.established_on, s.operator, s.source_id, s.source_ref, s.is_synthetic,
           COALESCE(v.n_meas, 0) AS n_meas, COALESCE(v.n_series, 0) AS n_series, COALESCE(v.n_variables, 0) AS n_variables
    FROM sites s
    LEFT JOIN (${SITE_ROLLUP_SQL}) v ON v.site_id = s.site_id
    ORDER BY s.zone, s.elevation_m DESC
  `;
  const rows = await db.all<Parameters<typeof toSiteRow2>[0]>(sql);
  return rows.map(toSiteRow2);
}

export async function sitesInWaterBody(db: CubeDb, municipality: string): Promise<SiteRow2[]> {
  const sql = `
    SELECT s.site_id, s.name, s.name_en, s.watershed, s.zone, s.lat, s.lon, s.elevation_m,
           s.municipality, s.muni_code, s.treatment, s.established_on, s.operator, s.source_id, s.source_ref, s.is_synthetic,
           COALESCE(v.n_meas, 0) AS n_meas, COALESCE(v.n_series, 0) AS n_series, COALESCE(v.n_variables, 0) AS n_variables
    FROM sites s
    JOIN (${SITE_ROLLUP_SQL}) v ON v.site_id = s.site_id
    WHERE s.municipality = ?
    ORDER BY s.elevation_m DESC
  `;
  const rows = await db.all<Parameters<typeof toSiteRow2>[0]>(sql, [municipality]);
  return rows.map(toSiteRow2);
}

export interface WaterBodyRow {
  name: string;
  nSites: number;
  elevMin: number | null;
  elevMax: number | null;
  zoneMin: number | null;
  zoneMax: number | null;
  nMeas: number;
  yFrom: number | null;
  yTo: number | null;
}

/** 測定値を持つ地点が2つ以上ある「水域・地域」（v1 `listWaterBodies`/`waterBodiesForVariable` 統合。design §3.4）。 */
export async function waterBodies(db: CubeDb, opt?: { series?: SeriesKey[] }): Promise<WaterBodyRow[]> {
  const params: SqlParam[] = [];
  const joins: string[] = [];
  if (opt?.series && opt.series.length > 0) {
    if (opt.series.length > MAX_ID_LIST) throw new Error(`waterBodies: series が ${opt.series.length} 件で上限 ${MAX_ID_LIST} を超えている`);
    joins.push(`JOIN json_each(?) sk ON sk.value = ${seriesKeySql("obs")}`);
    params.push(jsonEachParam(opt.series.map(seriesKeyString)));
  }

  const sql = `
    SELECT s.municipality AS name,
           COUNT(DISTINCT s.site_id) AS n_sites,
           MIN(s.elevation_m) AS elev_min, MAX(s.elevation_m) AS elev_max,
           MIN(s.zone) AS zone_min, MAX(s.zone) AS zone_max,
           SUM(v.n) AS n_meas, MIN(v.y_from) AS y_from, MAX(v.y_to) AS y_to
    FROM sites s
    JOIN (
      SELECT psr.external_key AS site_id, SUM(obs.n) AS n,
             MIN(CAST(substr(obs.period_start,1,4) AS INTEGER)) AS y_from,
             MAX(CAST(substr(obs.period_start,1,4) AS INTEGER)) AS y_to
      FROM observation_agg obs
      JOIN place_source_ref psr ON psr.place_id = obs.place_id AND psr.source_id = 'sites.site_id'
      ${joins.join("\n      ")}
      WHERE obs.place_kind = 'site' AND ${YEAR_GRAINS_SQL} AND ${MEAN_STAT_SQL}
      GROUP BY psr.external_key
    ) v ON v.site_id = s.site_id
    WHERE s.municipality IS NOT NULL AND s.municipality <> ''
    GROUP BY s.municipality
    HAVING n_sites >= 2
    ORDER BY n_meas DESC
  `;
  const rows = await db.all<{
    name: string;
    n_sites: number;
    elev_min: number | null;
    elev_max: number | null;
    zone_min: number | null;
    zone_max: number | null;
    n_meas: number;
    y_from: number | null;
    y_to: number | null;
  }>(sql, params);

  return rows.map((r) => ({
    name: r.name,
    nSites: r.n_sites,
    elevMin: r.elev_min,
    elevMax: r.elev_max,
    zoneMin: r.zone_min,
    zoneMax: r.zone_max,
    nMeas: r.n_meas,
    yFrom: r.y_from,
    yTo: r.y_to,
  }));
}
