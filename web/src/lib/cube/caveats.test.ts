import { describe, expect, it } from "vitest";
import { caveatKeysForTables } from "@/lib/registry/lookup-client";
import {
  caveatKeysForFacets,
  facetsForSeries,
  type CaveatFacets,
  type SeriesFacetInput,
  type SeriesFacetScope,
} from "./caveats";

/**
 * 橋渡しテスト（docs/plans/V2_SERVING_PR1.md §6.2）。
 *
 * v1 の「テーブル名 → 注記」（`caveatKeysForTables`、`web/src/lib/ai/caveats.test.ts` が
 * 固定しているのと同じ現行実装）と、v2 の「facet → 注記」（`caveatKeysForFacets`）が、
 * 同じ意味を持つテーブル/facet の組で**まったく同じキー列**（順序も含めて）を返すことを
 * 確認する。対応表 `TABLE_TO_FACET` は `scripts/registry/build_caveat.py` の
 * `_build_table_scope_rows()`（v2 facet を足した箇所）の複製であり、ロジックそのものは
 * 増やしていない（データ側の対応が変わったらここも合わせて直す）。
 *
 * `occurrence_place` は対象外: v1 の `derived.sqlite` に存在しない v2 専用の新設テーブルで、
 * v1 側に対応する `caveatsForTables(["occurrence_place"])` の実装（caveats.ts）自体が
 * 無い（`ORGANISM_TABLES` に含まれないため）。`occurrence_place` の v1 相当キー集合は
 * `["organismSite"]` だけだが、v2 facet 側は `dataset="organism_records"` を経由すると
 * organismSite 以外の4件（effort/regimes/gbifCutoff/share）も一緒に付いてしまう
 * （`build_caveat.py` のコメント参照）。この非対称は既知・意図どおりで、ここでは
 * 検証しない。
 */

const TABLE_TO_FACET: Record<string, CaveatFacets> = {
  sites: { placeKinds: ["site"] },

  measurements: { datasets: ["measurements"] },
  meas_year: { datasets: ["measurements"] },
  meas_month: { datasets: ["measurements"] },
  meas_daily: { datasets: ["measurements"] },
  meas_clim: { datasets: ["measurements"] },
  zone_year: { datasets: ["measurements"] },
  zone_clim: { datasets: ["measurements"] },
  var_catalog: { datasets: ["measurements"] },
  site_var: { datasets: ["measurements"] },

  organism_records: { datasets: ["organism_records"] },
  org_norm: { datasets: ["organism_records"] },
  org_group_year: { datasets: ["organism_records"] },
  org_watershed: { datasets: ["organism_records"] },
  org_watershed_year: { datasets: ["organism_records"] },
  species2: { datasets: ["organism_records"] },
  species_year2: { datasets: ["organism_records"] },
  species_month: { datasets: ["organism_records"] },
  effort_year: { datasets: ["organism_records"] },

  species_mesh_year: { placeKinds: ["grid01"] },
  mesh_all: { placeKinds: ["grid01"] },
  mesh_species: { placeKinds: ["grid01"] },
  mesh_year: { placeKinds: ["grid01"] },

  ias_species: { sourceIds: ["moe_ias_list"] },

  landuse_watershed: { themes: ["landuse"] },
  landuse_change: { themes: ["landuse"] },

  observers: { datasets: ["synthetic"] },
  interventions: { datasets: ["synthetic"] },
  decisions: { datasets: ["synthetic"] },
  quality_transitions: { datasets: ["synthetic"] },
  quality_monthly: { datasets: ["synthetic"] },
  event_observers: { datasets: ["synthetic"] },
};

/** 複数テーブルの facet を「初めて現れた順」を保って合成する（`caveatsForFacets` の
 * 出現順ソートに影響するため、単純な Set の再結合では順序が壊れうる）。 */
function bridge(tables: readonly string[]): CaveatFacets {
  const datasets: string[] = [];
  const themes: string[] = [];
  const placeKinds: string[] = [];
  const sourceIds: string[] = [];
  const seen = {
    datasets: new Set<string>(),
    themes: new Set<string>(),
    placeKinds: new Set<string>(),
    sourceIds: new Set<string>(),
  };
  const push = (bucket: string[], seenSet: Set<string>, values: readonly string[] | undefined) => {
    for (const v of values ?? []) {
      if (seenSet.has(v)) continue;
      seenSet.add(v);
      bucket.push(v);
    }
  };
  for (const t of tables) {
    const f = TABLE_TO_FACET[t];
    if (!f) continue;
    push(datasets, seen.datasets, f.datasets);
    push(themes, seen.themes, f.themes);
    push(placeKinds, seen.placeKinds, f.placeKinds);
    push(sourceIds, seen.sourceIds, f.sourceIds);
  }
  return { datasets, themes, placeKinds, sourceIds };
}

const ALL_BRIDGED_TABLES = Object.keys(TABLE_TO_FACET);

describe("caveatsForFacets — v1/v2 橋渡し（単一テーブル、全32表）", () => {
  for (const table of ALL_BRIDGED_TABLES) {
    it(table, () => {
      expect(caveatKeysForFacets(bridge([table]))).toEqual(caveatKeysForTables([table]));
    });
  }
});

describe("caveatsForFacets — v1/v2 橋渡し（tools.ts が渡す複合テーブル）", () => {
  // web/src/lib/ai/tools.ts が実際に makeResult({ tables: [...] }) へ渡している組
  // （リテラルどおり。`new Set([...]).add(...)` で組み立てている箇所は挿入順を追った）。
  // ここに含めたのは「dataset 系（measure/organism のテーブル）が引数の先頭に来る」組だけ。
  // 下の「既知の限界」テストが説明するとおり、`caveatsForFacets` は facet の**カテゴリ**
  // 固定順（datasets, themes, placeKinds, sourceIds, tables。§3.6）でしか並べないため、
  // `place_kind` 系（`sites`）が `dataset` 系より先に来る組（例:
  // `list_catalog(what:'waters')` の `["sites","site_var"]`）は順序までは一致しない。
  const COMPOSITES: readonly (readonly string[])[] = [
    ["var_catalog", "zone_year"], // get_timeseries, scope=zone
    ["var_catalog", "sites", "site_var", "meas_year"], // get_timeseries, scope=water, grain=year
    ["var_catalog", "sites", "site_var", "meas_month"], // scope=water, grain=month
    ["var_catalog", "sites", "site_var", "meas_daily"], // scope=water, grain=day
    ["var_catalog", "meas_daily"], // get_timeseries, scope=site, grain=day
    ["meas_clim", "zone_clim"], // get_seasonality
    ["org_group_year", "effort_year"], // get_biota, kind=group
    ["species_year2", "species2"], // get_biota, kind=species
    ["species_year2", "species_month"], // get_biota, kind=species+season
    ["quality_transitions", "quality_monthly", "interventions", "decisions", "observers", "event_observers"], // get_quality_progress
  ];

  for (const tables of COMPOSITES) {
    it(tables.join(" + "), () => {
      expect(caveatKeysForFacets(bridge(tables))).toEqual(caveatKeysForTables(tables));
    });
  }

  /**
   * 既知の限界（設計上の判断であり、このテストで顕在化させておく）。
   *
   * `caveatsForFacets` は facet の**カテゴリ**（datasets/themes/placeKinds/sourceIds/tables）
   * を固定順で平坦化してから並べる（§3.6）。一方 `caveatsForTables` は「渡されたテーブル
   * 引数の出現順」で並べる。両者が一致するのは、実際のテーブル引数の並びが
   * たまたま facet のカテゴリ順（dataset 系が先、place_kind 系が後）と揃っている場合だけ。
   *
   * `list_catalog(what:'waters')` の `["sites","site_var"]`（`web/src/lib/ai/tools.ts`）は
   * `sites`（place_kind 系）が `site_var`（dataset 系）より先に来るため、キー**集合**は
   * 一致するが並び順は変わる。`get_overview` の複合（`sites` が先頭）も同様。
   * v1 の `caveatsForTables` 自体はこの PR で一切変えていないので実害は無いが
   * （既存の AI 注記は無変更）、v2 側で `caveatsForFacets` を「v1 と同じ並びのドロップイン
   * 代替」として使う設計にするなら、PR-2 でこの非対称を解消するか許容するかを決める必要がある。
   */
  it("既知の限界: place_kind 系のテーブルが dataset 系より先だと並び順は変わる（キー集合は一致）", () => {
    const tables = ["sites", "site_var"]; // list_catalog(what:'waters')
    const v1 = caveatKeysForTables(tables);
    const v2 = caveatKeysForFacets(bridge(tables));
    expect(new Set(v2)).toEqual(new Set(v1));
    expect(v2).not.toEqual(v1);
  });
});

describe("facetsForSeries", () => {
  const measurementSeries = (theme: string | null, sourceIds: readonly (string | null)[]): SeriesFacetInput => ({
    dataset: "measurements",
    sourceIds,
    theme,
  });

  it("site スコープ: placeKinds=['site']、dataset/theme/sourceId の和集合を返す", () => {
    const scope: SeriesFacetScope = { kind: "site" };
    const series = [measurementSeries("water", ["atsugi_river_water_quality"])];
    expect(facetsForSeries(series, scope)).toEqual({
      datasets: ["measurements"],
      themes: ["water"],
      placeKinds: ["site"],
      sourceIds: ["atsugi_river_water_quality"],
    });
  });

  it("zone スコープ: placeKinds=['zone']", () => {
    const scope: SeriesFacetScope = { kind: "zone" };
    const series = [measurementSeries("water", ["atsugi_river_water_quality"])];
    expect(facetsForSeries(series, scope).placeKinds).toEqual(["zone"]);
  });

  it.each([["places"], ["water"], ["all_sites"]] as const)(
    "%s スコープも placeKinds=['site']（zone だけが特別）",
    (kind) => {
      const scope: SeriesFacetScope = { kind };
      expect(facetsForSeries([measurementSeries(null, [])], scope).placeKinds).toEqual(["site"]);
    },
  );

  it("source_id が null を含む系列（合成データ）は dataset に 'synthetic' も足す", () => {
    const scope: SeriesFacetScope = { kind: "site" };
    const series = [measurementSeries("water", [null])];
    expect(facetsForSeries(series, scope).datasets).toEqual(["measurements", "synthetic"]);
  });

  it("複数系列の dataset/theme/sourceId は重複を除いた和集合（初出順）", () => {
    const scope: SeriesFacetScope = { kind: "site" };
    const series = [
      measurementSeries("water", ["atsugi_river_water_quality"]),
      measurementSeries("water", ["env_kousui_sample_kanagawa"]),
      measurementSeries(null, [null]), // 合成: theme 無し、source_id 無し
    ];
    expect(facetsForSeries(series, scope)).toEqual({
      datasets: ["measurements", "synthetic"],
      themes: ["water"],
      placeKinds: ["site"],
      sourceIds: ["atsugi_river_water_quality", "env_kousui_sample_kanagawa"],
    });
  });

  it("caveatsForFacets(facetsForSeries(...)) が実際に measuredOn 等を引ける", () => {
    const scope: SeriesFacetScope = { kind: "site" };
    const series = [measurementSeries("water", ["atsugi_river_water_quality"])];
    expect(caveatKeysForFacets(facetsForSeries(series, scope))).toEqual(
      caveatKeysForTables(["measurements", "sites"]),
    );
  });
});
