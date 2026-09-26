/**
 * v1 側の alias→variable_id 束ね（`*_by_variable` 問い合わせ、design §3 #2）。
 *
 * **`@/lib/cube` を import しない**（v1 の「正解」を v2 のコードから作らないため——
 * タスク指示・design §8.1）。alias→variable_id の対応（registry の生ボキャブラリ）は
 * `registry.sqlite` を別接続で直接読むだけで、`@/lib/cube/series.ts` の
 * `representativeSeries`/`seriesForAlias` は一切使わない。
 *
 * **束ねの算術は「v1 の元の集計 SQL を、alias 1件の `=` の代わりに代表 alias
 * 集合の `IN (...)` で回す」方式にする**（このファイル自身は算術を持たず、
 * `adapters-v1.ts` 側で `scripts/b05_project_v1.py` の `_VAR_CATALOG_SQL`/
 * `_SITE_VAR_SQL`/`_ZONE_YEAR_SQL`/`_ZONE_CLIM_SQL`/`_MEAS_CLIM_SQL`/
 * `waterBodiesForVariable` と**同じ SQL 文字列**を alias 1件条件だけ変えて使う）。
 * 「複数 alias の avg を JS で加重平均して再構成する」方式は、v1 の元の SQL が
 * 何に対して等ウェイトを取っているか（年ごと・日ごと・地点年ごと）が問い合わせ
 * ごとに違うため近似になりうる（zone_year/zone_clim は `AVG(site年ごとの avg)`
 * であって `AVG(全日次値)` ではない、等）。SQL を丸ごと再実行すれば
 * 常に厳密に一致する——このモジュールは「どの alias を IN (...) に入れるか」
 * （代表/フォールバックの選定・grain の割り当て）だけを決める。
 */
import Database from "better-sqlite3";

const REPRESENTATIVE_STATS = new Set<string | null>([null, "mean", "point"]);

interface RawAliasTuple {
  alias: string;
  variable_id: string;
  stat: string | null;
  grain: string | null;
}

export type Basis = "day" | "fiscal_year" | "year";
export type Kind = "daily" | "annual";

export interface AliasInfo {
  alias: string;
  variableId: string;
  /** この alias の tuple のうち1つでも obs_stat が代表（null/mean/point）なら true。 */
  representative: boolean;
  /** この alias が 'day' grain の tuple を持つか（meas_daily/meas_month に載るか）。 */
  hasDayGrain: boolean;
  /** この alias が 'fiscal_year'/'year'（= v1 の 'annual' kind）の tuple を持つか。 */
  hasAnnualGrain: boolean;
  /** `hasAnnualGrain` が真のとき、その annual データがどちらの basis に属するか
   *  （grain='year' の tuple を持てば 'year'、そうでなければ 'fiscal_year'。
   *  同じ alias が両方持つことは T4 相当の不変条件として例外にする）。
   *  `hasAnnualGrain` が偽のときは意味を持たない（既定 'fiscal_year'）。 */
  annualBasis: Basis;
}

/** `registry.sqlite` を直接読む（`@/lib/registry/generated` は経由しない）。 */
function loadRawAliasTuples(registryDbPath: string, dataset: string): RawAliasTuple[] {
  const db = new Database(registryDbPath, { readonly: true, fileMustExist: true });
  try {
    return db
      .prepare(
        `SELECT DISTINCT alias, variable_id, stat, grain
         FROM variable_alias WHERE dataset = ? AND variable_id IS NOT NULL`,
      )
      .all(dataset) as RawAliasTuple[];
  } finally {
    db.close();
  }
}

const cache = new Map<string, Map<string, AliasInfo>>();

/**
 * alias（v1 の `variable` 列の値）ごとの情報。同じ (registryDbPath, dataset) の
 * 組み合わせについてはプロセス内でキャッシュする（`registry.sqlite` は
 * serving-diff の1回の実行中は不変という前提——他のキャッシュ
 * （`adapters-v2.ts` の `aliasCatalogCache` 等）と同じ規約）。
 */
export function loadAliasInfos(registryDbPath: string, dataset: string): Map<string, AliasInfo> {
  const cacheKey = `${registryDbPath}\u0000${dataset}`;
  const hit = cache.get(cacheKey);
  if (hit) return hit;

  const rows = loadRawAliasTuples(registryDbPath, dataset);
  const byAlias = new Map<string, RawAliasTuple[]>();
  for (const r of rows) {
    const list = byAlias.get(r.alias) ?? [];
    list.push(r);
    byAlias.set(r.alias, list);
  }

  const out = new Map<string, AliasInfo>();
  for (const [alias, tuples] of byAlias) {
    const variableIds = new Set(tuples.map((t) => t.variable_id));
    if (variableIds.size > 1) {
      throw new Error(
        `merge-v1: alias '${alias}' が複数の variable_id にまたがっている（T4 不変条件が破れている）: ${[...variableIds].join(",")}`,
      );
    }
    const variableId = tuples[0].variable_id;
    const hasYearGrain = tuples.some((t) => t.grain === "year");
    const hasFiscalYearGrain = tuples.some((t) => t.grain === "fiscal_year");
    if (hasYearGrain && hasFiscalYearGrain) {
      throw new Error(
        `merge-v1: alias '${alias}' が fiscal_year と year の両方の grain を持つ（annual バケットの割り当てが一意に決まらない）`,
      );
    }
    const hasDayGrain = tuples.some((t) => t.grain === "day");
    const hasAnnualGrain = hasYearGrain || hasFiscalYearGrain;
    const annualBasis: Basis = hasYearGrain ? "year" : "fiscal_year";

    // `obs_stat` は alias ごとに一意とは限らない（実測: alias 'pH' は
    // 出典によって day/point（合成・env_kousui）と day/mean（atsugi）の両方を
    // 持つ）。v1 の alias 単位の表（meas_year/meas_month/meas_daily/site_var）は
    // 出典・obs_stat を持たない（alias だけで既に混ざって集計されている）ため、
    // `AliasInfo` では obs_stat を追わない——`site_variables_by_variable` は
    // variable_id×basis まで（stat では束ねない。`aliasKindRoutes` 参照）。

    out.set(alias, {
      alias,
      variableId,
      representative: tuples.some((t) => REPRESENTATIVE_STATS.has(t.stat)),
      hasDayGrain,
      hasAnnualGrain,
      annualBasis,
    });
  }
  cache.set(cacheKey, out);
  return out;
}

/** テスト用（フィクスチャごとに別の registry.sqlite を読ませるとき）。 */
export function clearMergeV1Cache(): void {
  cache.clear();
}

function byVariable(infos: Map<string, AliasInfo>): Map<string, AliasInfo[]> {
  const out = new Map<string, AliasInfo[]>();
  for (const info of infos.values()) {
    const list = out.get(info.variableId) ?? [];
    list.push(info);
    out.set(info.variableId, list);
  }
  return out;
}

/**
 * ある variable_id を束ねるのに使う alias の集合——**代表 obs_stat の alias だけ**
 * （design §0 決定4 のフォールバック付き: 代表 alias が1つも無ければ全 alias に
 * フォールバックする。`@/lib/cube` の `representativeSeries` と同じ規約を、
 * alias 粒度で独立に実装する）。`year_series_site_by_variable`/`month_…`/`day_…`/
 * `zone_series_by_variable`/`climatology_by_variable`/`zone_climatology_by_variable`/
 * `water_bodies_for_variable_by_variable`——v2 側が `representativeSeries(variableId)`
 * を呼ぶ問い合わせ全部——が使う。
 */
export function representativeGroups(registryDbPath: string, dataset: string): Map<string, AliasInfo[]> {
  const grouped = byVariable(loadAliasInfos(registryDbPath, dataset));
  const out = new Map<string, AliasInfo[]>();
  for (const [variableId, group] of grouped) {
    const representative = group.filter((g) => g.representative);
    out.set(variableId, representative.length > 0 ? representative : group);
  }
  return out;
}

/**
 * ある variable_id に属する alias **全部**（代表フィルタなし）。`catalog.variableCatalog`/
 * `catalog.siteVariables`（v2 側。`variable_catalog_by_variable`/`site_variables_by_variable`
 * が呼ぶ）は obs_stat で絞り込まず、その variable_id に属する系列を全部束ねる
 * （`catalog.ts` の `bundleVariableCatalog`/`siteVariablesSummary` 参照——p75/p90/max/min
 * のような非代表 alias も n・avg に含まれる）。v1 側もこれに合わせて絞り込まない。
 */
export function allGroups(registryDbPath: string, dataset: string): Map<string, AliasInfo[]> {
  return byVariable(loadAliasInfos(registryDbPath, dataset));
}

/** `representativeGroups` の variable_id 一覧（`domains.variable_id` 用）。 */
export function variableIdsOf(registryDbPath: string, dataset: string): string[] {
  return [...representativeGroups(registryDbPath, dataset).keys()].sort();
}

/**
 * ある variable_id・basis に実際にデータを持つ代表 alias の集合。
 * `basis='day'` は `hasDayGrain`、それ以外は `hasAnnualGrain && annualBasis`
 * が一致する alias。
 *
 * **`hasAnnualGrain` で絞る**（`aliasKindRoutes` は絞らない——そちらの
 * docstring 参照）: `year_series_site_by_variable`/`zone_series_by_variable`
 * 等、この関数を使う v2 側は `representativeSeries(variableId)`（`aliasKindRoutes`
 * が支える `site_variables_by_variable`/`catalog.siteVariables` と違い、
 * value_grain が登録されている tuple の集合）を経由する。`observation.ts` の
 * `yearSeries`（`seriesForBasis`）は要求された basis に一致する value_grain の
 * tuple が1つも無いと例外を投げる——`hasAnnualGrain` で絞らずに真の annual
 * tuple を持たない alias（例: 'pH'）を fiscal_year ドメインに含めると、
 * v2 側の呼び出しが例外になる（`--only` の実測で確認済み）。絞った結果
 * v1 側だけが「地点によっては annual-kind の行を持つが、その行を
 * どの basis の問い合わせでも拾えない」隙間が残ることがある——これは
 * v2 の `yearSeries`/`seriesForBasis` の仕様（value_grain 単位の tuple
 * 選択）に起因する隙間で、lib/cube 側の設計判断（U4 の報告参照。
 * このアダプタでは埋められない）。
 */
export function aliasesForBasis(registryDbPath: string, dataset: string, variableId: string, basis: Basis): string[] {
  const group = representativeGroups(registryDbPath, dataset).get(variableId) ?? [];
  return group
    .filter((a) => (basis === "day" ? a.hasDayGrain : a.hasAnnualGrain && a.annualBasis === basis))
    .map((a) => a.alias);
}

/** ある variable_id の alias 全部（代表フィルタなし。kind を問わない。
 *  `variable_catalog_by_variable`/`water_bodies_for_variable_by_variable` 用）。 */
export function allAliasesFor(registryDbPath: string, dataset: string, variableId: string): string[] {
  return (allGroups(registryDbPath, dataset).get(variableId) ?? []).map((a) => a.alias);
}

/** ある variable_id の**代表** alias（kind を問わない。`water_bodies_for_variable_by_variable`
 *  用——v2 側が `representativeSeries(variableId)` を呼ぶので、非代表 alias
 *  （p75/p90/max/min）を含めない。`allAliasesFor` との違いはこの代表フィルタだけ）。 */
export function representativeAliasesFor(registryDbPath: string, dataset: string, variableId: string): string[] {
  return (representativeGroups(registryDbPath, dataset).get(variableId) ?? []).map((a) => a.alias);
}

/**
 * `site_variables_by_variable` 用: 全 variable_id の alias **全部**（代表フィルタなし
 * ——`allGroups` 参照）について、(alias, kind, variable_id, basis) の行。
 * meas_year/site_var の `variable`(alias)/`kind` から (variable_id, basis) への
 * 付け替え表そのもの。`stat`（obs_stat）は含めない——alias レベルでは一意に
 * 決まらない（実測: 'pH' は出典によって point/mean が混在する）ため、v1 の
 * alias 単位の表（元々 obs_stat を持たない）に合わせて variable_id×basis までで
 * 束ねる（`adapters-v2.ts` 側もこの粒度まで obs_stat を束ねて合わせる）。
 */
export interface AliasKindRoute {
  alias: string;
  kind: Kind;
  variableId: string;
  basis: Basis;
}

export function aliasKindRoutes(registryDbPath: string, dataset: string): AliasKindRoute[] {
  const groups = allGroups(registryDbPath, dataset);
  const out: AliasKindRoute[] = [];
  for (const [variableId, group] of groups) {
    for (const a of group) {
      if (a.hasDayGrain) {
        out.push({ alias: a.alias, kind: "daily", variableId, basis: "day" });
      }
      // kind='annual' は常に `annualBasis`（既定 'fiscal_year'、grain='year' の
      // tuple を持てば 'year'）に出す——真の annual tuple の登録
      // （`hasAnnualGrain`）は問わない。実測: alias 'pH' は登録された annual
      // tuple を持たない（day のみ）が、一部地点（atsugi 系）で同じ
      // value_grain='day' tuple の中に `input_grain='fiscal_year'` のセルが
      // 混ざる（出典が直接年度値だけを報告した年）。`site_variables_by_variable`
      // の v2 側（`adapters-v2.ts` の `siteSeriesBasis`）はセル単位で
      // `input_grain==='day'` か否かだけを見て basis を決める（alias に
      // 真の annual tuple が登録されているかは見ない）ため、v1 側もここで
      // 同じ「registration を問わない」判定に揃える——`hasAnnualGrain` で
      // 絞ると、v2 側が正しく 'day'/'fiscal_year' に分けているのに v1 側が
      // 'day' に丸ごと合流させてしまい、両者が食い違う（実測）。
      // （`year_series_site_by_variable` 等が使う `aliasesForBasis` は
      // 別の関数で、そちらは `yearSeries()` が基準に該当する系列が無いと
      // 例外を投げるのを避けるため意図的に `hasAnnualGrain` で絞っている
      // ——`aliasesForBasis` の docstring 参照）。
      out.push({ alias: a.alias, kind: "annual", variableId, basis: a.annualBasis });
    }
  }
  return out;
}

/** `? , ? , ...`（n 個）。better-sqlite3 の `IN (...)` 用（D1 の 100 件上限はここでは無関係）。 */
export function placeholders(n: number): string {
  return Array.from({ length: n }, () => "?").join(",");
}
