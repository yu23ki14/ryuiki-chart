import { describe, expect, it } from "vitest";
import {
  basisOf,
  basisOfCell,
  grainsForBasis,
  isRepresentativeObsStat,
  labelYear,
  representativeSeries,
  seriesForAlias,
  seriesForVariable,
  seriesInfo,
  seriesKeySql,
  seriesKeyString,
  withTheme,
  yearCellFilterForBasis,
  type SeriesKey,
} from "./series";

describe("isRepresentativeObsStat（Issue #48 PR-2 code-review #7: catalog.ts の非代表 stats 集計が使う判定）", () => {
  it("NULL・mean・point は代表統計量", () => {
    expect(isRepresentativeObsStat(null)).toBe(true);
    expect(isRepresentativeObsStat("mean")).toBe(true);
    expect(isRepresentativeObsStat("point")).toBe(true);
  });
  it("p75/p90/max/min 等は非代表", () => {
    expect(isRepresentativeObsStat("p75")).toBe(false);
    expect(isRepresentativeObsStat("p90")).toBe(false);
    expect(isRepresentativeObsStat("max")).toBe(false);
    expect(isRepresentativeObsStat("min")).toBe(false);
  });
});

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
  it("pH は4出典が2つの組（tuple）にまとまる（mean/day と point/day）", () => {
    const series = seriesForAlias("measurements", "pH");
    expect(series.length).toBe(2);

    const meanDay = series.find((s) => s.obsStat === "mean");
    expect(meanDay).toBeDefined();
    expect(meanDay!.sourceIds).toEqual(["atsugi_river_water_quality"]);

    const pointDay = series.find((s) => s.obsStat === "point");
    expect(pointDay).toBeDefined();
    // 合成（source_id NULL）と env_kousui_sample_kanagawa が同じ組を共有する
    // （PR-2 で b03 が合成データを除いた後の observation_agg には出典未記録の行は
    // 現れないが、`variable_alias`〔registry〕の宣言としては両方載っている——
    // `series.ts` の `isSynthetic` は D2 で撤去済み）。
    // 奄美の追加で env_kousui_sample_amami も同じ組に入った（組の数は変わらない）。
    expect(pointDay!.sourceIds.sort()).toEqual([null, "env_kousui_sample_amami", "env_kousui_sample_kanagawa"].sort());
  });

  it("存在しない (dataset, alias) は空配列", () => {
    expect(seriesForAlias("measurements", "存在しないやつ")).toEqual([]);
  });
});

describe("sourceIds は重複排除する（Issue #48 PR-1 code-review #2）", () => {
  // `雪_最深 積雪`/`雪_最深積雪`（空白の有無違いの2 alias）は同じ組
  // （weather.snow_depth_max・max/month）にまとまり、どちらも jma_monthly_kanagawa
  // という同じ出典。重複排除しないと sourceIds が [jma_monthly_kanagawa, jma_monthly_kanagawa]
  // になり、`envelope.ts` の `resolveProvenance` が同じ出典の n_rows を2倍に数えてしまう。
  const snowDepthMax: SeriesKey = {
    variableId: "common:variable:weather.snow_depth_max",
    obsStat: "max",
    unitId: "common:unit:cm",
    valueGrain: "month",
  };

  it("seriesInfo: 同じ出典の alias が2つあっても sourceIds は1件（元の順序は保つ）", () => {
    const info = seriesInfo(snowDepthMax);
    expect(info).toBeDefined();
    expect(info!.aliases).toEqual(["雪_最深 積雪", "雪_最深積雪"]);
    // 奄美の追加で jma_monthly_amami が加わる。各出典は1回ずつ。
    expect(info!.sourceIds).toEqual(["jma_monthly_kanagawa", "jma_monthly_amami"]);
  });

  it("seriesForVariable 経由でも同じ組は sourceIds が重複しない", () => {
    const series = seriesForVariable("common:variable:weather.snow_depth_max", { obsStats: "all" });
    const match = series.find((s) => s.obsStat === "max" && s.valueGrain === "month");
    expect(match).toBeDefined();
    expect(match!.sourceIds).toEqual(["jma_monthly_kanagawa", "jma_monthly_amami"]);
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

describe("representativeSeries（PR-2 §2.1、決定8/9）", () => {
  it("既定 stat='representative' は obsStat ∈ {mean, point, NULL} だけ（p75 等を含まない）", () => {
    const series = representativeSeries("common:variable:water.bod");
    expect(series.length).toBeGreaterThan(0);
    for (const s of series) expect([null, "mean", "point"]).toContain(s.obsStat);
    expect(series.some((s) => s.obsStat === "p75")).toBe(false);
  });

  it("BOD の代表系列は day と fiscal_year の両方にまたがる（実データ: mean/day・point/day・mean/fiscal_year）", () => {
    const series = representativeSeries("common:variable:water.bod");
    const valueGrains = new Set(series.map((s) => s.valueGrain));
    expect(valueGrains.has("day")).toBe(true);
    expect(valueGrains.has("fiscal_year")).toBe(true);
  });

  it("stat に具体的な obsStat を渡すとその組だけに絞る（BOD 75%値 = p75/fiscal_year）", () => {
    const series = representativeSeries("common:variable:water.bod", "measurements", "p75");
    expect(series.length).toBeGreaterThan(0);
    for (const s of series) expect(s.obsStat).toBe("p75");
  });

  it("フォールバック（危険#3）: land.max_subsidence は代表統計量（mean/point/NULL）が無いので全系列にフォールバックする", () => {
    const series = representativeSeries("common:variable:land.max_subsidence");
    expect(series.length).toBeGreaterThan(0);
    expect(series.some((s) => s.obsStat === "max")).toBe(true);
  });

  it("存在しない variableId は空配列のまま（フォールバックしても何も無い）", () => {
    expect(representativeSeries("common:variable:no.such.variable")).toEqual([]);
  });
});

describe("basisOf / grainsForBasis", () => {
  it("day を含む集合は basis='day'、grains=[year,month,day]", () => {
    const series: SeriesKey[] = [{ variableId: "x", obsStat: "mean", unitId: null, valueGrain: "day" }];
    expect(basisOf(series)).toEqual({ basis: "day", grains: ["year", "month", "day"] });
  });

  it("day と fiscal_year が混ざると day を優先する", () => {
    const series: SeriesKey[] = [
      { variableId: "x", obsStat: "mean", unitId: null, valueGrain: "fiscal_year" },
      { variableId: "x", obsStat: "point", unitId: null, valueGrain: "day" },
    ];
    expect(basisOf(series).basis).toBe("day");
  });

  it("fiscal_year のみは basis='fiscal_year'、grains=[fiscal_year]", () => {
    const series: SeriesKey[] = [{ variableId: "x", obsStat: "mean", unitId: null, valueGrain: "fiscal_year" }];
    expect(basisOf(series)).toEqual({ basis: "fiscal_year", grains: ["fiscal_year"] });
  });

  it("year のみ（地盤沈下等）は basis='year'、grains=[year]", () => {
    const series: SeriesKey[] = [{ variableId: "x", obsStat: "max", unitId: null, valueGrain: "year" }];
    expect(basisOf(series)).toEqual({ basis: "year", grains: ["year"] });
  });

  it("空配列は例外", () => {
    expect(() => basisOf([])).toThrow(/空/);
  });

  it("grainsForBasis: basisOf と同じ表", () => {
    expect(grainsForBasis("day")).toEqual(["year", "month", "day"]);
    expect(grainsForBasis("fiscal_year")).toEqual(["fiscal_year"]);
    expect(grainsForBasis("year")).toEqual(["year"]);
  });

});

describe("basisOfCell（セルの grain/input_grain から basis を決める。Issue #48 PR-2 統合後修正A #1）", () => {
  it("input_grain='day' は grain によらず basis='day'", () => {
    expect(basisOfCell({ grain: "year", inputGrain: "day" })).toBe("day");
    expect(basisOfCell({ grain: "month", inputGrain: "day" })).toBe("day");
  });

  it("value_grain='day' として登録された系列でも、input_grain='fiscal_year' のセルは basis='fiscal_year'（実測: 中津川 BOD）", () => {
    expect(basisOfCell({ grain: "fiscal_year", inputGrain: "fiscal_year" })).toBe("fiscal_year");
  });

  it("grain='year' かつ input_grain='year'（地盤沈下等の直接報告）は basis='year'", () => {
    expect(basisOfCell({ grain: "year", inputGrain: "year" })).toBe("year");
  });
});

describe("yearCellFilterForBasis（basisOfCell の逆写像。旧 seriesForBasis/inputGrainForBasis/cellGrainForBasis の統合）", () => {
  it("day: (grain=year, inputGrain=day)", () => {
    expect(yearCellFilterForBasis("day")).toEqual({ grain: "year", inputGrain: "day" });
  });

  it("fiscal_year: (grain=fiscal_year, inputGrain=same)", () => {
    expect(yearCellFilterForBasis("fiscal_year")).toEqual({ grain: "fiscal_year", inputGrain: "same" });
  });

  it("year: (grain=year, inputGrain=same)", () => {
    expect(yearCellFilterForBasis("year")).toEqual({ grain: "year", inputGrain: "same" });
  });

  it("basisOfCell と往復する（day/fiscal_year/year）", () => {
    for (const basis of ["day", "fiscal_year", "year"] as const) {
      const { grain, inputGrain } = yearCellFilterForBasis(basis);
      expect(basisOfCell({ grain, inputGrain: inputGrain === "same" ? grain : inputGrain })).toBe(basis);
    }
  });
});

describe("withTheme", () => {
  it("variable.theme を足す（BOD は water）", () => {
    const info = seriesInfo({ variableId: "common:variable:water.bod", obsStat: "mean", unitId: "common:unit:mg_per_l", valueGrain: "day" });
    expect(info).toBeDefined();
    expect(withTheme(info!).theme).toBe("water");
  });

  it("variable が見つからなければ theme は null", () => {
    const fake = { variableId: "common:variable:no.such.variable", obsStat: null, unitId: null, valueGrain: "", dataset: "measurements", sourceIds: [], sourceRefs: [], aliases: [] };
    expect(withTheme(fake).theme).toBeNull();
  });
});
