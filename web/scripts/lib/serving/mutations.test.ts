/**
 * 「変異で拾う」の実証（設計書 §5.3）。各変異を最小フィクスチャに当てて、
 * 素直な突き合わせ（`compareRuns`/`classifyDiff`）が必ず unexplained > 0（または
 * `declared_rot` は宣言が腐る）になることを確認する。
 */
import { describe, expect, it } from "vitest";
import { rowsByKey, toNormRows, type NormRow } from "./normalize";
import { classifyDiff, compareRuns, findRottenDeclarations, type ClassifyContext, type ExpectedDiffs } from "./classify";
import {
  ALL_MUTATION_NAMES,
  applyClassifyMutation,
  applyRowMutation,
  isClassifyMutation,
  isRowMutation,
  rowMutationAppliesTo,
} from "./mutations";

function unexplainedCount(v1: NormRow[], v2: NormRow[], ctx: Partial<ClassifyContext> = {}): number {
  const full: ClassifyContext = {
    expected: {},
    declared: { v1Table: null, builder: null },
    params: {},
    known: new Set(["declared", "rain_div10", "day_split", "unit_label_registry", "float_rounding"]),
    ...ctx,
  };
  const diffs = compareRuns(rowsByKey(v1), rowsByKey(v2));
  return diffs.map((d) => classifyDiff(d, full)).filter((c) => c.rule === "unexplained").length;
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
  it("rain_no_div10_rule は rain_div10 を無効化する", () => {
    const opts = applyClassifyMutation("rain_no_div10_rule");
    const v1 = toNormRows([{ d: "2020-01-01", mm: 1.23 }], ["d"], ["mm"], []);
    const v2 = toNormRows([{ d: "2020-01-01", mm: 12.3 }], ["d"], ["mm"], []);
    expect(unexplainedCount(v1, v2, { disabledRules: opts.disabledRules })).toBeGreaterThan(0);
  });

  it("day_split_rule_off は day_split を無効化する", () => {
    const opts = applyClassifyMutation("day_split_rule_off");
    const v1 = toNormRows([{ d: "2020-01-01", mm: 1 }], ["d"], ["mm"], []);
    const v2 = toNormRows([], ["d"], ["mm"], []);
    expect(unexplainedCount(v1, v2, { disabledRules: opts.disabledRules })).toBeGreaterThan(0);
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
    expect(results.every((r) => r.rule === "unexplained")).toBe(true);

    // 腐り検出: 何も matched に記録しない状態で findRottenDeclarations を呼べば
    // その宣言が腐って見える。
    const rotten = findRottenDeclarations(expected, new Set(["meas_year"]), new Map());
    expect(rotten).toEqual([{ table: "meas_year", key: ["a", "x", 2002, "daily"], kind: "value_diff" }]);
  });

  it("declared_rot はターゲット指定が無ければ例外にする", () => {
    expect(() => applyClassifyMutation("declared_rot")).toThrow();
  });

  it("isClassifyMutation/isRowMutation は互いに排他", () => {
    for (const name of ALL_MUTATION_NAMES) {
      expect(isRowMutation(name) !== isClassifyMutation(name)).toBe(true);
    }
  });
});
