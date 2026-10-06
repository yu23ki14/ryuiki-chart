/**
 * v2 アダプタ: `@/lib/cube`（問い合わせ層）の公開関数を、画面・API・AI と同じ既定値で呼び、
 * `serving_queries.yaml` の `id` ごとに `NormRow[]`（`compare` の列名）として返す。
 * `web/scripts/serving-snapshot.mts` が使う。生 SQL・表名を持たない（`adapters-v2.test.ts` が検査する）。
 *
 * 呼ぶのは「画面・API・AI（`web/src/app`・`components`・`lib/ai`）のテスト以外の呼び出し元がある」
 * 公開関数だけ。alias 起点の問い合わせ（旧 v1 の oracle 専用）は PR-5 で落とした。
 * `variable_id` 起点の系列は `representativeSeries`（代表系列の選定）を通る。
 * v1 の `kind`（daily/annual）に当たる区別は `basis`（`day`/`fiscal_year`/`year`）。
 */
import * as catalog from "@/lib/cube/catalog";
import {
  summarize,
  yearSeries,
  monthSeries,
  daySeries,
  seriesForAlias,
  representativeSeries,
  basisOfCell,
  unitLabel,
  UNLIMITED_CELL_LIMIT,
  type CubeDb,
  type CellSpec,
  type SeriesKey,
  type SeriesInfo,
  type AvgImputation,
  type CatalogSource,
  // 生物系（PR-3b）。画面・API・AI が呼ぶ公開関数だけ（生 SQL を持たない。設計書 §5.4）。
  speciesCatalog,
  taxonGroupYears,
  effortRowV1,
  effortYears,
  gridCatalog,
  occurrenceTotals,
  iasSpecies,
  speciesYears,
  speciesMonths,
  speciesMeshYears,
  speciesShareTrend,
  meshByYear,
  redlistSummary,
  // 文書・概況・流域（PR-4。`api/documents`・`app/page.tsx`・`api/geo/watersheds`・AI `get_overview` と同じ関数）。
  docSeriesList,
  docSeriesPoints,
  overviewCounts,
  watershedRollup,
  landuseHighlight,
} from "@/lib/cube";
import { sqliteCubeDb } from "@/lib/cube/db-sqlite";
import {
  parseTrendPeriods,
  toNormRows,
  type CompareSpec,
  type NormRow,
  type RawRow,
  type ScalarParam,
} from "./normalize";

export interface V2Paths {
  v2: string;
  registry: string;
  ryuiki: string;
  /** `cells.sqlite`（`doc_series_*` が読む `cells`/`notes`/`documents`。PR-4）。 */
  cells: string;
}

/** 初回の呼び出しで `sqliteCubeDb` を1回だけ開き、以降は使い回す（`closeV2Db()` で閉じる）。 */
let v2Db: (CubeDb & { close(): void }) | undefined;

export function openV2Db(paths: V2Paths): CubeDb & { close(): void } {
  if (!v2Db) v2Db = sqliteCubeDb(paths);
  return v2Db;
}

export function closeV2Db(): void {
  v2Db?.close();
  v2Db = undefined;
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

/**
 * `rain_monthly_clim` が使う spec（RAIN の全地点・日次 sum）。雨量は censored の概念が無いので
 * imputation を問わず常に "zero" 固定（`lib/cube` 自身の `rainMonthlyClim` も同様）。
 */
function rainDailySumSpec(): CellSpec {
  const series: SeriesKey[] = seriesForAlias("sensor_timeseries", "RAIN");
  return { series, scope: { kind: "all_sites" }, grain: "day", stats: ["sum"], imputation: "zero", limit: UNLIMITED_CELL_LIMIT };
}

/** 「上位 N は比べない」問い合わせ（`species_catalog`）の上限。 */
const V2_NO_LIMIT = 1_000_000;

async function fetchRawRows(
  db: CubeDb,
  id: string,
  params: Record<string, ScalarParam>,
  imputation: AvgImputation,
  catalogSource: CatalogSource,
): Promise<RawRow[]> {
  switch (id) {
    case "sites_list": {
      // 画面（`/sites`）・`get_sites`（AI）と同じ `catalog.sites({source:'summary'})`
      // を呼ぶ（design §8.4 チェック項目2）。`n_var` は `nVariables`
      // （distinct variable_id 数）——alias 数ではない（`sites_list`（design D の
      // 表）の意味変更。以前は独自ロールアップで distinct alias 数を数えていた）。
      const rows = await catalog.sites(db, { dataset: "measurements", source: catalogSource });
      return rows.map((r) => ({ site_id: r.siteId, n_meas: r.nMeas, n_var: r.nVariables }));
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
    case "sites_in_water_body": {
      const water = String(params.water);
      const rows = await catalog.sitesInWaterBody(db, water, { dataset: "measurements", source: catalogSource });
      return rows.map((r) => ({ site_id: r.siteId, n_meas: r.nMeas, n_var: r.nVariables, municipality: r.municipality }));
    }
    case "rain_monthly_clim": {
      const spec = rainDailySumSpec();
      const { rows } = await summarize(db, spec, "month_of_year", { measure: "sum_per_year" });
      return rows.map((r) => ({ month: r.month, mm: r.avg }));
    }
    /* ---------------------------------------------------------------- */
    /* by_variable（design §3 #2「series_merge」。alias→variable_id の束ね。   */
    /* ここは画面・AI と同じ `lib/cube` の公開関数（                                 */
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
      // 出典によって point/mean が混在する）。
      // (2) `basis` は `value_grain` だけでは決まらない——実測: alias
      // '生物化学的酸素要求量 BOD' の day/mean tuple（value_grain='day'）は
      // ある地点（atsugi の一部）で `input_grain='day'`（実測日次の積み上げ、
      // 36件）と `input_grain='fiscal_year'`（出典が直接年度値だけを報告、
      // 192件）の**両方**のセルを持つ。v1 の `kind`（`_MEAS_YEAR_SQL` の
      // `CASE WHEN input_grain='day' THEN 'daily' ELSE 'annual' END`）は
      // value_grain ではなく input_grain で決まるので、こちら（v2）も
      // `basisOfCell()`（`lib/cube/series.ts`。`inputGrain==='day'` か否か）で
      // 判定する——`basisFromValueGrain(valueGrain)` だけで判定すると、上の
      // ケースで本来 別basis（day と fiscal_year）になるはずの2グループを
      // 誤って1つの 'day' に合流させてしまう（n・avg が両方とも v1 と食い違う）。
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
        const basis = basisOfCell(r);
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

    /* ------------------------------------------------------------------ */
    /* 生物系（Issue #48 PR-3b、`docs/plans/V2_SERVING_PR3B.md` §2.2・§3.2・§5.4）。   */
    /* **`lib/cube` の公開関数だけ**を、画面・API・AI と同じ既定値（窓 1990〜2026・    */
    /* n≥80・`records` 補完の定数）で呼ぶ。列名を v1 に揃えて返すだけで、SQL も        */
    /* 表名も持たない（`adapters-v2.test.ts` がソースを検査する）。上限は「上位 N を    */
    /* 比べない」ために十分大きく取る。                                              */
    /* ------------------------------------------------------------------ */

    case "effort_years": {
      const rows = await effortYears(db);
      return rows.map(effortRowV1);
    }
    case "taxon_group_years": {
      const rows = await taxonGroupYears(db);
      return rows.map((r) => ({ year: r.year, taxon_group: r.taxonGroup, n: r.n, mesh_n: r.meshN }));
    }
    case "species_catalog": {
      const rows = await speciesCatalog(db, { limit: V2_NO_LIMIT, withNames: true });
      return rows.map((r) => ({
        binom: r.binom,
        taxon_group: r.taxonGroup,
        cls: r.class,
        family: r.family,
        n: r.n,
        has_red_list: r.nRedList > 0 ? 1 : 0,
        y_from: r.yFrom,
        y_to: r.yTo,
        n_years: r.nYears,
        mesh_n: r.nPlaces,
        label: r.label ?? r.binom,
      }));
    }
    case "species_years": {
      const rows = await speciesYears(db, [String(params.binom)]);
      return rows.map((r) => ({ year: r.year, n: r.n, mesh_n: r.meshN }));
    }
    case "species_months": {
      const rows = await speciesMonths(db, [String(params.binom)]);
      return rows.map((r) => ({ month: r.month, n: r.n }));
    }
    case "species_mesh_years": {
      const rows = await speciesMeshYears(db, String(params.binom));
      return rows.map((r) => ({ year: r.year, mlat: r.mlat, mlon: r.mlon, n: r.n }));
    }
    case "species_share_trend": {
      const [a, b] = parseTrendPeriods(params.periods);
      const rows = await speciesShareTrend(db, String(params.group), { from: a[0], to: a[1] }, { from: b[0], to: b[1] });
      return rows.map((r) => ({ binom: r.binom, n_a: r.nA, n_b: r.nB, total_a: r.totalA, total_b: r.totalB, label: r.label }));
    }
    case "mesh_all": {
      const rows = await gridCatalog(db);
      return rows.map((r) => ({ mlat: r.mlat, mlon: r.mlon, n: r.n, rl_n: r.rlN, species_n: r.speciesN, rl_species_n: r.rlSpeciesN }));
    }
    case "mesh_by_year": {
      const rows = await meshByYear(db, Number(params.year));
      return rows.map((r) => ({ mlat: r.mlat, mlon: r.mlon, n: r.n, species_n: r.speciesN, rl_n: r.rlN }));
    }
    case "ias_species": {
      const rows = await iasSpecies(db);
      return rows.map((r) => ({
        ias_category: r.iasCategory,
        binom: r.binom,
        name_ja: r.nameJa,
        taxon_group: r.taxonGroup,
        n: r.n,
        mesh_n: r.meshN,
        y_from: r.yFrom,
        y_to: r.yTo,
        n_since_2020: r.nSince,
      }));
    }
    case "redlist_summary": {
      const rows = await redlistSummary(db);
      return rows.map((r) => ({ list_year: r.listYear, list_name: r.listName, taxon_group_ja: r.taxonGroupJa, direction: r.direction, n: r.n }));
    }
    case "biota_totals": {
      const t = await occurrenceTotals(db);
      return [{ records: t.records, species: t.species, mesh: t.grids, gbif: t.gbif, inat: t.inat }];
    }
    case "watershed_rollup": {
      // 画面（`/api/geo/watersheds`）・AI `get_overview` と同じ `watershedRollup(db)` 1本。全 377 流域を返す。
      const { watersheds, landuseYears } = await watershedRollup(db);
      // v1 の列名（`built_km2_2006` 等）は版の年を含む。版が変わったら黙って列名がずれないよう止める。
      if (landuseYears !== null && (landuseYears.from !== 2006 || landuseYears.to !== 2016)) {
        throw new Error(`土地利用の版が 2006/2016 でない（${landuseYears.from}/${landuseYears.to}）: v1 の列名との対応を見直すこと`);
      }
      return watersheds.map((w) => ({
        watershed_id: w.watershedId,
        water_system_name: w.waterSystemName,
        area_km2: w.areaKm2,
        centroid_lat: w.centroidLat,
        centroid_lon: w.centroidLon,
        site_n: w.siteN,
        org_n: w.orgN,
        org_alien_n: w.orgAlienN,
        org_redlist_n: w.orgRedlistN,
        built_km2_2006: w.built.from,
        built_km2_2016: w.built.to,
        forest_km2_2006: w.forest.from,
        forest_km2_2016: w.forest.to,
        paddy_km2_2006: w.paddy.from,
        paddy_km2_2016: w.paddy.to,
      }));
    }
    case "doc_series_meta": {
      // `api/documents` と同じ minYears=3。label は API・UI と同じく `docSeriesList` が付ける（ここで作らない）。
      const rows = await docSeriesList(db, { minYears: 3 });
      return rows.map((r) => ({
        doc_id: r.docId,
        table_id: r.tableId,
        row_key: r.rowKey,
        label: r.label,
        page_no: r.pageNo,
        n_years: r.nYears,
        y_from: r.yFrom,
        y_to: r.yTo,
        unit: r.unit,
        doc_title: r.docTitle,
        publisher: r.publisher,
        url: r.url,
        license: r.license,
        n_warnings: r.nWarnings,
      }));
    }
    case "doc_series_points": {
      const rows = await docSeriesPoints(db, String(params.doc_id), String(params.table_id), String(params.row_key));
      return rows.map((r) => ({ fiscal_year: r.fiscalYear, value: r.value, unit: r.unit, page_no: r.pageNo }));
    }
    case "overview_counts": {
      // `app/page.tsx` と同じ `overviewCounts(db)`。n_meas/n_sensor/n_events は D2 で廃止（比べない）。
      const c = await overviewCounts(db);
      return [{ n_sites: c.sites, n_sources: c.sources, n_watersheds: c.watersheds, y_from: c.yFrom, y_to: c.yTo }];
    }
    case "landuse_highlight": {
      // `app/page.tsx` と同じ limit=8。
      const rows = await landuseHighlight(db, 8);
      return rows.map((r) => ({ watershed_id: r.watershedId, water_system_name: r.waterSystemName, delta: r.delta, area_km2: r.areaKm2 }));
    }
    default:
      throw new Error(`v2 アダプタが未対応の問い合わせ id: ${id}`);
  }
}

/** `catalogSource` の既定は summary（画面・API・AI と同じ経路）。 */
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
