import { describe, expect, it } from "vitest";
import { rowsByKey, toNormRows } from "./normalize";
import {
  classifyDiff,
  compareRuns,
  computeRainRecompute,
  findRottenDeclarations,
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
    expect(results.every((r) => r.rule === "declared")).toBe(true);
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
    expect(classifyDiff(diffs[0], ctx).rule).toBe("declared");
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
    expect(classifyDiff(diffs[0], ctx).rule).toBe("unexplained");
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
    expect(classifyDiff(diffs[0], ctx).rule).toBe("unexplained");
  });
});

describe("classifyDiff: rain_div10", () => {
  it("v2/10を丸めたものがv1と一致すれば rain_div10", () => {
    const v1 = rowsByKey(toNormRows([{ d: "2020-01-01", mm: 1.23 }], ["d"], ["mm"], []));
    const v2 = rowsByKey(toNormRows([{ d: "2020-01-01", mm: 12.3 }], ["d"], ["mm"], []));
    const diffs = compareRuns(v1, v2);
    const ctx = ctxBase({ known: new Set(["rain_div10"]) });
    expect(classifyDiff(diffs[0], ctx).rule).toBe("rain_div10");
  });

  it("既定の丸め(2桁)から外れる差は rain_div10 にならない", () => {
    const v1 = rowsByKey(toNormRows([{ d: "2020-01-01", mm: 1.23 }], ["d"], ["mm"], []));
    const v2 = rowsByKey(toNormRows([{ d: "2020-01-01", mm: 20 }], ["d"], ["mm"], []));
    const diffs = compareRuns(v1, v2);
    const ctx = ctxBase({ known: new Set(["rain_div10"]) });
    expect(classifyDiff(diffs[0], ctx).rule).toBe("unexplained");
  });

  it("--mutate rain_no_div10_rule 相当（disabledRulesで無効化）は unexplained に落ちる", () => {
    const v1 = rowsByKey(toNormRows([{ d: "2020-01-01", mm: 1.23 }], ["d"], ["mm"], []));
    const v2 = rowsByKey(toNormRows([{ d: "2020-01-01", mm: 12.3 }], ["d"], ["mm"], []));
    const diffs = compareRuns(v1, v2);
    const ctx = ctxBase({ known: new Set(["rain_div10"]), disabledRules: new Set(["rain_div10"]) });
    expect(classifyDiff(diffs[0], ctx).rule).toBe("unexplained");
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
    expect(classifyDiff(diffs[0], ctx).rule).toBe("day_split");
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
    expect(classifyDiff(diffs[0], ctx).rule).toBe("day_split");
  });

  it("両方に日はあるが値が違う場合も、再計算値と一致すれば day_split", () => {
    // 2020-01-01 に、ラベル日割りだと2件(0.8)、period_start日割りだと1件(0.5)しか属さない。
    const mixedRows: RainL2Row[] = [
      { periodRaw: "2020-01-01T10:00:00", periodStart: "2020-01-01T09:00:00", valueNum: 5 },
      { periodRaw: "2020-01-01T23:30:00", periodStart: "2020-01-02T22:30:00", valueNum: 3 },
    ];
    const r = computeRainRecompute(mixedRows);
    const v1 = rowsByKey(toNormRows([{ d: "2020-01-01", mm: r.byLabelDay.get("2020-01-01") }], ["d"], ["mm"], []));
    // v2 の `mm`（キューブの生の合計値）は `/10` していない（design §0 決定2・
    // `rain_div10` 規則参照）。`byPeriodStartDay` は再計算のための `/10` 後の値
    // なので、フィクスチャでも実際の v2 と同じ「生値」にして渡す（×10）。
    const v2 = rowsByKey(toNormRows([{ d: "2020-01-01", mm: r.byPeriodStartDay.get("2020-01-01")! * 10 }], ["d"], ["mm"], []));
    const diffs = compareRuns(v1, v2);
    expect(diffs).toHaveLength(1);
    const ctx = ctxBase({ known: new Set(["day_split"]), rain: r });
    expect(classifyDiff(diffs[0], ctx).rule).toBe("day_split");
  });

  it("rain が無ければ day_split は不発（unexplained）", () => {
    const v1 = rowsByKey(toNormRows([{ d: "2020-02-01", mm: 1 }], ["d"], ["mm"], []));
    const v2 = rowsByKey(toNormRows([], ["d"], ["mm"], []));
    const diffs = compareRuns(v1, v2);
    const ctx = ctxBase({ known: new Set(["day_split"]) });
    expect(classifyDiff(diffs[0], ctx).rule).toBe("unexplained");
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
    expect(classifyDiff(diffs[0], ctx).rule).toBe("unexplained");
  });
});

describe("classifyDiff: unit_label_registry", () => {
  it("v1がunit=NULL・v2が非NULLで、それ以外の列が一致すれば unit_label_registry", () => {
    const v1 = rowsByKey(toNormRows([{ y: 1, n: 5, unit: null }], ["y"], ["n"], ["unit"]));
    const v2 = rowsByKey(toNormRows([{ y: 1, n: 5, unit: "mg/L" }], ["y"], ["n"], ["unit"]));
    const diffs = compareRuns(v1, v2);
    const ctx = ctxBase({ known: new Set(["unit_label_registry"]) });
    expect(classifyDiff(diffs[0], ctx).rule).toBe("unit_label_registry");
  });

  it("数値列も食い違っていれば（value_diffが別に出るので）unit列単独のlabel_diffだけがunit_label_registryになる", () => {
    const v1 = rowsByKey(toNormRows([{ y: 1, n: 5, unit: null }], ["y"], ["n"], ["unit"]));
    const v2 = rowsByKey(toNormRows([{ y: 1, n: 6, unit: "mg/L" }], ["y"], ["n"], ["unit"]));
    const diffs = compareRuns(v1, v2);
    const kinds = diffs.map((d) => d.kind);
    expect(kinds).toContain("value_diff");
    expect(kinds).toContain("label_diff");
    const labelDiff = diffs.find((d) => d.kind === "label_diff")!;
    const ctx = ctxBase({ known: new Set(["unit_label_registry"]) });
    expect(classifyDiff(labelDiff, ctx).rule).toBe("unit_label_registry");
  });

  it("v1側が既にunitを持っていれば適用しない", () => {
    const v1 = rowsByKey(toNormRows([{ y: 1, unit: "mg/L" }], ["y"], [], ["unit"]));
    const v2 = rowsByKey(toNormRows([{ y: 1, unit: "mg/l" }], ["y"], [], ["unit"]));
    const diffs = compareRuns(v1, v2);
    const ctx = ctxBase({ known: new Set(["unit_label_registry"]) });
    expect(classifyDiff(diffs[0], ctx).rule).toBe("unexplained");
  });
});

describe("classifyDiff: float_rounding", () => {
  it("相対誤差1e-9以内なら float_rounding", () => {
    const v1 = rowsByKey(toNormRows([{ y: 1, avg: 1.0 + 1e-12 }], ["y"], ["avg"], []));
    const v2 = rowsByKey(toNormRows([{ y: 1, avg: 1.0 }], ["y"], ["avg"], []));
    // tolerance を渡さず(=0)比較して、value_diffとして出したものを float_rounding が拾えるか見る
    const diffs = compareRuns(v1, v2);
    const ctx = ctxBase({ known: new Set(["float_rounding"]) });
    expect(classifyDiff(diffs[0], ctx).rule).toBe("float_rounding");
  });

  it("誤差が大きければ float_rounding にならない", () => {
    const v1 = rowsByKey(toNormRows([{ y: 1, avg: 1.0 }], ["y"], ["avg"], []));
    const v2 = rowsByKey(toNormRows([{ y: 1, avg: 2.0 }], ["y"], ["avg"], []));
    const diffs = compareRuns(v1, v2);
    const ctx = ctxBase({ known: new Set(["float_rounding"]) });
    expect(classifyDiff(diffs[0], ctx).rule).toBe("unexplained");
  });
});

describe("classifyDiff: synthetic_excluded", () => {
  it("PR-1既定（syntheticSiteIds未指定）では不発", () => {
    const v1 = rowsByKey(toNormRows([{ y: 1, site_id: "synthetic-1" }], ["y"], [], ["site_id"]));
    const v2 = rowsByKey(toNormRows([], ["y"], [], ["site_id"]));
    const diffs = compareRuns(v1, v2);
    const ctx = ctxBase({ known: new Set(["synthetic_excluded"]) });
    expect(classifyDiff(diffs[0], ctx).rule).toBe("unexplained");
  });

  it("--pretend-synthetic-excluded 相当でsite_idが集合に入っていれば synthetic_excluded", () => {
    const v1 = rowsByKey(toNormRows([{ y: 1, site_id: "synthetic-1" }], ["y"], [], ["site_id"]));
    const v2 = rowsByKey(toNormRows([], ["y"], [], ["site_id"]));
    const diffs = compareRuns(v1, v2);
    const ctx = ctxBase({ known: new Set(["synthetic_excluded"]), syntheticSiteIds: new Set(["synthetic-1"]) });
    expect(classifyDiff(diffs[0], ctx).rule).toBe("synthetic_excluded");
  });
});

describe("優先順位", () => {
  it("declaredが最優先（他の規則にも当てはまりうる状況でdeclaredを選ぶ）", () => {
    const expected: ExpectedDiffs = {
      rain_daily: [{ key: ["2020-01-01"], kind: "value_diff", columns: ["mm"] }],
    };
    const v1 = rowsByKey(toNormRows([{ d: "2020-01-01", mm: 1.23 }], ["d"], ["mm"], []));
    const v2 = rowsByKey(toNormRows([{ d: "2020-01-01", mm: 12.3 }], ["d"], ["mm"], []));
    const diffs = compareRuns(v1, v2);
    const ctx = ctxBase({
      expected,
      declared: { v1Table: "rain_daily", builder: (_p, k) => [k[0]] },
      known: new Set(["declared", "rain_div10"]),
    });
    expect(classifyDiff(diffs[0], ctx).rule).toBe("declared");
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
