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
import { jsonEachParam, seriesFilterSql } from "./sql";
import { seriesKeyFromRow, seriesKeySql, seriesKeyString, type SeriesKey } from "./series";

export type CatalogSource = { kind: "live" } | { kind: "summary" };

/** `serving-diff` の v2 アダプタ（`scripts/lib/serving/adapters-v2.ts`）も
 *  同じ「年セル・mean 統計」の絞り込みを書く箇所があるため export する
 *  （テーブルエイリアスは `obs` 決め打ち——`sql.ts` の `OBS` と同じ規約）。 */
export const YEAR_GRAINS_SQL = "obs.grain IN ('year','fiscal_year')";
export const MEAN_STAT_SQL = "obs.stat = 'mean'";

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
  const series = seriesKeyFromRow(r);
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

/**
 * `dataset` を `variable_alias` から系列一覧に解決する（`variableCatalogByDataset`・
 * `datasetFilterSql` が共有する。b05 の `alias_lookup` と同じ列挙 SQL）。
 */
async function seriesForDataset(db: CubeDb, dataset: string): Promise<SeriesKey[]> {
  const rows = await db.all<DatasetTupleRow>(
    `SELECT DISTINCT variable_id, COALESCE(grain,'') AS g, COALESCE(stat,'') AS st, COALESCE(unit_id,'') AS u
     FROM variable_alias WHERE dataset = ?`,
    [dataset],
  );
  return rows.map((r) => ({ variableId: r.variable_id, obsStat: r.st || null, unitId: r.u || null, valueGrain: r.g }));
}

interface DatasetFilter {
  joins: string[];
  params: SqlParam[];
  /** `dataset` に系列が1つも無い（呼び出し側は0行として扱う）。 */
  empty: boolean;
}

/**
 * `sites`/`sitesInWaterBody`/`waterBodies`/`siteVariables`/`siteSeriesCells` の
 * `dataset` 絞り込みが共有する JOIN 断片（`seriesForDataset` + 既存の
 * `seriesFilterSql`——`variable_id` 前段フィルタ込みの索引が効く経路。
 * `waterBodies` の `series` 指定と同じ仕組みを `dataset` 全体に広げただけ）。
 */
async function datasetFilterSql(db: CubeDb, dataset: string, alias: string): Promise<DatasetFilter> {
  const series = await seriesForDataset(db, dataset);
  const f = seriesFilterSql(series, alias);
  if (!f) return { joins: [], params: [], empty: true };
  return { joins: f.joins, params: f.params, empty: false };
}

export interface DatasetCell {
  series: SeriesKey;
  inputGrain: string;
  grain: string;
  placeId: string;
  periodStart: string;
  n: number;
  nCensored: number;
}

/**
 * `dataset` に属する系列（tuple）に絞り込んだ、`place_kind='site'`・年グレイン・
 * mean 統計の生セル（集計しない。Issue #48 PR-1 論点A）。`sites` への JOIN は
 * 無い（`sites` に無い地点——厚木の一部・地盤沈下等——も含む。`siteSeriesCells()`
 * とは異なる集合であることに注意）。
 *
 * `variableCatalog(dataset)` と、呼び出し側（`scripts/lib/serving/adapters-v2.ts`
 * の `aliasCatalog`）が alias 単位に合流させる純関数の変換が、この1回の bulk
 * 問い合わせを共有する。alias 単位の distinct 地点数は、この生セルから
 * `Set` で数える必要がある——tuple 単位に事前集計した distinct 地点数を
 * 複数 tuple にまたがって単純合算すると、同じ地点が複数 tuple（例:
 * 同じ alias の mean/point）に同時に現れるケースで二重計上する
 * （実測で判明。`nPlaces` を alias 単位で合算しない設計にした理由）。
 */
export async function datasetCells(db: CubeDb, dataset: string): Promise<DatasetCell[]> {
  const datasetSeries = await seriesForDataset(db, dataset);
  if (datasetSeries.length === 0) return [];

  const variableIds = [...new Set(datasetSeries.map((s) => s.variableId))];
  const tupleSet = new Set(datasetSeries.map((s) => seriesKeyString(s)));

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
  const rows = await db.all<RawCell>(
    `SELECT obs.variable_id, obs.obs_stat, obs.unit_id, obs.value_grain, obs.input_grain, obs.grain,
            obs.place_id, obs.period_start, obs.n, obs.n_censored
     FROM observation_agg obs
     JOIN json_each(?) vid ON vid.value = obs.variable_id
     WHERE obs.place_kind = 'site' AND ${YEAR_GRAINS_SQL} AND ${MEAN_STAT_SQL}`,
    [jsonEachParam(variableIds)],
  );

  const out: DatasetCell[] = [];
  for (const r of rows) {
    const series = seriesKeyFromRow(r);
    if (!tupleSet.has(seriesKeyString(series))) continue;
    out.push({
      series,
      inputGrain: r.input_grain,
      grain: r.grain,
      placeId: r.place_id,
      periodStart: r.period_start,
      n: r.n,
      nCensored: r.n_censored,
    });
  }
  return out;
}

async function variableCatalogByDataset(db: CubeDb, dataset: string): Promise<SeriesCatalogRow[]> {
  const cells = await datasetCells(db, dataset);

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
    const groupKey = `${seriesKeyString(c.series)}|${c.inputGrain}`;
    let group = groups.get(groupKey);
    if (!group) {
      group = {
        series: c.series,
        inputGrain: c.inputGrain,
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
    group.places.add(c.placeId);
    const year = Number.parseInt(c.periodStart.slice(0, 4), 10);
    if (year < group.yFrom) group.yFrom = year;
    if (year > group.yTo) group.yTo = year;
    if (c.inputGrain === "day") group.nDaily += c.n;
    if (c.inputGrain === c.grain) group.nAnnual += c.n;
    group.nCensored += c.nCensored;
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

/**
 * 索引2 (place_id, variable_id, grain) を使う経路。v1 `site_var` 相当（design §3.4）。
 * `dataset` を指定すると `datasetFilterSql`（`waterBodies`/`sites` と同じ仕組み）で
 * 絞り込む（Issue #48 PR-1 論点A）。
 */
export async function siteVariables(db: CubeDb, placeId: string, opt?: { dataset?: string }): Promise<SiteSeriesRow[]> {
  const filter = opt?.dataset ? await datasetFilterSql(db, opt.dataset, "obs") : undefined;
  if (filter?.empty) return [];

  const sql = `
    SELECT obs.variable_id, obs.obs_stat, obs.unit_id, obs.value_grain, obs.grain, obs.input_grain,
           SUM(obs.n) AS n,
           MIN(CAST(substr(obs.period_start,1,4) AS INTEGER)) AS y_from,
           MAX(CAST(substr(obs.period_start,1,4) AS INTEGER)) AS y_to,
           AVG(obs.value_zero) AS avg
    FROM observation_agg obs
    ${(filter?.joins ?? []).join("\n    ")}
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
  }>(sql, [...(filter?.params ?? []), placeId]);

  return rows.map((r) => {
    const series = seriesKeyFromRow(r);
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

/**
 * 地点ロールアップ（n_meas/n_series/n_variables）の派生表。`extraJoins`
 * （`datasetFilterSql` が返す JOIN 断片）を挟めば `dataset` で絞り込める
 * （Issue #48 PR-1 論点A。`extraJoins` 省略時は従来どおり全 dataset 合算）。
 */
function siteRollupSql(extraJoins: readonly string[] = []): string {
  return `
    SELECT psr.external_key AS site_id, SUM(obs.n) AS n_meas,
           COUNT(DISTINCT (${seriesKeySql("obs")})) AS n_series,
           COUNT(DISTINCT obs.variable_id) AS n_variables
    FROM observation_agg obs
    JOIN place_source_ref psr ON psr.place_id = obs.place_id AND psr.source_id = 'sites.site_id'
    ${extraJoins.join("\n    ")}
    WHERE obs.place_kind = 'site' AND ${YEAR_GRAINS_SQL} AND ${MEAN_STAT_SQL}
    GROUP BY psr.external_key
  `;
}

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

/**
 * `sites` JOIN `place_source_ref` JOIN 年セル集計（design §3.4）。`dataset` を
 * 指定すると `datasetFilterSql` で絞り込む（Issue #48 PR-1 論点A）。
 */
export async function sites(db: CubeDb, opt?: { dataset?: string }): Promise<SiteRow2[]> {
  const filter = opt?.dataset ? await datasetFilterSql(db, opt.dataset, "obs") : undefined;
  if (filter?.empty) {
    // dataset に系列が1つも無い: 全地点を n_meas=0 等（ロールアップ無し）で返す。
    const rows = await db.all<Parameters<typeof toSiteRow2>[0]>(
      `SELECT s.site_id, s.name, s.name_en, s.watershed, s.zone, s.lat, s.lon, s.elevation_m,
              s.municipality, s.muni_code, s.treatment, s.established_on, s.operator, s.source_id, s.source_ref, s.is_synthetic,
              0 AS n_meas, 0 AS n_series, 0 AS n_variables
       FROM sites s
       ORDER BY s.zone, s.elevation_m DESC`,
    );
    return rows.map(toSiteRow2);
  }

  const sql = `
    SELECT s.site_id, s.name, s.name_en, s.watershed, s.zone, s.lat, s.lon, s.elevation_m,
           s.municipality, s.muni_code, s.treatment, s.established_on, s.operator, s.source_id, s.source_ref, s.is_synthetic,
           COALESCE(v.n_meas, 0) AS n_meas, COALESCE(v.n_series, 0) AS n_series, COALESCE(v.n_variables, 0) AS n_variables
    FROM sites s
    LEFT JOIN (${siteRollupSql(filter?.joins)}) v ON v.site_id = s.site_id
    ORDER BY s.zone, s.elevation_m DESC
  `;
  const rows = await db.all<Parameters<typeof toSiteRow2>[0]>(sql, filter?.params ?? []);
  return rows.map(toSiteRow2);
}

/**
 * `dataset` を指定すると `datasetFilterSql` で絞り込む（Issue #48 PR-1 論点A）。
 * v1 の `sitesInWaterBody` と同じく、ロールアップに INNER JOIN する（測定値が
 * 1件も無い地点は除外——`dataset` 指定時に系列が1つも無ければ0件を返す）。
 */
export async function sitesInWaterBody(db: CubeDb, municipality: string, opt?: { dataset?: string }): Promise<SiteRow2[]> {
  const filter = opt?.dataset ? await datasetFilterSql(db, opt.dataset, "obs") : undefined;
  if (filter?.empty) return [];

  const sql = `
    SELECT s.site_id, s.name, s.name_en, s.watershed, s.zone, s.lat, s.lon, s.elevation_m,
           s.municipality, s.muni_code, s.treatment, s.established_on, s.operator, s.source_id, s.source_ref, s.is_synthetic,
           COALESCE(v.n_meas, 0) AS n_meas, COALESCE(v.n_series, 0) AS n_series, COALESCE(v.n_variables, 0) AS n_variables
    FROM sites s
    JOIN (${siteRollupSql(filter?.joins)}) v ON v.site_id = s.site_id
    WHERE s.municipality = ?
    ORDER BY s.elevation_m DESC
  `;
  const rows = await db.all<Parameters<typeof toSiteRow2>[0]>(sql, [...(filter?.params ?? []), municipality]);
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

/**
 * 測定値を持つ地点が2つ以上ある「水域・地域」（v1 `listWaterBodies`/`waterBodiesForVariable` 統合。design §3.4）。
 * `series`（1系列集合に絞る。`waterBodiesForVariable` 相当）と `dataset`（データセット全体で
 * 絞り込む。`listWaterBodies` 相当——Issue #48 PR-1 論点A）はどちらか一方を渡す。
 */
export async function waterBodies(db: CubeDb, opt?: { series?: SeriesKey[]; dataset?: string }): Promise<WaterBodyRow[]> {
  const params: SqlParam[] = [];
  const joins: string[] = [];
  if (opt?.series && opt.series.length > 0) {
    if (opt.series.length > MAX_ID_LIST) throw new Error(`waterBodies: series が ${opt.series.length} 件で上限 ${MAX_ID_LIST} を超えている`);
    // `variable_id` 前段フィルタ込み（`sql.ts` の `seriesFilterSql` docstring 参照。
    // 索引の先頭列で絞り込んでから系列キーで仕上げる）。
    const f = seriesFilterSql(opt.series, "obs")!;
    joins.push(...f.joins);
    params.push(...f.params);
  } else if (opt?.dataset) {
    const filter = await datasetFilterSql(db, opt.dataset, "obs");
    if (filter.empty) return [];
    joins.push(...filter.joins);
    params.push(...filter.params);
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

export interface SiteSeriesCell {
  siteId: string;
  series: SeriesKey;
  inputGrain: string;
  grain: string;
  n: number;
  nCensored: number;
  yFrom: number;
  yTo: number;
}

/**
 * 地点（`sites.site_id`）×系列（tuple）×input_grain ごとの年セル合計
 * （Issue #48 PR-1 論点A）。`dataset` で絞り込む（`datasetFilterSql` 経由）。
 * `sites` に無い地点は対象外（INNER JOIN。`sites()`/`sitesInWaterBody()` と
 * 同じ前提）。
 *
 * **alias 単位への合流（v1 の `n_var`・`var_catalog` 相当）はここでは行わない**
 * ——catalog はここでは「dataset に属する tuple の集合」までしか知らない
 * （design §0 決定2: alias→variable_id の束ねは PR-2 の「値が動く」変更であり、
 * catalog は variable_id/tuple 単位のまま）。呼び出し側（`scripts/lib/serving/
 * adapters-v2.ts`）がこの行を `seriesForAlias`/`seriesInfo` で alias 単位に
 * 合流させる純関数の変換を行う——1回のこの問い合わせだけで済み、alias ごと・
 * 地点ごとの逐次問い合わせ（N+1）は発生しない。
 */
export async function siteSeriesCells(db: CubeDb, opt: { dataset: string }): Promise<SiteSeriesCell[]> {
  const filter = await datasetFilterSql(db, opt.dataset, "obs");
  if (filter.empty) return [];

  const sql = `
    SELECT psr.external_key AS site_id, obs.variable_id, obs.obs_stat, obs.unit_id, obs.value_grain,
           obs.input_grain, obs.grain,
           SUM(obs.n) AS n, SUM(obs.n_censored) AS n_censored,
           MIN(CAST(substr(obs.period_start,1,4) AS INTEGER)) AS y_from,
           MAX(CAST(substr(obs.period_start,1,4) AS INTEGER)) AS y_to
    FROM observation_agg obs
    JOIN place_source_ref psr ON psr.place_id = obs.place_id AND psr.source_id = 'sites.site_id'
    ${filter.joins.join("\n    ")}
    WHERE obs.place_kind = 'site' AND ${YEAR_GRAINS_SQL} AND ${MEAN_STAT_SQL}
    GROUP BY psr.external_key, obs.variable_id, obs.obs_stat, obs.unit_id, obs.value_grain, obs.input_grain, obs.grain
  `;
  const rows = await db.all<{
    site_id: string;
    variable_id: string;
    obs_stat: string | null;
    unit_id: string | null;
    value_grain: string | null;
    input_grain: string;
    grain: string;
    n: number;
    n_censored: number;
    y_from: number;
    y_to: number;
  }>(sql, filter.params);

  return rows.map((r) => ({
    siteId: r.site_id,
    series: seriesKeyFromRow(r),
    inputGrain: r.input_grain,
    grain: r.grain,
    n: r.n,
    nCensored: r.n_censored,
    yFrom: r.y_from,
    yTo: r.y_to,
  }));
}
