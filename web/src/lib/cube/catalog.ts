/**
 * カタログ系の問い合わせ（design §3.4・PR-2 design §4.3）。`CatalogSource` で出所を
 * 切り替える: 既定は `summary`（`summary_variable_catalog`/`summary_place_variable`、
 * `scripts/b13_build_summary.py` が作る事前集計。画面・API・AI・serving-diff はこちら）、
 * `live` は `observation_agg` を直接集計する経路（PR-1 の実装。summary の正しさを
 * 比べる統合テスト専用——実 DB に対しては summary より遅い）。
 *
 * `dataset` の絞り込みは `variable_alias` との JOIN で行う（`registry.sqlite`/D1 の
 * 生テーブルを直接読む。`series.ts`/`generated.ts` の中身が古くても常に最新の状態を反映する）。
 */
import type { CubeDb, SqlParam } from "./db";
import { MAX_ID_LIST } from "./db";
import { jsonEachParam, seriesFilterSql } from "./sql";
import { basisOfCell, seriesKeyFromRow, seriesKeySql, seriesKeyString, type SeriesKey } from "./series";

/**
 * データの出所（PR-2 design §4.3）。`summary`（既定）は `summary_variable_catalog`/
 * `summary_place_variable`（`scripts/b13_build_summary.py` が作る事前集計）を読む
 * ——画面・API・AI・serving-diff は全部こちらを呼ぶ。`live` は `observation_agg`
 * を直接集計する経路（PR-1 の実装で、summary の正しさを比べる統合テスト専用。
 * 実 DB に対しては summary より遅い——§3.4 のコメント参照）。
 */
export type CatalogSource = { kind: "live" } | { kind: "summary" };

const DEFAULT_CATALOG_SOURCE: CatalogSource = { kind: "summary" };

/** `serving-diff` の v2 アダプタ（`scripts/lib/serving/adapters-v2.ts`）も
 *  同じ「年セル・mean 統計」の絞り込みを書く箇所があるため export する
 *  （テーブルエイリアスは `obs` 決め打ち——`sql.ts` の `OBS` と同じ規約）。 */
export const YEAR_GRAINS_SQL = "obs.grain IN ('year','fiscal_year')";
export const MEAN_STAT_SQL = "obs.stat = 'mean'";

/**
 * 指標カタログ（v1 `var_catalog` の後継。design §0 決定4・§2.1・§4.3）。**variable_id
 * 単位に束ねた行**を返す——同じ variable_id に属する複数の系列（obs_stat/unit_id/
 * value_grain の組み合わせ違い。例: BOD の mean/day・point/day・mean/fiscal_year）を
 * 1行にまとめる。PR-1 の `SeriesCatalogRow`（系列＝tuple 単位）から変わった点で、
 * `lib/cube` の他の場所からもテストからも参照が無かったため破壊的に変更した。
 *
 * `nPlaces` は tuple ごとの distinct place 数を単純合算しない（同じ地点が複数 tuple
 * に同時に現れると二重計上する——PR-1 の知見どおり）。`unitId` は束ねた中で最も
 * `n` の大きい非NULLの unit_id（全部NULLなら null）。`stats` は束ねた中に現れる
 * 具体的な obs_stat の集合（`null`＝代表統計量は含めない。D4 の非代表統計量選択に使う）。
 */
export interface VariableCatalogRow {
  variableId: string;
  unitId: string | null;
  n: number;
  nPlaces: number;
  yFrom: number;
  yTo: number;
  nByBasis: { day: number; fiscalYear: number; year: number };
  nCensored: number;
  /** 束ねた中に現れる obs_stat（NULL を除く。ソート済み・重複無し）。 */
  stats: string[];
}

/**
 * `variableCatalog`（live/summary 共通）が集計するための、系列×地点1行。
 *
 * `grain`/`inputGrain`（セル自身の性質）を持つ——`nByBasis` の束ねは basis を
 * これで決める（`value_grain` の登録値では決めない。Issue #48 PR-2 統合後
 * 修正A #1・`series.ts` の `basisOfCell` docstring 参照）。
 */
interface CatalogCellAgg {
  variableId: string;
  obsStat: string | null;
  unitId: string | null;
  grain: string;
  inputGrain: string;
  placeId: string;
  n: number;
  nCensored: number;
  yFrom: number;
  yTo: number;
}

/** `unitCounts`（unit_id → 束ねた中の合計 n）から代表の unit_id を選ぶ。
 *  非NULL のうち `n` が最大のものを優先する（全部NULLなら null）。 */
function pickRepresentativeUnit(unitCounts: ReadonlyMap<string | null, number>): string | null {
  let best: string | null = null;
  let bestN = -1;
  for (const [unitId, n] of unitCounts) {
    if (unitId === null) continue;
    if (n > bestN) {
      best = unitId;
      bestN = n;
    }
  }
  return best;
}

function bundleVariableCatalog(rows: Iterable<CatalogCellAgg>): VariableCatalogRow[] {
  interface Group {
    unitCounts: Map<string | null, number>;
    n: number;
    places: Set<string>;
    yFrom: number;
    yTo: number;
    nByBasis: { day: number; fiscalYear: number; year: number };
    nCensored: number;
    stats: Set<string>;
  }
  const groups = new Map<string, Group>();
  for (const r of rows) {
    let g = groups.get(r.variableId);
    if (!g) {
      g = {
        unitCounts: new Map(),
        n: 0,
        places: new Set(),
        yFrom: Number.POSITIVE_INFINITY,
        yTo: Number.NEGATIVE_INFINITY,
        nByBasis: { day: 0, fiscalYear: 0, year: 0 },
        nCensored: 0,
        stats: new Set(),
      };
      groups.set(r.variableId, g);
    }
    g.n += r.n;
    g.places.add(r.placeId);
    g.unitCounts.set(r.unitId, (g.unitCounts.get(r.unitId) ?? 0) + r.n);
    if (r.yFrom < g.yFrom) g.yFrom = r.yFrom;
    if (r.yTo > g.yTo) g.yTo = r.yTo;
    const basis = basisOfCell(r);
    if (basis === "day") g.nByBasis.day += r.n;
    else if (basis === "fiscal_year") g.nByBasis.fiscalYear += r.n;
    else g.nByBasis.year += r.n;
    g.nCensored += r.nCensored;
    if (r.obsStat) g.stats.add(r.obsStat);
  }

  const out: VariableCatalogRow[] = [];
  for (const [variableId, g] of groups) {
    out.push({
      variableId,
      unitId: pickRepresentativeUnit(g.unitCounts),
      n: g.n,
      nPlaces: g.places.size,
      yFrom: g.yFrom,
      yTo: g.yTo,
      nByBasis: g.nByBasis,
      nCensored: g.nCensored,
      stats: [...g.stats].sort(),
    });
  }
  out.sort((a, b) => b.n - a.n);
  return out;
}

interface RawLiveCatalogCell {
  variable_id: string;
  obs_stat: string | null;
  unit_id: string | null;
  grain: string;
  input_grain: string;
  place_id: string;
  period_start: string;
  n: number;
  n_censored: number;
}

function yearOf(periodStart: string): number {
  return Number.parseInt(periodStart.slice(0, 4), 10);
}

/** `variableCatalog({source:'live'})` 用の生セル（`datasetCells` を再利用、dataset
 *  省略時は `observation_agg` を直接、絞り込み無しで読む）。 */
async function liveCatalogCells(db: CubeDb, dataset?: string): Promise<CatalogCellAgg[]> {
  if (dataset !== undefined) {
    const cells = await datasetCells(db, dataset);
    return cells.map((c) => ({
      variableId: c.series.variableId,
      obsStat: c.series.obsStat,
      unitId: c.series.unitId,
      grain: c.grain,
      inputGrain: c.inputGrain,
      placeId: c.placeId,
      n: c.n,
      nCensored: c.nCensored,
      yFrom: yearOf(c.periodStart),
      yTo: yearOf(c.periodStart),
    }));
  }
  const rows = await db.all<RawLiveCatalogCell>(
    `SELECT obs.variable_id, obs.obs_stat, obs.unit_id, obs.grain, obs.input_grain, obs.place_id, obs.period_start, obs.n, obs.n_censored
     FROM observation_agg obs
     WHERE obs.place_kind = 'site' AND ${YEAR_GRAINS_SQL} AND ${MEAN_STAT_SQL}`,
  );
  return rows.map((r) => ({
    variableId: r.variable_id,
    obsStat: r.obs_stat,
    unitId: r.unit_id,
    grain: r.grain,
    inputGrain: r.input_grain,
    placeId: r.place_id,
    n: r.n,
    nCensored: r.n_censored,
    yFrom: yearOf(r.period_start),
    yTo: yearOf(r.period_start),
  }));
}

interface RawSummaryPlaceCell {
  variable_id: string;
  obs_stat: string | null;
  unit_id: string | null;
  grain: string;
  input_grain: string;
  place_id: string;
  n: number;
  n_censored: number;
  y_from: number | null;
  y_to: number | null;
}

/**
 * `variableCatalog({source:'summary'})` 用の生セル。`summary_place_variable`
 * （地点×系列単位、時間はすでに畳み込み済み）を読む——`summary_variable_catalog`
 * （系列単位に事前集計済みで `place_id` を持たない）ではなく地点単位の表を読むのは、
 * variable_id への束ねで `nPlaces` を二重計上しないため（`bundleVariableCatalog` の
 * docstring・design §4.1「束ねは summary_place_variable の place 集合から数える」）。
 */
async function summaryCatalogCells(db: CubeDb, dataset?: string): Promise<CatalogCellAgg[]> {
  const filter = dataset !== undefined ? await datasetFilterSql(db, dataset, "spv") : undefined;
  if (filter?.empty) return [];

  const sql = `
    SELECT spv.variable_id, spv.obs_stat, spv.unit_id, spv.grain, spv.input_grain, spv.place_id,
           spv.n, spv.n_censored, spv.y_from, spv.y_to
    FROM summary_place_variable spv
    ${(filter?.joins ?? []).join("\n    ")}
  `;
  const rows = await db.all<RawSummaryPlaceCell>(sql, filter?.params ?? []);
  return rows.map((r) => ({
    variableId: r.variable_id,
    obsStat: r.obs_stat,
    unitId: r.unit_id,
    grain: r.grain,
    inputGrain: r.input_grain,
    placeId: r.place_id,
    n: r.n,
    nCensored: r.n_censored,
    yFrom: r.y_from ?? 0,
    yTo: r.y_to ?? 0,
  }));
}

export async function variableCatalog(db: CubeDb, opt?: { dataset?: string; source?: CatalogSource }): Promise<VariableCatalogRow[]> {
  const source = opt?.source ?? DEFAULT_CATALOG_SOURCE;
  const cells = source.kind === "summary" ? await summaryCatalogCells(db, opt?.dataset) : await liveCatalogCells(db, opt?.dataset);
  return bundleVariableCatalog(cells);
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

export interface SiteSeriesRow {
  series: SeriesKey;
  /**
   * `series` の tuple 文字列（`seriesKeyString`）に `grain`/`inputGrain` を足した
   * 一意キー（Issue #48 PR-2 統合後修正A #1）。**同じ tuple（`series`）が
   * `grain`/`inputGrain` 違いで複数行になりうる**——実測: 厚木系の中津川 BOD は
   * `value_grain='day'` の同じ tuple が `grain='year'・input_grain='day'`
   * （basis='day'）と `grain='fiscal_year'・input_grain='fiscal_year'`
   * （basis='fiscal_year'）の2行に分かれる。`seriesKeyString(series)` だけを
   * キーにすると（旧実装）この2行が同じキーに衝突し、Map に入れると片方が
   * 消える。
   */
  seriesKey: string;
  grain: string;
  inputGrain: string;
  n: number;
  yFrom: number;
  yTo: number;
  avg: number | null;
}

interface RawSiteSeriesRow {
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
}

function toSiteSeriesRow(r: RawSiteSeriesRow): SiteSeriesRow {
  const series = seriesKeyFromRow(r);
  return {
    series,
    seriesKey: `${seriesKeyString(series)}|${r.grain}|${r.input_grain}`,
    grain: r.grain,
    inputGrain: r.input_grain,
    n: r.n,
    yFrom: r.y_from,
    yTo: r.y_to,
    avg: r.avg,
  };
}

/**
 * `siteId`（`sites.site_id`、外部キー）から `place_source_ref` 経由で解決する
 * （Issue #48 PR-2 統合後修正A #2: 内部の `place_id` ではなく `site()`/`sites()`/
 * `Scope{kind:'site'}` と同じ `site_id` を受ける——`resolvePlaceId()` の複製が
 * `web/src/app/sites/[id]/page.tsx`・`web/src/lib/ai/tools.ts` にあったのをここに集約）。
 */
async function siteVariablesLive(db: CubeDb, siteId: string, imputation: AvgImputation, dataset?: string): Promise<SiteSeriesRow[]> {
  const filter = dataset ? await datasetFilterSql(db, dataset, "obs") : undefined;
  if (filter?.empty) return [];

  const valueCol = imputation === "zero" ? "obs.value_zero" : "obs.value_lod";
  const sql = `
    SELECT obs.variable_id, obs.obs_stat, obs.unit_id, obs.value_grain, obs.grain, obs.input_grain,
           SUM(obs.n) AS n,
           MIN(CAST(substr(obs.period_start,1,4) AS INTEGER)) AS y_from,
           MAX(CAST(substr(obs.period_start,1,4) AS INTEGER)) AS y_to,
           AVG(${valueCol}) AS avg
    FROM observation_agg obs
    JOIN place_source_ref psr ON psr.place_id = obs.place_id AND psr.source_id = 'sites.site_id'
    ${(filter?.joins ?? []).join("\n    ")}
    WHERE psr.external_key = ? AND obs.place_kind = 'site' AND ${YEAR_GRAINS_SQL} AND ${MEAN_STAT_SQL}
    GROUP BY obs.variable_id, obs.obs_stat, obs.unit_id, obs.value_grain, obs.grain, obs.input_grain
    ORDER BY n DESC
  `;
  const rows = await db.all<RawSiteSeriesRow>(sql, [...(filter?.params ?? []), siteId]);
  return rows.map(toSiteSeriesRow);
}

/**
 * `summary_place_variable` から1地点分の行を読む（design §2.1「variable_id×basis×stat
 * 単位（avg は lod）」）。実データでは `(variable_id, obs_stat, value_grain)` の組に対し
 * `grain`/`input_grain` が一意に決まる（同じ組が year と fiscal_year の両方の grain に
 * またがることは無い——観測済み）ため、`GROUP BY` に `grain`/`input_grain` を含めても
 * `summary_place_variable` の行をそのまま素通しするのと同じであり、`SiteSeriesRow`
 * の形（系列＝tuple 単位）を壊さずに出典だけ summary に切り替えられる。
 */
async function siteVariablesSummary(db: CubeDb, siteId: string, imputation: AvgImputation, dataset?: string): Promise<SiteSeriesRow[]> {
  const filter = dataset ? await datasetFilterSql(db, dataset, "spv") : undefined;
  if (filter?.empty) return [];

  const valueCol = imputation === "zero" ? "spv.avg_zero" : "spv.avg_lod";
  const sql = `
    SELECT spv.variable_id, spv.obs_stat, spv.unit_id, spv.value_grain, spv.grain, spv.input_grain,
           SUM(spv.n) AS n,
           MIN(spv.y_from) AS y_from,
           MAX(spv.y_to) AS y_to,
           AVG(${valueCol}) AS avg
    FROM summary_place_variable spv
    JOIN place_source_ref psr ON psr.place_id = spv.place_id AND psr.source_id = 'sites.site_id'
    ${(filter?.joins ?? []).join("\n    ")}
    WHERE psr.external_key = ?
    GROUP BY spv.variable_id, spv.obs_stat, spv.unit_id, spv.value_grain, spv.grain, spv.input_grain
    ORDER BY n DESC
  `;
  const rows = await db.all<RawSiteSeriesRow>(sql, [...(filter?.params ?? []), siteId]);
  return rows.map(toSiteSeriesRow);
}

/**
 * `avg` に使う値の選び方（design §2.2・§0-3）。`'zero'` は検閲値を0とみなす（v1 相当）、
 * `'lod'` は定量下限値とみなす（画面の既定・D6）。`observation.ts` の `Imputation`
 * （`'zero'|'lod'|'both'`）と違い `'both'` は無い——`avg` はスカラー1列なので選ぶしかない
 * （`envelope.ts`/`observation.ts` の「value_zero/value_lod を両方返す」設計とは別軸）。
 * 既定は置かない——呼び出し側（画面は `'lod'`、serving-diff の `--imputation zero` 実行は
 * `'zero'`）に明示させる（design §3「serving-diff を2回回す」・CLAUDE.md 開発フロー）。
 */
export type AvgImputation = "zero" | "lod";

/**
 * 索引2 (place_id, variable_id, grain) を使う経路。v1 `site_var` 相当（design §3.4）。
 * `dataset` を指定すると `datasetFilterSql`（`waterBodies`/`sites` と同じ仕組み）で
 * 絞り込む（Issue #48 PR-1 論点A）。`source` 既定は `summary`（design §4.3）。`imputation`
 * は必須（既定を置かない。上の `AvgImputation` docstring参照）——`avg` 列の意味その
 * ものを決めるので、呼び出し側に選ばせる。
 *
 * 第2引数は `site()`/`sites()`/`Scope{kind:'site'}` と同じ外部キーの `site_id`
 * （`sites.site_id`）を受ける（Issue #48 PR-2 統合後修正A #2。以前は内部の
 * `place_id` を要求しており、呼び出し側〔`web/src/app/sites/[id]/page.tsx`・
 * `web/src/lib/ai/tools.ts`〕がそれぞれ `resolvePlaceId()` を複製していた）。
 */
export async function siteVariables(
  db: CubeDb,
  siteId: string,
  opt: { imputation: AvgImputation; dataset?: string; source?: CatalogSource },
): Promise<SiteSeriesRow[]> {
  const source = opt.source ?? DEFAULT_CATALOG_SOURCE;
  return source.kind === "summary"
    ? siteVariablesSummary(db, siteId, opt.imputation, opt.dataset)
    : siteVariablesLive(db, siteId, opt.imputation, opt.dataset);
}

export interface SiteRow2 {
  siteId: string;
  name: string | null;
  nameEn: string | null;
  watershed: string | null;
  /** `sites.watershed` → `place_source_ref('watershed_meta.watershed_id')` →
   *  `place.name_ja`（design §2.1「water_system_name」）。`watershed` を持たない
   *  地点や、対応する `place` が無い（Phase A で登録していない）場合は null。 */
  waterSystemName: string | null;
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

/** `s.watershed` から水系名を引く JOIN 断片（`sites`/`sitesInWaterBody`/`site` が共有）。 */
const WATER_SYSTEM_NAME_JOIN = `
    LEFT JOIN place_source_ref wpsr ON wpsr.external_key = s.watershed AND wpsr.source_id = 'watershed_meta.watershed_id'
    LEFT JOIN place wp ON wp.place_id = wpsr.place_id`;
const WATER_SYSTEM_NAME_SELECT = "wp.name_ja AS water_system_name";

/**
 * 地点ロールアップ（n_meas/n_series/n_variables）の派生表。`extraJoins`
 * （`datasetFilterSql` が返す JOIN 断片。呼び出し側が `source` に合わせたエイリアス
 * （`obs`/`spv`）で呼んでおくこと）を挟めば `dataset` で絞り込める（Issue #48 PR-1
 * 論点A。`extraJoins` 省略時は従来どおり全 dataset 合算）。`source:'summary'` は
 * `summary_place_variable`（すでに `place_kind='site'`・年グレイン・`stat='mean'`
 * に絞り込み済み——WHERE が要らない）を読む。
 */
function siteRollupSql(source: CatalogSource, extraJoins: readonly string[] = []): string {
  if (source.kind === "summary") {
    return `
    SELECT psr.external_key AS site_id, SUM(spv.n) AS n_meas,
           COUNT(DISTINCT (${seriesKeySql("spv")})) AS n_series,
           COUNT(DISTINCT spv.variable_id) AS n_variables
    FROM summary_place_variable spv
    JOIN place_source_ref psr ON psr.place_id = spv.place_id AND psr.source_id = 'sites.site_id'
    ${extraJoins.join("\n    ")}
    GROUP BY psr.external_key
  `;
  }
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
  water_system_name: string | null;
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
    waterSystemName: r.water_system_name,
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

const SITE_COLUMNS_SQL = `s.site_id, s.name, s.name_en, s.watershed, ${WATER_SYSTEM_NAME_SELECT}, s.zone, s.lat, s.lon, s.elevation_m,
           s.municipality, s.muni_code, s.treatment, s.established_on, s.operator, s.source_id, s.source_ref, s.is_synthetic`;

/**
 * `sites` JOIN `place_source_ref` JOIN 年セル集計（design §3.4）。`dataset` を
 * 指定すると `datasetFilterSql` で絞り込む（Issue #48 PR-1 論点A）。`source` 既定は
 * `summary`（design §4.3）。
 */
export async function sites(db: CubeDb, opt?: { dataset?: string; source?: CatalogSource }): Promise<SiteRow2[]> {
  const source = opt?.source ?? DEFAULT_CATALOG_SOURCE;
  const alias = source.kind === "summary" ? "spv" : "obs";
  const filter = opt?.dataset ? await datasetFilterSql(db, opt.dataset, alias) : undefined;
  if (filter?.empty) {
    // dataset に系列が1つも無い: 全地点を n_meas=0 等（ロールアップ無し）で返す。
    const rows = await db.all<Parameters<typeof toSiteRow2>[0]>(
      `SELECT ${SITE_COLUMNS_SQL},
              0 AS n_meas, 0 AS n_series, 0 AS n_variables
       FROM sites s
       ${WATER_SYSTEM_NAME_JOIN}
       ORDER BY s.zone, s.elevation_m DESC`,
    );
    return rows.map(toSiteRow2);
  }

  const sql = `
    SELECT ${SITE_COLUMNS_SQL},
           COALESCE(v.n_meas, 0) AS n_meas, COALESCE(v.n_series, 0) AS n_series, COALESCE(v.n_variables, 0) AS n_variables
    FROM sites s
    ${WATER_SYSTEM_NAME_JOIN}
    LEFT JOIN (${siteRollupSql(source, filter?.joins)}) v ON v.site_id = s.site_id
    ORDER BY s.zone, s.elevation_m DESC
  `;
  const rows = await db.all<Parameters<typeof toSiteRow2>[0]>(sql, filter?.params ?? []);
  return rows.map(toSiteRow2);
}

/**
 * `sites()` の1地点版（design §2.1「新設」）。`/sites/[id]` 用——`sites()` 全件から
 * JS 側で探すのではなく `WHERE s.site_id = ?` を投げる。存在しない `siteId` は
 * `undefined`。
 */
export async function site(db: CubeDb, siteId: string, opt?: { dataset?: string; source?: CatalogSource }): Promise<SiteRow2 | undefined> {
  const source = opt?.source ?? DEFAULT_CATALOG_SOURCE;
  const alias = source.kind === "summary" ? "spv" : "obs";
  const filter = opt?.dataset ? await datasetFilterSql(db, opt.dataset, alias) : undefined;
  if (filter?.empty) {
    const rows = await db.all<Parameters<typeof toSiteRow2>[0]>(
      `SELECT ${SITE_COLUMNS_SQL},
              0 AS n_meas, 0 AS n_series, 0 AS n_variables
       FROM sites s
       ${WATER_SYSTEM_NAME_JOIN}
       WHERE s.site_id = ?`,
      [siteId],
    );
    return rows[0] ? toSiteRow2(rows[0]) : undefined;
  }

  const sql = `
    SELECT ${SITE_COLUMNS_SQL},
           COALESCE(v.n_meas, 0) AS n_meas, COALESCE(v.n_series, 0) AS n_series, COALESCE(v.n_variables, 0) AS n_variables
    FROM sites s
    ${WATER_SYSTEM_NAME_JOIN}
    LEFT JOIN (${siteRollupSql(source, filter?.joins)}) v ON v.site_id = s.site_id
    WHERE s.site_id = ?
  `;
  const rows = await db.all<Parameters<typeof toSiteRow2>[0]>(sql, [...(filter?.params ?? []), siteId]);
  return rows[0] ? toSiteRow2(rows[0]) : undefined;
}

/**
 * `dataset` を指定すると `datasetFilterSql` で絞り込む（Issue #48 PR-1 論点A）。
 * v1 の `sitesInWaterBody` と同じく、ロールアップに INNER JOIN する（測定値が
 * 1件も無い地点は除外——`dataset` 指定時に系列が1つも無ければ0件を返す）。
 * `source` 既定は `summary`。
 */
export async function sitesInWaterBody(
  db: CubeDb,
  municipality: string,
  opt?: { dataset?: string; source?: CatalogSource },
): Promise<SiteRow2[]> {
  const source = opt?.source ?? DEFAULT_CATALOG_SOURCE;
  const alias = source.kind === "summary" ? "spv" : "obs";
  const filter = opt?.dataset ? await datasetFilterSql(db, opt.dataset, alias) : undefined;
  if (filter?.empty) return [];

  const sql = `
    SELECT ${SITE_COLUMNS_SQL},
           COALESCE(v.n_meas, 0) AS n_meas, COALESCE(v.n_series, 0) AS n_series, COALESCE(v.n_variables, 0) AS n_variables
    FROM sites s
    ${WATER_SYSTEM_NAME_JOIN}
    JOIN (${siteRollupSql(source, filter?.joins)}) v ON v.site_id = s.site_id
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
 * 絞り込む。`listWaterBodies` 相当——Issue #48 PR-1 論点A）はどちらか一方を渡す。`source` 既定は `summary`。
 */
export async function waterBodies(db: CubeDb, opt?: { series?: SeriesKey[]; dataset?: string; source?: CatalogSource }): Promise<WaterBodyRow[]> {
  const source = opt?.source ?? DEFAULT_CATALOG_SOURCE;
  const alias = source.kind === "summary" ? "spv" : "obs";
  const params: SqlParam[] = [];
  const joins: string[] = [];
  if (opt?.series && opt.series.length > 0) {
    if (opt.series.length > MAX_ID_LIST) throw new Error(`waterBodies: series が ${opt.series.length} 件で上限 ${MAX_ID_LIST} を超えている`);
    // `variable_id` 前段フィルタ込み（`sql.ts` の `seriesFilterSql` docstring 参照。
    // 索引の先頭列で絞り込んでから系列キーで仕上げる）。
    const f = seriesFilterSql(opt.series, alias)!;
    joins.push(...f.joins);
    params.push(...f.params);
  } else if (opt?.dataset) {
    const filter = await datasetFilterSql(db, opt.dataset, alias);
    if (filter.empty) return [];
    joins.push(...filter.joins);
    params.push(...filter.params);
  }

  const innerSql =
    source.kind === "summary"
      ? `
      SELECT psr.external_key AS site_id, SUM(spv.n) AS n,
             MIN(spv.y_from) AS y_from, MAX(spv.y_to) AS y_to
      FROM summary_place_variable spv
      JOIN place_source_ref psr ON psr.place_id = spv.place_id AND psr.source_id = 'sites.site_id'
      ${joins.join("\n      ")}
      GROUP BY psr.external_key
    `
      : `
      SELECT psr.external_key AS site_id, SUM(obs.n) AS n,
             MIN(CAST(substr(obs.period_start,1,4) AS INTEGER)) AS y_from,
             MAX(CAST(substr(obs.period_start,1,4) AS INTEGER)) AS y_to
      FROM observation_agg obs
      JOIN place_source_ref psr ON psr.place_id = obs.place_id AND psr.source_id = 'sites.site_id'
      ${joins.join("\n      ")}
      WHERE obs.place_kind = 'site' AND ${YEAR_GRAINS_SQL} AND ${MEAN_STAT_SQL}
      GROUP BY psr.external_key
    `;

  const sql = `
    SELECT s.municipality AS name,
           COUNT(DISTINCT s.site_id) AS n_sites,
           MIN(s.elevation_m) AS elev_min, MAX(s.elevation_m) AS elev_max,
           MIN(s.zone) AS zone_min, MAX(s.zone) AS zone_max,
           SUM(v.n) AS n_meas, MIN(v.y_from) AS y_from, MAX(v.y_to) AS y_to
    FROM sites s
    JOIN (${innerSql}) v ON v.site_id = s.site_id
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
