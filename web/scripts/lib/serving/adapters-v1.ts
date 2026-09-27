/**
 * v1 アダプタ: `web/src/lib/queries.ts` を **無変更で** 呼び、`serving_queries.yaml`
 * の `id` ごとに行を集めて `NormRow[]` に正規化する。
 *
 * `queries.ts` の `import { query, queryOne, queryChunked, ph } from "./db"` は、
 * このプロセスを `node --import ./scripts/lib/serving/register-aliases.mjs` で
 * 起動したときだけ `web/scripts/lib/v1-db-shim.ts`（better-sqlite3）に差し替わる。
 * このファイル自身は `queries.ts` を普通に import するだけで、差し替えの仕組みを
 * 一切知らない（`register-aliases.mjs` のコメント参照）。
 *
 * パラメータの列挙（`enumerateParams`）は v1 の db（derived.sqlite/ryuiki.sqlite）
 * だけを見る（設計書 §1「domains の db は v1」）。v1-db-shim の `query()` を
 * 直接呼ぶ——`queries.ts` 経由ではなく、`serving_queries.yaml` の `domains`/
 * `only_existing` の SQL をそのまま実行する薄い経路。
 */
import Database from "better-sqlite3";
import * as queries from "../../../src/lib/queries";
import { query as v1RawQuery, ph } from "../v1-db-shim";
import * as mergeV1 from "./merge-v1";
import {
  toNormRows,
  type CompareSpec,
  type DomainDef,
  type NormRow,
  type QueryDef,
  type RawRow,
  type ScalarParam,
} from "./normalize";

const DATASET = "measurements";

/* ------------------------------------------------------------------ */
/* パラメータの列挙                                                     */
/* ------------------------------------------------------------------ */

async function resolveDomain(domains: Record<string, DomainDef>, name: string, registryDbPath: string): Promise<ScalarParam[]> {
  const d = domains[name];
  if (!d) throw new Error(`serving_queries.yaml に domains.${name} が無い`);
  if (d.values) return d.values;
  if (d.sql && d.db === "v1") {
    const rows = await v1RawQuery<Record<string, ScalarParam>>(d.sql);
    const firstCol = rows.length ? Object.keys(rows[0])[0] : undefined;
    if (!firstCol) return [];
    return rows.map((r) => r[firstCol]);
  }
  if (d.sql && d.db === "registry") {
    // `variable_id` ドメイン専用: v1 db は variable_id を知らないので
    // `registry.sqlite` を別接続で直接読む（`merge-v1.ts` と同じ規約）。
    const db = new Database(registryDbPath, { readonly: true, fileMustExist: true });
    try {
      const rows = db.prepare(d.sql).all() as Record<string, ScalarParam>[];
      const firstCol = rows.length ? Object.keys(rows[0])[0] : undefined;
      if (!firstCol) return [];
      return rows.map((r) => r[firstCol]);
    } finally {
      db.close();
    }
  }
  throw new Error(`domains.${name} の形が不正（sql+db(v1|registry) か values のどちらかが要る）`);
}

/**
 * `year_series_site_by_variable`/`month_series_site_by_variable`/
 * `day_series_site_by_variable` 用のパラメータ列挙（design §3 #2）。
 * `site_var`（(site_id, alias, kind) の distinct 一覧、既存 `site_id` ドメインが
 * 読むのと同じ表）を registry の alias→variable_id/basis 対応（`merge-v1.ts`）で
 * 付け替え、実在する (variable_id, site_id, basis) だけを列挙する
 * （`only_existing` と同じ「v1 の実データにある組だけを回す」考え方を、
 * variable_id という v1 に無い概念のぶんだけ registry 越しに行う）。
 */
interface SiteAliasKindRow {
  site_id: string;
  alias: string;
  kind: "daily" | "annual";
}

async function siteAliasKindRows(): Promise<SiteAliasKindRow[]> {
  return v1RawQuery<SiteAliasKindRow>(`SELECT DISTINCT site_id, variable AS alias, kind FROM site_var`);
}

async function enumerateYearSeriesByVariable(registryDbPath: string): Promise<Record<string, ScalarParam>[]> {
  const rows = await siteAliasKindRows();
  const infos = mergeV1.loadAliasInfos(registryDbPath, DATASET);
  const seen = new Set<string>();
  const out: Record<string, ScalarParam>[] = [];
  for (const r of rows) {
    const info = infos.get(r.alias);
    if (!info) continue;
    // `merge-v1.ts` の `aliasKindRoutes` と同じ規約: 真の annual tuple が無い
    // alias（`hasAnnualGrain=false`。例: 'pH'）は kind='annual' の行も 'day' に
    // 合流させる。
    const basis: mergeV1.Basis = r.kind === "daily" || !info.hasAnnualGrain ? "day" : info.annualBasis;
    const key = `${info.variableId}\u0000${r.site_id}\u0000${basis}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({ variable_id: info.variableId, site_id: r.site_id, basis });
  }
  return out;
}

/** `month_series_site_by_variable`/`day_series_site_by_variable`（basis='day' 固定
 *  ——`lib/cube` の `monthSeries`/`daySeries` 自体が day 以外を拒む）用の列挙。 */
async function enumerateDayBasisSeriesByVariable(registryDbPath: string): Promise<Record<string, ScalarParam>[]> {
  const rows = await siteAliasKindRows();
  const infos = mergeV1.loadAliasInfos(registryDbPath, DATASET);
  const seen = new Set<string>();
  const out: Record<string, ScalarParam>[] = [];
  for (const r of rows) {
    if (r.kind !== "daily") continue;
    const info = infos.get(r.alias);
    if (!info) continue;
    const key = `${info.variableId}\u0000${r.site_id}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({ variable_id: info.variableId, site_id: r.site_id });
  }
  return out;
}

/**
 * v1 の `site_var`（distinct site_id, alias）を registry の alias→variable_id
 * （`merge-v1.ts`。代表フィルタなし——`allGroups` 参照）で束ね、地点ごとの
 * distinct variable_id 数を数える。`sites_list` の `n_var` の意味変更
 * （alias 数→variable 数、design 表）用。
 */
async function distinctVariableCountsPerSite(registryDbPath: string): Promise<Map<string, number>> {
  const rows = await v1RawQuery<{ site_id: string; alias: string }>(`SELECT DISTINCT site_id, variable AS alias FROM site_var`);
  const infos = mergeV1.loadAliasInfos(registryDbPath, DATASET);
  const bySite = new Map<string, Set<string>>();
  for (const r of rows) {
    const info = infos.get(r.alias);
    if (!info) continue;
    let set = bySite.get(r.site_id);
    if (!set) {
      set = new Set();
      bySite.set(r.site_id, set);
    }
    set.add(info.variableId);
  }
  const out = new Map<string, number>();
  for (const [siteId, set] of bySite) out.set(siteId, set.size);
  return out;
}

/** `--mutate merge_rule_off` 専用: 束ねを無効化する（design §8.1 U4）。呼び出し側
 *  は代表 alias 集合の代わりに常に空配列を受け取り、v1 側の行が0件になる
 *  ——v2 側は変わらず正しく束ねるので、必ず `row_only_in_v2` として検出される。 */
function aliasListOrEmpty(mergeDisabled: boolean, aliases: readonly string[]): string[] {
  return mergeDisabled ? [] : [...aliases];
}

/**
 * `--mutate merge_rule_off` で v1 側のフェッチが変わる問い合わせ id の宣言。
 * `fetchRawRows` の switch のうち、`aliasListOrEmpty`（または `mergeDisabled ? [] :`）
 * を実際に使う `*_by_variable` case とちょうど同じ集合——ここでの宣言を唯一の
 * 正とし、`serving-diff.mts`（分類段で再フェッチが要るかの判定）もこれを呼ぶ。
 * 以前は `def.id.endsWith("_by_variable")` という別の推測を `serving-diff.mts`
 * 側に書いており、この switch の実装と二重に知識を持っていた。
 */
const MERGE_DISABLED_QUERY_IDS: ReadonlySet<string> = new Set([
  "variable_catalog_by_variable",
  "site_variables_by_variable",
  "year_series_site_by_variable",
  "month_series_site_by_variable",
  "day_series_site_by_variable",
  "zone_series_by_variable",
  "climatology_by_variable",
  "zone_climatology_by_variable",
  "water_bodies_for_variable_by_variable",
]);

export function usesMergeDisabled(id: string): boolean {
  return MERGE_DISABLED_QUERY_IDS.has(id);
}

function cartesian(paramNames: string[], values: Record<string, ScalarParam[]>): Record<string, ScalarParam>[] {
  let acc: Record<string, ScalarParam>[] = [{}];
  for (const name of paramNames) {
    const next: Record<string, ScalarParam>[] = [];
    for (const base of acc) {
      for (const v of values[name]) {
        next.push({ ...base, [name]: v });
      }
    }
    acc = next;
  }
  return acc;
}

/**
 * `--expand all`（既定）で使う、この問い合わせの全パラメータの組。
 * `year_series_site_by_variable`/`month_series_site_by_variable`/
 * `day_series_site_by_variable` は variable_id が v1 に無い概念のため専用の
 * 列挙（上の `enumerateYearSeriesByVariable`/`enumerateDayBasisSeriesByVariable`）
 * を使う。それ以外は `only_existing` があればそれを優先し（v1 の実データに
 * ある組だけを回す）、無ければ `params` の各ドメインの直積を返す。
 */
export async function enumerateParams(
  def: QueryDef,
  domains: Record<string, DomainDef>,
  registryDbPath: string,
): Promise<Record<string, ScalarParam>[]> {
  if (def.id === "year_series_site_by_variable") return enumerateYearSeriesByVariable(registryDbPath);
  if (def.id === "month_series_site_by_variable" || def.id === "day_series_site_by_variable") {
    return enumerateDayBasisSeriesByVariable(registryDbPath);
  }
  if (def.onlyExisting) {
    return v1RawQuery<Record<string, ScalarParam>>(def.onlyExisting);
  }
  const paramNames = Object.keys(def.params);
  if (paramNames.length === 0) return [{}];
  const values: Record<string, ScalarParam[]> = {};
  for (const name of paramNames) {
    const domainName = def.params[name].domain;
    values[name] = await resolveDomain(domains, domainName, registryDbPath);
  }
  return cartesian(paramNames, values);
}

/* ------------------------------------------------------------------ */
/* 問い合わせ本体（id ごとに queries.ts を呼ぶ）                          */
/* ------------------------------------------------------------------ */

async function highlightParams(variant: ScalarParam): Promise<[string, string]> {
  if (variant === "representative") {
    const [waters, cat] = await Promise.all([queries.listWaterBodies(), queries.variableCatalog()]);
    const water = waters[0]?.name ?? "境川（１）";
    const alias = cat[0]?.variable ?? "生物化学的酸素要求量 BOD";
    return [water, alias];
  }
  return ["境川（１）", "生物化学的酸素要求量 BOD"];
}

async function fetchRawRows(
  id: string,
  params: Record<string, ScalarParam>,
  registryDbPath: string,
  mergeDisabled: boolean,
): Promise<RawRow[]> {
  switch (id) {
    case "variable_catalog": {
      const rows = await queries.variableCatalog();
      return rows.map((r) => ({ ...r, alias: r.variable }));
    }
    case "sites_list": {
      // `n_var` は distinct variable_id 数（design「sites_list（n_var→variable
      // 数）」）。`queries.listSites()` 自身の `n_var`（distinct alias 数）は
      // 使わず、`distinctVariableCountsPerSite` で束ね直す。
      const rows = await queries.listSites();
      const variableCounts = await distinctVariableCountsPerSite(registryDbPath);
      return rows.map((r) => ({ site_id: r.site_id, n_meas: r.n_meas, n_var: variableCounts.get(r.site_id) ?? 0 }));
    }
    case "site_variables": {
      const rows = await queries.siteVariables(String(params.site_id));
      return rows.map((r) => ({ ...r, alias: r.variable }));
    }
    case "water_bodies": {
      const rows = await queries.listWaterBodies();
      return rows.map((r) => ({ ...r }));
    }
    case "water_bodies_for_variable": {
      return await queries.waterBodiesForVariable(String(params.alias));
    }
    case "sites_in_water_body": {
      // `sites_list` と同じ理由で `n_var` を variable_id 数に付け替える。
      const rows = await queries.sitesInWaterBody(String(params.water));
      const variableCounts = await distinctVariableCountsPerSite(registryDbPath);
      return rows.map((r) => ({
        site_id: r.site_id,
        n_meas: r.n_meas,
        n_var: variableCounts.get(r.site_id) ?? 0,
        municipality: r.municipality,
      }));
    }
    case "year_series_site": {
      const rows = await queries.yearSeries(
        String(params.alias),
        [String(params.site_id)],
        params.kind as "daily" | "annual",
      );
      return rows.map((r) => ({ ...r }));
    }
    case "month_series_site": {
      const rows = await queries.monthSeries(String(params.alias), [String(params.site_id)]);
      return rows.map((r) => ({ ...r }));
    }
    case "day_series_site": {
      const rows = await queries.daySeries(String(params.alias), [String(params.site_id)]);
      return rows.map((r) => ({ ...r }));
    }
    case "year_series_water": {
      const sites = await queries.sitesInWaterBody(String(params.water));
      const ids = sites.map((s) => s.site_id);
      const rows = await queries.yearSeries(String(params.alias), ids, params.kind as "daily" | "annual");
      return rows.map((r) => ({ ...r }));
    }
    case "zone_series": {
      const rows = await queries.zoneSeries(String(params.alias), params.kind as "daily" | "annual");
      return rows.map((r) => ({ ...r }));
    }
    case "climatology": {
      return await queries.climatology(String(params.alias));
    }
    case "zone_climatology": {
      return await queries.zoneClimatology(String(params.alias));
    }
    case "rain_monthly_clim": {
      // `rain_daily`/`rain_top_days`（`mode=rain`）は D5・読み手なしで PR-2 で
      // 削除した（`adapters-v2.ts` 冒頭コメント参照）。季節図が使う
      // `rain_monthly_clim` だけ残す。
      return await queries.rainMonthlyClim();
    }
    case "longitudinal_highlight": {
      const [water, alias] = await highlightParams(params.variant);
      return await queries.longitudinalHighlight(water, alias);
    }

    /* ------------------------------------------------------------------ */
    /* by_variable（design §3 #2）。alias 単位の v1 表を `merge-v1.ts` の         */
    /* 代表 alias 集合で `IN (...)` に束ね、`scripts/b05_project_v1.py` の元の    */
    /* 集計式をそのまま alias 1件→複数件に広げて再実行する（JS 側で加重平均を    */
    /* 再構成しない——`merge-v1.ts` のモジュール docstring 参照）。               */
    /* ------------------------------------------------------------------ */

    case "variable_catalog_by_variable": {
      const groups = mergeV1.allGroups(registryDbPath, DATASET);
      const out: RawRow[] = [];
      for (const [variableId, infos] of groups) {
        const aliases = aliasListOrEmpty(mergeDisabled, infos.map((a) => a.alias));
        if (aliases.length === 0) continue;
        const rows = await v1RawQuery<{
          unit: string | null;
          n: number | null;
          n_places: number;
          y_from: number | null;
          y_to: number | null;
          n_censored: number | null;
        }>(
          `SELECT MAX(unit) AS unit, SUM(n) AS n, COUNT(DISTINCT site_id) AS n_places,
                  MIN(year) AS y_from, MAX(year) AS y_to, SUM(n_censored) AS n_censored
           FROM meas_year WHERE variable IN (${ph(aliases)})`,
          aliases,
        );
        const r = rows[0];
        if (!r || r.n === null) continue;
        out.push({
          variable_id: variableId,
          unit: r.unit,
          n: r.n,
          n_places: r.n_places,
          y_from: r.y_from,
          y_to: r.y_to,
          n_censored: r.n_censored,
        });
      }
      return out;
    }
    case "site_variables_by_variable": {
      // `stat`（obs_stat）は束ねの key に含めない（`merge-v1.ts`
      // `aliasKindRoutes` の docstring 参照——alias 単位では一意に決まらない）。
      // `kind`（daily/annual）は `am.basis`（alias の登録 grain から決まる、
      // T4 相当の不変条件で一意）でそのまま basis に対応する——
      // v1 の `_MEAS_YEAR_SQL` 自身が `kind = CASE WHEN input_grain='day'
      // THEN 'daily' ELSE 'annual' END` で決めており、`adapters-v2.ts` 側も
      // `SiteSeriesRow.inputGrain`（=`day` かどうか）で同じ判定をする
      // （`@/lib/cube` の `basisOfCell` 参照）ので、alias 単位の kind→basis 対応で揃う。
      const siteId = String(params.site_id);
      const routes: mergeV1.AliasKindRoute[] = mergeDisabled ? [] : mergeV1.aliasKindRoutes(registryDbPath, DATASET);
      if (routes.length === 0) return [];
      // SQLite は `(VALUES ...) AS t(col1,col2)`（FROM 句での直接の列リネーム）を
      // サポートしない（実測: "near '(': syntax error"）。`WITH t(col1,col2) AS
      // (VALUES ...)` の名前付き CTE なら列名を持てる。
      const valuesSql = routes.map(() => "(?,?,?,?)").join(",");
      const valuesParams = routes.flatMap((r) => [r.alias, r.kind, r.variableId, r.basis]);
      return v1RawQuery<RawRow>(
        `WITH am(alias, kind, variable_id, basis) AS (VALUES ${valuesSql})
         SELECT am.variable_id AS variable_id, am.basis AS basis,
                SUM(y.n) AS n, MIN(y.year) AS y_from, MAX(y.year) AS y_to, AVG(y.avg) AS avg, MAX(y.unit) AS unit
         FROM meas_year y
         JOIN am ON am.alias = y.variable AND am.kind = y.kind
         WHERE y.site_id = ?
         GROUP BY am.variable_id, am.basis`,
        [...valuesParams, siteId],
      );
    }
    case "year_series_site_by_variable": {
      const variableId = String(params.variable_id);
      const siteId = String(params.site_id);
      const basis = String(params.basis) as mergeV1.Basis;
      const aliases = aliasListOrEmpty(mergeDisabled, mergeV1.aliasesForBasis(registryDbPath, DATASET, variableId, basis));
      if (aliases.length === 0) return [];
      const kind: mergeV1.Kind = basis === "day" ? "daily" : "annual";
      return v1RawQuery<RawRow>(
        `SELECT year, n, avg, min, max, n_censored, unit FROM meas_year
         WHERE site_id = ? AND kind = ? AND variable IN (${ph(aliases)})`,
        [siteId, kind, ...aliases],
      );
    }
    case "month_series_site_by_variable": {
      const variableId = String(params.variable_id);
      const siteId = String(params.site_id);
      const aliases = aliasListOrEmpty(mergeDisabled, mergeV1.aliasesForBasis(registryDbPath, DATASET, variableId, "day"));
      if (aliases.length === 0) return [];
      return v1RawQuery<RawRow>(
        `SELECT ym, n, avg FROM meas_month WHERE site_id = ? AND variable IN (${ph(aliases)})`,
        [siteId, ...aliases],
      );
    }
    case "day_series_site_by_variable": {
      const variableId = String(params.variable_id);
      const siteId = String(params.site_id);
      const aliases = aliasListOrEmpty(mergeDisabled, mergeV1.aliasesForBasis(registryDbPath, DATASET, variableId, "day"));
      if (aliases.length === 0) return [];
      return v1RawQuery<RawRow>(
        `SELECT d, value, n_censored FROM meas_daily WHERE site_id = ? AND variable IN (${ph(aliases)})`,
        [siteId, ...aliases],
      );
    }
    case "zone_series_by_variable": {
      // `s.zone IS NOT NULL`: `sites.zone` が NULL の地点（実測 352 地点中 62）を
      // 除く。v2 側のゾーン集計（`lib/cube/sql.ts` の `buildScopeSql`/
      // `zoneExprSql`）は `place_relation`（zone を持つ地点だけが登録される）を
      // INNER JOIN するため、zone 無し地点は最初から集計対象に現れない
      // （既存の alias 単位の `zone_series` が使う `zone_year` 表も、b05 の
      // `site_zone_lookup` が同じ INNER JOIN で作るので同様）。ここは
      // `sites` に直接 JOIN するため、絞り込まないと zone=NULL の
      // スプリアスな行（実測: `row_only_in_v1` として大量に出た）が混じる。
      const variableId = String(params.variable_id);
      const basis = String(params.basis) as mergeV1.Basis;
      const aliases = aliasListOrEmpty(mergeDisabled, mergeV1.aliasesForBasis(registryDbPath, DATASET, variableId, basis));
      if (aliases.length === 0) return [];
      const kind: mergeV1.Kind = basis === "day" ? "daily" : "annual";
      return v1RawQuery<RawRow>(
        `SELECT s.zone AS zone, y.year AS year,
                COUNT(DISTINCT y.site_id) AS n_sites, SUM(y.n) AS n, AVG(y.avg) AS avg, MAX(y.unit) AS unit
         FROM meas_year y JOIN sites s ON s.site_id = y.site_id
         WHERE y.kind = ? AND y.variable IN (${ph(aliases)}) AND s.zone IS NOT NULL
         GROUP BY s.zone, y.year`,
        [kind, ...aliases],
      );
    }
    case "climatology_by_variable": {
      const variableId = String(params.variable_id);
      const aliases = aliasListOrEmpty(mergeDisabled, mergeV1.aliasesForBasis(registryDbPath, DATASET, variableId, "day"));
      if (aliases.length === 0) return [];
      return v1RawQuery<RawRow>(
        `SELECT CAST(substr(d,6,2) AS INT) AS month, COUNT(*) AS n, AVG(value) AS avg, MIN(value) AS min, MAX(value) AS max, MAX(unit) AS unit
         FROM meas_daily WHERE variable IN (${ph(aliases)})
         GROUP BY month`,
        aliases,
      );
    }
    case "zone_climatology_by_variable": {
      // `s.zone IS NOT NULL`: `zone_series_by_variable` と同じ理由
      // （そのコメント参照）。
      const variableId = String(params.variable_id);
      const aliases = aliasListOrEmpty(mergeDisabled, mergeV1.aliasesForBasis(registryDbPath, DATASET, variableId, "day"));
      if (aliases.length === 0) return [];
      return v1RawQuery<RawRow>(
        `SELECT s.zone AS zone, m.month AS month, SUM(m.n) AS n, AVG(m.avg) AS avg, MAX(m.unit) AS unit
         FROM meas_month m JOIN sites s ON s.site_id = m.site_id
         WHERE m.variable IN (${ph(aliases)}) AND s.zone IS NOT NULL
         GROUP BY s.zone, m.month`,
        aliases,
      );
    }
    case "water_bodies_for_variable_by_variable": {
      // v2 側は `representativeSeries(variableId)`（代表フィルタあり）を渡す
      // ので、こちらも代表 alias だけを使う（`allAliasesFor` だと非代表 alias
      // ——例: 'BOD 75%値'——の n まで合算してしまい v2 と食い違う）。
      const variableId = String(params.variable_id);
      const aliases = aliasListOrEmpty(mergeDisabled, mergeV1.representativeAliasesFor(registryDbPath, DATASET, variableId));
      if (aliases.length === 0) return [];
      return v1RawQuery<RawRow>(
        `SELECT s.municipality AS name, COUNT(DISTINCT v.site_id) AS n_sites, SUM(v.n) AS n,
                MIN(v.y_from) AS y_from, MAX(v.y_to) AS y_to, MAX(s.elevation_m) AS elev_max
         FROM site_var v JOIN sites s USING(site_id)
         WHERE v.variable IN (${ph(aliases)}) AND s.municipality IS NOT NULL AND s.municipality <> ''
         GROUP BY s.municipality
         HAVING n_sites >= 2
         ORDER BY n_sites DESC, n DESC`,
        aliases,
      );
    }

    default:
      throw new Error(`v1 アダプタが未対応の問い合わせ id: ${id}`);
  }
}

/**
 * 1つの問い合わせ id・1組のパラメータに対する v1 側の結果を `NormRow[]` にして返す。
 * `mergeDisabled`（`--mutate merge_rule_off`）は by_variable 問い合わせだけに効く
 * （それ以外の id は無視する——`fetchRawRows` の各 case 参照）。
 */
export async function runV1Query(
  id: string,
  params: Record<string, ScalarParam>,
  compare: CompareSpec,
  registryDbPath: string,
  opts?: { mergeDisabled?: boolean },
): Promise<NormRow[]> {
  const rows = await fetchRawRows(id, params, registryDbPath, opts?.mergeDisabled ?? false);
  return toNormRows(rows, compare.key, compare.numeric, compare.label);
}
