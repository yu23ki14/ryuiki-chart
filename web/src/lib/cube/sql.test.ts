import { describe, expect, it } from "vitest";
import { MAX_ID_LIST } from "./db";
import { seriesFilterSql } from "./sql";
import type { SeriesKey } from "./series";

function series(n: number): SeriesKey[] {
  return Array.from({ length: n }, (_, i) => ({
    variableId: `common:variable:v${i}`,
    obsStat: "mean",
    unitId: null,
    valueGrain: "day",
  }));
}

describe("seriesFilterSql", () => {
  it("series が無い/空なら undefined", () => {
    expect(seriesFilterSql(undefined)).toBeUndefined();
    expect(seriesFilterSql([])).toBeUndefined();
  });

  it("variable_id の前段フィルタ + 系列キーの JOIN を返す", () => {
    const f = seriesFilterSql(series(2), "obs")!;
    expect(f.joins).toHaveLength(2);
    expect(f.joins[0]).toContain("obs.variable_id");
    expect(f.joins[1]).toContain("obs.value_grain");
    expect(f.params).toHaveLength(2);
  });

  it(`series が上限（${MAX_ID_LIST}）を超えると例外`, () => {
    expect(() => seriesFilterSql(series(MAX_ID_LIST + 1))).toThrow(/上限/);
  });

  it(`series がちょうど上限（${MAX_ID_LIST}）なら例外にならない`, () => {
    expect(() => seriesFilterSql(series(MAX_ID_LIST))).not.toThrow();
  });
});
