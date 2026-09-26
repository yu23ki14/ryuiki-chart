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

export type { BasisInfo, Grain, SeriesKey, SeriesInfo, SeriesForVariableOpt } from "./series";
export {
  seriesKeyString,
  seriesKeySql,
  seriesForAlias,
  seriesForVariable,
  seriesInfo,
  representativeSeries,
  basisOf,
  grainsForBasis,
  basisFromValueGrain,
  withTheme,
  labelYear,
} from "./series";

export { unitLabel } from "./unit";

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
  LimitedRows,
  StatTriple,
  YearPoint,
  YearSeriesOpt,
  SeriesPoint,
  MonthDaySeriesOpt,
} from "./observation";
export {
  queryCells,
  summarize,
  DEFAULT_CELL_LIMIT,
  UNLIMITED_CELL_LIMIT,
  yearSeries,
  monthSeries,
  daySeries,
  rainDaily,
  rainMonthlyClim,
} from "./observation";

export type { CatalogSource, VariableCatalogRow, SiteSeriesRow, SiteRow2, WaterBodyRow, SiteSeriesCell, DatasetCell } from "./catalog";
export {
  variableCatalog,
  siteVariables,
  sites,
  site,
  sitesInWaterBody,
  waterBodies,
  siteSeriesCells,
  datasetCells,
  YEAR_GRAINS_SQL,
  MEAN_STAT_SQL,
} from "./catalog";

export type { Envelope, EnvelopeColumn, EnvelopeCoverage, EnvelopeProvenance, EnvelopeExcluded } from "./envelope";
export { buildEnvelope, ENVELOPE_SPEC_VERSION } from "./envelope";
