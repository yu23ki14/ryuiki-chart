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
import { buildScopeSql, OBS, seriesFilterSql, zoneExprSql, type Scope } from "./sql";
import {
  basisOf,
  labelYear,
  MEASUREMENTS_DATASET,
  representativeSeries,
  SENSOR_DATASET,
  seriesKeyFromRow,
  seriesKeySql,
  seriesKeyString,
  yearCellFilterForBasis,
  type Grain,
  type SeriesInfo,
  type SeriesKey,
} from "./series";

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
  /** 'same' = 出典配布セル（input_grain = grain）。月までしか日付が言えない日間平均値を月から積み上げた年・年度セルも含む。 */
  inputGrain?: "day" | "hour" | "instant" | "same";
  /** `period_start` の範囲（文字列比較。日時関数は使わない: ADR-0024）。 */
  period?: { from?: string; to?: string };
  imputation: Imputation;
  /** 返す行数の上限（既定 `DEFAULT_CELL_LIMIT`）。超えたら `truncated: true` を
   *  返す（Issue #48 PR-1 §論点B。上限そのものを外したい呼び出し側は
   *  `UNLIMITED_CELL_LIMIT` を明示する——`serving-diff` はこちらを使う）。 */
  limit?: number;
}

/**
 * `CellSpec.limit` の既定値（画面が使う想定の問い合わせ規模に十分な余裕を
 * 持たせた上限）。実測で単発の問い合わせが最も大きいのは `rain_daily`
 * （全地点・日次の3,654行）で、これより十分大きい値にしてある。
 */
export const DEFAULT_CELL_LIMIT = 20_000;

/**
 * 上限を掛けたくない呼び出し側（`serving-diff` 等、v1 との突合に全行が要る）が
 * 明示的に渡す値。`LIMIT` に使うため有限の具体的な数値にする必要がある
 * （`Infinity` は SQL パラメータにバインドできない）。実データのどの
 * 問い合わせの行数よりも十分大きい。
 */
export const UNLIMITED_CELL_LIMIT = 1_000_000_000;

function limitOf(spec: CellSpec): number {
  return spec.limit ?? DEFAULT_CELL_LIMIT;
}

export interface LimitedRows<T> {
  rows: T[];
  truncated: boolean;
}

/**
 * SQL 側で `LIMIT limit+1` を掛けた結果（`rows`）を、呼び出し側が指定した
 * `limit` と比べる。`limit+1` 件返ってきていれば実際には上限を超えている
 * ことが分かるので、末尾の1行を落として `truncated: true` にする。
 */
function applyLimit<T>(rows: T[], limit: number): LimitedRows<T> {
  if (rows.length > limit) {
    return { rows: rows.slice(0, limit), truncated: true };
  }
  return { rows, truncated: false };
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
function seriesOrVariableClause(spec: CellSpec, alias: string): { joins?: string[]; where?: string; params: SqlParam[] } {
  if (spec.series && spec.series.length > 0) {
    const f = seriesFilterSql(spec.series, alias);
    return { joins: f!.joins, params: f!.params };
  }
  if (spec.variableId) {
    return { where: `${alias}.variable_id = ?`, params: [spec.variableId] };
  }
  throw new Error("queryCells/summarize: variableId か series のどちらかが必要");
}

/**
 * JOIN 節・WHERE 節それぞれのパラメータを別の配列で積み、最後に
 * `[...joinParams, ...whereParams]` として連結する（Issue #48 PR-1 code-review #1）。
 *
 * 最終的な SQL は `FROM ... ${joins.join(...)} ${whereSql(wheres)}` という並び
 * （JOIN 節がまとまって先、WHERE 節がまとまって後）で組み立てられる。この関数が
 * 返す `params` の並びはその文字列上の `?` の出現順と一致していなければならない
 * ——`variableId` 指定（`seriesOrVariableClause` が WHERE 句を返す）と
 * `water`/`places` スコープ（`buildScopeSql` が JOIN 句を返す）を同時に使うと、
 * 「WHERE 用のパラメータを先に積んでから JOIN 用のパラメータを積む」場当たりの
 * 順番では JOIN 節の `?` に WHERE 用の値が入れ替わってバインドされてしまう
 * （water は絞り込みが常に偽になって黙って0行、places は `json_each(?)` に
 * 文字列以外が渡って例外になる。実測で発覚）。JOIN 用/WHERE 用を常に別配列で
 * 持ち、両方が出揃ってから「JOIN 節の並び→WHERE 節の並び」の順で連結すれば、
 * どの組み合わせで呼ばれても構造的にずれない。
 */
function commonFilterSql(spec: CellSpec, alias: string): { joins: string[]; wheres: string[]; params: SqlParam[]; siteIdExpr: string } {
  const joins: string[] = [];
  const wheres: string[] = [];
  const joinParams: SqlParam[] = [];
  const whereParams: SqlParam[] = [];

  const sv = seriesOrVariableClause(spec, alias);
  if (sv.joins) {
    joins.push(...sv.joins);
    joinParams.push(...sv.params);
  }
  if (sv.where) {
    wheres.push(sv.where);
    whereParams.push(...sv.params);
  }

  const scopeSql = buildScopeSql(spec.scope, alias);
  joins.push(...scopeSql.joins);
  joinParams.push(...scopeSql.joinParams);
  wheres.push(...scopeSql.wheres);
  whereParams.push(...scopeSql.whereParams);

  const grains = grainsOf(spec);
  wheres.push(`${alias}.grain IN (${inClausePlaceholders(grains.length)})`);
  whereParams.push(...grains);

  const stats = statsOf(spec);
  wheres.push(`${alias}.stat IN (${inClausePlaceholders(stats.length)})`);
  whereParams.push(...stats);

  if (spec.inputGrain === "same") {
    // 出典配布セル（input_grain = grain）に加え、日付が月までしか言えない日間平均値
    // （value_grain≠'month'、復元した厚木。Issue #32-2）を月から積み上げた年・年度セルも含める。
    // value_grain='month' の系列（jma_monthly）の月→年の積み上げはここには出さない。
    wheres.push(`(${alias}.input_grain = ${alias}.grain OR (${alias}.input_grain = 'month' AND ${alias}.value_grain <> 'month'))`);
  } else if (spec.inputGrain) {
    wheres.push(`${alias}.input_grain = ?`);
    whereParams.push(spec.inputGrain);
  }

  if (spec.period?.from) {
    wheres.push(`${alias}.period_start >= ?`);
    whereParams.push(spec.period.from);
  }
  if (spec.period?.to) {
    wheres.push(`${alias}.period_start <= ?`);
    whereParams.push(spec.period.to);
  }

  return { joins, wheres, params: [...joinParams, ...whereParams], siteIdExpr: scopeSql.siteIdExpr };
}

function whereSql(wheres: string[]): string {
  return wheres.length ? `WHERE ${wheres.join(" AND ")}` : "";
}

function toCellRow(r: RawCellRow, imputation: Imputation): CellRow {
  const value = imputation === "zero" ? r.value_zero : imputation === "lod" ? r.value_lod : null;
  return {
    placeId: r.place_id,
    siteId: r.site_id,
    series: seriesKeyFromRow(r),
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
export async function queryCells(db: CubeDb, spec: CellSpec): Promise<LimitedRows<CellRow>> {
  const { joins, wheres, params, siteIdExpr } = commonFilterSql(spec, OBS);
  const limit = limitOf(spec);

  const sql = `
    SELECT ${OBS}.place_id AS place_id, ${siteIdExpr} AS site_id,
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
    LIMIT ?
  `;

  const rows = await db.all<RawCellRow>(sql, [...params, limit + 1]);
  return applyLimit(rows.map((r) => toCellRow(r, spec.imputation)), limit);
}

export type SummarizeBy = "place" | "zone" | "month_of_year" | "zone_month_of_year" | "series";

export interface SummarizeOpt {
  /** 既定 "avg"。"sum_per_year" = SUM(v)/COUNT(DISTINCT 年)（雨量の月別平年）。 */
  measure?: "avg" | "sum_per_year";
}

export interface MonthOfYearRow {
  month: number;
  n: number;
  /** `spec.imputation` で選んだ値（`'both'` のときは null。`avgZero`/`avgLod` を見る）。 */
  avg: number | null;
  /** `imputation:'both'` でも常に `value_lod` 基準（min/max は zero 側を別途持たない。
   *  呼び出し側〔`get_seasonality`〕はこれで足りる）。 */
  min: number | null;
  max: number | null;
  /** `imputation:'both'` のときだけ埋まる（それ以外は `undefined`）。 */
  avgZero?: number | null;
  avgLod?: number | null;
}

export interface ZoneYearRow {
  zone: number;
  grain: Grain;
  inputGrain: string;
  year: number;
  nSites: number;
  n: number;
  nCensored: number;
  nNotDetected: number;
  /** `spec.imputation` で選んだ値（`'both'` のときは null。`avgZero`/`avgLod` を見る）。 */
  avg: number | null;
  avgZero: number | null;
  avgLod: number | null;
}

export interface ZoneMonthRow {
  zone: number;
  month: number;
  nSites: number;
  n: number;
  /** `spec.imputation` で選んだ値（`'both'` のときは null。`avgZero`/`avgLod` を見る）。 */
  avg: number | null;
  /** `imputation:'both'` のときだけ埋まる（それ以外は `undefined`）。 */
  avgZero?: number | null;
  avgLod?: number | null;
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

async function summarizeMonthOfYear(db: CubeDb, spec: CellSpec, opt?: SummarizeOpt): Promise<LimitedRows<MonthOfYearRow>> {
  const { joins, wheres, params } = commonFilterSql(spec, OBS);
  const limit = limitOf(spec);

  // `imputation:'both'` は zero/lod の avg を1回の SQL で両方計算する（design 決定3・
  // Issue #48 PR-2 /simplify #11）——以前は呼び出し側（`get_seasonality`）が
  // `imputation:'zero'`/`'lod'` を2回叩いて JS 側でキーを合わせていた（`summarizeZone`
  // と同じ簡易合成）。min/max は常に value_lod 基準（呼び出し側はこれしか使わない）。
  if (spec.imputation === "both") {
    if (opt?.measure === "sum_per_year") {
      throw new Error("summarizeMonthOfYear: imputation='both' は measure='sum_per_year' 未対応（雨量は censored が無く imputation='zero' 固定で呼ぶため使っていない）");
    }
    const sql = `
      SELECT CAST(substr(${OBS}.period_start,6,2) AS INTEGER) AS month,
             COUNT(*) AS n,
             AVG(${OBS}.value_zero) AS avg_zero, AVG(${OBS}.value_lod) AS avg_lod,
             MIN(${OBS}.value_lod) AS min, MAX(${OBS}.value_lod) AS max
      FROM observation_agg ${OBS}
      ${joins.join("\n      ")}
      ${whereSql(wheres)}
      GROUP BY CAST(substr(${OBS}.period_start,6,2) AS INTEGER)
      ORDER BY month
      LIMIT ?
    `;
    const rows = await db.all<{ month: number; n: number; avg_zero: number | null; avg_lod: number | null; min: number | null; max: number | null }>(
      sql,
      [...params, limit + 1],
    );
    return applyLimit(
      rows.map((r) => ({ month: r.month, n: r.n, avg: null, min: r.min, max: r.max, avgZero: r.avg_zero, avgLod: r.avg_lod })),
      limit,
    );
  }

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
    LIMIT ?
  `;
  const rows = await db.all<{ month: number; n: number; avg: number | null; min: number | null; max: number | null }>(sql, [
    ...params,
    limit + 1,
  ]);
  return applyLimit(rows, limit);
}

async function summarizeZone(db: CubeDb, spec: CellSpec): Promise<LimitedRows<ZoneYearRow>> {
  const { joins, wheres, params } = commonFilterSql(spec, OBS);
  const limit = limitOf(spec);

  // `zg`/`zgz`（zone-group）: このゾーン集計自身が使うためだけの地点→ゾーンの JOIN
  // （design が想定する主な呼び出し方——`scope: { kind: "all_sites" }` で呼び、
  // ゾーンへの絞り込みは summarize 自身が行う——のときは commonFilterSql 側の
  // joins にはゾーン関連の JOIN が無いので、これが唯一の経路になる）。
  // `buildScopeSql` の "zone" スコープも同じ目的で `pr`/`zref` という別名を使うため、
  // `spec.scope.kind === 'zone'` で呼ばれると別名が衝突する（実測: SQLite が
  // "ambiguous column name" で拒む）。別名をここだけ変えて衝突を避ける——
  // どちらのスコープで呼ばれても正しく動くようにする（地点→ゾーンの辺は単射
  // なので、二重に JOIN しても行が増えることはない）。
  //
  // `value_zero`/`value_lod` の両方と `n_censored`/`n_not_detected` を常に1回の
  // SQL で計算する（Issue #48 PR-2 統合後修正A #4）——呼び出し側が `imputation:'zero'`/
  // `'lod'` を2回叩いて JS 側でキーを合わせていた簡易合成（旧 `get_timeseries` の
  // zone 分岐）を撤去するため。`spec.imputation==='both'` のときは `avg` を null にし
  // `avgZero`/`avgLod` を見させる（`observation_agg` の `imputation:'both'` と同じ約束）。
  const sql = `
    SELECT ${zoneExprSql("zgz")} AS zone, ${OBS}.grain AS grain, ${OBS}.input_grain AS input_grain,
           CAST(substr(${OBS}.period_start,1,4) AS INTEGER) AS year,
           COUNT(DISTINCT ${OBS}.place_id) AS n_sites, SUM(${OBS}.n) AS n,
           SUM(${OBS}.n_censored) AS n_censored, SUM(${OBS}.n_not_detected) AS n_not_detected,
           AVG(${OBS}.value_zero) AS avg_zero, AVG(${OBS}.value_lod) AS avg_lod
    FROM observation_agg ${OBS}
    JOIN place_relation zg ON zg.child_id = ${OBS}.place_id AND zg.relation = 'within'
    JOIN place_source_ref zgz ON zgz.place_id = zg.parent_id AND zgz.source_id = 'sites.zone'
    ${joins.join("\n    ")}
    ${whereSql(wheres)}
    GROUP BY zone, ${OBS}.grain, ${OBS}.input_grain, substr(${OBS}.period_start,1,4)
    ORDER BY zone, year
    LIMIT ?
  `;
  const rows = await db.all<{
    zone: number;
    grain: string;
    input_grain: string;
    year: number;
    n_sites: number;
    n: number;
    n_censored: number;
    n_not_detected: number;
    avg_zero: number | null;
    avg_lod: number | null;
  }>(sql, [...params, limit + 1]);
  return applyLimit(
    rows.map((r) => ({
      zone: r.zone,
      grain: r.grain as Grain,
      inputGrain: r.input_grain,
      year: r.year,
      nSites: r.n_sites,
      n: r.n,
      nCensored: r.n_censored,
      nNotDetected: r.n_not_detected,
      avg: spec.imputation === "zero" ? r.avg_zero : spec.imputation === "lod" ? r.avg_lod : null,
      avgZero: r.avg_zero,
      avgLod: r.avg_lod,
    })),
    limit,
  );
}

async function summarizeZoneMonth(db: CubeDb, spec: CellSpec): Promise<LimitedRows<ZoneMonthRow>> {
  const { joins, wheres, params } = commonFilterSql(spec, OBS);
  const limit = limitOf(spec);

  // `zg`/`zgz` の別名の理由は `summarizeZone` のコメント参照
  // （`buildScopeSql` の "zone" スコープが使う `pr`/`zref` との衝突を避ける）。
  // `imputation:'both'` は zero/lod の avg を1回の SQL で両方計算する（`summarizeZone`・
  // `summarizeMonthOfYear` と同じ理由。Issue #48 PR-2 /simplify #11）。
  if (spec.imputation === "both") {
    const sql = `
      SELECT ${zoneExprSql("zgz")} AS zone,
             CAST(substr(${OBS}.period_start,6,2) AS INTEGER) AS month,
             COUNT(DISTINCT ${OBS}.place_id) AS n_sites, SUM(${OBS}.n) AS n,
             AVG(${OBS}.value_zero) AS avg_zero, AVG(${OBS}.value_lod) AS avg_lod
      FROM observation_agg ${OBS}
      JOIN place_relation zg ON zg.child_id = ${OBS}.place_id AND zg.relation = 'within'
      JOIN place_source_ref zgz ON zgz.place_id = zg.parent_id AND zgz.source_id = 'sites.zone'
      ${joins.join("\n      ")}
      ${whereSql(wheres)}
      GROUP BY zone, month
      ORDER BY zone, month
      LIMIT ?
    `;
    const rows = await db.all<{ zone: number; month: number; n_sites: number; n: number; avg_zero: number | null; avg_lod: number | null }>(
      sql,
      [...params, limit + 1],
    );
    return applyLimit(
      rows.map((r) => ({ zone: r.zone, month: r.month, nSites: r.n_sites, n: r.n, avg: null, avgZero: r.avg_zero, avgLod: r.avg_lod })),
      limit,
    );
  }

  const v = valueExpr(spec.imputation, OBS);
  const sql = `
    SELECT ${zoneExprSql("zgz")} AS zone,
           CAST(substr(${OBS}.period_start,6,2) AS INTEGER) AS month,
           COUNT(DISTINCT ${OBS}.place_id) AS n_sites, SUM(${OBS}.n) AS n, AVG(${v}) AS avg
    FROM observation_agg ${OBS}
    JOIN place_relation zg ON zg.child_id = ${OBS}.place_id AND zg.relation = 'within'
    JOIN place_source_ref zgz ON zgz.place_id = zg.parent_id AND zgz.source_id = 'sites.zone'
    ${joins.join("\n    ")}
    ${whereSql(wheres)}
    GROUP BY zone, month
    ORDER BY zone, month
    LIMIT ?
  `;
  const rows = await db.all<{ zone: number; month: number; n_sites: number; n: number; avg: number | null }>(sql, [...params, limit + 1]);
  return applyLimit(
    rows.map((r) => ({ zone: r.zone, month: r.month, nSites: r.n_sites, n: r.n, avg: r.avg })),
    limit,
  );
}

async function summarizePlace(db: CubeDb, spec: CellSpec): Promise<LimitedRows<PlaceSummaryRow>> {
  const { joins, wheres, params, siteIdExpr } = commonFilterSql(spec, OBS);
  const limit = limitOf(spec);
  const v = valueExpr(spec.imputation, OBS);

  const sql = `
    SELECT ${OBS}.place_id AS place_id, ${siteIdExpr} AS site_id, ${OBS}.grain AS grain, ${OBS}.input_grain AS input_grain,
           SUM(${OBS}.n) AS n,
           MIN(CAST(substr(${OBS}.period_start,1,4) AS INTEGER)) AS y_from,
           MAX(CAST(substr(${OBS}.period_start,1,4) AS INTEGER)) AS y_to,
           AVG(${v}) AS avg
    FROM observation_agg ${OBS}
    ${joins.join("\n    ")}
    ${whereSql(wheres)}
    GROUP BY ${OBS}.place_id, ${OBS}.grain, ${OBS}.input_grain
    ORDER BY ${OBS}.place_id
    LIMIT ?
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
  }>(sql, [...params, limit + 1]);
  return applyLimit(
    rows.map((r) => ({
      placeId: r.place_id,
      siteId: r.site_id,
      grain: r.grain as Grain,
      inputGrain: r.input_grain,
      n: r.n,
      yFrom: r.y_from,
      yTo: r.y_to,
      avg: r.avg,
    })),
    limit,
  );
}

async function summarizeSeries(db: CubeDb, spec: CellSpec): Promise<LimitedRows<SeriesSummaryRow>> {
  const { joins, wheres, params } = commonFilterSql(spec, OBS);
  const limit = limitOf(spec);
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
    LIMIT ?
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
  }>(sql, [...params, limit + 1]);
  const mapped = rows.map((r) => {
    const series = seriesKeyFromRow(r);
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
  return applyLimit(mapped, limit);
}

export async function summarize(db: CubeDb, spec: CellSpec, by: "month_of_year", opt?: SummarizeOpt): Promise<LimitedRows<MonthOfYearRow>>;
export async function summarize(db: CubeDb, spec: CellSpec, by: "zone", opt?: SummarizeOpt): Promise<LimitedRows<ZoneYearRow>>;
export async function summarize(db: CubeDb, spec: CellSpec, by: "zone_month_of_year", opt?: SummarizeOpt): Promise<LimitedRows<ZoneMonthRow>>;
export async function summarize(db: CubeDb, spec: CellSpec, by: "place", opt?: SummarizeOpt): Promise<LimitedRows<PlaceSummaryRow>>;
export async function summarize(db: CubeDb, spec: CellSpec, by: "series", opt?: SummarizeOpt): Promise<LimitedRows<SeriesSummaryRow>>;
export async function summarize(db: CubeDb, spec: CellSpec, by: SummarizeBy, opt?: SummarizeOpt): Promise<LimitedRows<SummaryRow>>;
export async function summarize(db: CubeDb, spec: CellSpec, by: SummarizeBy, opt?: SummarizeOpt): Promise<LimitedRows<SummaryRow>> {
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

/* ------------------------------------------------------------------ */
/* 系列（代表系列・`basis`）に対する時系列の問い合わせ（PR-2 design §2.1・§2.2）        */
/* ------------------------------------------------------------------ */

const DEFAULT_DATASET = MEASUREMENTS_DATASET;

/**
 * `variableId`/`stat` の代表系列一覧を解決する（`representativeSeries()` の薄い
 * 包み）。空配列（該当する variableId・stat の組が登録に無い——呼び出し側の誤り）は
 * ここで気づけるよう例外にする（`yearSeries`/`monthSeries`/`daySeries` が共有）。
 *
 * **`basis` では絞り込まない**（Issue #48 PR-2 統合後修正A #1）: basis はセルの性質
 * （`grain`/`input_grain`）であり系列の登録（`value_grain`）ではないため、ここで
 * `value_grain` によって系列を落とすと、`value_grain='day'` として登録された系列の
 * 中に `input_grain='fiscal_year'` のセルがある地点（実測: 厚木系の中津川 BOD）の
 * 年度値がどの basis 指定でも出てこなくなる。`representativeSeries()` の全
 * `value_grain` をそのまま `CellSpec.series` に渡し、`basis` の絞り込みは
 * `yearCellFilterForBasis()` が返す `grain`/`inputGrain` でセル側に行わせる。
 */
function representativeSeriesOrThrow(variableId: string, stat: string | undefined): SeriesInfo[] {
  const all = representativeSeries(variableId, DEFAULT_DATASET, stat ?? "representative");
  if (all.length === 0) {
    throw new Error(`variableId=${variableId} stat=${stat ?? "representative"} に該当する系列が無い`);
  }
  return all;
}

export interface StatTriple {
  mean: number | null;
  min: number | null;
  max: number | null;
}

export interface YearPoint {
  placeId: string;
  siteId: string | null;
  /** `queryCells` が実際に返した grain（`'year'` または `'fiscal_year'`）。 */
  grain: Grain;
  periodStart: string;
  /** `labelYear(periodStart)`（`fiscal_year` は年度の始まりの年）。 */
  year: number;
  n: number;
  nCensored: number;
  unitId: string | null;
  /** `spec.imputation` で選んだ値（`'both'` のときは3つとも null。value_zero/value_lod を見る）。 */
  value: StatTriple;
  valueZero: StatTriple;
  valueLod: StatTriple;
}

/**
 * `adapters-v2.ts` の `pivotYearCells` の移設（design §2.1）。`observation_agg` の年セルは
 * stat ごとに別行（mean/min/max）なので、`(place_id, period_start)` でまとめてピボットする。
 * `n`/`n_censored`/`unit_id`/`site_id`/`grain` は同じキーの行なら stat によらず等しい
 * （同じ集計対象からの別の集計関数の値でしかないため）——最初に見た行の値を使う。
 *
 * ピボットのキーには**系列（`seriesKeyString`）も含める**（Issue #48 PR-2 code-review #3）。
 * `(placeId, periodStart)` だけをキーにすると、別系列（`obs_stat`/`unit_id` 違い）が
 * 同じ地点・期間に来たとき黙って1つの `YearPoint` に混ざる（後から来た系列の
 * `mean`/`min`/`max` が先の系列の値を上書きする）。実測では代表系列が同じ
 * (地点, 期間, grain) に2つ以上同居することは0件（design §0 決定4）——これを
 * 崩れてはいけない不変条件として固定し、破れていれば（`(placeId, periodStart, grain)`
 * に2つ以上の異なる系列が現れたら）例外にする。黙って選ばない。
 */
export function pivotYearCells(cells: readonly CellRow[]): YearPoint[] {
  const byKey = new Map<string, YearPoint>();
  const seriesByGroup = new Map<string, string>();
  for (const c of cells) {
    const seriesKey = seriesKeyString(c.series);
    const groupKey = `${c.placeId}|${c.periodStart}|${c.grain}`;
    const prevSeriesKey = seriesByGroup.get(groupKey);
    if (prevSeriesKey === undefined) {
      seriesByGroup.set(groupKey, seriesKey);
    } else if (prevSeriesKey !== seriesKey) {
      throw new Error(
        `pivotYearCells: place_id=${c.placeId} period_start=${c.periodStart} grain=${c.grain} に` +
          `複数の代表系列（${prevSeriesKey} と ${seriesKey}）が同居している。` +
          `代表系列は同じ地点・期間・粒度で高々1つという不変条件（design §0 決定4）が破れている。`,
      );
    }

    const k = `${groupKey}|${seriesKey}`;
    let row = byKey.get(k);
    if (!row) {
      row = {
        placeId: c.placeId,
        siteId: c.siteId,
        grain: c.grain,
        periodStart: c.periodStart,
        year: labelYear(c.periodStart),
        n: c.n,
        nCensored: c.nCensored,
        unitId: c.series.unitId,
        value: { mean: null, min: null, max: null },
        valueZero: { mean: null, min: null, max: null },
        valueLod: { mean: null, min: null, max: null },
      };
      byKey.set(k, row);
    }
    if (c.stat === "mean" || c.stat === "min" || c.stat === "max") {
      row.value[c.stat] = c.value;
      row.valueZero[c.stat] = c.valueZero;
      row.valueLod[c.stat] = c.valueLod;
    }
  }
  return [...byKey.values()];
}

export interface YearSeriesOpt {
  variableId: string;
  /** 既定 "representative"（`series.representativeSeries` と同じ既定）。 */
  stat?: string;
  /** 既定は `basisOf()` が選ぶ既定の基準（day 優先）。 */
  basis?: "day" | "fiscal_year" | "year";
  scope: Scope;
  period?: { from?: string; to?: string };
  imputation: Imputation;
  limit?: number;
}

/**
 * 年セル（`grain IN (year, fiscal_year)`、mean/min/max をピボット）。v1 `meas_year`/
 * `zone_year`/`site_var` 相当の時系列問い合わせが共有する経路（design §2.1）。
 */
export async function yearSeries(db: CubeDb, opt: YearSeriesOpt): Promise<LimitedRows<YearPoint>> {
  const series = representativeSeriesOrThrow(opt.variableId, opt.stat);
  const basis = opt.basis ?? basisOf(series).basis;
  const { grain, inputGrain } = yearCellFilterForBasis(basis);
  const spec: CellSpec = {
    series,
    scope: opt.scope,
    grain,
    stats: ["mean", "min", "max"],
    inputGrain,
    period: opt.period,
    imputation: opt.imputation,
    limit: opt.limit,
  };
  const { rows: cells, truncated } = await queryCells(db, spec);
  return { rows: pivotYearCells(cells), truncated };
}

export interface SeriesPoint {
  placeId: string;
  siteId: string | null;
  periodStart: string;
  n: number;
  nCensored: number;
  unitId: string | null;
  value: number | null;
  valueZero: number | null;
  valueLod: number | null;
}

/** month/day セル（1 (place, period) につき stat='mean' の1行）を `SeriesPoint` に
 *  詰め替える。`pivotYearCells` と同様、`tools.ts` の `get_timeseries`（month/day
 *  grain）が画面と同じ形の点を返すために export する（Issue #48 PR-2 code-review #5）。 */
export function toSeriesPoint(c: CellRow): SeriesPoint {
  return {
    placeId: c.placeId,
    siteId: c.siteId,
    periodStart: c.periodStart,
    n: c.n,
    nCensored: c.nCensored,
    unitId: c.series.unitId,
    value: c.value,
    valueZero: c.valueZero,
    valueLod: c.valueLod,
  };
}

export interface MonthDaySeriesOpt {
  variableId: string;
  stat?: string;
  scope: Scope;
  period?: { from?: string; to?: string };
  imputation: Imputation;
  limit?: number;
}

/**
 * `monthSeries`/`daySeries` が共有する実装（Issue #48 PR-2 /simplify #10。
 * grain だけが違う同じ処理だったので1関数にまとめた）。`basis='day'` の
 * 変数だけに対応する（月・日は検体値〔day〕を積み上げた粒度でしか意味を持たない
 * ——design §2.1「basis=day のみ許可、それ以外は例外」）。
 *
 * この変数の既定 basis（登録から優先順位で決めた基準）を検出したうえで day 以外を
 * 拒む——`basis="day"` を決め打ちで問い合わせると、day 系列が無い変数（例:
 * `land.max_subsidence`＝year のみ）でも「セルが無いので0行」になってしまい、
 * 呼び出し側に「basis が違う」と伝わらない。
 */
async function monthOrDaySeries(db: CubeDb, opt: MonthDaySeriesOpt, grain: "month" | "day"): Promise<LimitedRows<SeriesPoint>> {
  const series = representativeSeriesOrThrow(opt.variableId, opt.stat);
  const basis = basisOf(series).basis;
  if (basis !== "day") {
    const fnName = grain === "month" ? "monthSeries" : "daySeries";
    throw new Error(`${fnName}: basis='day' の変数だけに対応する（この変数の既定 basis は '${basis}'）`);
  }
  const spec: CellSpec = {
    series,
    scope: opt.scope,
    grain,
    stats: ["mean"],
    period: opt.period,
    imputation: opt.imputation,
    limit: opt.limit,
  };
  const { rows: cells, truncated } = await queryCells(db, spec);
  return { rows: cells.map(toSeriesPoint), truncated };
}

/** 月セル（`grain='month'`、`stat='mean'` のみ）。`monthOrDaySeries` 参照。 */
export async function monthSeries(db: CubeDb, opt: MonthDaySeriesOpt): Promise<LimitedRows<SeriesPoint>> {
  return monthOrDaySeries(db, opt, "month");
}

/** 日セル（`grain='day'`、`stat='mean'` のみ）。`monthSeries` と同じく basis='day' 限定。 */
export async function daySeries(db: CubeDb, opt: MonthDaySeriesOpt): Promise<LimitedRows<SeriesPoint>> {
  return monthOrDaySeries(db, opt, "day");
}

/* ------------------------------------------------------------------ */
/* 雨量（weather.precipitation、sensor_timeseries、hour→day sum）           */
/* ------------------------------------------------------------------ */

const RAIN_VARIABLE_ID = "common:variable:weather.precipitation";
const RAIN_DATASET = SENSOR_DATASET;

function rainSeries(): SeriesInfo[] {
  return representativeSeries(RAIN_VARIABLE_ID, RAIN_DATASET, "representative");
}

/**
 * RAIN（`weather.precipitation`）の全地点・日次 sum セル。v1 は `/10` した上で
 * ラベル日割りしていたが、`lib/cube` はどちらもしない（design §0 要点4「`/10` 撤去」・
 * 危険#4）——呼び出し側が原表記の値のまま扱う（単位不明は `unitUnknown` 注記）。
 */
export async function rainDaily(db: CubeDb, opt?: { period?: { from?: string; to?: string }; limit?: number }): Promise<LimitedRows<SeriesPoint>> {
  const spec: CellSpec = {
    series: rainSeries(),
    scope: { kind: "all_sites" },
    grain: "day",
    stats: ["sum"],
    period: opt?.period,
    imputation: "zero",
    limit: opt?.limit,
  };
  const { rows: cells, truncated } = await queryCells(db, spec);
  return { rows: cells.map(toSeriesPoint), truncated };
}

/** RAIN の月別平年値（`SUM(v)/COUNT(DISTINCT 年)`）。v1 の `/10` はしない（同上）。 */
export async function rainMonthlyClim(db: CubeDb): Promise<LimitedRows<MonthOfYearRow>> {
  const spec: CellSpec = {
    series: rainSeries(),
    scope: { kind: "all_sites" },
    grain: "day",
    stats: ["sum"],
    imputation: "zero",
  };
  return summarize(db, spec, "month_of_year", { measure: "sum_per_year" });
}

export { MAX_ID_LIST };
