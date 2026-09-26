/**
 * `lib/cube`（Issue #48 PR-1a「問い合わせ層」）の公開 API。
 *
 * 既存の読み取り経路（`@/lib/queries`・`@/lib/ai/tools`・画面・API）はこのモジュールを
 * 使わない（design §2「既存の読み取り経路は無変更」）。import するのはテスト・
 * `serving-diff`（PR-1c）・PR-2 のアダプタだけ。
 *
 * `db-sqlite.ts`（better-sqlite3、Node 専用）はここでは re-export しない
 * （アプリ〔Cloudflare Workers〕から誤って import されないよう、必要な側が
 * `@/lib/cube/db-sqlite` を直接 import する）。
 */
export type { CubeDb, Row, SqlParam } from "./db";
export { assertD1Compatible, MAX_ID_LIST } from "./db";

export { d1CubeDb } from "./db-d1";

export type { Scope } from "./sql";
export { jsonEachParam, seriesFilterSql, buildScopeSql } from "./sql";

export type { Grain, SeriesKey, SeriesInfo, SeriesForVariableOpt } from "./series";
export { seriesKeyString, seriesKeySql, seriesForAlias, seriesForVariable, seriesInfo, isSynthetic, labelYear } from "./series";

export type {
  CellSpec,
  CellRow,
  Stat,
  Imputation,
  SummarizeBy,
  SummarizeOpt,
  SummaryRow,
  MonthOfYearRow,
  ZoneYearRow,
  ZoneMonthRow,
  PlaceSummaryRow,
  SeriesSummaryRow,
} from "./observation";
export { queryCells, summarize } from "./observation";

export type { CatalogSource, SeriesCatalogRow, SiteSeriesRow, SiteRow2, WaterBodyRow } from "./catalog";
export { variableCatalog, siteVariables, sites, sitesInWaterBody, waterBodies } from "./catalog";

export type { Envelope, EnvelopeColumn, EnvelopeCoverage, EnvelopeProvenance, EnvelopeExcluded } from "./envelope";
export { buildEnvelope, ENVELOPE_SPEC_VERSION } from "./envelope";
