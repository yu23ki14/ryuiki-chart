import { describe, expect, it } from "vitest";
import { caveatKeysForTables } from "@/lib/registry/lookup-client";
import { caveatKeysForFacets, facetsForSeries, type FacetRef, type SeriesFacetInput } from "./caveats";
import type { Scope } from "./sql";

/**
 * 橋渡しテスト（docs/plans/V2_SERVING_PR1.md §6.2、Issue #48 PR-1 統合 §5）。
 *
 * v1 の「テーブル名 → 注記」（`caveatKeysForTables`、`web/src/lib/ai/caveats.test.ts` が
 * 固定しているのと同じ現行実装）と、v2 の「facet → 注記」（`caveatKeysForFacets`）が、
 * 同じ意味を持つテーブル/facet の組で**まったく同じキー列**（順序も含めて）を返すことを
 * 確認する。対応表 `TABLE_TO_FACET` は `scripts/registry/build_caveat.py` の
 * `_build_table_scope_rows()`（v2 facet を足した箇所）の複製であり、ロジックそのものは
 * 増やしていない（データ側の対応が変わったらここも合わせて直す）。
 *
 * `caveatsForFacets` は「渡された facet 参照の出現順」をそのまま使う（`caveatsForTables`
 * が「渡されたテーブル引数の出現順」を使うのと同じ）ため、`bridge()` はテーブルを
 * 順に見て対応する facet 参照を初出順で並べるだけでよい——facet の**種類**で
 * グループ化する必要はもう無い（以前はカテゴリ固定順で平坦化していたため、
 * `place_kind` 系のテーブルが `dataset` 系より先に来る組で順序がずれていた）。
 *
 * `occurrence_place` は対象外: v1 の `derived.sqlite` に存在しない v2 専用の新設テーブルで、
 * v1 側に対応する `caveatsForTables(["occurrence_place"])` の実装（caveats.ts）自体が
 * 無い（`ORGANISM_TABLES` に含まれないため）。`occurrence_place` の v1 相当キー集合は
 * `["organismSite"]` だけだが、v2 facet 側は `dataset="organism_records"` を経由すると
 * organismSite 以外の4件（effort/regimes/gbifCutoff/share）も一緒に付いてしまう
 * （`build_caveat.py` のコメント参照）。この非対称は既知・意図どおりで、ここでは
 * 検証しない。
 */

const TABLE_TO_FACET: Record<string, FacetRef> = {
  sites: { kind: "place_kind", ref: "site" },

  measurements: { kind: "dataset", ref: "measurements" },
  meas_year: { kind: "dataset", ref: "measurements" },
  meas_month: { kind: "dataset", ref: "measurements" },
  meas_daily: { kind: "dataset", ref: "measurements" },
  meas_clim: { kind: "dataset", ref: "measurements" },
  zone_year: { kind: "dataset", ref: "measurements" },
  zone_clim: { kind: "dataset", ref: "measurements" },
  var_catalog: { kind: "dataset", ref: "measurements" },
  site_var: { kind: "dataset", ref: "measurements" },

  organism_records: { kind: "dataset", ref: "organism_records" },
  org_norm: { kind: "dataset", ref: "organism_records" },
  org_group_year: { kind: "dataset", ref: "organism_records" },
  org_watershed: { kind: "dataset", ref: "organism_records" },
  org_watershed_year: { kind: "dataset", ref: "organism_records" },
  species2: { kind: "dataset", ref: "organism_records" },
  species_year2: { kind: "dataset", ref: "organism_records" },
  species_month: { kind: "dataset", ref: "organism_records" },
  effort_year: { kind: "dataset", ref: "organism_records" },

  species_mesh_year: { kind: "place_kind", ref: "grid01" },
  mesh_all: { kind: "place_kind", ref: "grid01" },
  mesh_species: { kind: "place_kind", ref: "grid01" },
  mesh_year: { kind: "place_kind", ref: "grid01" },

  ias_species: { kind: "source_id", ref: "moe_ias_list" },

  landuse_watershed: { kind: "variable_theme", ref: "landuse" },
  landuse_change: { kind: "variable_theme", ref: "landuse" },

  observers: { kind: "dataset", ref: "synthetic" },
  interventions: { kind: "dataset", ref: "synthetic" },
  decisions: { kind: "dataset", ref: "synthetic" },
  quality_transitions: { kind: "dataset", ref: "synthetic" },
  quality_monthly: { kind: "dataset", ref: "synthetic" },
  event_observers: { kind: "dataset", ref: "synthetic" },
};

/** 複数テーブルの facet 参照を「初めて現れた順」を保って合成する。 */
function bridge(tables: readonly string[]): FacetRef[] {
  const refs: FacetRef[] = [];
  const seen = new Set<string>();
  for (const t of tables) {
    const f = TABLE_TO_FACET[t];
    if (!f) continue;
    const k = `${f.kind}\u0000${f.ref}`;
    if (seen.has(k)) continue;
    seen.add(k);
    refs.push(f);
  }
  return refs;
}

const ALL_BRIDGED_TABLES = Object.keys(TABLE_TO_FACET);

describe("caveatsForFacets — v1/v2 橋渡し（単一テーブル、全32表）", () => {
  for (const table of ALL_BRIDGED_TABLES) {
    it(table, () => {
      expect(caveatKeysForFacets(bridge([table]))).toEqual(caveatKeysForTables([table]));
    });
  }
});

describe("caveatsForFacets — v1/v2 橋渡し（tools.ts が渡す複合テーブル。順序まで一致）", () => {
  // web/src/lib/ai/tools.ts が実際に makeResult({ tables: [...] }) へ渡している組
  // （リテラルどおり。`new Set([...]).add(...)` で組み立てている箇所は挿入順を追った）。
  // `place_kind` 系（`sites`）が `dataset` 系（`site_var` 等）より先に来る組
  // （`list_catalog(what:'waters')` の `["sites","site_var"]`）も含めて、全件
  // 順序まで一致する（facet 参照の出現順をそのまま使うようになったため）。
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
    ["sites", "site_var"], // list_catalog(what:'waters')。以前は順序がずれていた組。
  ];

  for (const tables of COMPOSITES) {
    it(tables.join(" + "), () => {
      expect(caveatKeysForFacets(bridge(tables))).toEqual(caveatKeysForTables(tables));
    });
  }
});

describe("facetsForSeries", () => {
  const measurementSeries = (theme: string | null, sourceIds: (string | null)[]): SeriesFacetInput => ({
    variableId: "common:variable:water.bod",
    obsStat: "mean",
    unitId: "common:unit:mg_per_l",
    valueGrain: "day",
    dataset: "measurements",
    aliases: ["生物化学的酸素要求量 BOD"],
    sourceIds,
    theme,
  });

  it("site スコープ: place_kind='site'、dataset/theme/source_id を初出順で返す", () => {
    const scope: Scope = { kind: "site", siteId: "s1" };
    const series = [measurementSeries("water", ["atsugi_river_water_quality"])];
    expect(facetsForSeries(series, scope)).toEqual([
      { kind: "dataset", ref: "measurements" },
      { kind: "variable_theme", ref: "water" },
      { kind: "source_id", ref: "atsugi_river_water_quality" },
      { kind: "place_kind", ref: "site" },
    ]);
  });

  it("zone スコープ: place_kind='zone'", () => {
    const scope: Scope = { kind: "zone" };
    const series = [measurementSeries("water", ["atsugi_river_water_quality"])];
    expect(facetsForSeries(series, scope)).toContainEqual({ kind: "place_kind", ref: "zone" });
  });

  it.each([["places"], ["water"], ["all_sites"]] as const)(
    "%s スコープも place_kind='site'（zone だけが特別）",
    (kind) => {
      const scope = { kind } as Scope;
      expect(facetsForSeries([measurementSeries(null, [])], scope)).toContainEqual({
        kind: "place_kind",
        ref: "site",
      });
    },
  );

  it("source_id が null を含む系列（合成データ）は dataset に 'synthetic' も足す", () => {
    const scope: Scope = { kind: "site", siteId: "s1" };
    const series = [measurementSeries("water", [null])];
    expect(facetsForSeries(series, scope)).toEqual([
      { kind: "dataset", ref: "measurements" },
      { kind: "variable_theme", ref: "water" },
      { kind: "dataset", ref: "synthetic" },
      { kind: "place_kind", ref: "site" },
    ]);
  });

  it("複数系列の dataset/theme/source_id は重複を除いた初出順", () => {
    const scope: Scope = { kind: "site", siteId: "s1" };
    const series = [
      measurementSeries("water", ["atsugi_river_water_quality"]),
      measurementSeries("water", ["env_kousui_sample_kanagawa"]),
      measurementSeries(null, [null]), // 合成: theme 無し、source_id 無し
    ];
    expect(facetsForSeries(series, scope)).toEqual([
      { kind: "dataset", ref: "measurements" },
      { kind: "variable_theme", ref: "water" },
      { kind: "source_id", ref: "atsugi_river_water_quality" },
      { kind: "source_id", ref: "env_kousui_sample_kanagawa" },
      { kind: "dataset", ref: "synthetic" },
      { kind: "place_kind", ref: "site" },
    ]);
  });

  it("caveatsForFacets(facetsForSeries(...)) が実際に measuredOn 等を引ける", () => {
    const scope: Scope = { kind: "site", siteId: "s1" };
    const series = [measurementSeries("water", ["atsugi_river_water_quality"])];
    expect(caveatKeysForFacets(facetsForSeries(series, scope))).toEqual(
      caveatKeysForTables(["measurements", "sites"]),
    );
  });
});
