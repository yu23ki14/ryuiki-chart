import { describe, expect, it } from "vitest";
import { keyString, rowsByKey, toNormRows } from "./normalize";

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
