import { describe, expect, it } from "vitest";
import { caveatKeysForTables } from "@/lib/registry/lookup-client";
import { caveatKeysForFacets, facetsForOccurrence, facetsForSeries, type FacetRef, type SeriesFacetInput } from "./caveats";
import type { Scope } from "./sql";

/**
 * facet → 注記（`caveatKeysForFacets`）のテスト（docs/plans/V2_SERVING_PR1.md §6.2）。
 *
 * Issue #48 PR-5 で v1 の派生表・原本表が DROP され、v1 の「テーブル名 → 注記」の行は
 * `sites`（zone/municipality）だけになった。以前ここにあった v1/v2 の橋渡しテスト
 * （テーブル名で引いた結果と facet で引いた結果の一致）は、比べる相手が消えたので撤去し、
 * facet 側の期待値を直接固定する。`sites` だけは v1 の table 行と facet 行（place_kind='site'）が
 * 同じ並びを返すことを今も確かめる。
 */

describe("caveatKeysForFacets — facet ごとの注記キー（順序込み）", () => {
  it.each([
    [{ kind: "dataset", ref: "measurements" }, ["measuredOn", "censoredLod", "duplicates", "aboveLod"]],
    [{ kind: "dataset", ref: "organism_records" }, ["organismSite", "effort", "regimes", "gbifCutoff", "share"]],
    [{ kind: "dataset", ref: "synthetic" }, ["synthetic"]],
    [{ kind: "place_kind", ref: "site" }, ["zone", "municipality"]],
    [{ kind: "place_kind", ref: "zone" }, ["zone"]],
    [{ kind: "place_kind", ref: "grid01" }, ["share", "effort"]],
    [{ kind: "source_id", ref: "moe_ias_list" }, ["isAlien"]],
    [{ kind: "variable_theme", ref: "landuse" }, ["landuseDefinitionChange"]],
  ] as [FacetRef, string[]][])("%j", (facet, keys) => {
    expect(caveatKeysForFacets([facet])).toEqual(keys);
  });

  it("`censored`（zero 系列を名指しする旧キー）はどの facet からも出ない（censoredLod に一本化済み）", () => {
    const all = [
      { kind: "dataset", ref: "measurements" },
      { kind: "dataset", ref: "organism_records" },
      { kind: "place_kind", ref: "site" },
    ] as FacetRef[];
    expect(caveatKeysForFacets(all)).not.toContain("censored");
  });

  it("sites: v1 の table 行と facet（place_kind='site'）が同じキー列を返す", () => {
    expect(caveatKeysForFacets([{ kind: "place_kind", ref: "site" }])).toEqual(caveatKeysForTables(["sites"]));
  });
});

describe("facetsForSeries", () => {
  // `unitId` は既定で非NULL（単位が判明している系列）にしてある——`variable` facet は
  // `unitId===null` の系列だけに push する（統合後の追加決定。下の describe 参照）ので、
  // 既存の dataset/theme/source_id の並びを確かめるテストが誤って variable facet の
  // 有無に依存しないようにする。
  const measurementSeries = (theme: string | null, sourceIds: (string | null)[], unitId: string | null = "common:unit:mg_per_l"): SeriesFacetInput => ({
    variableId: "common:variable:water.bod",
    obsStat: "mean",
    unitId,
    valueGrain: "day",
    dataset: "measurements",
    aliases: ["生物化学的酸素要求量 BOD"],
    sourceIds,
    theme,
  });

  it("site スコープ: place_kind='site'、dataset/theme/source_id を初出順で返す（unitId 既知なので variable facet は付かない）", () => {
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

  it("source_id が null（出典未記録）の系列でも 'synthetic' は足さない（PR-2 D2。b03 が合成行を除くため、除外後の observation_agg には現れない）", () => {
    const scope: Scope = { kind: "site", siteId: "s1" };
    const series = [measurementSeries("water", [null])];
    expect(facetsForSeries(series, scope)).toEqual([
      { kind: "dataset", ref: "measurements" },
      { kind: "variable_theme", ref: "water" },
      { kind: "place_kind", ref: "site" },
    ]);
  });

  it("複数系列の dataset/theme/source_id は重複を除いた初出順", () => {
    const scope: Scope = { kind: "site", siteId: "s1" };
    const series = [
      measurementSeries("water", ["atsugi_river_water_quality"]),
      measurementSeries("water", ["env_kousui_sample_kanagawa"]),
      measurementSeries(null, [null]), // theme 無し、source_id 無し
    ];
    expect(facetsForSeries(series, scope)).toEqual([
      { kind: "dataset", ref: "measurements" },
      { kind: "variable_theme", ref: "water" },
      { kind: "source_id", ref: "atsugi_river_water_quality" },
      { kind: "source_id", ref: "env_kousui_sample_kanagawa" },
      { kind: "place_kind", ref: "site" },
    ]);
  });

  describe("variable facet（unitId===null の系列だけに push する。統合後の追加決定）", () => {
    it("unitId が null の系列は variable facet を push する（unitUnknown 用）", () => {
      const scope: Scope = { kind: "site", siteId: "s1" };
      const series = [measurementSeries("water", ["atsugi_river_water_quality"], null)];
      expect(facetsForSeries(series, scope)).toEqual([
        { kind: "dataset", ref: "measurements" },
        { kind: "variable_theme", ref: "water" },
        { kind: "source_id", ref: "atsugi_river_water_quality" },
        { kind: "variable", ref: "common:variable:water.bod" },
        { kind: "place_kind", ref: "site" },
      ]);
    });

    it("unitId が既知の系列は variable facet を push しない（単位不明ではないため）", () => {
      const scope: Scope = { kind: "site", siteId: "s1" };
      const series = [measurementSeries("water", ["atsugi_river_water_quality"], "common:unit:mg_per_l")];
      expect(facetsForSeries(series, scope).some((f) => f.kind === "variable")).toBe(false);
    });

    it("同じ variableId で unitId あり/なしの系列が混ざるとき、unitId ありだけを渡せば variable facet は付かない（water.water_temp のような混在ケース）", () => {
      const scope: Scope = { kind: "site", siteId: "s1" };
      const known = measurementSeries("water", ["atsugi_river_water_quality"], "common:unit:degc");
      expect(facetsForSeries([known], scope).some((f) => f.kind === "variable")).toBe(false);
    });

    it("unitId が null の系列と既知の系列が混ざると、variable facet は1回だけ push する", () => {
      const scope: Scope = { kind: "site", siteId: "s1" };
      const unknown = measurementSeries("water", ["atsugi_river_water_quality"], null);
      const known = measurementSeries("water", ["env_kousui_sample_kanagawa"], "common:unit:degc");
      const refs = facetsForSeries([unknown, known], scope);
      expect(refs.filter((f) => f.kind === "variable")).toEqual([{ kind: "variable", ref: "common:variable:water.bod" }]);
    });
  });

  it("caveatsForFacets(facetsForSeries(...)) が実際に measuredOn 等を引ける（dataset='measurements' なので censoredLod）", () => {
    const scope: Scope = { kind: "site", siteId: "s1" };
    const series = [measurementSeries("water", ["atsugi_river_water_quality"])];
    expect(caveatKeysForFacets(facetsForSeries(series, scope))).toEqual([
      "measuredOn", "censoredLod", "duplicates", "aboveLod", "zone", "municipality",
    ]);
  });
});

describe("facetsForOccurrence（Issue #48 PR-3b）", () => {
  it("organism_records を常に、grid01 を引くとき place_kind、IAS のとき source_id を積む", () => {
    expect(facetsForOccurrence({ places: ["watershed"] })).toEqual([{ kind: "dataset", ref: "organism_records" }]);
    expect(facetsForOccurrence({ places: ["grid01"] })).toEqual([
      { kind: "dataset", ref: "organism_records" },
      { kind: "place_kind", ref: "grid01" },
    ]);
    expect(facetsForOccurrence({ places: ["grid01", "watershed"], ias: true }).map((f) => f.kind)).toEqual(["dataset", "place_kind", "source_id"]);
  });
  it("引いた注記に organism/mesh/IAS の主要なキーが入る（v1 表名ベースの table は使わない）", () => {
    const f = facetsForOccurrence({ places: ["grid01"], ias: true });
    expect(f.some((x) => x.kind === "table")).toBe(false);
    const keys = caveatKeysForFacets(f);
    expect(keys).toEqual(expect.arrayContaining(["organismSite", "effort", "share", "isAlien"]));
  });
});
