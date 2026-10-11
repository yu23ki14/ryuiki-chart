/**
 * 種の一覧を「流域・期間・赤リスト」で絞る問い合わせ（`speciesCatalog` の `placeId`/`yearFrom`/`yearTo`/`redListOnly`）。
 *
 * `summary_species_catalog` は流域も期間も持たないので、`occurrence_agg` を直接 GROUP BY する
 * （`watershedYears` と同じ書き方: 年族のセル、流域は索引 `place_period`、出典・地域の絞りもそのまま効く）。
 * 流域の指定時は `place_kind='watershed'` の系列だけを数える（`n` は流域に解決できた記録の件数。海上・流域の外の
 * 記録は `place_id` NULL のセルに入るのでここには出ない）。`nLocated`/`nPlaces` は grid01 系列の値で、流域の指定時は 0。
 *
 * 赤リストの出所（`redListCategory`/`redListSource`）は D1 の語彙から引く（v2 の `occurrence.red_list_category`/
 * `red_list_source` と同じ値。`scripts/m03_organisms.py` の `taxa_lookup` と同じ規則）:
 * 地域の県版 → 無ければ環境省の全国版（`taxa.redlist_national`、出所は 'national'）。
 * 県版は `PREF_REDLIST`（`scripts/regions.py` の `pref_redlist` と同じ宣言）で、奄美は `taxon_assessment`
 * （`kgrl2014`）、神奈川は `taxa.redlist_kanagawa`（出所は `taxon_assessment` の新しい版）。
 * 種（binom）の中で亜種などの taxon が違うカテゴリを持つときは、赤リスト件数が最も多い taxon のものを返す。
 */
import { OCCURRENCE_AGG_INDEX } from "@/db/schema-cube";
import type { RegionId } from "@/lib/region";
import type { CubeDb, SqlParam } from "./db";
import { OCC_BOTH_KINDS_YEAR, OCC_MESH_N, OCC_N_ALL, OCC_N_LOCATED, OCC_SUM, labelMap } from "./occurrence";
import { regionPred } from "./region";
import { YEAR_GRAINS, jsonEachParam, uniq } from "./sql";
import type { SpeciesCatalogRow } from "./catalog";

export const NATIONAL_SOURCE = "national";

/** 地域ごとの県版レッドリストの宣言（`scripts/regions.py` の `pref_redlist` と揃える）。 */
export const PREF_REDLIST: Readonly<Record<string, { kind: "taxa_column"; listIds: readonly string[] } | { kind: "assessment"; listId: string }>> = {
  "jp-14": { kind: "taxa_column", listIds: ["rl2020", "rl2026"] },
  "jp-46": { kind: "assessment", listId: "kgrl2014" },
};

export interface SpeciesInPlaceOpt {
  placeId?: string;
  yearFrom?: number;
  yearTo?: number;
  redListOnly?: boolean;
  group?: string | null;
  limit?: number;
  withNames?: boolean;
  search?: { cond: string; params: SqlParam[] } | null;
  sourceIds?: readonly string[];
  region?: RegionId;
}

type R = Record<string, string | number | null>;

const yearStart = (y: number) => String(y).padStart(4, "0");

function filters(opt: SpeciesInPlaceOpt): { index: string; where: string; params: SqlParam[] } {
  const params: SqlParam[] = [];
  let where: string;
  let index: string = OCCURRENCE_AGG_INDEX.kindGrainPeriod;
  if (opt.placeId !== undefined) {
    index = OCCURRENCE_AGG_INDEX.placePeriod;
    where = `o.place_kind = 'watershed' AND o.place_id = ? AND o.grain IN ${YEAR_GRAINS}`;
    params.push(opt.placeId);
  } else {
    where = OCC_BOTH_KINDS_YEAR;
  }
  if (opt.yearFrom !== undefined) {
    where += " AND o.period_start >= ?";
    params.push(yearStart(opt.yearFrom));
  }
  if (opt.yearTo !== undefined) {
    where += " AND o.period_start < ?";
    params.push(yearStart(opt.yearTo + 1));
  }
  if (opt.sourceIds !== undefined) {
    where += " AND o.source_id IN (SELECT value FROM json_each(?))";
    params.push(jsonEachParam(uniq(opt.sourceIds)));
  }
  const rp = regionPred("o", opt.region);
  if (rp.sql) {
    where += ` AND ${rp.sql}`;
    params.push(...rp.params);
  }
  return { index, where, params };
}

export async function speciesInPlace(db: CubeDb, opt: SpeciesInPlaceOpt): Promise<SpeciesCatalogRow[]> {
  const f = filters(opt);
  const params: SqlParam[] = [...f.params];
  let extra = "";
  if (opt.search) {
    extra += ` AND ${opt.search.cond}`;
    params.push(...opt.search.params);
  }
  const having: string[] = [];
  if (opt.group) {
    having.push("MAX(t.taxon_group) = ?");
    params.push(opt.group);
  }
  if (opt.redListOnly) having.push("SUM(o.n_red_list) > 0");
  params.push(opt.limit ?? 200);
  const rows = await db.all<R>(
    `SELECT t.canonical_binomial AS binom, MAX(t.taxon_group) AS taxon_group, MAX(t."class") AS "class", MAX(t.family) AS family,
            ${OCC_N_ALL} AS n, ${OCC_N_LOCATED} AS n_located,
            ${OCC_SUM("n_red_list", "watershed")} AS n_red_list,
            ${OCC_SUM("n_alien", "watershed")} AS n_alien,
            ${OCC_MESH_N} AS n_places,
            MIN(CAST(substr(o.period_start, 1, 4) AS INTEGER)) AS y_from,
            MAX(CAST(substr(o.period_start, 1, 4) AS INTEGER)) AS y_to,
            COUNT(DISTINCT substr(o.period_start, 1, 4)) AS n_years
     FROM occurrence_agg o INDEXED BY ${f.index}
     JOIN taxon t ON t.taxon_id = o.taxon_id
     WHERE ${f.where} AND t.canonical_binomial IS NOT NULL${extra}
     GROUP BY t.canonical_binomial${having.length ? ` HAVING ${having.join(" AND ")}` : ""}
     ORDER BY n DESC, binom LIMIT ?`,
    params,
  );
  const out: SpeciesCatalogRow[] = rows.map((r) => ({
    binom: r.binom as string,
    taxonGroup: r.taxon_group as string | null,
    class: r.class as string | null,
    family: r.family as string | null,
    n: r.n as number,
    nLocated: r.n_located as number,
    nRedList: r.n_red_list as number,
    nAlien: r.n_alien as number,
    nPlaces: r.n_places as number,
    yFrom: r.y_from as number | null,
    yTo: r.y_to as number | null,
    nYears: r.n_years as number,
  }));
  if (opt.withNames && out.length > 0) {
    const labels = await labelMap(db, out.map((r) => r.binom), {});
    for (const r of out) r.label = labels.get(r.binom) ?? r.binom;
  }
  await attachRedListOrigin(db, out, f);
  return out;
}

const normName = (s: string | null) => (s ?? "").replace(/\s+/g, " ").trim().toLowerCase();

/** 赤リスト件数のある種に、カテゴリと出所を付ける（無い種は null のまま）。 */
async function attachRedListOrigin(db: CubeDb, rows: SpeciesCatalogRow[], f: { index: string; where: string; params: SqlParam[] }): Promise<void> {
  const listed = rows.filter((r) => r.nRedList > 0);
  for (const r of rows) {
    r.redListCategory = null;
    r.redListSource = null;
  }
  if (listed.length === 0) return;
  // 種の中の (taxon, 地域) ごとの赤リスト件数。最も多い taxon の判定を種の値にする。
  const parts = await db.all<R>(
    `SELECT t.canonical_binomial AS binom, t.scientific_name AS sci, o.region_id AS region_id, SUM(o.n_red_list) AS rl
     FROM occurrence_agg o INDEXED BY ${f.index}
     JOIN taxon t ON t.taxon_id = o.taxon_id
     WHERE ${f.where} AND o.n_red_list > 0
       AND t.canonical_binomial IN (SELECT value FROM json_each(?))
     GROUP BY t.canonical_binomial, t.taxon_id, o.region_id`,
    [...f.params, jsonEachParam(listed.map((r) => r.binom))],
  );
  const keys = uniq(parts.map((p) => normName(p.sci as string | null)).filter(Boolean));
  if (keys.length === 0) return;
  const keyParam = jsonEachParam(keys);
  const assess = await db.all<R>(
    `SELECT lower(trim(scientific_name_raw)) AS k, list_id, list_year, category_raw, category_code
     FROM taxon_assessment
     WHERE lower(trim(scientific_name_raw)) IN (SELECT value FROM json_each(?))
     ORDER BY list_year DESC`,
    [keyParam],
  );
  const taxa = await db.all<R>(
    `SELECT taxon_id AS k, redlist_kanagawa, redlist_national FROM taxa WHERE taxon_id IN (SELECT value FROM json_each(?))`,
    [keyParam],
  );
  const taxaBy = new Map(taxa.map((t) => [t.k as string, t]));
  const text = (a: R) => (a.category_code ? `${a.category_raw}（${a.category_code}）` : (a.category_raw as string));
  const assessOf = (k: string, listIds: readonly string[]) => assess.find((a) => a.k === k && listIds.includes(a.list_id as string));

  const best = new Map<string, { rl: number; category: string | null; source: string | null }>();
  for (const p of parts) {
    const k = normName(p.sci as string | null);
    const decl = PREF_REDLIST[p.region_id as string];
    let category: string | null = null;
    let source: string | null = null;
    if (decl?.kind === "assessment") {
      const a = assessOf(k, [decl.listId]);
      if (a) [category, source] = [text(a), decl.listId];
    } else if (decl?.kind === "taxa_column") {
      const t = taxaBy.get(k);
      if (t?.redlist_kanagawa) [category, source] = [t.redlist_kanagawa as string, (assessOf(k, decl.listIds)?.list_id as string | undefined) ?? null];
    }
    if (category === null) {
      const nat = taxaBy.get(k)?.redlist_national as string | null | undefined;
      if (nat) [category, source] = [nat, NATIONAL_SOURCE];
    }
    const cur = best.get(p.binom as string);
    if (!cur || (p.rl as number) > cur.rl) best.set(p.binom as string, { rl: p.rl as number, category, source });
  }
  for (const r of rows) {
    const b = best.get(r.binom);
    if (b) [r.redListCategory, r.redListSource] = [b.category, b.source];
  }
}
