/**
 * v2 アダプタ: `@/lib/cube`（Issue #48 PR-1「1a 問い合わせ層」が作る問い合わせ層）を
 * 呼び、v1 アダプタ（`adapters-v1.ts`）と同じ `id` ごとに、同じ列名の行を
 * `NormRow[]` として返す。
 *
 * **注意（1c 実装時点で 1a は未着手）**: このファイルは設計書（Issue #48 PR-1 設計、
 * §3「lib/cube の API」）に書かれている型・関数名だけを頼りに書いてある。
 * `@/lib/cube` はまだ存在しないため、`npx tsc --noEmit` はこのファイルで
 * `Cannot find module '@/lib/cube'` 系のエラーを出す（意図的にそのままにしてある。
 * 統合時に 1a の実装に合わせて調整すること——詳しくは 1c の報告を参照）。
 *
 * 期待している `@/lib/cube` の形（設計書 §3 のまま。実装が違えばここを直す）:
 *   - `sqliteCubeDb({ v2, registry, ryuiki }): CubeDb & { close(): void }`
 *   - `queryCells(db, spec: CellSpec): Promise<CellRow[]>`
 *   - `summarize(db, spec: CellSpec, by, opt?): Promise<SummaryRow[]>`
 *   - `catalog.variableCatalog(db)` / `catalog.siteVariables(db, placeId)` /
 *     `catalog.sites(db)` / `catalog.waterBodies(db, opt?)` /
 *     `catalog.sitesInWaterBody(db, municipality)`
 *   - `seriesForAlias(dataset, alias): SeriesInfo[]`
 *   - `labelYear(periodStart): number`
 *   - `unitFor(unitId): string | null`（設計書 §3.2。無ければ `unitId` をそのまま
 *     ラベルとして使うのでも動く——ここでは `unitFor` が無いケースに備えて
 *     `?? unitId` にフォールバックしている）
 */
import {
  sqliteCubeDb,
  queryCells,
  summarize,
  catalog,
  seriesForAlias,
  labelYear,
  unitFor,
  type CubeDb,
  type CellSpec,
  type SeriesKey,
} from "@/lib/cube";
import { toNormRows, type CompareSpec, type NormRow, type RawRow, type ScalarParam } from "./normalize";

export interface V2Paths {
  v2: string;
  registry: string;
  ryuiki: string;
}

let sharedDb: (CubeDb & { close(): void }) | undefined;

export function openV2Db(paths: V2Paths): CubeDb & { close(): void } {
  if (!sharedDb) sharedDb = sqliteCubeDb(paths);
  return sharedDb;
}

export function closeV2Db(): void {
  sharedDb?.close();
  sharedDb = undefined;
}

const RAIN_TOP_N = 10;

function unitLabel(unitId: string | null): string | null {
  if (unitId === null) return null;
  return unitFor ? (unitFor(unitId) ?? unitId) : unitId;
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
        alias: r.alias,
        unit: unitLabel(r.unitId),
        n: r.n,
        n_sites: r.nSites,
        y_from: r.yFrom,
        y_to: r.yTo,
        n_daily: r.nDaily,
        n_annual: r.nAnnual,
        n_censored: r.nCensored,
      }));
    }
    case "sites_list": {
      const rows = await catalog.sites(db);
      return rows.map((r) => ({ site_id: r.siteId, n_meas: r.nMeas, n_var: r.nVar }));
    }
    case "site_variables": {
      const rows = await catalog.siteVariables(db, String(params.site_id));
      return rows.map((r) => ({ alias: r.alias, kind: r.kind, n: r.n, y_from: r.yFrom, y_to: r.yTo, avg: r.avg, unit: unitLabel(r.unitId) }));
    }
    case "water_bodies": {
      const rows = await catalog.waterBodies(db);
      return rows.map((r) => ({ ...r }));
    }
    case "water_bodies_for_variable": {
      const series = seriesForAlias("measurements", String(params.alias));
      const rows = await catalog.waterBodies(db, { series });
      return rows.map((r) => ({ ...r }));
    }
    case "sites_in_water_body": {
      const rows = await catalog.sitesInWaterBody(db, String(params.water));
      return rows.map((r) => ({ site_id: r.siteId, n_meas: r.nMeas, n_var: r.nVar, municipality: r.municipality }));
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
      return rows.map((r) => ({
        zone: r.zone,
        year: labelYear(r.periodStart),
        n_sites: r.nSites,
        n: r.n,
        avg: r.avg,
        unit: unitLabel(r.series?.unitId ?? null),
      }));
    }
    case "climatology": {
      const series = seriesForAlias("measurements", String(params.alias));
      const spec: CellSpec = { series, scope: { kind: "all_sites" }, grain: "day", imputation: "zero" };
      const rows = await summarize(db, spec, "month_of_year");
      return rows.map((r) => ({ month: r.month, n: r.n, avg: r.avg, min: r.min, max: r.max, unit: unitLabel(r.series?.unitId ?? null) }));
    }
    case "zone_climatology": {
      const series = seriesForAlias("measurements", String(params.alias));
      const spec: CellSpec = { series, scope: { kind: "zone" }, grain: "month" as CellSpec["grain"], imputation: "zero" };
      const rows = await summarize(db, spec, "zone_month_of_year");
      return rows.map((r) => ({ zone: r.zone, month: r.month, n: r.n, avg: r.avg, unit: unitLabel(r.series?.unitId ?? null) }));
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
      const alias =
        params.variant === "representative"
          ? (await catalog.variableCatalog(db))[0]?.alias
          : "生物化学的酸素要求量 BOD";
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
      return rows.map((r) => ({ site_id: r.placeId, avg: r.avg, n: r.n, unit: unitLabel(r.series?.unitId ?? null) }));
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
