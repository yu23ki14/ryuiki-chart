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
import * as queries from "../../../src/lib/queries";
import { query as v1RawQuery } from "../v1-db-shim";
import {
  toNormRows,
  type CompareSpec,
  type DomainDef,
  type NormRow,
  type QueryDef,
  type RawRow,
  type ScalarParam,
} from "./normalize";

/* ------------------------------------------------------------------ */
/* パラメータの列挙                                                     */
/* ------------------------------------------------------------------ */

async function resolveDomain(domains: Record<string, DomainDef>, name: string): Promise<ScalarParam[]> {
  const d = domains[name];
  if (!d) throw new Error(`serving_queries.yaml に domains.${name} が無い`);
  if (d.values) return d.values;
  if (d.sql && d.db === "v1") {
    const rows = await v1RawQuery<Record<string, ScalarParam>>(d.sql);
    const firstCol = rows.length ? Object.keys(rows[0])[0] : undefined;
    if (!firstCol) return [];
    return rows.map((r) => r[firstCol]);
  }
  throw new Error(`domains.${name} の形が不正（sql+db か values のどちらかが要る）`);
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
 * `only_existing` があればそれを優先し（v1 の実データにある組だけを回す）、
 * 無ければ `params` の各ドメインの直積を返す。
 */
export async function enumerateParams(
  def: QueryDef,
  domains: Record<string, DomainDef>,
): Promise<Record<string, ScalarParam>[]> {
  if (def.onlyExisting) {
    return v1RawQuery<Record<string, ScalarParam>>(def.onlyExisting);
  }
  const paramNames = Object.keys(def.params);
  if (paramNames.length === 0) return [{}];
  const values: Record<string, ScalarParam[]> = {};
  for (const name of paramNames) {
    const domainName = def.params[name].domain;
    values[name] = await resolveDomain(domains, domainName);
  }
  return cartesian(paramNames, values);
}

/* ------------------------------------------------------------------ */
/* 問い合わせ本体（id ごとに queries.ts を呼ぶ）                          */
/* ------------------------------------------------------------------ */

const RAIN_FROM = "0001-01-01";
const RAIN_TO = "9999-12-31";
const RAIN_TOP_N = 10;

/** `rain_top_days` の順位付け（v1/v2 で ORDER BY のタイブレークが揺れないよう、
 *  mm 降順の後ろに日付昇順の副ソートを必ずかけてから rank を振る）。 */
function rankRainDays(rows: { d: string; mm: number }[]): RawRow[] {
  const sorted = [...rows].sort((a, b) => b.mm - a.mm || a.d.localeCompare(b.d));
  return sorted.slice(0, RAIN_TOP_N).map((r, i) => ({ rank: i + 1, d: r.d, mm: r.mm }));
}

async function highlightParams(variant: ScalarParam): Promise<[string, string]> {
  if (variant === "representative") {
    const [waters, cat] = await Promise.all([queries.listWaterBodies(), queries.variableCatalog()]);
    const water = waters[0]?.name ?? "境川（１）";
    const alias = cat[0]?.variable ?? "生物化学的酸素要求量 BOD";
    return [water, alias];
  }
  return ["境川（１）", "生物化学的酸素要求量 BOD"];
}

async function fetchRawRows(id: string, params: Record<string, ScalarParam>): Promise<RawRow[]> {
  switch (id) {
    case "variable_catalog": {
      const rows = await queries.variableCatalog();
      return rows.map((r) => ({ ...r, alias: r.variable }));
    }
    case "sites_list": {
      const rows = await queries.listSites();
      return rows.map((r) => ({ ...r }));
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
      const rows = await queries.sitesInWaterBody(String(params.water));
      return rows.map((r) => ({ ...r }));
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
    case "rain_daily": {
      return await queries.rainDaily(RAIN_FROM, RAIN_TO);
    }
    case "rain_monthly_clim": {
      return await queries.rainMonthlyClim();
    }
    case "rain_top_days": {
      const rows = await queries.rainTopDays(RAIN_TOP_N * 4);
      return rankRainDays(rows);
    }
    case "longitudinal_highlight": {
      const [water, alias] = await highlightParams(params.variant);
      return await queries.longitudinalHighlight(water, alias);
    }
    default:
      throw new Error(`v1 アダプタが未対応の問い合わせ id: ${id}`);
  }
}

/** 1つの問い合わせ id・1組のパラメータに対する v1 側の結果を `NormRow[]` にして返す。 */
export async function runV1Query(
  id: string,
  params: Record<string, ScalarParam>,
  compare: CompareSpec,
): Promise<NormRow[]> {
  const rows = await fetchRawRows(id, params);
  return toNormRows(rows, compare.key, compare.numeric, compare.label);
}
