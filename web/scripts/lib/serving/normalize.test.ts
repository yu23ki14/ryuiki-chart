import { describe, expect, it } from "vitest";
import { keyString, parseTrendPeriods, redlistGroupParam, rowsByKey, toNormRows, withOrdinal } from "./normalize";

describe("toNormRows", () => {
  it("列名でキー/数値/ラベルに振り分ける", () => {
    const rows = [{ site_id: "a", year: 2020, avg: 1.5, unit: "mg/L", extra: "x" }];
    const norm = toNormRows(rows, ["year"], ["avg"], ["unit"]);
    expect(norm).toEqual([{ key: [2020], numeric: { avg: 1.5 }, label: { unit: "mg/L" } }]);
  });

  it("NULL/undefined を null にそろえる", () => {
    const rows = [{ year: 2020, avg: null, unit: undefined }];
    const norm = toNormRows(rows, ["year"], ["avg"], ["unit"]);
    expect(norm[0].numeric.avg).toBeNull();
    expect(norm[0].label.unit).toBeNull();
  });

  it("数値文字列は number に変換する", () => {
    const rows = [{ year: 2020, avg: "1.5" }];
    const norm = toNormRows(rows, ["year"], ["avg"], []);
    expect(norm[0].numeric.avg).toBe(1.5);
  });
});

describe("rowsByKey", () => {
  it("key の JSON 文字列で引けるようにする", () => {
    const rows = toNormRows([{ y: 1 }, { y: 2 }], ["y"], [], []);
    const m = rowsByKey(rows);
    expect(m.get(keyString([1]))).toEqual(rows[0]);
    expect(m.size).toBe(2);
  });

  it("重複キーは例外にする", () => {
    const rows = toNormRows([{ y: 1 }, { y: 1 }], ["y"], [], []);
    expect(() => rowsByKey(rows)).toThrow();
  });
});

describe("withOrdinal（同じキー列の行に連番を足す）", () => {
  const rows = [
    { sci: "A a", ja: "x", rank: 2 },
    { sci: "A a", ja: "x", rank: 1 },
    { sci: "B b", ja: "y", rank: 5 },
  ];

  it("キー列が同じ行は全列の昇順で 0,1,… と番号が付き、rowsByKey の重複キー例外にならない", () => {
    const out = withOrdinal(rows, ["sci", "ja"]);
    expect(out.map((r) => [r.sci, r.rank, r.ord])).toEqual([
      ["A a", 1, 0],
      ["A a", 2, 1],
      ["B b", 5, 0],
    ]);
    expect(() => rowsByKey(toNormRows(out, ["sci", "ja", "ord"], ["rank"], []))).not.toThrow();
  });

  it("入力の並びが違っても同じ行の集合には同じ連番が付く（v1・v2 で並びが違っても突き合わせられる）", () => {
    const a = withOrdinal(rows, ["sci", "ja"]);
    const b = withOrdinal([...rows].reverse(), ["sci", "ja"]);
    const key = (r: { sci: string; rank: number; ord: number }) => `${r.sci}|${r.rank}|${r.ord}`;
    expect(new Set(a.map(key))).toEqual(new Set(b.map(key)));
  });

  it("キー列が null/未定義でも落ちない", () => {
    expect(withOrdinal([{ sci: null, ja: "x" }, { ja: "x" }], ["sci", "ja"]).map((r) => r.ord)).toEqual([0, 1]);
  });
});

describe("parseTrendPeriods / redlistGroupParam", () => {
  it("期間 A/B の文字列を数値の組にする。形が違えば例外", () => {
    expect(parseTrendPeriods("2018-2020:2022-2024")).toEqual([
      [2018, 2020],
      [2022, 2024],
    ]);
    expect(() => parseTrendPeriods("2018-2020")).toThrow();
  });
  it("'' は「全分類群」（undefined）", () => {
    expect(redlistGroupParam("")).toBeUndefined();
    expect(redlistGroupParam("鳥類")).toBe("鳥類");
  });
});
