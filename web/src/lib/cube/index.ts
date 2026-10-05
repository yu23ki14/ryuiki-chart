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
export { jsonEachParam, seriesFilterSql, buildScopeSql, occDefaultTo, IAS_SINCE_YEAR } from "./sql";

export type { BasisInfo, Grain, SeriesKey, SeriesInfo, SeriesForVariableOpt } from "./series";
export {
  seriesKeyString,
  seriesKeySql,
  seriesForAlias,
  seriesForVariable,
  seriesInfo,
  representativeSeries,
  basisOf,
  basisOfCell,
  isRepresentativeObsStat,
  grainsForBasis,
  yearCellFilterForBasis,
  withTheme,
  labelYear,
  MEASUREMENTS_DATASET,
  SENSOR_DATASET,
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
  pivotYearCells,
  toSeriesPoint,
} from "./observation";

export type { CatalogSource, AvgImputation, VariableCatalogRow, SiteSeriesRow, SiteRow2, WaterBodyRow, SiteSeriesCell, DatasetCell } from "./catalog";
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
export { buildEnvelope, buildZoneEnvelope, ENVELOPE_SPEC_VERSION } from "./envelope";

export * from "./occurrence";
export * from "./assessment";
export type {
  SpeciesCatalogRow,
  TaxonGroupYearRow,
  EffortYearRow,
  GridCatalogRow,
  OccurrenceTotals,
  WatershedOccurrenceRow,
  WatershedOccurrence,
  IasSpeciesRow,
} from "./catalog";
export { speciesCatalog, taxonGroupYears, effortYears, effortRowV1, gridCatalog, occurrenceTotals, watershedOccurrence, iasSpecies } from "./catalog";
export type { OverviewCounts, LanduseCell, WatershedRollupRow } from "./catalog";
export { overviewCounts, watershedRollup, landuseHighlight } from "./catalog";
export type { DocSeriesMeta, DocSeriesPoint } from "./documents";
export { DOC_SERIES_WHERE, rowKeyLabel, docSeriesList, docSeriesPoints } from "./documents";
export { gridCellOfPlaceId, watershedIdOfPlaceId, placeIdOfWatershedId } from "./grid";
export { facetsForOccurrence } from "./caveats";
