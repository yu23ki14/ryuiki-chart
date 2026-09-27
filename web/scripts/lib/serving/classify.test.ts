import { describe, expect, it } from "vitest";
import { rowsByKey, toNormRows } from "./normalize";
import {
  classifyDiff,
  compareRuns,
  computeRainRecompute,
  findRottenDeclarations,
  type Classification,
  type ClassifyContext,
  type ExpectedDiffs,
  type RainL2Row,
} from "./classify";

function ctxBase(overrides: Partial<ClassifyContext> = {}): ClassifyContext {
  return {
    expected: {},
    declared: { v1Table: null, builder: null },
    params: {},
    known: new Set(),
    ...overrides,
  };
}

/**
 * `Classification.rules`（説明の鎖が使った規則の集合）を、単一規則のテストが
 * 読みやすいように文字列へ潰す小さな補助関数。空集合は `"unexplained"`、複数
 * 要素は `+` で連結してソートする（複数系統にまたがる診断を確かめるテストは
 * `.rules` を直接 `toEqual(new Set([...]))` で見る）。
 */
function ruleOf(c: Classification): string {
  if (c.rules.size === 0) return "unexplained";
  return [...c.rules].sort().join("+");
}

describe("compareRuns", () => {
  it("v1にしか無い行は row_only_in_v1", () => {
    const v1 = rowsByKey(toNormRows([{ y: 2020, n: 1 }], ["y"], ["n"], []));
    const v2 = rowsByKey(toNormRows([], ["y"], ["n"], []));
    const diffs = compareRuns(v1, v2);
    expect(diffs).toEqual([{ key: [2020], kind: "row_only_in_v1", columns: [], v1: v1.get("[2020]") }]);
  });

  it("v2にしか無い行は row_only_in_v2", () => {
    const v1 = rowsByKey(toNormRows([], ["y"], ["n"], []));
    const v2 = rowsByKey(toNormRows([{ y: 2020, n: 1 }], ["y"], ["n"], []));
    const diffs = compareRuns(v1, v2);
    expect(diffs[0].kind).toBe("row_only_in_v2");
  });

  it("数値列が食い違えば value_diff（食い違った列だけを挙げる）", () => {
    const v1 = rowsByKey(toNormRows([{ y: 2020, n: 1, avg: 1.0 }], ["y"], ["n", "avg"], []));
    const v2 = rowsByKey(toNormRows([{ y: 2020, n: 1, avg: 2.0 }], ["y"], ["n", "avg"], []));
    const diffs = compareRuns(v1, v2);
    expect(diffs).toEqual([expect.objectContaining({ kind: "value_diff", columns: ["avg"] })]);
  });

  it("既定の許容差は0（浮動小数のごく小さな差も拾う）", () => {
    const v1 = rowsByKey(toNormRows([{ y: 2020, avg: 1.0 }], ["y"], ["avg"], []));
    const v2 = rowsByKey(toNormRows([{ y: 2020, avg: 1.0 + 1e-6 }], ["y"], ["avg"], []));
    expect(compareRuns(v1, v2)).toHaveLength(1);
  });

  it("tolerance を渡すとその範囲内は差分にしない", () => {
    const v1 = rowsByKey(toNormRows([{ y: 2020, avg: 1.0 }], ["y"], ["avg"], []));
    const v2 = rowsByKey(toNormRows([{ y: 2020, avg: 1.0 + 1e-12 }], ["y"], ["avg"], []));
    expect(compareRuns(v1, v2, { avg: 1e-9 })).toHaveLength(0);
  });

  it("ラベル列が食い違えば label_diff。数値列とは別のRowDiffとして両方出る", () => {
    const v1 = rowsByKey(toNormRows([{ y: 2020, avg: 2, unit: "mg/L" }], ["y"], ["avg"], ["unit"]));
    const v2 = rowsByKey(toNormRows([{ y: 2020, avg: 3, unit: null }], ["y"], ["avg"], ["unit"]));
    const diffs = compareRuns(v1, v2);
    expect(diffs).toHaveLength(2);
    expect(diffs.map((d) => d.kind).sort()).toEqual(["label_diff", "value_diff"]);
  });

  it("完全一致なら空", () => {
    const v1 = rowsByKey(toNormRows([{ y: 2020, avg: 1 }], ["y"], ["avg"], []));
    const v2 = rowsByKey(toNormRows([{ y: 2020, avg: 1 }], ["y"], ["avg"], []));
    expect(compareRuns(v1, v2)).toEqual([]);
  });
});

describe("classifyDiff: declared", () => {
  const expected: ExpectedDiffs = {
    meas_year: [
      {
        key: ["site-a", "変数X", 2002, "daily"],
        kind: "value_diff",
        columns: ["n", "avg", "min", "n_censored"],
      },
      { key: ["site-a", "変数X", 2003, "daily"], kind: "row_only_in_candidate" },
    ],
  };

  it("宣言済みキー・列が一致すれば declared", () => {
    const v1 = rowsByKey(toNormRows([{ year: 2002, n: 5, avg: 1, min: 0, max: 2 }], ["year"], ["n", "avg", "min", "max"], []));
    const v2 = rowsByKey(toNormRows([{ year: 2002, n: 4, avg: 1.5, min: 0.5, max: 2 }], ["year"], ["n", "avg", "min", "max"], []));
    const diffs = compareRuns(v1, v2);
    const ctx = ctxBase({
      expected,
      declared: { v1Table: "meas_year", builder: (p, k) => [p.site_id, p.alias, k[0], p.kind] },
      params: { site_id: "site-a", alias: "変数X", kind: "daily" },
      known: new Set(["declared"]),
    });
    const results = diffs.map((d) => classifyDiff(d, ctx));
    expect(results.every((r) => ruleOf(r) === "declared")).toBe(true);
  });

  it("row_only_in_candidate（v2にしか無い）の宣言は row_only_in_v2 に対応する", () => {
    const v1 = rowsByKey(toNormRows([], ["year"], [], []));
    const v2 = rowsByKey(toNormRows([{ year: 2003 }], ["year"], [], []));
    const diffs = compareRuns(v1, v2);
    const ctx = ctxBase({
      expected,
      declared: { v1Table: "meas_year", builder: (p, k) => [p.site_id, p.alias, k[0], p.kind] },
      params: { site_id: "site-a", alias: "変数X", kind: "daily" },
      known: new Set(["declared"]),
    });
    expect(ruleOf(classifyDiff(diffs[0], ctx))).toBe("declared");
  });

  it("キーが一致しなければ declared にならない（unexplained）", () => {
    const v1 = rowsByKey(toNormRows([{ year: 2099, n: 1 }], ["year"], ["n"], []));
    const v2 = rowsByKey(toNormRows([{ year: 2099, n: 2 }], ["year"], ["n"], []));
    const diffs = compareRuns(v1, v2);
    const ctx = ctxBase({
      expected,
      declared: { v1Table: "meas_year", builder: (p, k) => [p.site_id, p.alias, k[0], p.kind] },
      params: { site_id: "site-a", alias: "変数X", kind: "daily" },
      known: new Set(["declared"]),
    });
    expect(ruleOf(classifyDiff(diffs[0], ctx))).toBe("unexplained");
  });

  it("known に declared が無ければ、宣言があっても適用しない", () => {
    const v1 = rowsByKey(toNormRows([{ year: 2002, n: 5 }], ["year"], ["n"], []));
    const v2 = rowsByKey(toNormRows([{ year: 2002, n: 4 }], ["year"], ["n"], []));
    const diffs = compareRuns(v1, v2);
    const ctx = ctxBase({
      expected,
      declared: { v1Table: "meas_year", builder: (p, k) => [p.site_id, p.alias, k[0], p.kind] },
      params: { site_id: "site-a", alias: "変数X", kind: "daily" },
      known: new Set(),
    });
    expect(ruleOf(classifyDiff(diffs[0], ctx))).toBe("unexplained");
  });
});

describe("classifyDiff: day_split", () => {
  // v1(ラベル日割り)は 23:00〜翌0:00 の1時間が「翌日」に入る、v2(period_start日割り)は
  // その1時間が「当日」に残る、という実際の癖を各テストの最小フィクスチャで再現する。

  it("ラベル日にしか無い日は row_only_in_v1 が day_split で説明できる", () => {
    const onlyLabelRows: RainL2Row[] = [
      { periodRaw: "2020-02-01T00:30:00", periodStart: "2020-01-31T23:30:00", valueNum: 10 },
    ];
    const r = computeRainRecompute(onlyLabelRows);
    const v1 = rowsByKey(toNormRows([{ d: "2020-02-01", mm: 1 }], ["d"], ["mm"], []));
    const v2 = rowsByKey(toNormRows([], ["d"], ["mm"], []));
    const diffs = compareRuns(v1, v2);
    const ctx = ctxBase({ known: new Set(["day_split"]), rain: r });
    expect(ruleOf(classifyDiff(diffs[0], ctx))).toBe("day_split");
  });

  it("period_start日にしか無い日は row_only_in_v2 が day_split で説明できる", () => {
    const onlyStartRows: RainL2Row[] = [
      { periodRaw: "2020-02-01T00:30:00", periodStart: "2020-01-31T23:30:00", valueNum: 10 },
    ];
    const r = computeRainRecompute(onlyStartRows);
    const v1 = rowsByKey(toNormRows([], ["d"], ["mm"], []));
    const v2 = rowsByKey(toNormRows([{ d: "2020-01-31", mm: 1 }], ["d"], ["mm"], []));
    const diffs = compareRuns(v1, v2);
    const ctx = ctxBase({ known: new Set(["day_split"]), rain: r });
    expect(ruleOf(classifyDiff(diffs[0], ctx))).toBe("day_split");
  });

  it("両方に日はあるが値が違う場合も、再計算値と一致すれば day_split", () => {
    // 2020-01-01 に、ラベル日割りだと2件(0.8)、period_start日割りだと1件(0.5)しか属さない。
    const mixedRows: RainL2Row[] = [
      { periodRaw: "2020-01-01T10:00:00", periodStart: "2020-01-01T09:00:00", valueNum: 5 },
      { periodRaw: "2020-01-01T23:30:00", periodStart: "2020-01-02T22:30:00", valueNum: 3 },
    ];
    const r = computeRainRecompute(mixedRows);
    const v1 = rowsByKey(toNormRows([{ d: "2020-01-01", mm: r.byLabelDay.get("2020-01-01") }], ["d"], ["mm"], []));
    // v2 の `mm`（キューブの生の合計値）は `/10` していない（design §0 決定2）。
    // `byPeriodStartDay` は再計算のための `/10` 後の値なので、フィクスチャでも
    // 実際の v2 と同じ「生値」にして渡す（×10）。
    const v2 = rowsByKey(toNormRows([{ d: "2020-01-01", mm: r.byPeriodStartDay.get("2020-01-01")! * 10 }], ["d"], ["mm"], []));
    const diffs = compareRuns(v1, v2);
    expect(diffs).toHaveLength(1);
    const ctx = ctxBase({ known: new Set(["day_split"]), rain: r });
    expect(ruleOf(classifyDiff(diffs[0], ctx))).toBe("day_split");
  });

  it("rain が無ければ day_split は不発（unexplained）", () => {
    const v1 = rowsByKey(toNormRows([{ d: "2020-02-01", mm: 1 }], ["d"], ["mm"], []));
    const v2 = rowsByKey(toNormRows([], ["d"], ["mm"], []));
    const diffs = compareRuns(v1, v2);
    const ctx = ctxBase({ known: new Set(["day_split"]) });
    expect(ruleOf(classifyDiff(diffs[0], ctx))).toBe("unexplained");
  });

  it("--mutate day_split_rule_off 相当は unexplained に落ちる", () => {
    const onlyLabelRows: RainL2Row[] = [
      { periodRaw: "2020-02-01T00:30:00", periodStart: "2020-01-31T23:30:00", valueNum: 10 },
    ];
    const r = computeRainRecompute(onlyLabelRows);
    const v1 = rowsByKey(toNormRows([{ d: "2020-02-01", mm: 1 }], ["d"], ["mm"], []));
    const v2 = rowsByKey(toNormRows([], ["d"], ["mm"], []));
    const diffs = compareRuns(v1, v2);
    const ctx = ctxBase({ known: new Set(["day_split"]), rain: r, disabledRules: new Set(["day_split"]) });
    expect(ruleOf(classifyDiff(diffs[0], ctx))).toBe("unexplained");
  });
});

describe("classifyDiff: day_split（月次・rain_monthly_clim、rainGrain:'month'）", () => {
  // 本番で `rain_div10` が唯一残っていた `rain_monthly_clim` は月次
  // （`classifyDaySplitMonthly`）でしか判定していない。ここまでの `day_split`
  // describe ブロックは全て日次（既定の rainGrain）の経路しか通っておらず、
  // 本番で実際に使われる月次の経路には1件もテストが無かった
  // （Issue #48 PR-2 統合後 修正C で判明: `--only rain_monthly_clim --mutate
  // rain_no_div10_rule` を実データで回すと rain_div10 が1件も選ばれず、
  // 変異を検出できなかった）。

  it("ラベル日にしか属さない月は row_only_in_v1 が day_split(月次) で説明できる", () => {
    const onlyLabelEvent: RainL2Row[] = [
      { periodRaw: "2020-02-01T00:30:00", periodStart: "2020-01-31T23:30:00", valueNum: 10 },
    ];
    const r = computeRainRecompute(onlyLabelEvent);
    // ラベル日割りだと 2月、period_start 日割りだと 1月に属する→2月はv1にしか無い。
    const v1 = rowsByKey(toNormRows([{ month: 2, mm: 1 }], ["month"], ["mm"], []));
    const v2 = rowsByKey(toNormRows([], ["month"], ["mm"], []));
    const diffs = compareRuns(v1, v2);
    const ctx = ctxBase({ known: new Set(["day_split"]), rain: r, rainGrain: "month" });
    expect(ruleOf(classifyDiff(diffs[0], ctx))).toBe("day_split");
  });

  it("period_start日にしか属さない月は row_only_in_v2 が day_split(月次) で説明できる", () => {
    const onlyLabelEvent: RainL2Row[] = [
      { periodRaw: "2020-02-01T00:30:00", periodStart: "2020-01-31T23:30:00", valueNum: 10 },
    ];
    const r = computeRainRecompute(onlyLabelEvent);
    // 同じ1件の事象から、今度は1月（period_start側）を見る: v1に無く v2にだけ有る。
    const v1 = rowsByKey(toNormRows([], ["month"], ["mm"], []));
    const v2 = rowsByKey(toNormRows([{ month: 1, mm: 100 }], ["month"], ["mm"], []));
    const diffs = compareRuns(v1, v2);
    const ctx = ctxBase({ known: new Set(["day_split"]), rain: r, rainGrain: "month" });
    expect(ruleOf(classifyDiff(diffs[0], ctx))).toBe("day_split");
  });

  it("日付境界のずれが無くても、/10 換算だけの差を day_split(月次) がそのまま説明する（rain_div10 を撤去した理由）", () => {
    // ラベル日・period_start 日が完全に同じ日（境界をまたがない）事象だけで
    // 月別平年値を作る——「日割りのずれ」は一切無い、純粋な /10 の差だけの状況。
    const noBoundaryCross: RainL2Row[] = [
      { periodRaw: "2020-03-15T10:00:00", periodStart: "2020-03-15T09:00:00", valueNum: 50 },
    ];
    const r = computeRainRecompute(noBoundaryCross);
    const v1 = rowsByKey(toNormRows([{ month: 3, mm: r.monthlyLabel.get(3) }], ["month"], ["mm"], []));
    // v2 の `mm`（キューブの生の合計値）は `/10` していない（design §0 決定2）。
    const v2 = rowsByKey(toNormRows([{ month: 3, mm: r.monthlyPeriodStartRaw.get(3) }], ["month"], ["mm"], []));
    const diffs = compareRuns(v1, v2);
    expect(diffs).toHaveLength(1); // 日付境界のずれが無いのに、なお value_diff が出る（=純粋な /10 の差）
    const ctx = ctxBase({ known: new Set(["day_split"]), rain: r, rainGrain: "month" });
    expect(ruleOf(classifyDiff(diffs[0], ctx))).toBe("day_split");
  });

  it("--mutate day_split_rule_off 相当（月次）は unexplained に落ちる", () => {
    const onlyLabelEvent: RainL2Row[] = [
      { periodRaw: "2020-02-01T00:30:00", periodStart: "2020-01-31T23:30:00", valueNum: 10 },
    ];
    const r = computeRainRecompute(onlyLabelEvent);
    const v1 = rowsByKey(toNormRows([{ month: 2, mm: 1 }], ["month"], ["mm"], []));
    const v2 = rowsByKey(toNormRows([], ["month"], ["mm"], []));
    const diffs = compareRuns(v1, v2);
    const ctx = ctxBase({
      known: new Set(["day_split"]),
      rain: r,
      rainGrain: "month",
      disabledRules: new Set(["day_split"]),
    });
    expect(ruleOf(classifyDiff(diffs[0], ctx))).toBe("unexplained");
  });
});

describe("classifyDiff: unit_label_registry", () => {
  it("v1がunit=NULL・v2が非NULLで、それ以外の列が一致し、v2の単位がレジストリのsymbolと一致すれば unit_label_registry", () => {
    const v1 = rowsByKey(toNormRows([{ y: 1, n: 5, unit: null }], ["y"], ["n"], ["unit"]));
    const v2 = rowsByKey(toNormRows([{ y: 1, n: 5, unit: "mg/L" }], ["y"], ["n"], ["unit"]));
    const diffs = compareRuns(v1, v2);
    const ctx = ctxBase({
      known: new Set(["unit_label_registry"]),
      params: { alias: "変数X" },
      expectedUnitSymbol: new Map([["変数X", "mg/L"]]),
    });
    expect(ruleOf(classifyDiff(diffs[0], ctx))).toBe("unit_label_registry");
  });

  it("alias が params に無ければ diff.key[0]（variable_catalog/site_variables の行キー）から解決する", () => {
    const v1 = rowsByKey(toNormRows([{ alias: "変数X", n: 5, unit: null }], ["alias"], ["n"], ["unit"]));
    const v2 = rowsByKey(toNormRows([{ alias: "変数X", n: 5, unit: "mg/L" }], ["alias"], ["n"], ["unit"]));
    const diffs = compareRuns(v1, v2);
    const ctx = ctxBase({
      known: new Set(["unit_label_registry"]),
      expectedUnitSymbol: new Map([["変数X", "mg/L"]]),
    });
    expect(ruleOf(classifyDiff(diffs[0], ctx))).toBe("unit_label_registry");
  });

  it("数値列も食い違っていれば（value_diffが別に出るので）unit列単独のlabel_diffだけがunit_label_registryになる", () => {
    const v1 = rowsByKey(toNormRows([{ y: 1, n: 5, unit: null }], ["y"], ["n"], ["unit"]));
    const v2 = rowsByKey(toNormRows([{ y: 1, n: 6, unit: "mg/L" }], ["y"], ["n"], ["unit"]));
    const diffs = compareRuns(v1, v2);
    const kinds = diffs.map((d) => d.kind);
    expect(kinds).toContain("value_diff");
    expect(kinds).toContain("label_diff");
    const labelDiff = diffs.find((d) => d.kind === "label_diff")!;
    const ctx = ctxBase({
      known: new Set(["unit_label_registry"]),
      params: { alias: "変数X" },
      expectedUnitSymbol: new Map([["変数X", "mg/L"]]),
    });
    expect(ruleOf(classifyDiff(labelDiff, ctx))).toBe("unit_label_registry");
  });

  it("v1側が既にunitを持っていれば適用しない", () => {
    const v1 = rowsByKey(toNormRows([{ y: 1, unit: "mg/L" }], ["y"], [], ["unit"]));
    const v2 = rowsByKey(toNormRows([{ y: 1, unit: "mg/l" }], ["y"], [], ["unit"]));
    const diffs = compareRuns(v1, v2);
    const ctx = ctxBase({
      known: new Set(["unit_label_registry"]),
      params: { alias: "変数X" },
      expectedUnitSymbol: new Map([["変数X", "mg/l"]]),
    });
    expect(ruleOf(classifyDiff(diffs[0], ctx))).toBe("unexplained");
  });

  it("known に unit_label_registry が無ければ、他の条件を満たしても適用しない（unexplained）", () => {
    const v1 = rowsByKey(toNormRows([{ y: 1, n: 5, unit: null }], ["y"], ["n"], ["unit"]));
    const v2 = rowsByKey(toNormRows([{ y: 1, n: 5, unit: "mg/L" }], ["y"], ["n"], ["unit"]));
    const diffs = compareRuns(v1, v2);
    const ctx = ctxBase({
      known: new Set(), // unit_label_registry を許していない問い合わせ相当
      params: { alias: "変数X" },
      expectedUnitSymbol: new Map([["変数X", "mg/L"]]),
    });
    expect(ruleOf(classifyDiff(diffs[0], ctx))).toBe("unexplained");
  });

  it("v2の単位がその系列のレジストリsymbolと一致しなければ、非NULLでも unit_label_registry にならない", () => {
    const v1 = rowsByKey(toNormRows([{ y: 1, n: 5, unit: null }], ["y"], ["n"], ["unit"]));
    // v2 が非NULLではあるが、レジストリ上この alias の正しい symbol（mg/L）とは違う値。
    const v2 = rowsByKey(toNormRows([{ y: 1, n: 5, unit: "kg" }], ["y"], ["n"], ["unit"]));
    const diffs = compareRuns(v1, v2);
    const ctx = ctxBase({
      known: new Set(["unit_label_registry"]),
      params: { alias: "変数X" },
      expectedUnitSymbol: new Map([["変数X", "mg/L"]]),
    });
    expect(ruleOf(classifyDiff(diffs[0], ctx))).toBe("unexplained");
  });

  it("expectedUnitSymbol が渡されていなければ安全側に倒して unexplained", () => {
    const v1 = rowsByKey(toNormRows([{ y: 1, n: 5, unit: null }], ["y"], ["n"], ["unit"]));
    const v2 = rowsByKey(toNormRows([{ y: 1, n: 5, unit: "mg/L" }], ["y"], ["n"], ["unit"]));
    const diffs = compareRuns(v1, v2);
    const ctx = ctxBase({ known: new Set(["unit_label_registry"]), params: { alias: "変数X" } });
    expect(ruleOf(classifyDiff(diffs[0], ctx))).toBe("unexplained");
  });
});

describe("classifyDiff: float_rounding", () => {
  it("相対誤差1e-9以内なら float_rounding", () => {
    const v1 = rowsByKey(toNormRows([{ y: 1, avg: 1.0 + 1e-12 }], ["y"], ["avg"], []));
    const v2 = rowsByKey(toNormRows([{ y: 1, avg: 1.0 }], ["y"], ["avg"], []));
    // tolerance を渡さず(=0)比較して、value_diffとして出したものを float_rounding が拾えるか見る
    const diffs = compareRuns(v1, v2);
    const ctx = ctxBase({ known: new Set(["float_rounding"]) });
    expect(ruleOf(classifyDiff(diffs[0], ctx))).toBe("float_rounding");
  });

  it("誤差が大きければ float_rounding にならない", () => {
    const v1 = rowsByKey(toNormRows([{ y: 1, avg: 1.0 }], ["y"], ["avg"], []));
    const v2 = rowsByKey(toNormRows([{ y: 1, avg: 2.0 }], ["y"], ["avg"], []));
    const diffs = compareRuns(v1, v2);
    const ctx = ctxBase({ known: new Set(["float_rounding"]) });
    expect(ruleOf(classifyDiff(diffs[0], ctx))).toBe("unexplained");
  });
});

describe("classifyDiff: synthetic_excluded（design §1「差分の差分」・v1互換キューブ）", () => {
  it("v2CompatByKey 未指定では不発（--v1compat-db 未指定・v1-only 相当）", () => {
    const v1 = rowsByKey(toNormRows([{ y: 1, n: 5 }], ["y"], ["n"], []));
    const v2 = rowsByKey(toNormRows([], ["y"], ["n"], []));
    const diffs = compareRuns(v1, v2);
    const ctx = ctxBase({ known: new Set(["synthetic_excluded"]) });
    expect(ruleOf(classifyDiff(diffs[0], ctx))).toBe("unexplained");
  });

  it("row_only_in_v1: v2compat（合成込み）が v1 と一致すれば synthetic_excluded", () => {
    const v1 = rowsByKey(toNormRows([{ y: 1, n: 5 }], ["y"], ["n"], []));
    const v2 = rowsByKey(toNormRows([], ["y"], ["n"], []));
    const v2Compat = rowsByKey(toNormRows([{ y: 1, n: 5 }], ["y"], ["n"], []));
    const diffs = compareRuns(v1, v2);
    const ctx = ctxBase({ known: new Set(["synthetic_excluded"]), v2CompatByKey: v2Compat });
    expect(ruleOf(classifyDiff(diffs[0], ctx))).toBe("synthetic_excluded");
  });

  it("row_only_in_v1: v2compat の値が v1 と食い違えば unexplained（合成除外以外の理由で消えた行の疑い）", () => {
    const v1 = rowsByKey(toNormRows([{ y: 1, n: 5 }], ["y"], ["n"], []));
    const v2 = rowsByKey(toNormRows([], ["y"], ["n"], []));
    const v2Compat = rowsByKey(toNormRows([{ y: 1, n: 999 }], ["y"], ["n"], []));
    const diffs = compareRuns(v1, v2);
    const ctx = ctxBase({ known: new Set(["synthetic_excluded"]), v2CompatByKey: v2Compat });
    expect(ruleOf(classifyDiff(diffs[0], ctx))).toBe("unexplained");
  });

  it("value_diff: 許容列で v1==v2compat かつ v2compat≠v2(本番) なら synthetic_excluded", () => {
    const v1 = rowsByKey(toNormRows([{ y: 1, n: 10 }], ["y"], ["n"], []));
    const v2 = rowsByKey(toNormRows([{ y: 1, n: 8 }], ["y"], ["n"], []));
    const v2Compat = rowsByKey(toNormRows([{ y: 1, n: 10 }], ["y"], ["n"], []));
    const diffs = compareRuns(v1, v2);
    const ctx = ctxBase({ known: new Set(["synthetic_excluded"]), v2CompatByKey: v2Compat });
    expect(ruleOf(classifyDiff(diffs[0], ctx))).toBe("synthetic_excluded");
  });

  it("value_diff: v2compat と v2(本番) が同じ（合成除外の影響を受けていない）なら unexplained", () => {
    const v1 = rowsByKey(toNormRows([{ y: 1, n: 10 }], ["y"], ["n"], []));
    const v2 = rowsByKey(toNormRows([{ y: 1, n: 8 }], ["y"], ["n"], []));
    const v2Compat = rowsByKey(toNormRows([{ y: 1, n: 8 }], ["y"], ["n"], []));
    const diffs = compareRuns(v1, v2);
    const ctx = ctxBase({ known: new Set(["synthetic_excluded"]), v2CompatByKey: v2Compat });
    expect(ruleOf(classifyDiff(diffs[0], ctx))).toBe("unexplained");
  });

  it("value_diff: 許容列（SYNTHETIC_EXCLUDED_VALUE_COLUMNS）以外の列は対象外", () => {
    const v1 = rowsByKey(toNormRows([{ y: 1, elev_max: 10 }], ["y"], ["elev_max"], []));
    const v2 = rowsByKey(toNormRows([{ y: 1, elev_max: 8 }], ["y"], ["elev_max"], []));
    const v2Compat = rowsByKey(toNormRows([{ y: 1, elev_max: 10 }], ["y"], ["elev_max"], []));
    const diffs = compareRuns(v1, v2);
    const ctx = ctxBase({ known: new Set(["synthetic_excluded"]), v2CompatByKey: v2Compat });
    expect(ruleOf(classifyDiff(diffs[0], ctx))).toBe("unexplained");
  });

  it("row_only_in_v2 は対象外（合成除外で行が増えることは無い——常に unexplained）", () => {
    const v1 = rowsByKey(toNormRows([], ["y"], ["n"], []));
    const v2 = rowsByKey(toNormRows([{ y: 1, n: 5 }], ["y"], ["n"], []));
    const v2Compat = rowsByKey(toNormRows([{ y: 1, n: 5 }], ["y"], ["n"], []));
    const diffs = compareRuns(v1, v2);
    const ctx = ctxBase({ known: new Set(["synthetic_excluded"]), v2CompatByKey: v2Compat });
    expect(ruleOf(classifyDiff(diffs[0], ctx))).toBe("unexplained");
  });

  it("--mutate synthetic_rule_off 相当（disabledRules）は unexplained に落ちる", () => {
    const v1 = rowsByKey(toNormRows([{ y: 1, n: 5 }], ["y"], ["n"], []));
    const v2 = rowsByKey(toNormRows([], ["y"], ["n"], []));
    const v2Compat = rowsByKey(toNormRows([{ y: 1, n: 5 }], ["y"], ["n"], []));
    const diffs = compareRuns(v1, v2);
    const ctx = ctxBase({
      known: new Set(["synthetic_excluded"]),
      v2CompatByKey: v2Compat,
      disabledRules: new Set(["synthetic_excluded"]),
    });
    expect(ruleOf(classifyDiff(diffs[0], ctx))).toBe("unexplained");
  });
});

describe("classifyDiff: 説明の鎖（declared・synthetic_excluded・lod_imputation。docs/plans/V2_SERVING_PR2.md §1・§3）", () => {
  it("v1Table 経由: 宣言が列の一部だけを覆い、残りが synthetic_excluded で説明できれば {declared, synthetic_excluded}", () => {
    // `var_catalog`/`浮遊物質量 SS` の実測ケースの再現: n は宣言済み（below_lod の
    // 既知バグ）、n_sites は合成データの除外軸（宣言には無い）。
    const v1 = rowsByKey(toNormRows([{ variable: "ss", n: 10, n_sites: 5 }], ["variable"], ["n", "n_sites"], []));
    const v2 = rowsByKey(toNormRows([{ variable: "ss", n: 8, n_sites: 3 }], ["variable"], ["n", "n_sites"], []));
    const v2Compat = rowsByKey(toNormRows([{ variable: "ss", n: 999, n_sites: 5 }], ["variable"], ["n", "n_sites"], []));
    const diffs = compareRuns(v1, v2);
    const expected: ExpectedDiffs = { var_catalog: [{ key: ["ss"], kind: "value_diff", columns: ["n"] }] };
    const ctx = ctxBase({
      expected,
      declared: { v1Table: "var_catalog", builder: (_p, k) => [k[0]] },
      known: new Set(["declared", "synthetic_excluded"]),
      v2CompatByKey: v2Compat,
    });
    const c = classifyDiff(diffs[0], ctx);
    expect(c.rules).toEqual(new Set(["declared", "synthetic_excluded"]));
    expect(c.declaredMatches).toHaveLength(1);
    expect(c.declaredMatches[0].table).toBe("var_catalog");
  });

  it("残りの列が synthetic_excluded の許容列に無ければ unexplained（規則を緩めない）が、declared が使われた記録（declaredMatches）は残る（段1で使われたかで腐りを数える）", () => {
    const v1 = rowsByKey(toNormRows([{ variable: "ss", n: 10, elev_max: 5 }], ["variable"], ["n", "elev_max"], []));
    const v2 = rowsByKey(toNormRows([{ variable: "ss", n: 8, elev_max: 3 }], ["variable"], ["n", "elev_max"], []));
    const v2Compat = rowsByKey(toNormRows([{ variable: "ss", n: 999, elev_max: 5 }], ["variable"], ["n", "elev_max"], []));
    const diffs = compareRuns(v1, v2);
    const expected: ExpectedDiffs = { var_catalog: [{ key: ["ss"], kind: "value_diff", columns: ["n"] }] };
    const ctx = ctxBase({
      expected,
      declared: { v1Table: "var_catalog", builder: (_p, k) => [k[0]] },
      known: new Set(["declared", "synthetic_excluded"]),
      v2CompatByKey: v2Compat,
    });
    const c = classifyDiff(diffs[0], ctx);
    expect(ruleOf(c)).toBe("unexplained");
    expect(c.declaredMatches).toHaveLength(1); // n 列では declared が段1で使われた（overall unexplained でも記録は残る）
    expect(c.declaredMatches[0].table).toBe("var_catalog");
  });

  it("残りの列が v1==compat を満たさなければ unexplained（below_lod バグ以外の理由まで飲み込まない）", () => {
    const v1 = rowsByKey(toNormRows([{ variable: "ss", n: 10, n_sites: 5 }], ["variable"], ["n", "n_sites"], []));
    const v2 = rowsByKey(toNormRows([{ variable: "ss", n: 8, n_sites: 3 }], ["variable"], ["n", "n_sites"], []));
    // compat の n_sites が v1 と食い違う（合成除外では説明できない別の原因の疑い）。
    const v2Compat = rowsByKey(toNormRows([{ variable: "ss", n: 999, n_sites: 999 }], ["variable"], ["n", "n_sites"], []));
    const diffs = compareRuns(v1, v2);
    const expected: ExpectedDiffs = { var_catalog: [{ key: ["ss"], kind: "value_diff", columns: ["n"] }] };
    const ctx = ctxBase({
      expected,
      declared: { v1Table: "var_catalog", builder: (_p, k) => [k[0]] },
      known: new Set(["declared", "synthetic_excluded"]),
      v2CompatByKey: v2Compat,
    });
    expect(ruleOf(classifyDiff(diffs[0], ctx))).toBe("unexplained");
  });

  it("3つの原因が同じセルに重なる（中津川 SS 10月の実例の再現。declared＋synthetic_excluded＋lod_imputation の全部が必要）", () => {
    // v1 は below_lod の既知バグで below_lod 行を丸ごと落とす（n・avg・min の
    // 全列が動く）。compat_zero はそのバグを持たない（v1 と食い違う＝declared）。
    // v2_zero は compat_zero から合成データ1件を除いた値（n・avg が動く＝
    // synthetic_excluded）。v2_lod は zero→lod の切り替えで avg・min が動く
    // （lod_imputation）——列によって「どの段で・どれだけ動くか」が違う。
    const cols = ["n", "avg", "min", "n_censored"] as const;
    const v1 = rowsByKey(toNormRows([{ variable: "ss", month: 10, n: 10, avg: 1.0, min: 0.5, n_censored: 2 }], ["variable", "month"], [...cols], []));
    const v2Compat = rowsByKey(toNormRows([{ variable: "ss", month: 10, n: 12, avg: 0.9, min: 0.3, n_censored: 2 }], ["variable", "month"], [...cols], []));
    const v2Zero = rowsByKey(toNormRows([{ variable: "ss", month: 10, n: 11, avg: 0.95, min: 0.3, n_censored: 2 }], ["variable", "month"], [...cols], []));
    const v2 = rowsByKey(toNormRows([{ variable: "ss", month: 10, n: 11, avg: 1.2, min: 0.4, n_censored: 2 }], ["variable", "month"], [...cols], []));
    const diffs = compareRuns(v1, v2);
    expect(diffs).toHaveLength(1);
    expect(diffs[0].columns.slice().sort()).toEqual(["avg", "min", "n"]); // n_censored は動かない

    const expected: ExpectedDiffs = {
      meas_clim: [{ key: ["ss", 10], kind: "value_diff", columns: ["n", "avg", "min"] }],
    };
    const ctx = ctxBase({
      expected,
      declared: { v1Table: "meas_clim", builder: (_p, k) => [k[0], k[1]] },
      known: new Set(["declared", "synthetic_excluded", "lod_imputation"]),
      v2CompatByKey: v2Compat,
      v2ZeroByKey: v2Zero,
    });
    const c = classifyDiff(diffs[0], ctx);
    expect(c.rules).toEqual(new Set(["declared", "synthetic_excluded", "lod_imputation"]));
    expect(c.declaredMatches.length).toBeGreaterThan(0);
    expect(c.declaredMatches.every((m) => m.table === "meas_clim")).toBe(true);
  });

  it("by_variable（v1Table 無し）: byVariableDeclared 経由で束ねた alias の宣言が row_only_in_v2 を説明する", () => {
    // `day_series_site_by_variable`/`meas_daily` の実測ケース（below_lod の
    // 新規セルは v1 に無い row_only_in_v2）の再現。
    const v1 = rowsByKey(toNormRows([], ["d"], ["value"], []));
    const v2 = rowsByKey(toNormRows([{ d: "2002-11-06", value: 0 }], ["d"], ["value"], []));
    const diffs = compareRuns(v1, v2);
    const expected: ExpectedDiffs = {
      meas_daily: [{ key: ["site1", "浮遊物質量 SS", "2002-11-06"], kind: "row_only_in_candidate" }],
    };
    const ctx = ctxBase({
      expected,
      params: { site_id: "site1", variable_id: "common:variable:water.ss" },
      known: new Set(["declared", "synthetic_excluded"]),
      byVariableDeclared: {
        v1Table: "meas_daily",
        aliasesFor: () => ["浮遊物質量 SS"],
        buildKey: (alias, k) => [String(ctx.params.site_id), alias, k[0]],
      },
    });
    const c = classifyDiff(diffs[0], ctx);
    expect(c.rules).toEqual(new Set(["declared"]));
    expect(c.declaredMatches[0]?.table).toBe("meas_daily");
  });

  it("by_variable: 束ねたどの alias でも宣言が見つからなければ unexplained", () => {
    const v1 = rowsByKey(toNormRows([], ["d"], ["value"], []));
    const v2 = rowsByKey(toNormRows([{ d: "2002-11-06", value: 0 }], ["d"], ["value"], []));
    const diffs = compareRuns(v1, v2);
    const expected: ExpectedDiffs = {
      meas_daily: [{ key: ["site1", "浮遊物質量 SS", "1999-01-01"], kind: "row_only_in_candidate" }],
    };
    const ctx = ctxBase({
      expected,
      params: { site_id: "site1", variable_id: "common:variable:water.ss" },
      known: new Set(["declared", "synthetic_excluded"]),
      byVariableDeclared: {
        v1Table: "meas_daily",
        aliasesFor: () => ["浮遊物質量 SS"],
        buildKey: (alias, k) => [String(ctx.params.site_id), alias, k[0]],
      },
    });
    expect(ruleOf(classifyDiff(diffs[0], ctx))).toBe("unexplained");
  });

  it("by_variable: 宣言の columns が diff.columns を完全に覆えば synthetic を使わず declared", () => {
    const v1 = rowsByKey(toNormRows([{ month: 10, n: 5, avg: 1.0 }], ["month"], ["n", "avg"], []));
    const v2 = rowsByKey(toNormRows([{ month: 10, n: 6, avg: 0.9 }], ["month"], ["n", "avg"], []));
    const diffs = compareRuns(v1, v2);
    const expected: ExpectedDiffs = {
      meas_clim: [{ key: ["浮遊物質量 SS", 10], kind: "value_diff", columns: ["n", "avg"] }],
    };
    const ctx = ctxBase({
      expected,
      params: { variable_id: "common:variable:water.ss" },
      known: new Set(["declared"]), // synthetic_excluded 無しでも完全一致は declared 単独で通る
      byVariableDeclared: {
        v1Table: "meas_clim",
        aliasesFor: () => ["浮遊物質量 SS"],
        buildKey: (alias, k) => [alias, k[0]],
      },
    });
    const c = classifyDiff(diffs[0], ctx);
    expect(c.rules).toEqual(new Set(["declared"]));
    expect(c.declaredMatches[0]?.table).toBe("meas_clim");
  });

  it("--mutate declared_rot 相当（disabledRot）は組み合わせでも unexplained に落ちる", () => {
    const v1 = rowsByKey(toNormRows([{ variable: "ss", n: 10, n_sites: 5 }], ["variable"], ["n", "n_sites"], []));
    const v2 = rowsByKey(toNormRows([{ variable: "ss", n: 8, n_sites: 3 }], ["variable"], ["n", "n_sites"], []));
    const v2Compat = rowsByKey(toNormRows([{ variable: "ss", n: 999, n_sites: 5 }], ["variable"], ["n", "n_sites"], []));
    const diffs = compareRuns(v1, v2);
    const expected: ExpectedDiffs = { var_catalog: [{ key: ["ss"], kind: "value_diff", columns: ["n"] }] };
    const ctx = ctxBase({
      expected,
      declared: { v1Table: "var_catalog", builder: (_p, k) => [k[0]] },
      known: new Set(["declared", "synthetic_excluded"]),
      v2CompatByKey: v2Compat,
      declaredRot: { table: "var_catalog", key: ["ss"], kind: "value_diff" },
    });
    expect(ruleOf(classifyDiff(diffs[0], ctx))).toBe("unexplained");
  });
});

describe("classifyDiff: lod_imputation（design §3 #1・--imputation lod）", () => {
  it("v1==v2(zero) かつ許容列（avg）が食い違えば lod_imputation（n_censored>0）", () => {
    const v1 = rowsByKey(toNormRows([{ y: 1, avg: 1.0, n_censored: 3 }], ["y"], ["avg", "n_censored"], []));
    const v2 = rowsByKey(toNormRows([{ y: 1, avg: 1.5, n_censored: 3 }], ["y"], ["avg", "n_censored"], []));
    const v2Zero = rowsByKey(toNormRows([{ y: 1, avg: 1.0, n_censored: 3 }], ["y"], ["avg", "n_censored"], []));
    const diffs = compareRuns(v1, v2);
    const ctx = ctxBase({ known: new Set(["lod_imputation"]), v2ZeroByKey: v2Zero });
    expect(ruleOf(classifyDiff(diffs[0], ctx))).toBe("lod_imputation");
  });

  it("n_censored 列があり 0 なら lod_imputation にならない（検閲が無いのに値が動くのは別の原因）", () => {
    const v1 = rowsByKey(toNormRows([{ y: 1, avg: 1.0, n_censored: 0 }], ["y"], ["avg", "n_censored"], []));
    const v2 = rowsByKey(toNormRows([{ y: 1, avg: 1.5, n_censored: 0 }], ["y"], ["avg", "n_censored"], []));
    const v2Zero = rowsByKey(toNormRows([{ y: 1, avg: 1.0, n_censored: 0 }], ["y"], ["avg", "n_censored"], []));
    const diffs = compareRuns(v1, v2);
    const ctx = ctxBase({ known: new Set(["lod_imputation"]), v2ZeroByKey: v2Zero });
    expect(ruleOf(classifyDiff(diffs[0], ctx))).toBe("unexplained");
  });

  it("n_censored=0 でも lod 側がNULLになった（全件不検出）なら lod_imputation になる（実測: alias 'cn'/'pcb'）", () => {
    // b04 の不変条件は「value_zero≠value_lod ⇒ n_censored>0 **or**
    // n_not_detected>0」という OR（CLAUDE.md 参照）。v1 は n_not_detected を
    // 区別できないので、lod 側の値が NULL になったことを不検出の代理指標として
    // 認める（実測: シアン・PCB のような不検出だらけの項目で n_censored=0 の
    // まま value_lod が NULL になる）。
    const v1 = rowsByKey(toNormRows([{ y: 1, avg: 0.0, n_censored: 0 }], ["y"], ["avg", "n_censored"], []));
    const v2 = rowsByKey(toNormRows([{ y: 1, avg: null, n_censored: 0 }], ["y"], ["avg", "n_censored"], []));
    const v2Zero = rowsByKey(toNormRows([{ y: 1, avg: 0.0, n_censored: 0 }], ["y"], ["avg", "n_censored"], []));
    const diffs = compareRuns(v1, v2);
    const ctx = ctxBase({ known: new Set(["lod_imputation"]), v2ZeroByKey: v2Zero });
    expect(ruleOf(classifyDiff(diffs[0], ctx))).toBe("lod_imputation");
  });

  it("n_censored 列が無い合算問い合わせ（zone/climatology 等）は b04 の不変条件に依拠し確認しない", () => {
    const v1 = rowsByKey(toNormRows([{ y: 1, avg: 1.0 }], ["y"], ["avg"], []));
    const v2 = rowsByKey(toNormRows([{ y: 1, avg: 1.5 }], ["y"], ["avg"], []));
    const v2Zero = rowsByKey(toNormRows([{ y: 1, avg: 1.0 }], ["y"], ["avg"], []));
    const diffs = compareRuns(v1, v2);
    const ctx = ctxBase({ known: new Set(["lod_imputation"]), v2ZeroByKey: v2Zero });
    expect(ruleOf(classifyDiff(diffs[0], ctx))).toBe("lod_imputation");
  });

  it("v2ZeroByKey 未指定（--imputation zero 実行）では不発", () => {
    const v1 = rowsByKey(toNormRows([{ y: 1, avg: 1.0 }], ["y"], ["avg"], []));
    const v2 = rowsByKey(toNormRows([{ y: 1, avg: 1.5 }], ["y"], ["avg"], []));
    const diffs = compareRuns(v1, v2);
    const ctx = ctxBase({ known: new Set(["lod_imputation"]) });
    expect(ruleOf(classifyDiff(diffs[0], ctx))).toBe("unexplained");
  });

  it("v1 が v2(zero) と食い違っていれば（zero 自体に回帰があるので）lod_imputation にならない", () => {
    const v1 = rowsByKey(toNormRows([{ y: 1, avg: 1.0 }], ["y"], ["avg"], []));
    const v2 = rowsByKey(toNormRows([{ y: 1, avg: 1.5 }], ["y"], ["avg"], []));
    const v2Zero = rowsByKey(toNormRows([{ y: 1, avg: 9.9 }], ["y"], ["avg"], []));
    const diffs = compareRuns(v1, v2);
    const ctx = ctxBase({ known: new Set(["lod_imputation"]), v2ZeroByKey: v2Zero });
    expect(ruleOf(classifyDiff(diffs[0], ctx))).toBe("unexplained");
  });

  it("許容列（avg/min/max/value）以外は対象外", () => {
    const v1 = rowsByKey(toNormRows([{ y: 1, n: 10 }], ["y"], ["n"], []));
    const v2 = rowsByKey(toNormRows([{ y: 1, n: 8 }], ["y"], ["n"], []));
    const v2Zero = rowsByKey(toNormRows([{ y: 1, n: 10 }], ["y"], ["n"], []));
    const diffs = compareRuns(v1, v2);
    const ctx = ctxBase({ known: new Set(["lod_imputation"]), v2ZeroByKey: v2Zero });
    expect(ruleOf(classifyDiff(diffs[0], ctx))).toBe("unexplained");
  });

  it("--mutate lod_rule_off 相当（disabledRules）は unexplained に落ちる", () => {
    const v1 = rowsByKey(toNormRows([{ y: 1, avg: 1.0, n_censored: 3 }], ["y"], ["avg", "n_censored"], []));
    const v2 = rowsByKey(toNormRows([{ y: 1, avg: 1.5, n_censored: 3 }], ["y"], ["avg", "n_censored"], []));
    const v2Zero = rowsByKey(toNormRows([{ y: 1, avg: 1.0, n_censored: 3 }], ["y"], ["avg", "n_censored"], []));
    const diffs = compareRuns(v1, v2);
    const ctx = ctxBase({
      known: new Set(["lod_imputation"]),
      v2ZeroByKey: v2Zero,
      disabledRules: new Set(["lod_imputation"]),
    });
    expect(ruleOf(classifyDiff(diffs[0], ctx))).toBe("unexplained");
  });
});

describe("classifyDiff: 行変異への耐性（v2TrueByKey/v2TrueZeroByKey、Issue #48 PR-2 統合後 修正C）", () => {
  // 実データ（`--only year_series_site,year_series_water --mutate swap_kind
  // --v1compat-db data/db/v2_v1compat.sqlite`）で、`synthetic_excluded` が
  // 「v1==compat かつ compat≠v2」だけを見ていたために、行変異で書き換えた
  // 45,335 件の value_diff（実際に合成データの影響を受ける24地点をはるかに
  // 超える210地点に及んだ）を「合成データの除外」として誤って説明していた。
  // `v2TrueByKey`（行変異を当てる前の生の v2 行）が無ければ、この誤りを
  // classify.ts 単体では再現できない——ここではその状況をフィクスチャで固定する。

  it("diff.v2 が v2TrueByKey と食い違えば synthetic_excluded にならない（swap_kind/lod_instead_of_zero 相当）", () => {
    const v1 = rowsByKey(toNormRows([{ y: 1, n: 10 }], ["y"], ["n"], []));
    // v2 側は行変異で n:999 に書き換えられている。
    const v2 = rowsByKey(toNormRows([{ y: 1, n: 999 }], ["y"], ["n"], []));
    const v2Compat = rowsByKey(toNormRows([{ y: 1, n: 10 }], ["y"], ["n"], []));
    // 行変異を当てる前の、v2 が実際に計算していた値（v1と一致——合成データの影響も無い）。
    const v2True = rowsByKey(toNormRows([{ y: 1, n: 10 }], ["y"], ["n"], []));
    const diffs = compareRuns(v1, v2);
    const ctx = ctxBase({
      known: new Set(["synthetic_excluded"]),
      v2CompatByKey: v2Compat,
      v2TrueByKey: v2True,
    });
    expect(ruleOf(classifyDiff(diffs[0], ctx))).toBe("unexplained");
  });

  it("v2TrueByKey が diff.v2 と一致していれば（行変異が無ければ）これまでどおり synthetic_excluded", () => {
    const v1 = rowsByKey(toNormRows([{ y: 1, n: 10 }], ["y"], ["n"], []));
    const v2 = rowsByKey(toNormRows([{ y: 1, n: 8 }], ["y"], ["n"], []));
    const v2Compat = rowsByKey(toNormRows([{ y: 1, n: 10 }], ["y"], ["n"], []));
    const v2True = rowsByKey(toNormRows([{ y: 1, n: 8 }], ["y"], ["n"], [])); // 変異なし＝v2そのもの
    const diffs = compareRuns(v1, v2);
    const ctx = ctxBase({
      known: new Set(["synthetic_excluded"]),
      v2CompatByKey: v2Compat,
      v2TrueByKey: v2True,
    });
    expect(ruleOf(classifyDiff(diffs[0], ctx))).toBe("synthetic_excluded");
  });

  it("row_only_in_v1: v2TrueByKey にまだ行が残っていれば（drop_series 等で消しただけ）synthetic_excluded にならない", () => {
    const v1 = rowsByKey(toNormRows([{ y: 1, n: 5 }], ["y"], ["n"], []));
    const v2 = rowsByKey(toNormRows([], ["y"], ["n"], [])); // 行変異で消された
    const v2Compat = rowsByKey(toNormRows([{ y: 1, n: 5 }], ["y"], ["n"], []));
    const v2True = rowsByKey(toNormRows([{ y: 1, n: 5 }], ["y"], ["n"], [])); // 本当はまだ存在する
    const diffs = compareRuns(v1, v2);
    const ctx = ctxBase({
      known: new Set(["synthetic_excluded"]),
      v2CompatByKey: v2Compat,
      v2TrueByKey: v2True,
    });
    expect(ruleOf(classifyDiff(diffs[0], ctx))).toBe("unexplained");
  });

  it("row_only_in_v1: v2TrueByKey が渡されていなければ（既存の挙動どおり）これまでどおり synthetic_excluded", () => {
    const v1 = rowsByKey(toNormRows([{ y: 1, n: 5 }], ["y"], ["n"], []));
    const v2 = rowsByKey(toNormRows([], ["y"], ["n"], []));
    const v2Compat = rowsByKey(toNormRows([{ y: 1, n: 5 }], ["y"], ["n"], []));
    const diffs = compareRuns(v1, v2);
    const ctx = ctxBase({ known: new Set(["synthetic_excluded"]), v2CompatByKey: v2Compat });
    expect(ruleOf(classifyDiff(diffs[0], ctx))).toBe("synthetic_excluded");
  });

  it("純粋な zero→lod の差（合成データの影響が無い地点）は synthetic_excluded で説明しない——lod_imputation が有効なら lod_imputation が説明する", () => {
    const v1 = rowsByKey(toNormRows([{ y: 1, avg: 1.0, n_censored: 3 }], ["y"], ["avg", "n_censored"], []));
    const v2 = rowsByKey(toNormRows([{ y: 1, avg: 1.5, n_censored: 3 }], ["y"], ["avg", "n_censored"], []));
    // この地点は合成データの影響が無いので、compat（合成込み・zero）は
    // 「本当にzeroなら」の値（v2TrueZeroByKey）と同じ。
    const v2Compat = rowsByKey(toNormRows([{ y: 1, avg: 1.0, n_censored: 3 }], ["y"], ["avg", "n_censored"], []));
    const v2TrueZero = rowsByKey(toNormRows([{ y: 1, avg: 1.0, n_censored: 3 }], ["y"], ["avg", "n_censored"], []));
    const diffs = compareRuns(v1, v2);
    const ctx = ctxBase({
      known: new Set(["synthetic_excluded", "lod_imputation"]),
      v2CompatByKey: v2Compat,
      v2ZeroByKey: v2TrueZero,
      v2TrueZeroByKey: v2TrueZero,
    });
    expect(ruleOf(classifyDiff(diffs[0], ctx))).toBe("lod_imputation");
  });

  it("...--mutate lod_rule_off 相当: 合成データの影響が無い地点なら synthetic_excluded が肩代わりせず unexplained に落ちる（lod_rule_off が検出できなかった実際の原因）", () => {
    const v1 = rowsByKey(toNormRows([{ y: 1, avg: 1.0, n_censored: 3 }], ["y"], ["avg", "n_censored"], []));
    const v2 = rowsByKey(toNormRows([{ y: 1, avg: 1.5, n_censored: 3 }], ["y"], ["avg", "n_censored"], []));
    const v2Compat = rowsByKey(toNormRows([{ y: 1, avg: 1.0, n_censored: 3 }], ["y"], ["avg", "n_censored"], []));
    const v2TrueZero = rowsByKey(toNormRows([{ y: 1, avg: 1.0, n_censored: 3 }], ["y"], ["avg", "n_censored"], []));
    const diffs = compareRuns(v1, v2);
    const ctx = ctxBase({
      known: new Set(["synthetic_excluded", "lod_imputation"]),
      v2CompatByKey: v2Compat,
      v2ZeroByKey: v2TrueZero,
      v2TrueZeroByKey: v2TrueZero,
      disabledRules: new Set(["lod_imputation"]),
    });
    expect(ruleOf(classifyDiff(diffs[0], ctx))).toBe("unexplained");
  });

  it("合成データの影響も受けている地点（compatがv2_zeroと食い違う）でも、lod_rule_off なら段3（zero→lod）を説明できず unexplained になる（段を分けたぶん、synthetic_excluded が lod の分まで肩代わりしなくなった——旧 `classifySyntheticExcludedV1Compat` が compat と最終値を直接比べていたために起きていた `--mutate lod_rule_off` の検出漏れの裏返し。`docs/plans/V2_SERVING_PR2.md` §1）", () => {
    const v1 = rowsByKey(toNormRows([{ y: 1, avg: 1.0 }], ["y"], ["avg"], []));
    const v2 = rowsByKey(toNormRows([{ y: 1, avg: 1.5 }], ["y"], ["avg"], []));
    const v2Compat = rowsByKey(toNormRows([{ y: 1, avg: 1.0 }], ["y"], ["avg"], []));
    // 合成データを除いた「本当の v2_zero」値は compat（合成込み）と食い違う
    // ＝この行は実際に合成データの影響を受けている（段2は synthetic_excluded で説明できる）。
    const v2TrueZero = rowsByKey(toNormRows([{ y: 1, avg: 0.9 }], ["y"], ["avg"], []));
    const diffs = compareRuns(v1, v2);
    const ctx = ctxBase({
      known: new Set(["synthetic_excluded", "lod_imputation"]),
      v2CompatByKey: v2Compat,
      v2ZeroByKey: v2TrueZero, // 実際の lod 実行時の配線（v2TrueZeroByKey と同じ行）
      v2TrueZeroByKey: v2TrueZero,
      disabledRules: new Set(["lod_imputation"]),
    });
    // 段2（compat_zero↔v2_zero）は synthetic_excluded で説明できるが、
    // 段3（v2_zero↔v2_lod）は lod_imputation を無効化しているため説明できない。
    // 「説明の鎖」は各段を独立に検証するので、synthetic_excluded が段3の分まで
    // 肩代わりすることは無い——これが本題（3原因重なり）の設計が解決したかった、
    // 「特例を積み増さないと重なりを説明できない」状態そのものの解消。
    expect(ruleOf(classifyDiff(diffs[0], ctx))).toBe("unexplained");
  });

  it("v2TrueZeroByKey が渡されていなければ（既存の挙動どおり）これまでどおり synthetic_excluded", () => {
    const v1 = rowsByKey(toNormRows([{ y: 1, avg: 1.0 }], ["y"], ["avg"], []));
    const v2 = rowsByKey(toNormRows([{ y: 1, avg: 1.5 }], ["y"], ["avg"], []));
    const v2Compat = rowsByKey(toNormRows([{ y: 1, avg: 1.0 }], ["y"], ["avg"], []));
    const diffs = compareRuns(v1, v2);
    const ctx = ctxBase({ known: new Set(["synthetic_excluded"]), v2CompatByKey: v2Compat });
    expect(ruleOf(classifyDiff(diffs[0], ctx))).toBe("synthetic_excluded");
  });

  it("diff.v2 が v2TrueByKey と食い違えば lod_imputation にならない（lod_instead_of_zero 相当、--imputation lod）", () => {
    const v1 = rowsByKey(toNormRows([{ y: 1, avg: 1.0, n_censored: 3 }], ["y"], ["avg", "n_censored"], []));
    // v2 側（--imputation lod の本番行）は行変異でさらに書き換えられている。
    const v2 = rowsByKey(toNormRows([{ y: 1, avg: 1000001.5, n_censored: 3 }], ["y"], ["avg", "n_censored"], []));
    const v2Zero = rowsByKey(toNormRows([{ y: 1, avg: 1.0, n_censored: 3 }], ["y"], ["avg", "n_censored"], []));
    // 行変異を当てる前の、本当の lod 値（v1とはずれるが、これが正しい zero→lod の差）。
    const v2True = rowsByKey(toNormRows([{ y: 1, avg: 1.5, n_censored: 3 }], ["y"], ["avg", "n_censored"], []));
    const diffs = compareRuns(v1, v2);
    const ctx = ctxBase({
      known: new Set(["lod_imputation"]),
      v2ZeroByKey: v2Zero,
      v2TrueByKey: v2True,
    });
    expect(ruleOf(classifyDiff(diffs[0], ctx))).toBe("unexplained");
  });
});

describe("優先順位", () => {
  it("declaredが最優先（day_splitにも当てはまりうる状況でdeclaredを選ぶ）", () => {
    const onlyLabelEvent: RainL2Row[] = [
      { periodRaw: "2020-02-01T00:30:00", periodStart: "2020-01-31T23:30:00", valueNum: 10 },
    ];
    const r = computeRainRecompute(onlyLabelEvent);
    const expected: ExpectedDiffs = {
      rain_monthly_clim: [{ key: [2], kind: "row_only_in_baseline" }],
    };
    const v1 = rowsByKey(toNormRows([{ month: 2, mm: 1 }], ["month"], ["mm"], []));
    const v2 = rowsByKey(toNormRows([], ["month"], ["mm"], []));
    const diffs = compareRuns(v1, v2);
    const ctx = ctxBase({
      expected,
      declared: { v1Table: "rain_monthly_clim", builder: (_p, k) => [k[0]] },
      known: new Set(["declared", "day_split"]),
      rain: r,
      rainGrain: "month",
    });
    expect(ruleOf(classifyDiff(diffs[0], ctx))).toBe("declared");
  });
});

describe("findRottenDeclarations", () => {
  const expected: ExpectedDiffs = {
    meas_year: [
      { key: ["a", "x", 2002, "daily"], kind: "value_diff", columns: ["n"] },
      { key: ["a", "x", 2003, "daily"], kind: "value_diff", columns: ["n"] },
    ],
    org_norm: [{ key: ["gbif__1"], kind: "value_diff", columns: ["cls"] }],
  };

  it("対象テーブルで1件も使われなかった宣言を返す", () => {
    const matched = new Map([["meas_year", new Set(["value_diff\u0000[\"a\",\"x\",2002,\"daily\"]"])]]);
    const rotten = findRottenDeclarations(expected, new Set(["meas_year"]), matched);
    expect(rotten).toEqual([{ table: "meas_year", key: ["a", "x", 2003, "daily"], kind: "value_diff" }]);
  });

  it("対象外のテーブル（org_norm、PR-3b）は無視する", () => {
    const rotten = findRottenDeclarations(expected, new Set(["meas_year"]), new Map());
    expect(rotten.every((r) => r.table !== "org_norm")).toBe(true);
  });

  it("全部使われていれば空", () => {
    const matched = new Map([
      [
        "meas_year",
        new Set([
          "value_diff\u0000[\"a\",\"x\",2002,\"daily\"]",
          "value_diff\u0000[\"a\",\"x\",2003,\"daily\"]",
        ]),
      ],
    ]);
    expect(findRottenDeclarations(expected, new Set(["meas_year"]), matched)).toEqual([]);
  });
});
