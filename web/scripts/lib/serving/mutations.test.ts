/**
 * 「変異で拾う」の実証（設計書 §5.3）。各変異を最小フィクスチャに当てて、
 * 素直な突き合わせ（`compareRuns`/`classifyDiff`）が必ず unexplained > 0（または
 * `declared_rot` は宣言が腐る）になることを確認する。
 */
import { describe, expect, it } from "vitest";
import { rowsByKey, toNormRows, type NormRow } from "./normalize";
import {
  binomMonthKey,
  classifyDiff,
  compareRuns,
  findRottenDeclarations,
  watershedYearKey,
  type BiotaExpectations,
  type ClassifyContext,
  type ExpectedDiffs,
  type KnownRule,
} from "./classify";
import {
  ALL_MUTATION_NAMES,
  applyClassifyMutation,
  applyRowMutation,
  isClassifyMutation,
  isRowMutation,
  isV1Mutation,
  rowMutationAppliesTo,
} from "./mutations";

function unexplainedCount(v1: NormRow[], v2: NormRow[], ctx: Partial<ClassifyContext> = {}): number {
  const full: ClassifyContext = {
    expected: {},
    declared: { v1Table: null, builder: null },
    params: {},
    known: new Set(["declared", "day_split", "unit_label_registry", "float_rounding"]),
    ...ctx,
  };
  const diffs = compareRuns(rowsByKey(v1), rowsByKey(v2));
  return diffs.map((d) => classifyDiff(d, full)).filter((c) => c.rules.size === 0).length;
}

describe("行変異は unexplained > 0 で必ず落ちる", () => {
  it("lod_instead_of_zero: 検閲セルの値をずらすと拾われる", () => {
    const v1 = toNormRows(
      [{ y: 2020, n_censored: 3, avg: 1.0 }],
      ["y"],
      ["n_censored", "avg"],
      [],
    );
    const v2raw = toNormRows([{ y: 2020, n_censored: 3, avg: 1.0 }], ["y"], ["n_censored", "avg"], []);
    const mutated = applyRowMutation("lod_instead_of_zero", "year_series_site", v2raw);
    expect(unexplainedCount(v1, mutated)).toBeGreaterThan(0);
  });

  it("lod_instead_of_zero: synthetic_excluded/lod_imputation が有効な現実的な known でも拾われる（Issue #48 PR-2 統合後 修正C。実データでは synthetic_excluded に飲み込まれ NG だった）", () => {
    const v1 = toNormRows([{ y: 2020, n_censored: 3, avg: 1.0 }], ["y"], ["n_censored", "avg"], []);
    const v2raw = toNormRows([{ y: 2020, n_censored: 3, avg: 1.0 }], ["y"], ["n_censored", "avg"], []);
    const v2TrueByKey = rowsByKey(v2raw); // 行変異を当てる前の、本当の v2 の値（v1と一致）
    const v2Compat = rowsByKey(toNormRows([{ y: 2020, n_censored: 3, avg: 1.0 }], ["y"], ["n_censored", "avg"], []));
    const mutated = applyRowMutation("lod_instead_of_zero", "year_series_site", v2raw);
    expect(
      unexplainedCount(v1, mutated, {
        known: new Set(["declared", "synthetic_excluded", "lod_imputation"]),
        v2CompatByKey: v2Compat,
        v2TrueByKey,
        v2TrueZeroByKey: v2Compat, // この地点は合成データの影響が無い
      }),
    ).toBeGreaterThan(0);
  });

  it("lod_instead_of_zero: 検閲されていないセルはそもそも変わらない（no-op）", () => {
    const rows = toNormRows([{ y: 2020, n_censored: 0, avg: 1.0 }], ["y"], ["n_censored", "avg"], []);
    const mutated = applyRowMutation("lod_instead_of_zero", "year_series_site", rows);
    expect(mutated).toEqual(rows);
  });

  it("drop_series: 行が減るので row_only_in_v1 が出る", () => {
    const v1 = toNormRows(
      [
        { y: 1, n: 1 },
        { y: 2, n: 1 },
      ],
      ["y"],
      ["n"],
      [],
    );
    const mutated = applyRowMutation("drop_series", "year_series_site", v1);
    expect(unexplainedCount(v1, mutated)).toBeGreaterThan(0);
  });

  it("swap_kind: year_series_site で行の対応がずれる", () => {
    const v1 = toNormRows(
      [
        { y: 1, n: 10 },
        { y: 2, n: 20 },
      ],
      ["y"],
      ["n"],
      [],
    );
    const mutated = applyRowMutation("swap_kind", "year_series_site", v1);
    expect(unexplainedCount(v1, mutated)).toBeGreaterThan(0);
  });

  it("swap_kind: synthetic_excluded が有効な現実的な known でも拾われる（Issue #48 PR-2 統合後 修正C。実データでは210地点・45,335件が synthetic_excluded に飲み込まれ NG だった）", () => {
    const v1raw = [
      { y: 1, n: 10 },
      { y: 2, n: 20 },
    ];
    const v1 = toNormRows(v1raw, ["y"], ["n"], []);
    const v2TrueByKey = rowsByKey(toNormRows(v1raw, ["y"], ["n"], [])); // 行変異前は v1 と一致（合成の影響も無い）
    const v2Compat = rowsByKey(toNormRows(v1raw, ["y"], ["n"], []));
    const mutated = applyRowMutation("swap_kind", "year_series_site", toNormRows(v1raw, ["y"], ["n"], []));
    expect(
      unexplainedCount(v1, mutated, {
        known: new Set(["declared", "synthetic_excluded"]),
        v2CompatByKey: v2Compat,
        v2TrueByKey,
      }),
    ).toBeGreaterThan(0);
  });

  it("swap_kind: 無関係な問い合わせには効かない（no-op）", () => {
    const rows = toNormRows([{ y: 1, n: 1 }], ["y"], ["n"], []);
    expect(applyRowMutation("swap_kind", "climatology", rows)).toEqual(rows);
    expect(rowMutationAppliesTo("swap_kind", "climatology")).toBe(false);
  });

  it("no_unit: unit を欠かすと label_diff が拾われる（unit_label_registryの向きが逆なので unexplained）", () => {
    const v1 = toNormRows([{ y: 1, unit: "mg/L" }], ["y"], [], ["unit"]);
    const v2 = toNormRows([{ y: 1, unit: "mg/L" }], ["y"], [], ["unit"]);
    const mutated = applyRowMutation("no_unit", "year_series_site", v2);
    // v1 が非NULL・v2 がNULLになる = unit_label_registry の向き（v1がNULL）とは逆なので
    // 規則には当てはまらず unexplained になる。
    expect(unexplainedCount(v1, mutated)).toBeGreaterThan(0);
  });

  it("month_off_by_one: month_series_site の ym をずらす", () => {
    const v1 = toNormRows([{ ym: "2020-05", n: 1 }], ["ym"], ["n"], []);
    const mutated = applyRowMutation("month_off_by_one", "month_series_site", v1);
    expect(unexplainedCount(v1, mutated)).toBeGreaterThan(0);
  });

  it("include_watershed_cells: 行を複製すると重複キー検出で例外になる", () => {
    const v2 = toNormRows([{ y: 1, n: 1 }], ["y"], ["n"], []);
    const mutated = applyRowMutation("include_watershed_cells", "sites_list", v2);
    expect(() => rowsByKey(mutated)).toThrow();
  });

  it("全ての行変異名がフィクスチャで一度は適用される（列挙もれの防止）", () => {
    const rows = toNormRows([{ y: 1, n: 1, n_censored: 0 }], ["y"], ["n", "n_censored"], []);
    for (const name of ALL_MUTATION_NAMES) {
      if (isRowMutation(name)) {
        expect(() => applyRowMutation(name, "year_series_site", rows)).not.toThrow();
      }
    }
  });
});

describe("分類器変異", () => {
  it("rain_no_div10_rule / rain_div10 は撤去済み（Issue #48 PR-2 統合後 修正C: rain_monthly_clim では day_split が全件を先に説明し、rain_div10 は実質的な検証を持たなかった）", () => {
    expect(ALL_MUTATION_NAMES).not.toContain("rain_no_div10_rule");
    expect(() => applyClassifyMutation("rain_no_div10_rule" as never)).toThrow();
  });

  it("day_split_rule_off は day_split を無効化する", () => {
    const opts = applyClassifyMutation("day_split_rule_off");
    const v1 = toNormRows([{ d: "2020-01-01", mm: 1 }], ["d"], ["mm"], []);
    const v2 = toNormRows([], ["d"], ["mm"], []);
    expect(unexplainedCount(v1, v2, { disabledRules: opts.disabledRules })).toBeGreaterThan(0);
  });

  it("synthetic_rule_off は synthetic_excluded を無効化する", () => {
    const opts = applyClassifyMutation("synthetic_rule_off");
    const v1 = toNormRows([{ y: 1, n: 5 }], ["y"], ["n"], []);
    const v2 = toNormRows([], ["y"], ["n"], []);
    const v2Compat = rowsByKey(toNormRows([{ y: 1, n: 5 }], ["y"], ["n"], []));
    expect(
      unexplainedCount(v1, v2, {
        known: new Set(["synthetic_excluded"]),
        disabledRules: opts.disabledRules,
        v2CompatByKey: v2Compat,
      }),
    ).toBeGreaterThan(0);
  });

  it("lod_rule_off は lod_imputation を無効化する", () => {
    const opts = applyClassifyMutation("lod_rule_off");
    const v1 = toNormRows([{ y: 1, avg: 1.0, n_censored: 3 }], ["y"], ["avg", "n_censored"], []);
    const v2 = toNormRows([{ y: 1, avg: 1.5, n_censored: 3 }], ["y"], ["avg", "n_censored"], []);
    const v2Zero = rowsByKey(toNormRows([{ y: 1, avg: 1.0, n_censored: 3 }], ["y"], ["avg", "n_censored"], []));
    expect(
      unexplainedCount(v1, v2, {
        known: new Set(["lod_imputation"]),
        disabledRules: opts.disabledRules,
        v2ZeroByKey: v2Zero,
      }),
    ).toBeGreaterThan(0);
  });

  it("lod_rule_off: synthetic_excluded が有効な現実的な known でも、合成データの影響が無い地点なら肩代わりせず拾われる（Issue #48 PR-2 統合後 修正C。実データでは NG だった）", () => {
    const opts = applyClassifyMutation("lod_rule_off");
    const v1 = toNormRows([{ y: 1, avg: 1.0, n_censored: 3 }], ["y"], ["avg", "n_censored"], []);
    const v2 = toNormRows([{ y: 1, avg: 1.5, n_censored: 3 }], ["y"], ["avg", "n_censored"], []);
    // compat（合成込み・zero）はこの地点では合成の影響が無いので、真のzero値と同じ。
    const v2Compat = rowsByKey(toNormRows([{ y: 1, avg: 1.0, n_censored: 3 }], ["y"], ["avg", "n_censored"], []));
    const v2Zero = rowsByKey(toNormRows([{ y: 1, avg: 1.0, n_censored: 3 }], ["y"], ["avg", "n_censored"], []));
    expect(
      unexplainedCount(v1, v2, {
        known: new Set(["declared", "synthetic_excluded", "lod_imputation"]),
        disabledRules: opts.disabledRules,
        v2CompatByKey: v2Compat,
        v2ZeroByKey: v2Zero,
        v2TrueZeroByKey: v2Zero,
      }),
    ).toBeGreaterThan(0);
  });

  it("declared_rot は指定した宣言を無視させる（腐りとして検出できる）", () => {
    const expected: ExpectedDiffs = {
      meas_year: [{ key: ["a", "x", 2002, "daily"], kind: "value_diff", columns: ["n"] }],
    };
    const target = { table: "meas_year", key: ["a", "x", 2002, "daily"], kind: "value_diff" as const };
    const opts = applyClassifyMutation("declared_rot", { declaredRotTarget: target });

    const v1 = toNormRows([{ year: 2002, n: 5 }], ["year"], ["n"], []);
    const v2 = toNormRows([{ year: 2002, n: 4 }], ["year"], ["n"], []);
    const diffs = compareRuns(rowsByKey(v1), rowsByKey(v2));
    const ctx: ClassifyContext = {
      expected,
      declared: { v1Table: "meas_year", builder: (p, k) => [p.site_id, p.alias, k[0], p.kind] },
      params: { site_id: "a", alias: "x", kind: "daily" },
      known: new Set(["declared"]),
      declaredRot: opts.declaredRot,
    };
    const results = diffs.map((d) => classifyDiff(d, ctx));
    expect(results.every((r) => r.rules.size === 0)).toBe(true);

    // 腐り検出: 何も matched に記録しない状態で findRottenDeclarations を呼べば
    // その宣言が腐って見える。
    const rotten = findRottenDeclarations(expected, new Set(["meas_year"]), new Map());
    expect(rotten).toEqual([{ table: "meas_year", key: ["a", "x", 2002, "daily"], kind: "value_diff" }]);
  });

  it("declared_rot はターゲット指定が無ければ例外にする", () => {
    expect(() => applyClassifyMutation("declared_rot")).toThrow();
  });

  it("isRowMutation/isClassifyMutation/isV1Mutation は互いに排他（どれか1つだけに属する）", () => {
    for (const name of ALL_MUTATION_NAMES) {
      const flags = [isRowMutation(name), isClassifyMutation(name), isV1Mutation(name)];
      expect(flags.filter(Boolean)).toHaveLength(1);
    }
  });

  it("merge_rule_off は V1 変異（v1 側の束ねを止める。design §8.1 U4）", () => {
    expect(isV1Mutation("merge_rule_off")).toBe(true);
    expect(isRowMutation("merge_rule_off")).toBe(false);
    expect(isClassifyMutation("merge_rule_off")).toBe(false);
  });
});

/**
 * 生物系の変異 9 種（PR-3b §3.3）。分類器変異は「規則を無効化すると説明が消える」、行変異は
 * 「v2 を壊すと、規則が有効でも説明されない」ことを、`classify-biota.test.ts` と同じ最小フィクスチャで確かめる。
 */
describe("生物系の変異（PR-3b §3.3）", () => {
  const ALL_BIOTA_KNOWN = new Set<KnownRule>([
    "watershed_memo",
    "species_n_definition",
    "month_cell_membership",
    "vernacular_label_rule",
    "undated_excluded",
  ]);

  function unexplained(spec: { key: string[]; numeric: string[]; label: string[] }, v1: Record<string, unknown>[], v2: NormRow[], ctx: Partial<ClassifyContext>): number {
    const full: ClassifyContext = { expected: {}, declared: { v1Table: null, builder: null }, params: {}, known: ALL_BIOTA_KNOWN, ...ctx };
    const n1 = toNormRows(v1, spec.key, spec.numeric, spec.label);
    return compareRuns(rowsByKey(n1), rowsByKey(v2)).map((d) => classifyDiff(d, full)).filter((c) => c.rules.size === 0).length;
  }
  const norm = (spec: { key: string[]; numeric: string[]; label: string[] }, rows: Record<string, unknown>[]) =>
    toNormRows(rows, spec.key, spec.numeric, spec.label);

  const WS = { key: ["watershed_id", "year"], numeric: ["n", "species_n", "alien_n", "redlist_n"], label: [] };
  const wsBiota: BiotaExpectations = {
    wsYear: new Map([[watershedYearKey("A", 2020), { n: 12, alienN: 0, redlistN: 0, speciesNameN: 5, speciesTaxonN: 7 }]]),
  };
  const wsV1 = [{ watershed_id: "A", year: 2020, n: 10, species_n: 5, alien_n: 0, redlist_n: 0 }];
  const wsV2 = [{ watershed_id: "A", year: 2020, n: 12, species_n: 7, alien_n: 0, redlist_n: 0 }];

  it("変異なしなら 2 規則で全部説明できる（以降の変異の比較元）", () => {
    expect(unexplained(WS, wsV1, norm(WS, wsV2), { queryId: "watershed_year", biota: wsBiota })).toBe(0);
  });

  it("memo_rule_off: watershed_year が unexplained になる", () => {
    const opts = applyClassifyMutation("memo_rule_off");
    expect(unexplained(WS, wsV1, norm(WS, wsV2), { queryId: "watershed_year", biota: wsBiota, disabledRules: opts.disabledRules })).toBeGreaterThan(0);
  });

  it("species_n_rule_off: species_n だけの差（定義の違い）が unexplained になる", () => {
    const opts = applyClassifyMutation("species_n_rule_off");
    const biota: BiotaExpectations = { wsYear: new Map([[watershedYearKey("A", 2020), { n: 10, alienN: 0, redlistN: 0, speciesNameN: 5, speciesTaxonN: 7 }]]) };
    const v2 = [{ ...wsV2[0], n: 10 }];
    expect(unexplained(WS, wsV1, norm(WS, v2), { queryId: "watershed_year", biota })).toBe(0);
    expect(unexplained(WS, wsV1, norm(WS, v2), { queryId: "watershed_year", biota, disabledRules: opts.disabledRules })).toBeGreaterThan(0);
  });

  it("month_rule_off: species_months が unexplained になる", () => {
    const opts = applyClassifyMutation("month_rule_off");
    const spec = { key: ["month"], numeric: ["n"], label: [] };
    const biota: BiotaExpectations = { monthV1: new Map([[binomMonthKey("Fx a", 1), 10]]), monthV2: new Map([[binomMonthKey("Fx a", 1), 9]]) };
    const ctx = { queryId: "species_months", params: { binom: "Fx a" }, biota };
    expect(unexplained(spec, [{ month: 1, n: 10 }], norm(spec, [{ month: 1, n: 9 }]), ctx)).toBe(0);
    expect(unexplained(spec, [{ month: 1, n: 10 }], norm(spec, [{ month: 1, n: 9 }]), { ...ctx, disabledRules: opts.disabledRules })).toBeGreaterThan(0);
  });

  it("label_rule_off: 表示名の違いが unexplained になる（species_labels/species_catalog/species_share_trend）", () => {
    const opts = applyClassifyMutation("label_rule_off");
    const spec = { key: ["binom"], numeric: [], label: ["label"] };
    const biota: BiotaExpectations = { labels: new Map([["Fx a", "アルファ"]]) };
    for (const queryId of ["species_labels", "species_catalog", "species_share_trend"]) {
      const ctx = { queryId, biota };
      expect(unexplained(spec, [{ binom: "Fx a", label: "別名" }], norm(spec, [{ binom: "Fx a", label: "アルファ" }]), ctx)).toBe(0);
      expect(unexplained(spec, [{ binom: "Fx a", label: "別名" }], norm(spec, [{ binom: "Fx a", label: "アルファ" }]), { ...ctx, disabledRules: opts.disabledRules })).toBeGreaterThan(0);
    }
  });

  it("undated_rule_off: biota_totals が unexplained になる", () => {
    const opts = applyClassifyMutation("undated_rule_off");
    const spec = { key: [], numeric: ["records", "species", "mesh", "gbif", "inat"], label: [] };
    const biota: BiotaExpectations = { undated: { records: 6, gbif: 5, inat: 1 } };
    const v1 = [{ records: 100, species: 10, mesh: 5, gbif: 80, inat: 20 }];
    const v2 = norm(spec, [{ records: 94, species: 10, mesh: 5, gbif: 75, inat: 19 }]);
    expect(unexplained(spec, v1, v2, { queryId: "biota_totals", biota })).toBe(0);
    expect(unexplained(spec, v1, v2, { queryId: "biota_totals", biota, disabledRules: opts.disabledRules })).toBeGreaterThan(0);
  });

  it("label_wrong: 規則が有効でも、再計算と食い違うラベルは unexplained（規則が何でも説明する穴になっていない）", () => {
    const spec = { key: ["binom"], numeric: [], label: ["label"] };
    const biota: BiotaExpectations = { labels: new Map([["Fx a", "アルファ"], ["Fx b", "ベータ"]]) };
    const v2raw = norm(spec, [{ binom: "Fx a", label: "アルファ" }, { binom: "Fx b", label: "ベータ" }]);
    const ctx = { queryId: "species_labels", biota };
    // v1 が別の名前（規則が説明する通常の差）→ 変異なしなら 0
    const v1 = [{ binom: "Fx a", label: "旧名" }, { binom: "Fx b", label: "旧名2" }];
    expect(unexplained(spec, v1, v2raw, ctx)).toBe(0);
    const mutated = applyRowMutation("label_wrong", "species_labels", v2raw);
    expect(mutated[0].label.label).not.toBe("アルファ");
    expect(unexplained(spec, v1, mutated, ctx)).toBeGreaterThan(0);
    // v1 = v2 で差が無かった行でも、変異で食い違えば拾う
    expect(unexplained(spec, [{ binom: "Fx a", label: "アルファ" }, { binom: "Fx b", label: "ベータ" }], mutated, ctx)).toBeGreaterThan(0);
  });

  it("drop_species_rows: species_years の1種ぶんを落とすと row_only_in_v1 で unexplained", () => {
    const spec = { key: ["year"], numeric: ["n", "mesh_n"], label: [] };
    const v1 = [{ year: 2020, n: 5, mesh_n: 2 }, { year: 2021, n: 6, mesh_n: 2 }];
    const v2 = norm(spec, v1);
    expect(unexplained(spec, v1, v2, { queryId: "species_years", known: new Set() })).toBe(0);
    const mutated = applyRowMutation("drop_species_rows", "species_years", v2);
    expect(mutated).toHaveLength(0);
    expect(unexplained(spec, v1, mutated, { queryId: "species_years", known: new Set() })).toBeGreaterThan(0);
  });

  it("inflate_n: effort_years・mesh_by_year・ias_species の n を +1 すると説明できる規則が無く unexplained", () => {
    const spec = { key: ["year"], numeric: ["n", "species_n"], label: [] };
    const v1 = [{ year: 2020, n: 5, species_n: 2 }];
    for (const queryId of ["effort_years", "mesh_by_year", "ias_species"]) {
      const mutated = applyRowMutation("inflate_n", queryId, norm(spec, v1));
      expect(mutated[0].numeric.n).toBe(6);
      expect(unexplained(spec, v1, mutated, { queryId, known: new Set() })).toBeGreaterThan(0);
    }
    // 対象外の問い合わせでは no-op
    const untouched = applyRowMutation("inflate_n", "species_years", norm(spec, v1));
    expect(untouched[0].numeric.n).toBe(5);
  });

  it("month_off_by_one: species_months にも効く（月が1つずれて row_only になり、説明できない）", () => {
    const spec = { key: ["month"], numeric: ["n"], label: [] };
    expect(rowMutationAppliesTo("month_off_by_one", "species_months")).toBe(true);
    const v1 = [{ month: 1, n: 5 }, { month: 2, n: 6 }];
    // 期待値は v1 規則＝v2 規則（所属が原因の差は無い）ので、ずれた行は説明されない
    const biota: BiotaExpectations = {
      monthV1: new Map([[binomMonthKey("Fx a", 1), 5], [binomMonthKey("Fx a", 2), 6]]),
      monthV2: new Map([[binomMonthKey("Fx a", 1), 5], [binomMonthKey("Fx a", 2), 6]]),
    };
    const ctx = { queryId: "species_months", params: { binom: "Fx a" }, biota };
    const v2 = norm(spec, v1);
    expect(unexplained(spec, v1, v2, ctx)).toBe(0);
    const mutated = applyRowMutation("month_off_by_one", "species_months", v2);
    expect(unexplained(spec, v1, mutated, ctx)).toBeGreaterThan(0);
  });

  it("生物系の行変異の対象問い合わせ（宣言表）", () => {
    expect(rowMutationAppliesTo("label_wrong", "species_labels")).toBe(true);
    expect(rowMutationAppliesTo("label_wrong", "species_catalog")).toBe(false);
    expect(rowMutationAppliesTo("drop_species_rows", "species_years")).toBe(true);
    expect(rowMutationAppliesTo("drop_species_rows", "year_series_site")).toBe(false);
    for (const id of ["effort_years", "mesh_by_year", "ias_species"]) expect(rowMutationAppliesTo("inflate_n", id)).toBe(true);
    expect(rowMutationAppliesTo("inflate_n", "mesh_all")).toBe(false);
  });

  it("9 変異が全部 ALL_MUTATION_NAMES にあり、種別が排他", () => {
    for (const name of ["memo_rule_off", "species_n_rule_off", "month_rule_off", "label_rule_off", "undated_rule_off"]) {
      expect(ALL_MUTATION_NAMES).toContain(name);
      expect(isClassifyMutation(name)).toBe(true);
    }
    for (const name of ["label_wrong", "drop_species_rows", "inflate_n"]) {
      expect(ALL_MUTATION_NAMES).toContain(name);
      expect(isRowMutation(name)).toBe(true);
    }
    expect(ALL_MUTATION_NAMES).toContain("month_off_by_one");
  });
});
