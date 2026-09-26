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
import { sqliteCubeDb, type SqliteCubeDbOptions } from "@/lib/cube/db-sqlite";
import * as catalog from "@/lib/cube/catalog";
import {
  queryCells,
  summarize,
  seriesForAlias,
  seriesInfo,
  seriesFilterSql,
  isSynthetic,
  labelYear,
  YEAR_GRAINS_SQL,
  MEAN_STAT_SQL,
  type CubeDb,
  type CellSpec,
  type CellRow,
  type SeriesKey,
  type SeriesInfo,
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

export function openV2Db(paths: V2Paths, opts?: SqliteCubeDbOptions): CubeDb & { close(): void } {
  if (!sharedDb) sharedDb = sqliteCubeDb(paths, opts);
  // `sharedDb` は module スコープの `let`（`closeV2Db` からも再代入される）ため、
  // TypeScript は直前の代入によるナローイングをここでは効かせない
  // （クロージャから書き換えられうる変数の narrowing 制限）。直前の if で
  // 必ず代入済みなので non-null で問題ない。
  return sharedDb!;
}

export function closeV2Db(): void {
  sharedDb?.close();
  sharedDb = undefined;
  siteMeasurementRollupCache = undefined;
  siteMunicipalityCache = undefined;
  aliasCatalogCache = undefined;
}

/**
 * `--pretend-synthetic-excluded`（設計書 §9-4・PR-1 統合オーナー決定）専用:
 * 「地点の全セルが合成系列（`isSynthetic`）だけからできている」`place_id` の集合を
 * `observation_agg` から機械的に求める。ゾーン集計で合成データと実データが同じ
 * 系列（tuple）に混ざる地点（例: 浮遊物質量 SS の atsugi）はここでは対象外
 * （atsugi 自身は実データの tuple も持つので「全部合成」ではない）。
 * `sites.is_synthetic` を読まない（v1 の宣言に頼らず lib/cube の `isSynthetic` だけを
 * 正にする——タスク指示「合成地点・系列の集合は lib/cube の isSynthetic から埋める」）。
 */
export async function computeSyntheticPlaceIds(db: CubeDb): Promise<string[]> {
  const rows = await db.all<{
    place_id: string;
    variable_id: string;
    obs_stat: string | null;
    unit_id: string | null;
    value_grain: string | null;
  }>(
    `SELECT DISTINCT obs.place_id AS place_id, obs.variable_id AS variable_id, obs.obs_stat AS obs_stat,
            obs.unit_id AS unit_id, obs.value_grain AS value_grain
     FROM observation_agg obs
     WHERE obs.place_kind = 'site' AND ${YEAR_GRAINS_SQL} AND ${MEAN_STAT_SQL}`,
  );
  const allSyntheticByPlace = new Map<string, boolean>();
  for (const r of rows) {
    const info = seriesInfo({ variableId: r.variable_id, obsStat: r.obs_stat, unitId: r.unit_id, valueGrain: r.value_grain ?? "" });
    const synthetic = !!info && isSynthetic(info);
    const prev = allSyntheticByPlace.get(r.place_id);
    allSyntheticByPlace.set(r.place_id, prev === undefined ? synthetic : prev && synthetic);
  }
  return [...allSyntheticByPlace.entries()].filter(([, allSynthetic]) => allSynthetic).map(([placeId]) => placeId);
}

/** `computeSyntheticPlaceIds` の結果を v1 の `site_id`（`sites.site_id`）に逆引きする。 */
export async function siteIdsForPlaceIds(db: CubeDb, placeIds: readonly string[]): Promise<string[]> {
  if (placeIds.length === 0) return [];
  const rows = await db.all<{ external_key: string }>(
    `SELECT external_key FROM place_source_ref
     WHERE source_id = 'sites.site_id' AND place_id IN (SELECT value FROM json_each(?))`,
    [JSON.stringify(placeIds)],
  );
  return rows.map((r) => r.external_key);
}

const RAIN_TOP_N = 10;

function unitLabel(unitId: string | null): string | null {
  return unitSymbol(unitId);
}

/**
 * `year_series_site`/`year_series_water` が使う。`observation_agg` の年セルは
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
    if (c.stat === "mean") row.avg = c.valueZero;
    else if (c.stat === "min") row.min = c.valueZero;
    else if (c.stat === "max") row.max = c.valueZero;
  }
  return [...byKey.values()];
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
  yFrom: number | null;
  yTo: number | null;
  nDaily: number;
  nAnnual: number;
  nCensored: number;
}

/**
 * alias に対応する系列集合（複数 tuple ありうる）を1つに合流させた年セル集計
 * （v1 `_VAR_CATALOG_SQL` の `GROUP BY variable` 相当——`kind`（daily/annual）も
 * またいで合流する）。`@/lib/cube` の `seriesFilterSql`（`variable_id` 前段フィルタ
 * 込み）を使い、`observation_agg` に直接問い合わせる。
 */
async function seriesYearlyTotal(db: CubeDb, series: readonly SeriesInfo[]): Promise<SeriesYearlyTotal | null> {
  const alias = "obs";
  const f = seriesFilterSql(series as readonly SeriesKey[], alias);
  if (!f) return null;
  const sql = `
    SELECT SUM(${alias}.n) AS n, COUNT(DISTINCT ${alias}.place_id) AS n_sites,
           MIN(CAST(substr(${alias}.period_start,1,4) AS INTEGER)) AS y_from,
           MAX(CAST(substr(${alias}.period_start,1,4) AS INTEGER)) AS y_to,
           SUM(CASE WHEN ${alias}.input_grain = 'day' THEN ${alias}.n ELSE 0 END) AS n_daily,
           SUM(CASE WHEN ${alias}.input_grain = ${alias}.grain THEN ${alias}.n ELSE 0 END) AS n_annual,
           SUM(${alias}.n_censored) AS n_censored
    FROM observation_agg ${alias}
    ${f.joins.join("\n    ")}
    WHERE ${alias}.place_kind = 'site' AND ${YEAR_GRAINS_SQL} AND ${MEAN_STAT_SQL}
  `;
  const rows = await db.all<{
    n: number | null;
    n_sites: number;
    y_from: number | null;
    y_to: number | null;
    n_daily: number;
    n_annual: number;
    n_censored: number;
  }>(sql, f.params);
  const r = rows[0];
  if (!r || r.n === null) return null;
  return { n: r.n, nSites: r.n_sites, yFrom: r.y_from, yTo: r.y_to, nDaily: r.n_daily, nAnnual: r.n_annual, nCensored: r.n_censored };
}

/* -------------------------------------------------------------------- */
/* 地点ロールアップ（`sites_list`/`sites_in_water_body`）: `measurements`      */
/* データセットだけに絞った n_meas・distinct alias 数（= v1 の n_var）       */
/* -------------------------------------------------------------------- */

interface SiteRollup {
  nMeas: number;
  /** この地点にデータがある alias の集合（`n_var` はこの集合の大きさ）。 */
  aliases: Set<string>;
}

let siteMeasurementRollupCache: Map<string, SiteRollup> | undefined;

/**
 * v1 の `site_var`（`meas_year` を `dataset='measurements'` の alias にだけ
 * INNER JOIN して作る——`scripts/b05_project_v1.py` の `_alias_lookup_sql`）相当を
 * 地点単位に合流させたもの。`aliases` は「distinct alias 数」（`catalog.ts` の
 * `nVariables`＝distinct variable_id 数でも `nSeries`＝distinct tuple 数でもない。
 * 1 alias が複数 tuple にまたがる場合も1と数える——design §0 決定2）を数えるのにも、
 * `site_variables` がこの地点で問い合わせるべき alias を列挙するのにも使う
 * （`catalog.siteVariables(db, placeId)` は `place_id` を取る関数で、v1 の
 * `site_id` 文字列をそのまま渡すと1件も一致しない——`place_source_ref` の
 * 逆引きが要る。ここは既に `psr.external_key`（site_id）で集計しているので
 * その問題が起きない）。
 */
async function siteMeasurementRollup(db: CubeDb): Promise<Map<string, SiteRollup>> {
  if (siteMeasurementRollupCache) return siteMeasurementRollupCache;
  const sql = `
    SELECT psr.external_key AS site_id, obs.variable_id, obs.obs_stat, obs.unit_id, obs.value_grain,
           SUM(obs.n) AS n
    FROM observation_agg obs
    JOIN place_source_ref psr ON psr.place_id = obs.place_id AND psr.source_id = 'sites.site_id'
    WHERE obs.place_kind = 'site' AND ${YEAR_GRAINS_SQL} AND ${MEAN_STAT_SQL}
    GROUP BY psr.external_key, obs.variable_id, obs.obs_stat, obs.unit_id, obs.value_grain
  `;
  const rows = await db.all<{
    site_id: string;
    variable_id: string;
    obs_stat: string | null;
    unit_id: string | null;
    value_grain: string | null;
    n: number;
  }>(sql);

  const out = new Map<string, SiteRollup>();
  for (const r of rows) {
    const info = seriesInfo({ variableId: r.variable_id, obsStat: r.obs_stat, unitId: r.unit_id, valueGrain: r.value_grain ?? "" });
    // v1 の site_var は measurements の alias にしか INNER JOIN しない
    // （sensor_timeseries 由来のセルは対象外——上記コメント参照）。
    if (!info || info.dataset !== "measurements") continue;
    let e = out.get(r.site_id);
    if (!e) {
      e = { nMeas: 0, aliases: new Set() };
      out.set(r.site_id, e);
    }
    e.nMeas += r.n;
    const a = info.aliases[0];
    if (a) e.aliases.add(a);
  }

  siteMeasurementRollupCache = out;
  return out;
}

let siteMunicipalityCache: Map<string, string | null> | undefined;

async function siteMunicipalities(db: CubeDb): Promise<Map<string, string | null>> {
  if (siteMunicipalityCache) return siteMunicipalityCache;
  const rows = await db.all<{ site_id: string; municipality: string | null }>("SELECT site_id, municipality FROM sites");
  siteMunicipalityCache = new Map(rows.map((r) => [r.site_id, r.municipality]));
  return siteMunicipalityCache;
}

interface AliasCatalogEntry {
  alias: string;
  series: SeriesInfo[];
  agg: SeriesYearlyTotal;
}

let aliasCatalogCache: AliasCatalogEntry[] | undefined;

/**
 * `variable_catalog` の中身（alias 単位に合流した年セル集計、n 降順）。
 * `longitudinal_highlight` の `variant: representative` も同じ並び
 * （v1 の `queries.variableCatalog()` の `ORDER BY n DESC` と同じ意味）から
 * 「最も測定数が多い alias」を選ぶ。
 */
async function aliasCatalog(db: CubeDb): Promise<AliasCatalogEntry[]> {
  if (aliasCatalogCache) return aliasCatalogCache;
  const out: AliasCatalogEntry[] = [];
  for (const alias of MEASUREMENTS_ALIASES) {
    const series = seriesForAlias("measurements", alias);
    const agg = await seriesYearlyTotal(db, series);
    if (!agg) continue;
    out.push({ alias, series, agg });
  }
  out.sort((a, b) => b.agg.n - a.agg.n);
  aliasCatalogCache = out;
  return out;
}

/**
 * measurements の alias ごとの、レジストリ上の正しい unit symbol（`series[0].unitId` の
 * `unitSymbol()`——`variable_catalog`/`site_variables`/`zone_series` 等の `unit` 列と
 * 同じ計算式）。DB を読まない（`seriesForAlias`/`unitSymbol` はどちらも registry の
 * 生成物だけを見る）ので、`db` を開く前でも呼べる。`classify.ts` の
 * `unit_label_registry` 規則が「v2 側の非NULL値なら何でも通す」のではなく、実際に
 * その系列の `unit_id` の symbol と一致するかまで確かめるのに使う。
 */
export function expectedUnitSymbols(): ReadonlyMap<string, string | null> {
  const out = new Map<string, string | null>();
  for (const alias of MEASUREMENTS_ALIASES) {
    const series = seriesForAlias("measurements", alias);
    out.set(alias, unitLabel(series[0]?.unitId ?? null));
  }
  return out;
}

/**
 * `rain_daily`/`rain_monthly_clim`/`rain_top_days` の3問い合わせが共有する
 * spec（RAIN の全地点・日次 sum。`/simplify` 指摘: 3箇所に同じ組み立てが
 * コピペされていた）。
 */
function rainDailySumSpec(): CellSpec {
  const series: SeriesKey[] = seriesForAlias("sensor_timeseries", "RAIN").map((s) => ({
    variableId: s.variableId,
    obsStat: s.obsStat,
    unitId: s.unitId,
    valueGrain: s.valueGrain,
  }));
  return { series, scope: { kind: "all_sites" }, grain: "day", stats: ["sum"], imputation: "zero" };
}

async function fetchRawRows(db: CubeDb, id: string, params: Record<string, ScalarParam>): Promise<RawRow[]> {
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
      const rollup = await siteMeasurementRollup(db);
      const municipalities = await siteMunicipalities(db);
      return [...municipalities.keys()].map((site_id) => {
        const m = rollup.get(site_id);
        return { site_id, n_meas: m?.nMeas ?? 0, n_var: m?.aliases.size ?? 0 };
      });
    }
    case "site_variables": {
      const siteId = String(params.site_id);
      const rollup = await siteMeasurementRollup(db);
      const aliasSet = rollup.get(siteId)?.aliases ?? new Set<string>();
      const out: RawRow[] = [];
      for (const alias of aliasSet) {
        const series = seriesForAlias("measurements", alias);
        const unit = unitLabel(series[0]?.unitId ?? null);
        const rows = await summarize(
          db,
          { series, scope: { kind: "site", siteId }, grain: ["year", "fiscal_year"], imputation: "zero" },
          "place",
        );
        for (const r of rows) {
          out.push({
            alias,
            // v1 の `kind`（`site_var.kind`）は daily/annual。`input_grain='day'` が
            // 積み上げ（日次セルから）、それ以外は出典配布（design §3.2）。
            kind: r.inputGrain === "day" ? "daily" : "annual",
            n: r.n,
            y_from: r.yFrom,
            y_to: r.yTo,
            avg: r.avg,
            unit,
          });
        }
      }
      return out;
    }
    case "water_bodies": {
      const rows = await catalog.waterBodies(db);
      // `catalog.waterBodies()`（無条件・series 指定なし）の `n_meas` は
      // `dataset` を絞らず地点の全セルを SUM するため、その地点が
      // sensor_timeseries（雨量等）のセルも同時に持っていると混入する。
      // v1 の `listWaterBodies()` は `site_var`（measurements の alias にしか
      // INNER JOIN しない）経由なので、ここも `siteMeasurementRollup`
      // （measurements だけに絞った地点別ロールアップ）で SUM し直す
      // （`water_bodies_for_variable` は `series` を明示するので混入しない）。
      const rollup = await siteMeasurementRollup(db);
      const municipalities = await siteMunicipalities(db);
      const nMeasByMunicipality = new Map<string, number>();
      for (const [siteId, m] of rollup) {
        const muni = municipalities.get(siteId);
        if (!muni) continue;
        nMeasByMunicipality.set(muni, (nMeasByMunicipality.get(muni) ?? 0) + m.nMeas);
      }
      return rows.map((r) => ({
        name: r.name,
        n_sites: r.nSites,
        n_meas: nMeasByMunicipality.get(r.name) ?? 0,
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
      const water = String(params.water);
      const rollup = await siteMeasurementRollup(db);
      const municipalities = await siteMunicipalities(db);
      const out: RawRow[] = [];
      for (const [siteId, municipality] of municipalities) {
        if (municipality !== water) continue;
        const m = rollup.get(siteId);
        // v1 の `sitesInWaterBody` は `site_var` に INNER JOIN する
        // （測定値が1件も無い地点は除外——`web/src/lib/queries.ts` 参照）。
        if (!m) continue;
        out.push({ site_id: siteId, n_meas: m.nMeas, n_var: m.aliases.size, municipality });
      }
      return out;
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
        imputation: "zero",
      };
      const cells = await queryCells(db, spec);
      return pivotYearCells(cells);
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
      const spec = rainDailySumSpec();
      const cells = await queryCells(db, spec);
      return cells.map((c) => ({ d: c.periodStart.slice(0, 10), mm: c.valueZero }));
    }
    case "rain_monthly_clim": {
      const spec = rainDailySumSpec();
      const rows = await summarize(db, spec, "month_of_year", { measure: "sum_per_year" });
      return rows.map((r) => ({ month: r.month, mm: r.avg }));
    }
    case "rain_top_days": {
      const spec = rainDailySumSpec();
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
        imputation: "zero",
      };
      const rows = await summarize(db, spec, "place");
      const unit = unitLabel(series[0]?.unitId ?? null);
      return rows.map((r) => ({ site_id: r.siteId, avg: r.avg, n: r.n, unit }));
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
