/**
 * v2 アダプタ: `@/lib/cube`（Issue #48 PR-1「1a 問い合わせ層」が作る問い合わせ層）を
 * 呼び、v1 アダプタ（`adapters-v1.ts`）と同じ `id` ごとに、同じ列名の行を
 * `NormRow[]` として返す。
 *
 * **系列の混ぜ方（設計書 §3.3・§4.2）**: alias に対応する問い合わせは
 * `seriesForAlias(dataset, alias)` が返す系列の集合を**そのまま**（1グループに
 * 混ぜて）`lib/cube` に渡す。「代表系列1件で近似する」箇所は無い——
 * `variable_catalog`/`site_variables` も、alias が複数の系列（tuple）に
 * またがる場合（例: `生物化学的酸素要求量 BOD` は day/mean・day/point・
 * fiscal_year/mean の3系列）は全部を1つの alias 行に合流させる
 * （v1 の `var_catalog`/`site_var` が `meas_year` を `variable`（=alias）単位で
 * `GROUP BY` しているのと同じ意味——`scripts/b05_project_v1.py` の
 * `_VAR_CATALOG_SQL`/`_SITE_VAR_SQL` 参照）。
 *
 * v1 の `kind`（daily/annual）は `input_grain` との対応（設計書 §3.2:
 * `kind = CASE WHEN input_grain='day' THEN 'daily' ELSE 'annual' END`、
 * `scripts/b05_project_v1.py` の `_MEAS_YEAR_SQL` と同じ式）でこのファイルに閉じる。
 * `@/lib/cube` は daily/annual という語を知らない。
 */
import Database from "better-sqlite3";
import { sqliteCubeDb } from "@/lib/cube/db-sqlite";
import * as catalog from "@/lib/cube/catalog";
import {
  queryCells,
  summarize,
  yearSeries,
  monthSeries,
  daySeries,
  seriesForAlias,
  representativeSeries,
  seriesInfo,
  labelYear,
  UNLIMITED_CELL_LIMIT,
  type CubeDb,
  type CellSpec,
  type CellRow,
  type SeriesKey,
  type SeriesInfo,
  type AvgImputation,
  type CatalogSource,
} from "@/lib/cube";
import { GENERATED_VARIABLE_ALIASES, type GeneratedVariableAlias } from "@/lib/registry/generated";
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
  if (sharedDb) aliasCatalogCache.delete(sharedDb);
  sharedDb?.close();
  sharedDb = undefined;
}

function unitLabel(unitId: string | null): string | null {
  return unitSymbol(unitId);
}

/**
 * `year_series_site`/`year_series_water` が使う。キューブの年セルは
 * stat ごとに別行（`mean`/`min`/`max`）なので、`queryCells` は1 (place, period) につき
 * 最大3行を返す——`lib/cube` はここをピボットしない設計（design §3.3「mean/min/max の
 * ピボットは JS で行う（(place, series, period_start) でまとめる）。b05 の自己 JOIN は
 * 使わない」）ので、このアダプタでピボットする。
 *
 * 1つの (place, period_start) に2つ以上の系列（`series` に渡した複数 tuple のうち）が
 * 同時にセルを持つことは実データ上は起きない（各地点は1つの出典＝1つの系列にしか
 * 属さない。複数系列が混ざるのは「ゾーン」集計だけ——design §3.3「系列の混ぜ方」）。
 * 万一起きれば `stat==='mean'` の2つ目が最初の1つ目を上書きするのではなく、
 * 別の系列の値を静かに合成してしまう前に気づけるよう、ここでは検出しない
 * （`rowsByKey` が同じ (year) キーの重複行として例外にする——診断としては
 * 十分で、ここで無理に多系列対応するとかえって隠れたバグを見えなくする）。
 */
function pivotYearCells(cells: readonly CellRow[]): RawRow[] {
  const byKey = new Map<string, RawRow>();
  for (const c of cells) {
    const k = `${c.placeId}|${c.periodStart}`;
    let row = byKey.get(k);
    if (!row) {
      row = { site_id: c.siteId, year: labelYear(c.periodStart), n: c.n, n_censored: c.nCensored, unit: unitLabel(c.series.unitId) };
      byKey.set(k, row);
    }
    // `c.value` は `spec.imputation`（呼び出し側が渡した zero/lod）で選ばれた値
    // （`toCellRow` 参照）。v1 比較は常に「今回の imputation で選んだ値」対
    // 「今回の imputation で選んだ値」の突き合わせなので、`valueZero` 決め打ちにしない。
    if (c.stat === "mean") row.avg = c.value;
    else if (c.stat === "min") row.min = c.value;
    else if (c.stat === "max") row.max = c.value;
  }
  return [...byKey.values()];
}

/** `representativeSeries()`/`seriesForAlias()` の結果から単位を1つ選ぶ
 *  （`variable_id`/`alias` 単位の集計に単位ラベルを添えるときの共通ヘルパ。
 *  最初に見つかった非NULL の unit_id——`catalog.ts` の `pickRepresentativeUnit`
 *  ほど厳密な「n が最大」の選び方はしないが、束ねた系列群の unit_id は実測上
 *  ほぼ全て1種類に揃っている——D3 前の危険領域はレジストリ側の話）。 */
function firstUnit(series: readonly SeriesInfo[]): string | null {
  for (const s of series) if (s.unitId) return s.unitId;
  return series[0]?.unitId ?? null;
}

/**
 * `SiteSeriesRow` から basis を決める。`series.ts` の `basisOf`/`basisFromValueGrain`
 * のように `value_grain`（登録された tuple）だけでは決まらない——同じ
 * value_grain='day' の tuple が、地点によっては `input_grain='fiscal_year'`
 * のセル（出典が直接年度値だけを報告した年）も持つ（実測: atsugi の一部地点。
 * `site_variables_by_variable` の case docstring参照）。v1 の `kind`
 * （`input_grain='day'` かどうかで決まる）と同じ判定基準に揃える。
 */
function siteSeriesBasis(r: { inputGrain: string; grain: string }): "day" | "fiscal_year" | "year" {
  if (r.inputGrain === "day") return "day";
  return r.grain === "year" ? "year" : "fiscal_year";
}

/** `unitCounts`（unit_id → 束ねた中の重み合計）から非NULL・最大重みの unit_id を選ぶ
 *  （`catalog.ts` の `pickRepresentativeUnit` と同じ考え方。`site_variables_by_variable`
 *  の obs_stat 束ねで使う）。 */
function pickUnitByWeight(unitCounts: ReadonlyMap<string | null, number>): string | null {
  let best: string | null = null;
  let bestWeight = -1;
  for (const [unitId, weight] of unitCounts) {
    if (unitId === null) continue;
    if (weight > bestWeight) {
      best = unitId;
      bestWeight = weight;
    }
  }
  return best;
}

/* -------------------------------------------------------------------- */
/* alias 単位への合流（`variable_catalog`/`site_variables`）              */
/* -------------------------------------------------------------------- */

const MEASUREMENTS_ALIASES: readonly string[] = [
  ...new Set(
    (GENERATED_VARIABLE_ALIASES as readonly GeneratedVariableAlias[])
      .filter((a) => a.dataset === "measurements")
      .map((a) => a.alias),
  ),
];

interface SeriesYearlyTotal {
  n: number;
  nSites: number;
  yFrom: number;
  yTo: number;
  nDaily: number;
  nAnnual: number;
  nCensored: number;
}

interface AliasCatalogEntry {
  alias: string;
  series: SeriesInfo[];
  agg: SeriesYearlyTotal;
}

// `db`（`CubeDb`）ごとにキャッシュする——serving-diff は同じプロセス内で
// 本番 `v2Db` と `--v1compat-db` の第2接続を両方開き、同じ問い合わせ id を
// 両方の db に対して順に流す（design §1「差分の差分」）。以前は単一の
// モジュール変数（`db` を無視）だったため、1回目の呼び出し（本番 `v2Db`）で
// キャッシュを埋めると、2回目の呼び出し（v1compat 接続）が実際には
// v1compat を1度も読まずキャッシュ（本番の値）をそのまま返していた——
// `variable_catalog` の `synthetic_excluded` 判定が「v2compat ≠ v2(本番)」を
// 恒等的に満たせず不発になり、DO/pH/SS/気温/水温（合成データを含む5項目）が
// 常に unexplained になる原因だった（Issue #48 PR-2 統合後 修正B）。
const aliasCatalogCache = new WeakMap<CubeDb, AliasCatalogEntry[]>();

/**
 * `variable_catalog` の中身（alias 単位に合流した年セル集計、n 降順）。
 * `catalog.datasetCells(db, "measurements")`（1回の bulk 問い合わせ、
 * `variable_id` 前段フィルタ込みで dataset 絞り込み——`catalog.ts` 参照）が返す
 * 生セルを、alias 単位に合流させる純関数の変換（Issue #48 PR-1 論点A: 以前は
 * alias ごとに別クエリを投げる N+1 だった）。
 *
 * `n_sites`（distinct 地点数）は `Set` で数える——同じ alias の複数 tuple
 * （例: mean/point）が同じ地点に同時に現れることが実測である（`浮遊物質量 SS`
 * 等）ため、tuple 単位に事前集計した distinct 地点数を単純合算すると二重計上
 * する。`catalog.datasetCells()` が生セル（未集計）を返すのはこのため。
 *
 * `catalog.datasetCells()` は `place_kind='site'` の全セルを対象にし
 * （`sites` への JOIN は無い）、`sites` に無い地点（厚木の一部・地盤沈下等）も
 * 含む——`catalog.siteSeriesCells()`（`sites` に INNER JOIN する、
 * `siteMeasurementRollup` 用）とは異なる集合なので使い分ける。
 */
async function aliasCatalog(db: CubeDb): Promise<AliasCatalogEntry[]> {
  const cached = aliasCatalogCache.get(db);
  if (cached) return cached;
  const cells = await catalog.datasetCells(db, "measurements");

  interface Group {
    series: SeriesInfo[];
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
    const info = seriesInfo(c.series);
    const alias = info?.aliases[0];
    if (!alias) continue;
    let g = groups.get(alias);
    if (!g) {
      g = {
        series: seriesForAlias("measurements", alias),
        n: 0,
        places: new Set(),
        yFrom: Number.POSITIVE_INFINITY,
        yTo: Number.NEGATIVE_INFINITY,
        nDaily: 0,
        nAnnual: 0,
        nCensored: 0,
      };
      groups.set(alias, g);
    }
    g.n += c.n;
    g.places.add(c.placeId);
    const year = Number.parseInt(c.periodStart.slice(0, 4), 10);
    if (year < g.yFrom) g.yFrom = year;
    if (year > g.yTo) g.yTo = year;
    if (c.inputGrain === "day") g.nDaily += c.n;
    if (c.inputGrain === c.grain) g.nAnnual += c.n;
    g.nCensored += c.nCensored;
  }

  const out: AliasCatalogEntry[] = [...groups.entries()].map(([alias, g]) => ({
    alias,
    series: g.series,
    agg: { n: g.n, nSites: g.places.size, yFrom: g.yFrom, yTo: g.yTo, nDaily: g.nDaily, nAnnual: g.nAnnual, nCensored: g.nCensored },
  }));
  out.sort((a, b) => b.agg.n - a.agg.n);
  aliasCatalogCache.set(db, out);
  return out;
}

/**
 * measurements の alias ごとの、レジストリ上の正しい unit symbol。`registry.sqlite` の
 * `variable_alias`/`unit` を **SQL で直接**読む（Issue #48 PR-1 code-review #3）。
 *
 * 以前は `unitLabel(seriesForAlias("measurements", alias)[0]?.unitId ?? null)`——
 * `fetchRawRows` が v2 側の `unit` 列を計算するのと**全く同じ式**——で「期待値」を
 * 計算していた。これだと `classify.ts` の `unit_label_registry` 規則の
 * `expected === v2Unit` が構造的に常に真になり（両者が同じ入力から同じ式で
 * 計算される以上、一致しないことがあり得ない）、`seriesForAlias`/`generated.ts`
 * 側に実際にバグがあっても検出できない見かけ上の検証だった。
 *
 * ここでは `seriesForAlias`（`generated.ts` 経由）を一切使わず、`registry.sqlite`
 * の生テーブルを別の接続で直接読む。ある alias の `variable_alias` 行の `unit_id`
 * が（NULL を除いて）1種類に定まらない場合はこの alias を返り値に含めない
 * （`classify.ts` 側は `expectedUnitSymbol.get(alias)` が `undefined` なら
 * unexplained に倒す——「1つに定まらないなら期待値を主張しない」）。
 */
export function expectedUnitSymbols(registryDbPath: string): ReadonlyMap<string, string | null> {
  const db = new Database(registryDbPath, { readonly: true, fileMustExist: true });
  try {
    const distinctUnitIds = db.prepare(
      `SELECT DISTINCT unit_id FROM variable_alias WHERE dataset = 'measurements' AND alias = ? AND unit_id IS NOT NULL`,
    );
    const unitSymbolById = db.prepare(`SELECT symbol FROM unit WHERE unit_id = ?`);

    const out = new Map<string, string | null>();
    for (const alias of MEASUREMENTS_ALIASES) {
      const rows = distinctUnitIds.all(alias) as { unit_id: string }[];
      if (rows.length !== 1) continue; // 0件（全行NULL）/2件以上（1つに定まらない）は期待値なし
      const unitRow = unitSymbolById.get(rows[0].unit_id) as { symbol: string | null } | undefined;
      out.set(alias, unitRow ? (unitRow.symbol ?? "") : null);
    }
    return out;
  } finally {
    db.close();
  }
}

/**
 * `expectedUnitSymbols` の variable_id 版（`*_by_variable` 問い合わせ用。
 * design §3 #2）。ある variable_id に属する alias 全部（代表フィルタなし
 * ——`variable_catalog_by_variable`/`site_variables_by_variable` が束ねる範囲と
 * 揃える）の `unit_id` が1種類に定まれば、その symbol を期待値にする。
 * `expectedUnitSymbols` と同じ理由で `seriesForAlias`/`representativeSeries`
 * を経由しない（`registry.sqlite` を直接読む）。
 */
export function expectedUnitSymbolsByVariable(registryDbPath: string): ReadonlyMap<string, string | null> {
  const db = new Database(registryDbPath, { readonly: true, fileMustExist: true });
  try {
    const variableIds = db
      .prepare(`SELECT DISTINCT variable_id FROM variable_alias WHERE dataset = 'measurements' AND variable_id IS NOT NULL`)
      .all() as { variable_id: string }[];
    const distinctUnitIds = db.prepare(
      `SELECT DISTINCT unit_id FROM variable_alias WHERE dataset = 'measurements' AND variable_id = ? AND unit_id IS NOT NULL`,
    );
    const unitSymbolById = db.prepare(`SELECT symbol FROM unit WHERE unit_id = ?`);

    const out = new Map<string, string | null>();
    for (const { variable_id: variableId } of variableIds) {
      const rows = distinctUnitIds.all(variableId) as { unit_id: string }[];
      if (rows.length !== 1) continue;
      const unitRow = unitSymbolById.get(rows[0].unit_id) as { symbol: string | null } | undefined;
      out.set(variableId, unitRow ? (unitRow.symbol ?? "") : null);
    }
    return out;
  } finally {
    db.close();
  }
}

/**
 * `rain_monthly_clim` が使う spec（RAIN の全地点・日次 sum）。v1 に読み手のある
 * `rain_daily`/`rain_top_days`（`mode=rain`。D5・読み手なしのため PR-2 で削除）は
 * この serving-diff からも削除した——残すのは季節図（`mode=season`）が
 * 引き続き使う `rain_monthly_clim` だけ（U4 の判断。報告参照）。雨量は
 * censored の概念が無いので imputation を問わず常に "zero" 固定でよい
 * （`lib/cube` 自身の `rainMonthlyClim` も同様に固定——`observation.ts` 参照）。
 */
function rainDailySumSpec(): CellSpec {
  const series: SeriesKey[] = seriesForAlias("sensor_timeseries", "RAIN");
  return { series, scope: { kind: "all_sites" }, grain: "day", stats: ["sum"], imputation: "zero", limit: UNLIMITED_CELL_LIMIT };
}

async function fetchRawRows(
  db: CubeDb,
  id: string,
  params: Record<string, ScalarParam>,
  imputation: AvgImputation,
  catalogSource: CatalogSource,
): Promise<RawRow[]> {
  switch (id) {
    case "variable_catalog": {
      const entries = await aliasCatalog(db);
      return entries.map(({ alias, series, agg }) => ({
        alias,
        unit: unitLabel(series[0]?.unitId ?? null),
        n: agg.n,
        n_sites: agg.nSites,
        y_from: agg.yFrom,
        y_to: agg.yTo,
        n_daily: agg.nDaily,
        n_annual: agg.nAnnual,
        n_censored: agg.nCensored,
      }));
    }
    case "sites_list": {
      // 画面（`/sites`）・`get_sites`（AI）と同じ `catalog.sites({source:'summary'})`
      // を呼ぶ（design §8.4 チェック項目2）。`n_var` は `nVariables`
      // （distinct variable_id 数）——alias 数ではない（`sites_list`（design D の
      // 表）の意味変更。以前は独自ロールアップで distinct alias 数を数えていた）。
      const rows = await catalog.sites(db, { dataset: "measurements", source: catalogSource });
      return rows.map((r) => ({ site_id: r.siteId, n_meas: r.nMeas, n_var: r.nVariables }));
    }
    case "site_variables": {
      // `catalog.siteVariables(placeId, {dataset:"measurements", imputation})`（1回の
      // 問い合わせ）が返す系列（tuple）単位の行を alias 単位に付け替える
      // 純関数の変換（Issue #48 PR-1 論点A: 以前は地点にある alias ごとに
      // summarize() を別々に呼ぶ N+1 だった）。
      const siteId = String(params.site_id);
      const rows = await catalog.siteVariables(db, siteId, { dataset: "measurements", imputation, source: catalogSource });
      const out: RawRow[] = [];
      for (const r of rows) {
        const info = seriesInfo(r.series);
        const alias = info?.aliases[0];
        if (!alias) continue;
        out.push({
          alias,
          // v1 の `kind`（`site_var.kind`）は daily/annual。`input_grain='day'` が
          // 積み上げ（日次セルから）、それ以外は出典配布（design §3.2）。
          kind: r.inputGrain === "day" ? "daily" : "annual",
          n: r.n,
          y_from: r.yFrom,
          y_to: r.yTo,
          avg: r.avg,
          unit: unitLabel(r.series.unitId),
        });
      }
      return out;
    }
    case "water_bodies": {
      // 画面（`/sites`・`/api/geo/sites`）と同じ `catalog.waterBodies({dataset})`
      // を呼ぶ（design §8.4 チェック項目2。以前は地点ロールアップの独自集計だった）。
      const rows = await catalog.waterBodies(db, { dataset: "measurements", source: catalogSource });
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
      const rows = await catalog.waterBodies(db, { series, source: catalogSource });
      return rows.map((r) => ({ name: r.name, n_sites: r.nSites, n: r.nMeas, y_from: r.yFrom, y_to: r.yTo, elev_max: r.elevMax }));
    }
    case "sites_in_water_body": {
      const water = String(params.water);
      const rows = await catalog.sitesInWaterBody(db, water, { dataset: "measurements", source: catalogSource });
      return rows.map((r) => ({ site_id: r.siteId, n_meas: r.nMeas, n_var: r.nVariables, municipality: r.municipality }));
    }
    case "year_series_site":
    case "year_series_water": {
      const series = seriesForAlias("measurements", String(params.alias));
      const scope: CellSpec["scope"] =
        id === "year_series_site"
          ? { kind: "site", siteId: String(params.site_id) }
          : { kind: "water", municipality: String(params.water) };
      const spec: CellSpec = {
        series,
        scope,
        grain: ["year", "fiscal_year"],
        stats: ["mean", "min", "max"],
        inputGrain: params.kind === "daily" ? "day" : "same",
        imputation,
        limit: UNLIMITED_CELL_LIMIT,
      };
      const { rows: cells } = await queryCells(db, spec);
      return pivotYearCells(cells);
    }
    case "month_series_site": {
      const series = seriesForAlias("measurements", String(params.alias));
      const spec: CellSpec = {
        series,
        scope: { kind: "site", siteId: String(params.site_id) },
        grain: "month" as CellSpec["grain"],
        stats: ["mean"],
        imputation,
        limit: UNLIMITED_CELL_LIMIT,
      };
      const { rows: cells } = await queryCells(db, spec);
      return cells.map((c) => ({ site_id: c.siteId, ym: c.periodStart.slice(0, 7), n: c.n, avg: c.value }));
    }
    case "day_series_site": {
      const series = seriesForAlias("measurements", String(params.alias));
      const spec: CellSpec = {
        series,
        scope: { kind: "site", siteId: String(params.site_id) },
        grain: "day",
        stats: ["mean"],
        imputation,
        limit: UNLIMITED_CELL_LIMIT,
      };
      const { rows: cells } = await queryCells(db, spec);
      return cells.map((c) => ({ site_id: c.siteId, d: c.periodStart.slice(0, 10), value: c.value, n_censored: c.nCensored }));
    }
    case "zone_series": {
      const series = seriesForAlias("measurements", String(params.alias));
      const spec: CellSpec = {
        series,
        scope: { kind: "zone" },
        grain: ["year", "fiscal_year"],
        stats: ["mean"],
        inputGrain: params.kind === "daily" ? "day" : "same",
        imputation,
        limit: UNLIMITED_CELL_LIMIT,
      };
      const { rows } = await summarize(db, spec, "zone");
      // `SummaryRow`（`zone` バリアント＝`ZoneYearRow`）は行ごとの系列情報を持たない
      // （`observation.ts` 参照——複数系列を1グループに混ぜて summarize するのが
      // 設計の前提のため）。呼び出し時に確定している `series`（1 alias 分）から
      // 単位を引く（design §3.3 の単位の項）。
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
      const spec: CellSpec = { series, scope: { kind: "all_sites" }, grain: "day", imputation, limit: UNLIMITED_CELL_LIMIT };
      const { rows } = await summarize(db, spec, "month_of_year");
      const unit = unitLabel(series[0]?.unitId ?? null);
      return rows.map((r) => ({ month: r.month, n: r.n, avg: r.avg, min: r.min, max: r.max, unit }));
    }
    case "zone_climatology": {
      const series = seriesForAlias("measurements", String(params.alias));
      const spec: CellSpec = {
        series,
        scope: { kind: "zone" },
        grain: "month" as CellSpec["grain"],
        imputation,
        limit: UNLIMITED_CELL_LIMIT,
      };
      const { rows } = await summarize(db, spec, "zone_month_of_year");
      const unit = unitLabel(series[0]?.unitId ?? null);
      return rows.map((r) => ({ zone: r.zone, month: r.month, n: r.n, avg: r.avg, unit }));
    }
    case "rain_monthly_clim": {
      const spec = rainDailySumSpec();
      const { rows } = await summarize(db, spec, "month_of_year", { measure: "sum_per_year" });
      return rows.map((r) => ({ month: r.month, mm: r.avg }));
    }
    case "longitudinal_highlight": {
      const water =
        params.variant === "representative" ? (await catalog.waterBodies(db))[0]?.name : "境川（１）";
      let alias: string;
      let series: SeriesInfo[];
      if (params.variant === "representative") {
        const top = (await aliasCatalog(db))[0];
        alias = top?.alias ?? "生物化学的酸素要求量 BOD";
        series = top ? top.series : seriesForAlias("measurements", alias);
      } else {
        alias = "生物化学的酸素要求量 BOD";
        series = seriesForAlias("measurements", alias);
      }
      const spec: CellSpec = {
        series,
        scope: { kind: "water", municipality: String(water) },
        grain: "year",
        inputGrain: "day",
        period: { from: "2020-01-01" },
        imputation,
        limit: UNLIMITED_CELL_LIMIT,
      };
      const { rows } = await summarize(db, spec, "place");
      const unit = unitLabel(series[0]?.unitId ?? null);
      return rows.map((r) => ({ site_id: r.siteId, avg: r.avg, n: r.n, unit }));
    }

    /* ---------------------------------------------------------------- */
    /* by_variable（design §3 #2「series_merge」。alias→variable_id の束ね。   */
    /* v1 側は `merge-v1.ts`（registry の alias→variable_id 対応）で束ね直した */
    /* 行と突き合わせる——ここは画面・AI と同じ `lib/cube` の公開関数（               */
    /* `representativeSeries`/`yearSeries`/`monthSeries`/`daySeries`/`summarize`/ */
    /* `catalog.*`）を呼ぶだけで、束ねの算術は一切持たない（束ねは lib/cube の    */
    /* SQL・`representativeSeries` の選定に委ねる）。                          */
    /* ---------------------------------------------------------------- */

    case "variable_catalog_by_variable": {
      const rows = await catalog.variableCatalog(db, { dataset: "measurements", source: catalogSource });
      return rows.map((r) => ({
        variable_id: r.variableId,
        unit: unitLabel(r.unitId),
        n: r.n,
        n_places: r.nPlaces,
        y_from: r.yFrom,
        y_to: r.yTo,
        n_censored: r.nCensored,
      }));
    }
    case "site_variables_by_variable": {
      // `catalog.siteVariables` は (variable_id, obs_stat, unit_id, value_grain,
      // grain, input_grain) ごとに別行を返す。ここで variable_id×basis まで
      // 束ねる（avg は design の「Σ(avg·n)/Σn」）——束ねる理由は2つ:
      // (1) obs_stat が alias 単位では一意に決まらない（実測: alias 'pH' は
      // 出典によって point/mean が混在する——`merge-v1.ts` の docstring 参照）。
      // (2) `basis` は `value_grain` だけでは決まらない——実測: alias
      // '生物化学的酸素要求量 BOD' の day/mean tuple（value_grain='day'）は
      // ある地点（atsugi の一部）で `input_grain='day'`（実測日次の積み上げ、
      // 36件）と `input_grain='fiscal_year'`（出典が直接年度値だけを報告、
      // 192件）の**両方**のセルを持つ。v1 の `kind`（`_MEAS_YEAR_SQL` の
      // `CASE WHEN input_grain='day' THEN 'daily' ELSE 'annual' END`）は
      // value_grain ではなく input_grain で決まるので、こちら（v2）も
      // `siteSeriesBasis()`（`inputGrain==='day'` か否か）で判定する
      // ——`basisFromValueGrain(valueGrain)` だけで判定すると、上のケースで
      // 本来 別basis（day と fiscal_year）になるはずの2グループを誤って
      // 1つの 'day' に合流させてしまう（n・avg が両方とも v1 と食い違う）。
      const siteId = String(params.site_id);
      const rows = await catalog.siteVariables(db, siteId, { dataset: "measurements", imputation, source: catalogSource });

      interface StatGroup {
        n: number;
        yFrom: number;
        yTo: number;
        avgWeightedSum: number;
        avgWeight: number;
        unitCounts: Map<string | null, number>;
      }
      const groups = new Map<string, { variableId: string; basis: string; g: StatGroup }>();
      for (const r of rows) {
        const basis = siteSeriesBasis(r);
        const key = `${r.series.variableId}\u0000${basis}`;
        let entry = groups.get(key);
        if (!entry) {
          entry = {
            variableId: r.series.variableId,
            basis,
            g: { n: 0, yFrom: Number.POSITIVE_INFINITY, yTo: Number.NEGATIVE_INFINITY, avgWeightedSum: 0, avgWeight: 0, unitCounts: new Map() },
          };
          groups.set(key, entry);
        }
        entry.g.n += r.n;
        if (r.yFrom < entry.g.yFrom) entry.g.yFrom = r.yFrom;
        if (r.yTo > entry.g.yTo) entry.g.yTo = r.yTo;
        if (r.avg !== null) {
          entry.g.avgWeightedSum += r.avg * r.n;
          entry.g.avgWeight += r.n;
        }
        entry.g.unitCounts.set(r.series.unitId, (entry.g.unitCounts.get(r.series.unitId) ?? 0) + r.n);
      }

      return [...groups.values()].map(({ variableId, basis, g }) => ({
        variable_id: variableId,
        basis,
        n: g.n,
        y_from: g.yFrom,
        y_to: g.yTo,
        avg: g.avgWeight > 0 ? g.avgWeightedSum / g.avgWeight : null,
        unit: unitLabel(pickUnitByWeight(g.unitCounts)),
      }));
    }
    case "year_series_site_by_variable": {
      const { rows: points } = await yearSeries(db, {
        variableId: String(params.variable_id),
        basis: params.basis as "day" | "fiscal_year" | "year",
        scope: { kind: "site", siteId: String(params.site_id) },
        imputation,
        limit: UNLIMITED_CELL_LIMIT,
      });
      return points.map((p) => ({
        year: p.year,
        n: p.n,
        n_censored: p.nCensored,
        avg: p.value.mean,
        min: p.value.min,
        max: p.value.max,
        unit: unitLabel(p.unitId),
      }));
    }
    case "month_series_site_by_variable": {
      const { rows: points } = await monthSeries(db, {
        variableId: String(params.variable_id),
        scope: { kind: "site", siteId: String(params.site_id) },
        imputation,
        limit: UNLIMITED_CELL_LIMIT,
      });
      return points.map((p) => ({ ym: p.periodStart.slice(0, 7), n: p.n, avg: p.value }));
    }
    case "day_series_site_by_variable": {
      const { rows: points } = await daySeries(db, {
        variableId: String(params.variable_id),
        scope: { kind: "site", siteId: String(params.site_id) },
        imputation,
        limit: UNLIMITED_CELL_LIMIT,
      });
      return points.map((p) => ({ d: p.periodStart.slice(0, 10), value: p.value, n_censored: p.nCensored }));
    }
    case "zone_series_by_variable": {
      const variableId = String(params.variable_id);
      const basis = params.basis as "day" | "fiscal_year" | "year";
      const series = representativeSeries(variableId, "measurements");
      const spec: CellSpec = {
        series,
        scope: { kind: "zone" },
        // basis='day' は積み上げ（year グレインだけ生まれる。fiscal_year は
        // 含めても input_grain='day' の行が無いので無害）。basis='fiscal_year'/
        // 'year' は出典配布（grain 自体が意味を持つ）なので、その grain だけに
        // 絞る——絞らないと `inputGrain:'same'` は fiscal_year 基準でも year 基準
        // でも同じ式（input_grain=grain）になり、2つの basis が同じ行を返して
        // しまう（実測のバグ。`year_series_site_by_variable`/`observation.ts`
        // の `yearSeries` は `yearCellFilterForBasis` がセル自身の `grain`/
        // `input_grain` で絞る（系列を `value_grain` で絞り込まない）ため、
        // この種の混同が起きない）。
        grain: basis === "day" ? ["year", "fiscal_year"] : [basis],
        stats: ["mean"],
        inputGrain: basis === "day" ? "day" : "same",
        imputation,
        limit: UNLIMITED_CELL_LIMIT,
      };
      const { rows } = await summarize(db, spec, "zone");
      const unit = unitLabel(firstUnit(series));
      return rows.map((r) => ({ zone: r.zone, year: r.year, n_sites: r.nSites, n: r.n, avg: r.avg, unit }));
    }
    case "climatology_by_variable": {
      const variableId = String(params.variable_id);
      const series = representativeSeries(variableId, "measurements");
      const spec: CellSpec = { series, scope: { kind: "all_sites" }, grain: "day", imputation, limit: UNLIMITED_CELL_LIMIT };
      const { rows } = await summarize(db, spec, "month_of_year");
      const unit = unitLabel(firstUnit(series));
      return rows.map((r) => ({ month: r.month, n: r.n, avg: r.avg, min: r.min, max: r.max, unit }));
    }
    case "zone_climatology_by_variable": {
      const variableId = String(params.variable_id);
      const series = representativeSeries(variableId, "measurements");
      const spec: CellSpec = {
        series,
        scope: { kind: "zone" },
        grain: "month" as CellSpec["grain"],
        imputation,
        limit: UNLIMITED_CELL_LIMIT,
      };
      const { rows } = await summarize(db, spec, "zone_month_of_year");
      const unit = unitLabel(firstUnit(series));
      return rows.map((r) => ({ zone: r.zone, month: r.month, n: r.n, avg: r.avg, unit }));
    }
    case "water_bodies_for_variable_by_variable": {
      const variableId = String(params.variable_id);
      const series = representativeSeries(variableId, "measurements");
      const rows = await catalog.waterBodies(db, { series, source: catalogSource });
      return rows.map((r) => ({ name: r.name, n_sites: r.nSites, n: r.nMeas, y_from: r.yFrom, y_to: r.yTo, elev_max: r.elevMax }));
    }

    default:
      throw new Error(`v2 アダプタが未対応の問い合わせ id: ${id}`);
  }
}

/**
 * `catalogSource`（既定 `{kind:'summary'}`——画面・API・AI と同じ経路）。
 * `--v1compat-db` の第2接続（`serving-diff.mts`）もこの既定のまま呼ぶ。
 * `scripts/b00_run_full_gate.py` の `PIPELINE_STEPS`（CI `sample-gate` も同様）が
 * v1互換段にも `scripts/b13_build_summary.py --v2-db data/db/v2_v1compat.sqlite`
 * を足したため、`v2_v1compat.sqlite` の事前集計 summary 2表は
 * `--include-synthetic` 後のキューブから作り直され、本番の `v2.sqlite` とは
 * 別内容になっている（以前は `v2.sqlite` をコピーした時点のままで本番と
 * 同じ値しか返らず、`{kind:'live'}` で観測キューブの生表を直接集計する
 * 回避策が要った——その制約は解消済み）。
 */
export async function runV2Query(
  db: CubeDb,
  id: string,
  params: Record<string, ScalarParam>,
  compare: CompareSpec,
  imputation: AvgImputation,
  catalogSource: CatalogSource = { kind: "summary" },
): Promise<NormRow[]> {
  const rows = await fetchRawRows(db, id, params, imputation, catalogSource);
  return toNormRows(rows, compare.key, compare.numeric, compare.label);
}
