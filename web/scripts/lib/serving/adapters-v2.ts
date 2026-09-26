/**
 * v2 アダプタ: `@/lib/cube`（Issue #48 PR-1「1a 問い合わせ層」が作る問い合わせ層）を
 * 呼び、v1 アダプタ（`adapters-v1.ts`）と同じ `id` ごとに、同じ列名の行を
 * `NormRow[]` として返す。
 *
 * **1a の実 API に合わせてある（Issue #48 PR-1 統合時点）**:
 *   - `sqliteCubeDb` は `@/lib/cube` からは re-export されない（index.ts のコメント
 *     参照——アプリから誤って import されないよう、Node 専用の `db-sqlite.ts` を
 *     直接 import する）。
 *   - `catalog` は名前空間としては export されていない（`variableCatalog`/
 *     `siteVariables`/`sites`/`sitesInWaterBody`/`waterBodies` が個別関数として
 *     export されている）ので、`import * as catalog from "@/lib/cube/catalog"` で
 *     名前空間に束ねる（呼び出し側の `catalog.xxx(...)` はそのまま）。
 *   - `unitFor` は無い。単位のシンボル解決は `@/lib/registry/lookup` の
 *     `unitSymbol(unitId)`（`web/src/lib/queries.ts` 等、v1 経路が使うのと同じ
 *     レジストリの読み出し層）を使う。
 *   - `SummaryRow` の各バリアント（`ZoneYearRow`/`MonthOfYearRow`/`ZoneMonthRow`/
 *     `PlaceSummaryRow`）は行ごとの `series`/`periodStart` を持たない
 *     （`SeriesSummaryRow` だけが持つ。`observation.ts` 参照）。`zone_series`/
 *     `climatology`/`zone_climatology`/`longitudinal_highlight` は単位を
 *     「その問い合わせに渡した `series`（呼び出し元で確定済みの1系列）」から
 *     直接取る。`year` は `ZoneYearRow.year`（`labelYear` を経由しない実数）を
 *     そのまま使う。
 *
 * **既知の未整理点（次の担当が serving-diff を全量実行するときに見ること）**:
 *   `variable_catalog`/`site_variables` は `catalog.ts` が「系列
 *   （variable_id, obs_stat, unit_id, value_grain）」単位で返すのに対し、
 *   v1 の `var_catalog`/`site_var` は「alias（表記）」単位の1行——同じ系列に
 *   複数 alias が対応する場合はここでは `seriesInfo(series).aliases[0]`
 *   （先頭の1つ）を使っている。alias 単位への正しい束ね直しは行っていない。
 */
import { sqliteCubeDb } from "@/lib/cube/db-sqlite";
import * as catalog from "@/lib/cube/catalog";
import {
  queryCells,
  summarize,
  seriesForAlias,
  seriesInfo,
  labelYear,
  type CubeDb,
  type CellSpec,
  type SeriesKey,
} from "@/lib/cube";
import { unitSymbol } from "@/lib/registry/lookup";
import { toNormRows, type CompareSpec, type NormRow, type RawRow, type ScalarParam } from "./normalize";

export interface V2Paths {
  v2: string;
  registry: string;
  ryuiki: string;
}

let sharedDb: (CubeDb & { close(): void }) | undefined;

export function openV2Db(paths: V2Paths): CubeDb & { close(): void } {
  if (!sharedDb) sharedDb = sqliteCubeDb(paths);
  // `sharedDb` は module スコープの `let`（`closeV2Db` からも再代入される）ため、
  // TypeScript は直前の代入によるナローイングをここでは効かせない
  // （クロージャから書き換えられうる変数の narrowing 制限）。直前の if で
  // 必ず代入済みなので non-null で問題ない。
  return sharedDb!;
}

export function closeV2Db(): void {
  sharedDb?.close();
  sharedDb = undefined;
}

const RAIN_TOP_N = 10;

function unitLabel(unitId: string | null): string | null {
  return unitSymbol(unitId);
}

// v1 の `kind`（daily/annual）は queries.ts 側では行ごとの列だが、この設計では
// `params.kind` としてクエリ側が既に持っている（year_series_site/year_series_water/
// zone_series の呼び出し元がそう定義している）ので、`input_grain` から `kind` を
// 再構築する必要はない（`inputGrain: params.kind === "daily" ? "day" : "same"` として
// v2 への問い合わせ条件にそのまま使うだけ）。

async function fetchRawRows(db: CubeDb, id: string, params: Record<string, ScalarParam>): Promise<RawRow[]> {
  switch (id) {
    case "variable_catalog": {
      const rows = await catalog.variableCatalog(db);
      return rows.map((r) => ({
        alias: seriesInfo(r.series)?.aliases[0] ?? r.series.variableId,
        unit: unitLabel(r.series.unitId),
        n: r.n,
        n_sites: r.nPlaces,
        y_from: r.yFrom,
        y_to: r.yTo,
        n_daily: r.nDaily,
        n_annual: r.nAnnual,
        n_censored: r.nCensored,
      }));
    }
    case "sites_list": {
      const rows = await catalog.sites(db);
      return rows.map((r) => ({ site_id: r.siteId, n_meas: r.nMeas, n_var: r.nVariables }));
    }
    case "site_variables": {
      const rows = await catalog.siteVariables(db, String(params.site_id));
      return rows.map((r) => ({
        alias: seriesInfo(r.series)?.aliases[0] ?? r.series.variableId,
        // v1 の `kind`（`site_var.kind`）は daily/annual。`input_grain='day'` が
        // 積み上げ（日次セルから）、それ以外は出典配布（design §3.2）。
        kind: r.inputGrain === "day" ? "daily" : "annual",
        n: r.n,
        y_from: r.yFrom,
        y_to: r.yTo,
        avg: r.avg,
        unit: unitLabel(r.series.unitId),
      }));
    }
    case "water_bodies": {
      const rows = await catalog.waterBodies(db);
      return rows.map((r) => ({
        name: r.name,
        n_sites: r.nSites,
        n_meas: r.nMeas,
        y_from: r.yFrom,
        y_to: r.yTo,
        elev_min: r.elevMin,
        elev_max: r.elevMax,
        zone_min: r.zoneMin,
        zone_max: r.zoneMax,
      }));
    }
    case "water_bodies_for_variable": {
      const series = seriesForAlias("measurements", String(params.alias));
      const rows = await catalog.waterBodies(db, { series });
      return rows.map((r) => ({ name: r.name, n_sites: r.nSites, n: r.nMeas, y_from: r.yFrom, y_to: r.yTo, elev_max: r.elevMax }));
    }
    case "sites_in_water_body": {
      const rows = await catalog.sitesInWaterBody(db, String(params.water));
      return rows.map((r) => ({ site_id: r.siteId, n_meas: r.nMeas, n_var: r.nVariables, municipality: r.municipality }));
    }
    case "year_series_site":
    case "year_series_water": {
      const series = seriesForAlias("measurements", String(params.alias));
      const placeIds =
        id === "year_series_site"
          ? [String(params.site_id)]
          : (await catalog.sitesInWaterBody(db, String(params.water))).map((r) => r.siteId);
      const spec: CellSpec = {
        series,
        scope: { kind: "places", placeIds },
        grain: ["year", "fiscal_year"],
        stats: ["mean", "min", "max"],
        inputGrain: params.kind === "daily" ? "day" : "same",
        imputation: "zero",
      };
      const cells = await queryCells(db, spec);
      return cells.map((c) => ({
        site_id: c.siteId,
        year: labelYear(c.periodStart),
        n: c.n,
        avg: c.stat === "mean" ? c.valueZero : undefined,
        min: c.stat === "min" ? c.valueZero : undefined,
        max: c.stat === "max" ? c.valueZero : undefined,
        n_censored: c.nCensored,
        unit: unitLabel(c.series.unitId),
      }));
    }
    case "month_series_site": {
      const series = seriesForAlias("measurements", String(params.alias));
      const spec: CellSpec = {
        series,
        scope: { kind: "site", siteId: String(params.site_id) },
        grain: "month" as CellSpec["grain"],
        stats: ["mean"],
        imputation: "zero",
      };
      const cells = await queryCells(db, spec);
      return cells.map((c) => ({ site_id: c.siteId, ym: c.periodStart.slice(0, 7), n: c.n, avg: c.valueZero }));
    }
    case "day_series_site": {
      const series = seriesForAlias("measurements", String(params.alias));
      const spec: CellSpec = {
        series,
        scope: { kind: "site", siteId: String(params.site_id) },
        grain: "day",
        stats: ["mean"],
        imputation: "zero",
      };
      const cells = await queryCells(db, spec);
      return cells.map((c) => ({ site_id: c.siteId, d: c.periodStart.slice(0, 10), value: c.valueZero, n_censored: c.nCensored }));
    }
    case "zone_series": {
      const series = seriesForAlias("measurements", String(params.alias));
      const spec: CellSpec = {
        series,
        scope: { kind: "zone" },
        grain: ["year", "fiscal_year"],
        stats: ["mean"],
        inputGrain: params.kind === "daily" ? "day" : "same",
        imputation: "zero",
      };
      const rows = await summarize(db, spec, "zone");
      // `SummaryRow`（`zone` バリアント＝`ZoneYearRow`）は行ごとの系列情報を持たない
      // （`observation.ts` 参照——複数系列を1グループに混ぜて summarize するのが
      // 設計の前提のため）。呼び出し時に確定している `series`（1 alias 分）から
      // 単位を引く。
      const unit = unitLabel(series[0]?.unitId ?? null);
      return rows.map((r) => ({
        zone: r.zone,
        year: r.year,
        n_sites: r.nSites,
        n: r.n,
        avg: r.avg,
        unit,
      }));
    }
    case "climatology": {
      const series = seriesForAlias("measurements", String(params.alias));
      const spec: CellSpec = { series, scope: { kind: "all_sites" }, grain: "day", imputation: "zero" };
      const rows = await summarize(db, spec, "month_of_year");
      const unit = unitLabel(series[0]?.unitId ?? null);
      return rows.map((r) => ({ month: r.month, n: r.n, avg: r.avg, min: r.min, max: r.max, unit }));
    }
    case "zone_climatology": {
      const series = seriesForAlias("measurements", String(params.alias));
      const spec: CellSpec = { series, scope: { kind: "zone" }, grain: "month" as CellSpec["grain"], imputation: "zero" };
      const rows = await summarize(db, spec, "zone_month_of_year");
      const unit = unitLabel(series[0]?.unitId ?? null);
      return rows.map((r) => ({ zone: r.zone, month: r.month, n: r.n, avg: r.avg, unit }));
    }
    case "rain_daily": {
      const series: SeriesKey[] = seriesForAlias("sensor_timeseries", "RAIN").map((s) => ({
        variableId: s.variableId,
        obsStat: s.obsStat,
        unitId: s.unitId,
        valueGrain: s.valueGrain,
      }));
      const spec: CellSpec = { series, scope: { kind: "all_sites" }, grain: "day", stats: ["sum"], imputation: "zero" };
      const cells = await queryCells(db, spec);
      return cells.map((c) => ({ d: c.periodStart.slice(0, 10), mm: c.valueZero }));
    }
    case "rain_monthly_clim": {
      const series: SeriesKey[] = seriesForAlias("sensor_timeseries", "RAIN").map((s) => ({
        variableId: s.variableId,
        obsStat: s.obsStat,
        unitId: s.unitId,
        valueGrain: s.valueGrain,
      }));
      const spec: CellSpec = { series, scope: { kind: "all_sites" }, grain: "day", stats: ["sum"], imputation: "zero" };
      const rows = await summarize(db, spec, "month_of_year", { measure: "sum_per_year" });
      return rows.map((r) => ({ month: r.month, mm: r.avg }));
    }
    case "rain_top_days": {
      const series: SeriesKey[] = seriesForAlias("sensor_timeseries", "RAIN").map((s) => ({
        variableId: s.variableId,
        obsStat: s.obsStat,
        unitId: s.unitId,
        valueGrain: s.valueGrain,
      }));
      const spec: CellSpec = { series, scope: { kind: "all_sites" }, grain: "day", stats: ["sum"], imputation: "zero" };
      const cells = await queryCells(db, spec);
      const sorted = cells
        .map((c) => ({ d: c.periodStart.slice(0, 10), mm: c.valueZero ?? 0 }))
        .sort((a, b) => b.mm - a.mm || a.d.localeCompare(b.d))
        .slice(0, RAIN_TOP_N * 4);
      return sorted.slice(0, RAIN_TOP_N).map((r, i) => ({ rank: i + 1, d: r.d, mm: r.mm }));
    }
    case "longitudinal_highlight": {
      const water =
        params.variant === "representative" ? (await catalog.waterBodies(db))[0]?.name : "境川（１）";
      let alias: string;
      if (params.variant === "representative") {
        const top = (await catalog.variableCatalog(db))[0];
        alias = top ? (seriesInfo(top.series)?.aliases[0] ?? top.series.variableId) : "生物化学的酸素要求量 BOD";
      } else {
        alias = "生物化学的酸素要求量 BOD";
      }
      const series = seriesForAlias("measurements", String(alias));
      const siteIds = (await catalog.sitesInWaterBody(db, String(water))).map((r) => r.siteId);
      const spec: CellSpec = {
        series,
        scope: { kind: "places", placeIds: siteIds },
        grain: "year",
        inputGrain: "day",
        period: { from: "2020-01-01" },
        imputation: "zero",
      };
      const rows = await summarize(db, spec, "place");
      const unit = unitLabel(series[0]?.unitId ?? null);
      return rows.map((r) => ({ site_id: r.placeId, avg: r.avg, n: r.n, unit }));
    }
    default:
      throw new Error(`v2 アダプタが未対応の問い合わせ id: ${id}`);
  }
}

export async function runV2Query(
  db: CubeDb,
  id: string,
  params: Record<string, ScalarParam>,
  compare: CompareSpec,
): Promise<NormRow[]> {
  const rows = await fetchRawRows(db, id, params);
  return toNormRows(rows, compare.key, compare.numeric, compare.label);
}
