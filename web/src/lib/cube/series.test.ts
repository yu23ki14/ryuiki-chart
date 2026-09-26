import { describe, expect, it } from "vitest";
import { isSynthetic, labelYear, seriesForAlias, seriesForVariable, seriesInfo, seriesKeySql, seriesKeyString } from "./series";

describe("seriesKeyString", () => {
  it("b05 の _AKEY_EXPR と同じ連結順・NULL の扱い（variable_id|value_grain|obs_stat|unit_id）", () => {
    expect(seriesKeyString({ variableId: "common:variable:water.bod", obsStat: "mean", unitId: null, valueGrain: "day" })).toBe(
      "common:variable:water.bod|day|mean|",
    );
    expect(seriesKeyString({ variableId: "common:variable:water.ph", obsStat: null, unitId: "common:unit:dimensionless", valueGrain: "" })).toBe(
      "common:variable:water.ph|||common:unit:dimensionless",
    );
  });
});

describe("seriesKeySql", () => {
  it("引数で受けたエイリアスを使い、c./d. を使わない（assertD1Compatible と衝突しない）", () => {
    const sql = seriesKeySql("obs");
    expect(sql).toContain("obs.variable_id");
    expect(sql).not.toMatch(/\b[cd]\.[A-Za-z_]/);
  });
});

describe("seriesForAlias（実データ: registry/variable_alias.csv 由来の generated.ts）", () => {
  it("pH は3出典が2つの組（tuple）にまとまる（mean/day と point/day）", () => {
    const series = seriesForAlias("measurements", "pH");
    expect(series.length).toBe(2);

    const meanDay = series.find((s) => s.obsStat === "mean");
    expect(meanDay).toBeDefined();
    expect(meanDay!.sourceIds).toEqual(["atsugi_river_water_quality"]);
    expect(isSynthetic(meanDay!)).toBe(false);

    const pointDay = series.find((s) => s.obsStat === "point");
    expect(pointDay).toBeDefined();
    // 合成（source_id NULL）と env_kousui_sample_kanagawa が同じ組を共有する
    expect(pointDay!.sourceIds.sort()).toEqual([null, "env_kousui_sample_kanagawa"].sort());
    expect(isSynthetic(pointDay!)).toBe(true);
  });

  it("存在しない (dataset, alias) は空配列", () => {
    expect(seriesForAlias("measurements", "存在しないやつ")).toEqual([]);
  });
});

describe("seriesForVariable", () => {
  it("representative（既定）は mean/point/NULL の obsStat だけを返す", () => {
    const series = seriesForVariable("common:variable:water.bod", { dataset: "measurements" });
    expect(series.length).toBeGreaterThan(0);
    for (const s of series) {
      expect([null, "mean", "point"]).toContain(s.obsStat);
    }
    // p75 が代表系列から除外されていること（env_kousui_annual_kanagawa の BOD 75%値）
    expect(series.some((s) => s.obsStat === "p75")).toBe(false);
  });

  it('obsStats: "all" は p75 等も含める', () => {
    const all = seriesForVariable("common:variable:water.bod", { dataset: "measurements", obsStats: "all" });
    expect(all.some((s) => s.obsStat === "p75")).toBe(true);
  });

  it("dataset を指定しないと sensor_timeseries 側も混ざりうる（フィルタ無し）", () => {
    const withoutDataset = seriesForVariable("common:variable:water.bod");
    const withDataset = seriesForVariable("common:variable:water.bod", { dataset: "measurements" });
    expect(withoutDataset.length).toBeGreaterThanOrEqual(withDataset.length);
  });
});

describe("seriesInfo（逆引き）", () => {
  it("組から SeriesInfo を引ける", () => {
    const info = seriesInfo({ variableId: "common:variable:water.ph", obsStat: "mean", unitId: "common:unit:dimensionless", valueGrain: "day" });
    expect(info).toBeDefined();
    expect(info!.dataset).toBe("measurements");
    expect(info!.aliases).toContain("pH");
  });

  it("存在しない組は undefined", () => {
    expect(seriesInfo({ variableId: "no:such:variable", obsStat: null, unitId: null, valueGrain: "" })).toBeUndefined();
  });
});

describe("labelYear", () => {
  it("暦年は先頭4桁、fiscal_year も period_start の先頭4桁（年度の始まりの年）", () => {
    expect(labelYear("2024-01-01")).toBe(2024);
    expect(labelYear("2024-04-01")).toBe(2024);
  });
});
