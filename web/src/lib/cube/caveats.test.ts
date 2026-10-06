import { describe, expect, it } from "vitest";
import {
  caveatKeysForFacets,
  facetsForOccurrence,
  facetsForSeries,
  facetsForTables,
  placeKind,
  sourceEditionOf,
  unitUnknownOf,
  variableCaveats,
  DATASET_TABLES,
  variableTheme,
  type FacetRef,
  type SeriesFacetInput,
} from "./caveats";
import type { Scope } from "./sql";
import { GENERATED_CAVEAT_SCOPE } from "@/lib/registry/generated-client";

/**
 * facet → 注記（`caveatKeysForFacets`）のテスト（docs/plans/V2_SERVING_PR1.md §6.2）。
 *
 * Issue #35 で scope_kind を ADR-0013 の6種（variable/place/source_edition/observation_set/
 * dataset/taxon）に寄せた（宣言は registry/caveat_scope.yaml）。ここでは新しい語彙での期待値を
 * 固定する。注記の結果（キーと順序）は語彙の変更前と同じで、変わるのは宣言した差分だけ:
 *   - share は流域（dataset=organism_records）に付かず grid01 だけ。
 *   - aboveLod は dataset=measurements 全体ではなく透明度（variable）だけ。
 *   - flowTidalBackflow（流量の逆流）が新設。
 */

describe("caveatKeysForFacets — facet ごとの注記キー（順序込み）", () => {
  it.each([
    [{ kind: "dataset", ref: "measurements" }, ["measuredOn", "censoredLod", "duplicates"]],
    [{ kind: "dataset", ref: "sites" }, ["zone", "municipality"]],
    [{ kind: "dataset", ref: "organism_records" }, ["organismSite", "effort", "regimes", "gbifCutoff"]],
    [{ kind: "observation_set", ref: "is_synthetic=1" }, ["synthetic"]],
    [placeKind("site"), ["zone", "municipality"]],
    [placeKind("zone"), ["zone"]],
    [placeKind("grid01"), ["share", "effort"]],
    [sourceEditionOf("moe_ias_list"), ["isAlien"]],
    [variableTheme("landuse"), ["landuseDefinitionChange"]],
    [{ kind: "variable", ref: "common:variable:water.transparency" }, ["aboveLod"]],
    [{ kind: "variable", ref: "common:variable:hydro.flow" }, ["flowTidalBackflow"]],
    [unitUnknownOf("common:variable:air.photochemical_oxidant"), ["unitUnknown"]],
  ] as [FacetRef, string[]][])("%j", (facet, keys) => {
    expect(caveatKeysForFacets([facet])).toEqual(keys);
  });

  it("`censored`（zero 系列を名指しする旧キー）はどの facet からも出ない（censoredLod に一本化済み）", () => {
    const all = [
      { kind: "dataset", ref: "measurements" },
      { kind: "dataset", ref: "organism_records" },
      placeKind("site"),
    ] as FacetRef[];
    expect(caveatKeysForFacets(all)).not.toContain("censored");
  });

  it("配信表 sites（dataset）と place=place_kind=site が同じキー列を返す", () => {
    expect(caveatKeysForFacets(facetsForTables(["sites"]))).toEqual(caveatKeysForFacets([placeKind("site")]));
  });

  it("旧語彙（table/place_kind/source_id/variable_theme/cell 等）の行は caveat_scope に残っていない", () => {
    for (const kind of ["table", "table_prefix", "place_kind", "source_id", "variable_theme", "cell", "cell_table"]) {
      expect(caveatKeysForFacets([{ kind, ref: "site" } as unknown as FacetRef])).toEqual([]);
    }
  });

  it("流域だけの生物（get_overview の facet）には share が付かない。grid01 には付く", () => {
    expect(caveatKeysForFacets(facetsForOccurrence({ places: ["watershed"] }))).toEqual(["organismSite", "effort", "regimes", "gbifCutoff"]);
    expect(caveatKeysForFacets(facetsForOccurrence({ places: ["grid01"] }))).toEqual(["organismSite", "effort", "regimes", "gbifCutoff", "share"]);
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
      variableTheme("water"),
      sourceEditionOf("atsugi_river_water_quality"),
      { kind: "variable", ref: "common:variable:water.bod" },
      placeKind("site"),
    ]);
  });

  it("zone スコープ: place_kind='zone'", () => {
    const scope: Scope = { kind: "zone" };
    const series = [measurementSeries("water", ["atsugi_river_water_quality"])];
    expect(facetsForSeries(series, scope)).toContainEqual(placeKind("zone"));
  });

  it.each([["places"], ["water"], ["all_sites"]] as const)(
    "%s スコープも place_kind='site'（zone だけが特別）",
    (kind) => {
      const scope = { kind } as Scope;
      expect(facetsForSeries([measurementSeries(null, [])], scope)).toContainEqual(placeKind("site"));
    },
  );

  it("source_id が null（出典未記録）の系列でも 'synthetic' は足さない（PR-2 D2。b03 が合成行を除くため、除外後の observation_agg には現れない）", () => {
    const scope: Scope = { kind: "site", siteId: "s1" };
    const series = [measurementSeries("water", [null])];
    expect(facetsForSeries(series, scope)).toEqual([
      { kind: "dataset", ref: "measurements" },
      variableTheme("water"),
      { kind: "variable", ref: "common:variable:water.bod" },
      placeKind("site"),
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
      variableTheme("water"),
      sourceEditionOf("atsugi_river_water_quality"),
      { kind: "variable", ref: "common:variable:water.bod" },
      sourceEditionOf("env_kousui_sample_kanagawa"),
      placeKind("site"),
    ]);
  });

  describe("variable / observation_set facet", () => {
    it("variable:<id> は単位の有無によらず常に push し、単位不明（unitId===null）の系列だけ observation_set も push する", () => {
      const scope: Scope = { kind: "site", siteId: "s1" };
      const series = [measurementSeries("water", ["atsugi_river_water_quality"], null)];
      expect(facetsForSeries(series, scope)).toEqual([
        { kind: "dataset", ref: "measurements" },
        variableTheme("water"),
        sourceEditionOf("atsugi_river_water_quality"),
        { kind: "variable", ref: "common:variable:water.bod" },
        unitUnknownOf("common:variable:water.bod"),
        placeKind("site"),
      ]);
    });

    it("unitId が既知の系列には unitUnknown（observation_set）を push しない（単位不明ではないため）", () => {
      const scope: Scope = { kind: "site", siteId: "s1" };
      const series = [measurementSeries("water", ["atsugi_river_water_quality"], "common:unit:mg_per_l")];
      expect(facetsForSeries(series, scope).some((f) => f.kind === "observation_set")).toBe(false);
    });

    it("同じ variableId で unitId あり/なしの系列が混ざるとき、unitUnknown の facet は1回だけ（water.water_temp のような混在ケース）", () => {
      const scope: Scope = { kind: "site", siteId: "s1" };
      const unknown = measurementSeries("water", ["atsugi_river_water_quality"], null);
      const known = measurementSeries("water", ["env_kousui_sample_kanagawa"], "common:unit:degc");
      const refs = facetsForSeries([unknown, known], scope);
      expect(refs.filter((f) => f.kind === "observation_set")).toEqual([unitUnknownOf("common:variable:water.bod")]);
      expect(refs.filter((f) => f.kind === "variable" && f.ref.startsWith("common:"))).toHaveLength(1);
    });
  });

  it("caveatsForFacets(facetsForSeries(...)) が実際に measuredOn 等を引ける（dataset='measurements' なので censoredLod）", () => {
    const scope: Scope = { kind: "site", siteId: "s1" };
    const series = [measurementSeries("water", ["atsugi_river_water_quality"])];
    // aboveLod は透明度（variable）だけなので、BOD の系列には付かない（Issue #35 の宣言した差分）。
    expect(caveatKeysForFacets(facetsForSeries(series, scope))).toEqual([
      "measuredOn", "censoredLod", "duplicates", "zone", "municipality",
    ]);
  });

  it("透明度の系列には aboveLod、流量の系列には単位の有無によらず flowTidalBackflow が付く", () => {
    const scope: Scope = { kind: "site", siteId: "s1" };
    const mk = (variableId: string, unitId: string | null): SeriesFacetInput => ({
      ...measurementSeries("water", ["env_kousui_sample_kanagawa"], unitId),
      variableId,
    });
    expect(caveatKeysForFacets(facetsForSeries([mk("common:variable:water.transparency", "common:unit:m")], scope))).toContain("aboveLod");
    expect(caveatKeysForFacets(facetsForSeries([mk("common:variable:hydro.flow", "common:unit:m3_per_s")], scope))).toContain("flowTidalBackflow");
    expect(caveatKeysForFacets(facetsForSeries([mk("common:variable:hydro.flow", null)], scope))).toEqual(
      expect.arrayContaining(["flowTidalBackflow", "unitUnknown"]),
    );
    expect(caveatKeysForFacets(facetsForSeries([mk("common:variable:water.bod", "common:unit:mg_per_l")], scope))).not.toContain("aboveLod");
  });
});

describe("facetsForOccurrence（Issue #48 PR-3b）", () => {
  it("organism_records を常に、grid01 を引くとき place、IAS のとき source_edition を積む", () => {
    expect(facetsForOccurrence({ places: ["watershed"] })).toEqual([{ kind: "dataset", ref: "organism_records" }]);
    expect(facetsForOccurrence({ places: ["grid01"] })).toEqual([
      { kind: "dataset", ref: "organism_records" },
      placeKind("grid01"),
    ]);
    expect(facetsForOccurrence({ places: ["grid01", "watershed"], ias: true }).map((f) => f.kind)).toEqual(["dataset", "place", "source_edition"]);
  });
  it("引いた注記に organism/mesh/IAS の主要なキーが入る（v1 表名ベースの table は使わない）", () => {
    const f = facetsForOccurrence({ places: ["grid01"], ias: true });
    expect(f.some((x) => (x.kind as string) === "table")).toBe(false);
    const keys = caveatKeysForFacets(f);
    expect(keys).toEqual(expect.arrayContaining(["organismSite", "effort", "share", "isAlien"]));
  });
});

describe("ref ヘルパが作る scope_ref は宣言（GENERATED_CAVEAT_SCOPE）に実在する", () => {
  const exists = (f: FacetRef) => GENERATED_CAVEAT_SCOPE.some((s) => s.scopeKind === f.kind && s.scopeRef === f.ref);

  it.each([
    ["placeKind(site)", placeKind("site")],
    ["placeKind(zone)", placeKind("zone")],
    ["placeKind(grid01)", placeKind("grid01")],
    ["variableTheme(landuse)", variableTheme("landuse")],
    ["sourceEditionOf(moe_ias_list)", sourceEditionOf("moe_ias_list")],
  ] as [string, FacetRef][])("%s", (_name, facet) => {
    expect(exists(facet)).toBe(true);
  });

  it("unitUnknownOf: 宣言された observation_set の variable=<id>&unit_id=null と同じ文字列を作る", () => {
    const rows = GENERATED_CAVEAT_SCOPE.filter((s) => s.scopeKind === "observation_set" && s.caveatKey === "unitUnknown");
    expect(rows.length).toBeGreaterThan(0);
    for (const r of rows) {
      const m = /^variable=(.+)&unit_id=null$/.exec(r.scopeRef);
      expect(m).not.toBeNull();
      expect(unitUnknownOf(m![1]).ref).toBe(r.scopeRef);
    }
  });

  it("DATASET_TABLES の各表は dataset の scope 行として宣言されている（ずれたら止まる）", () => {
    for (const t of DATASET_TABLES) {
      expect(exists({ kind: "dataset", ref: t })).toBe(true);
    }
  });

  it("variableCaveats: 流量の逆流・透明度の aboveLod。変数スコープの無い変数は空", () => {
    expect(variableCaveats("common:variable:hydro.flow").map((c) => c.key)).toEqual(["flowTidalBackflow"]);
    expect(variableCaveats("common:variable:water.transparency").map((c) => c.key)).toEqual(["aboveLod"]);
    expect(variableCaveats("common:variable:water.bod")).toEqual([]);
  });
});
