/**
 * 観測キューブ（`observation_agg`）への問い合わせ（design §3.3）。
 *
 * `summarize()` の集計式は `scripts/b05_project_v1.py` の SQL を正にする（v1 との
 * 一致仕様）。SQL 側で `AVG`/`SUM`/`COUNT` する（JS 側で再集計すると浮動小数の
 * 加算順序が変わり b05 と一致しなくなりうるため——CLAUDE.md の SQLite 3.43 の注記と
 * 同じ理由）。
 */
import type { CubeDb, SqlParam } from "./db";
import { MAX_ID_LIST } from "./db";
import { buildScopeSql, OBS, seriesFilterSql, type Scope } from "./sql";
import { seriesKeySql, seriesKeyString, type Grain, type SeriesKey } from "./series";

export type { Scope } from "./sql";

export type Stat = "mean" | "min" | "max" | "sum";
export type Imputation = "zero" | "lod" | "both";

export interface CellSpec {
  /** 索引1 (variable_id, place_id, grain, stat, period_start) を使う主経路。 */
  variableId?: string;
  /** 省略時は variableId の全系列（フィルタしない）。 */
  series?: SeriesKey[];
  scope: Scope;
  grain: Grain | Grain[];
  /** 既定 ['mean']。 */
  stats?: Stat[];
  /** 'same' = 出典配布セル（input_grain = grain）。 */
  inputGrain?: "day" | "hour" | "instant" | "same";
  /** `period_start` の範囲（文字列比較。日時関数は使わない: ADR-0024）。 */
  period?: { from?: string; to?: string };
  imputation: Imputation;
}

export interface CellRow {
  placeId: string;
  siteId: string | null;
  series: SeriesKey;
  inputGrain: string;
  grain: Grain;
  periodStart: string;
  periodEnd: string;
  stat: string;
  value: number | null;
  valueZero: number | null;
  valueLod: number | null;
  n: number;
  nCensored: number;
  nNotDetected: number;
  nPlaces: number;
}

interface RawCellRow {
  place_id: string;
  site_id: string | null;
  variable_id: string;
  obs_stat: string | null;
  unit_id: string | null;
  value_grain: string | null;
  input_grain: string;
  grain: string;
  period_start: string;
  period_end: string;
  stat: string;
  value_zero: number | null;
  value_lod: number | null;
  n: number;
  n_censored: number;
  n_not_detected: number;
  n_places: number;
}

function grainsOf(spec: CellSpec): Grain[] {
  return Array.isArray(spec.grain) ? spec.grain : [spec.grain];
}

function statsOf(spec: CellSpec): Stat[] {
  return spec.stats && spec.stats.length > 0 ? spec.stats : ["mean"];
}

function inClausePlaceholders(n: number): string {
  return Array.from({ length: n }, () => "?").join(",");
}

/** `variableId`/`series` のどちらかを要求する共通フィルタ（`WHERE` 句1本 or `JOIN`）。 */
function seriesOrVariableClause(spec: CellSpec, alias: string): { join?: string; where?: string; params: SqlParam[] } {
  if (spec.series && spec.series.length > 0) {
    const f = seriesFilterSql(spec.series, alias);
    return { join: f!.join, params: f!.params };
  }
  if (spec.variableId) {
    return { where: `${alias}.variable_id = ?`, params: [spec.variableId] };
  }
  throw new Error("queryCells/summarize: variableId か series のどちらかが必要");
}

function commonFilterSql(spec: CellSpec, alias: string): { joins: string[]; wheres: string[]; params: SqlParam[] } {
  const joins: string[] = [];
  const wheres: string[] = [];
  const params: SqlParam[] = [];

  const sv = seriesOrVariableClause(spec, alias);
  if (sv.join) joins.push(sv.join);
  if (sv.where) wheres.push(sv.where);
  params.push(...sv.params);

  const scopeSql = buildScopeSql(spec.scope, alias);
  joins.push(...scopeSql.joins);
  wheres.push(...scopeSql.wheres);
  params.push(...scopeSql.params);

  const grains = grainsOf(spec);
  wheres.push(`${alias}.grain IN (${inClausePlaceholders(grains.length)})`);
  params.push(...grains);

  const stats = statsOf(spec);
  wheres.push(`${alias}.stat IN (${inClausePlaceholders(stats.length)})`);
  params.push(...stats);

  if (spec.inputGrain === "same") {
    wheres.push(`${alias}.input_grain = ${alias}.grain`);
  } else if (spec.inputGrain) {
    wheres.push(`${alias}.input_grain = ?`);
    params.push(spec.inputGrain);
  }

  if (spec.period?.from) {
    wheres.push(`${alias}.period_start >= ?`);
    params.push(spec.period.from);
  }
  if (spec.period?.to) {
    wheres.push(`${alias}.period_start <= ?`);
    params.push(spec.period.to);
  }

  return { joins, wheres, params };
}

function whereSql(wheres: string[]): string {
  return wheres.length ? `WHERE ${wheres.join(" AND ")}` : "";
}

function toCellRow(r: RawCellRow, imputation: Imputation): CellRow {
  const value = imputation === "zero" ? r.value_zero : imputation === "lod" ? r.value_lod : null;
  return {
    placeId: r.place_id,
    siteId: r.site_id,
    series: { variableId: r.variable_id, obsStat: r.obs_stat, unitId: r.unit_id, valueGrain: r.value_grain ?? "" },
    inputGrain: r.input_grain,
    grain: r.grain as Grain,
    periodStart: r.period_start,
    periodEnd: r.period_end,
    stat: r.stat,
    value,
    valueZero: r.value_zero,
    valueLod: r.value_lod,
    n: r.n,
    nCensored: r.n_censored,
    nNotDetected: r.n_not_detected,
    nPlaces: r.n_places,
  };
}

/**
 * `observation_agg` から未ピボットのセルを返す（1行 = 1 (place, series, period, stat)）。
 * mean/min/max のピボットは呼び出し側（JS）で行う（design §3.3。b05 の自己 JOIN は使わない）。
 */
export async function queryCells(db: CubeDb, spec: CellSpec): Promise<CellRow[]> {
  const { joins, wheres, params } = commonFilterSql(spec, OBS);
  const scopeSql = buildScopeSql(spec.scope, OBS);

  const sql = `
    SELECT ${OBS}.place_id AS place_id, ${scopeSql.siteIdExpr} AS site_id,
           ${OBS}.variable_id AS variable_id, ${OBS}.obs_stat AS obs_stat, ${OBS}.unit_id AS unit_id,
           ${OBS}.value_grain AS value_grain, ${OBS}.input_grain AS input_grain, ${OBS}.grain AS grain,
           ${OBS}.period_start AS period_start, ${OBS}.period_end AS period_end, ${OBS}.stat AS stat,
           ${OBS}.value_zero AS value_zero, ${OBS}.value_lod AS value_lod,
           ${OBS}.n AS n, ${OBS}.n_censored AS n_censored, ${OBS}.n_not_detected AS n_not_detected,
           ${OBS}.n_places AS n_places
    FROM observation_agg ${OBS}
    ${joins.join("\n    ")}
    ${whereSql(wheres)}
    ORDER BY ${OBS}.place_id, ${OBS}.period_start, ${OBS}.stat
  `;

  const rows = await db.all<RawCellRow>(sql, params);
  return rows.map((r) => toCellRow(r, spec.imputation));
}

export type SummarizeBy = "place" | "zone" | "month_of_year" | "zone_month_of_year" | "series";

export interface SummarizeOpt {
  /** 既定 "avg"。"sum_per_year" = SUM(v)/COUNT(DISTINCT 年)（雨量の月別平年）。 */
  measure?: "avg" | "sum_per_year";
}

export interface MonthOfYearRow {
  month: number;
  n: number;
  avg: number | null;
  min: number | null;
  max: number | null;
}

export interface ZoneYearRow {
  zone: number;
  grain: Grain;
  inputGrain: string;
  year: number;
  nSites: number;
  n: number;
  avg: number | null;
}

export interface ZoneMonthRow {
  zone: number;
  month: number;
  nSites: number;
  n: number;
  avg: number | null;
}

export interface PlaceSummaryRow {
  placeId: string;
  siteId: string | null;
  grain: Grain;
  inputGrain: string;
  n: number;
  yFrom: number;
  yTo: number;
  avg: number | null;
}

export interface SeriesSummaryRow {
  seriesKey: string;
  series: SeriesKey;
  inputGrain: string;
  n: number;
  nPlaces: number;
  yFrom: number;
  yTo: number;
  nDaily: number;
  nAnnual: number;
  nCensored: number;
}

export type SummaryRow = MonthOfYearRow | ZoneYearRow | ZoneMonthRow | PlaceSummaryRow | SeriesSummaryRow;

function valueExpr(imputation: Imputation, alias: string): string {
  if (imputation === "zero") return `${alias}.value_zero`;
  if (imputation === "lod") return `${alias}.value_lod`;
  throw new Error("summarize: imputation='both' は使えない（value_zero/value_lod のどちらかを選ぶ）");
}

function rowsToSeriesKey(r: { variable_id: string; obs_stat: string | null; unit_id: string | null; value_grain: string | null }): SeriesKey {
  return { variableId: r.variable_id, obsStat: r.obs_stat, unitId: r.unit_id, valueGrain: r.value_grain ?? "" };
}

async function summarizeMonthOfYear(db: CubeDb, spec: CellSpec, opt?: SummarizeOpt): Promise<MonthOfYearRow[]> {
  const { joins, wheres, params } = commonFilterSql(spec, OBS);
  const v = valueExpr(spec.imputation, OBS);
  const avgExpr =
    opt?.measure === "sum_per_year"
      ? `SUM(${v}) * 1.0 / COUNT(DISTINCT substr(${OBS}.period_start,1,4))`
      : `AVG(${v})`;

  const sql = `
    SELECT CAST(substr(${OBS}.period_start,6,2) AS INTEGER) AS month,
           COUNT(*) AS n, ${avgExpr} AS avg, MIN(${v}) AS min, MAX(${v}) AS max
    FROM observation_agg ${OBS}
    ${joins.join("\n    ")}
    ${whereSql(wheres)}
    GROUP BY CAST(substr(${OBS}.period_start,6,2) AS INTEGER)
    ORDER BY month
  `;
  const rows = await db.all<{ month: number; n: number; avg: number | null; min: number | null; max: number | null }>(sql, params);
  return rows;
}

async function summarizeZone(db: CubeDb, spec: CellSpec): Promise<ZoneYearRow[]> {
  const { joins, wheres, params } = commonFilterSql(spec, OBS);
  const v = valueExpr(spec.imputation, OBS);

  const sql = `
    SELECT CAST(zref.external_key AS INTEGER) AS zone, ${OBS}.grain AS grain, ${OBS}.input_grain AS input_grain,
           CAST(substr(${OBS}.period_start,1,4) AS INTEGER) AS year,
           COUNT(DISTINCT ${OBS}.place_id) AS n_sites, SUM(${OBS}.n) AS n, AVG(${v}) AS avg
    FROM observation_agg ${OBS}
    JOIN place_relation pr ON pr.child_id = ${OBS}.place_id AND pr.relation = 'within'
    JOIN place_source_ref zref ON zref.place_id = pr.parent_id AND zref.source_id = 'sites.zone'
    ${joins.join("\n    ")}
    ${whereSql(wheres)}
    GROUP BY zone, ${OBS}.grain, ${OBS}.input_grain, substr(${OBS}.period_start,1,4)
    ORDER BY zone, year
  `;
  const rows = await db.all<{ zone: number; grain: string; input_grain: string; year: number; n_sites: number; n: number; avg: number | null }>(
    sql,
    params,
  );
  return rows.map((r) => ({ zone: r.zone, grain: r.grain as Grain, inputGrain: r.input_grain, year: r.year, nSites: r.n_sites, n: r.n, avg: r.avg }));
}

async function summarizeZoneMonth(db: CubeDb, spec: CellSpec): Promise<ZoneMonthRow[]> {
  const { joins, wheres, params } = commonFilterSql(spec, OBS);
  const v = valueExpr(spec.imputation, OBS);

  const sql = `
    SELECT CAST(zref.external_key AS INTEGER) AS zone,
           CAST(substr(${OBS}.period_start,6,2) AS INTEGER) AS month,
           COUNT(DISTINCT ${OBS}.place_id) AS n_sites, SUM(${OBS}.n) AS n, AVG(${v}) AS avg
    FROM observation_agg ${OBS}
    JOIN place_relation pr ON pr.child_id = ${OBS}.place_id AND pr.relation = 'within'
    JOIN place_source_ref zref ON zref.place_id = pr.parent_id AND zref.source_id = 'sites.zone'
    ${joins.join("\n    ")}
    ${whereSql(wheres)}
    GROUP BY zone, month
    ORDER BY zone, month
  `;
  const rows = await db.all<{ zone: number; month: number; n_sites: number; n: number; avg: number | null }>(sql, params);
  return rows.map((r) => ({ zone: r.zone, month: r.month, nSites: r.n_sites, n: r.n, avg: r.avg }));
}

async function summarizePlace(db: CubeDb, spec: CellSpec): Promise<PlaceSummaryRow[]> {
  const { joins, wheres, params } = commonFilterSql(spec, OBS);
  const scopeSql = buildScopeSql(spec.scope, OBS);
  const v = valueExpr(spec.imputation, OBS);

  const sql = `
    SELECT ${OBS}.place_id AS place_id, ${scopeSql.siteIdExpr} AS site_id, ${OBS}.grain AS grain, ${OBS}.input_grain AS input_grain,
           SUM(${OBS}.n) AS n,
           MIN(CAST(substr(${OBS}.period_start,1,4) AS INTEGER)) AS y_from,
           MAX(CAST(substr(${OBS}.period_start,1,4) AS INTEGER)) AS y_to,
           AVG(${v}) AS avg
    FROM observation_agg ${OBS}
    ${joins.join("\n    ")}
    ${whereSql(wheres)}
    GROUP BY ${OBS}.place_id, ${OBS}.grain, ${OBS}.input_grain
    ORDER BY ${OBS}.place_id
  `;
  const rows = await db.all<{
    place_id: string;
    site_id: string | null;
    grain: string;
    input_grain: string;
    n: number;
    y_from: number;
    y_to: number;
    avg: number | null;
  }>(sql, params);
  return rows.map((r) => ({
    placeId: r.place_id,
    siteId: r.site_id,
    grain: r.grain as Grain,
    inputGrain: r.input_grain,
    n: r.n,
    yFrom: r.y_from,
    yTo: r.y_to,
    avg: r.avg,
  }));
}

async function summarizeSeries(db: CubeDb, spec: CellSpec): Promise<SeriesSummaryRow[]> {
  const { joins, wheres, params } = commonFilterSql(spec, OBS);
  const seriesKeySqlAlias = seriesKeySql(OBS);

  const sql = `
    SELECT ${OBS}.variable_id AS variable_id, ${OBS}.obs_stat AS obs_stat, ${OBS}.unit_id AS unit_id, ${OBS}.value_grain AS value_grain,
           ${OBS}.input_grain AS input_grain,
           SUM(${OBS}.n) AS n, COUNT(DISTINCT ${OBS}.place_id) AS n_places,
           MIN(CAST(substr(${OBS}.period_start,1,4) AS INTEGER)) AS y_from,
           MAX(CAST(substr(${OBS}.period_start,1,4) AS INTEGER)) AS y_to,
           SUM(CASE WHEN ${OBS}.input_grain = 'day' THEN ${OBS}.n ELSE 0 END) AS n_daily,
           SUM(CASE WHEN ${OBS}.input_grain = ${OBS}.grain THEN ${OBS}.n ELSE 0 END) AS n_annual,
           SUM(${OBS}.n_censored) AS n_censored
    FROM observation_agg ${OBS}
    ${joins.join("\n    ")}
    ${whereSql(wheres)}
    GROUP BY ${seriesKeySqlAlias}, ${OBS}.input_grain
    ORDER BY n DESC
  `;
  const rows = await db.all<{
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
  }>(sql, params);
  return rows.map((r) => {
    const series = rowsToSeriesKey(r);
    return {
      seriesKey: seriesKeyString(series),
      series,
      inputGrain: r.input_grain,
      n: r.n,
      nPlaces: r.n_places,
      yFrom: r.y_from,
      yTo: r.y_to,
      nDaily: r.n_daily,
      nAnnual: r.n_annual,
      nCensored: r.n_censored,
    };
  });
}

export async function summarize(db: CubeDb, spec: CellSpec, by: "month_of_year", opt?: SummarizeOpt): Promise<MonthOfYearRow[]>;
export async function summarize(db: CubeDb, spec: CellSpec, by: "zone", opt?: SummarizeOpt): Promise<ZoneYearRow[]>;
export async function summarize(db: CubeDb, spec: CellSpec, by: "zone_month_of_year", opt?: SummarizeOpt): Promise<ZoneMonthRow[]>;
export async function summarize(db: CubeDb, spec: CellSpec, by: "place", opt?: SummarizeOpt): Promise<PlaceSummaryRow[]>;
export async function summarize(db: CubeDb, spec: CellSpec, by: "series", opt?: SummarizeOpt): Promise<SeriesSummaryRow[]>;
export async function summarize(db: CubeDb, spec: CellSpec, by: SummarizeBy, opt?: SummarizeOpt): Promise<SummaryRow[]>;
export async function summarize(db: CubeDb, spec: CellSpec, by: SummarizeBy, opt?: SummarizeOpt): Promise<SummaryRow[]> {
  switch (by) {
    case "month_of_year":
      return summarizeMonthOfYear(db, spec, opt);
    case "zone":
      return summarizeZone(db, spec);
    case "zone_month_of_year":
      return summarizeZoneMonth(db, spec);
    case "place":
      return summarizePlace(db, spec);
    case "series":
      return summarizeSeries(db, spec);
  }
}

export { MAX_ID_LIST };
