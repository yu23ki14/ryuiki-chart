import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { buildCubeFixture, FX, type CubeFixture } from "./__fixtures__/cube-fixture";
import { daySeries, monthSeries, pivotYearCells, queryCells, rainDaily, rainMonthlyClim, summarize, yearSeries } from "./observation";
import type { CellRow, CellSpec } from "./observation";

let fx: CubeFixture;
beforeEach(() => {
  fx = buildCubeFixture();
});
afterEach(() => {
  fx.db.close();
});

describe("queryCells: scope", () => {
  it("site スコープ: fx_site_a の mean/day 系列（3日分）", async () => {
    const spec: CellSpec = {
      series: [FX.series.ssMean],
      scope: { kind: "site", siteId: FX.sites.a },
      grain: "day",
      stats: ["mean"],
      imputation: "zero",
    };
    const { rows } = await queryCells(fx.db, spec);
    expect(rows).toHaveLength(3);
    expect(rows.every((r) => r.siteId === FX.sites.a)).toBe(true);
    expect(rows.map((r) => r.periodStart)).toEqual(["2024-01-01", "2024-01-02", "2024-01-03"]);
  });

  it("water スコープ: 境川（１）は fx_site_a/b の2地点のみ（sites に無い fx_place_c は除外）", async () => {
    const spec: CellSpec = {
      series: [FX.series.ssMean],
      scope: { kind: "water", municipality: FX.municipality },
      grain: "day",
      stats: ["mean"],
      imputation: "zero",
    };
    const { rows } = await queryCells(fx.db, spec);
    const siteIds = new Set(rows.map((r) => r.siteId));
    expect(siteIds).toEqual(new Set([FX.sites.a]));
  });

  it("all_sites スコープ: sites に無い fx_place_c も含む（site_id は NULL）", async () => {
    const spec: CellSpec = {
      series: [FX.series.ssMean],
      scope: { kind: "all_sites" },
      grain: "day",
      stats: ["mean"],
      imputation: "zero",
    };
    const { rows } = await queryCells(fx.db, spec);
    const placeIds = new Set(rows.map((r) => r.placeId));
    expect(placeIds).toEqual(new Set([FX.places.a, FX.places.c]));
    const cRow = rows.find((r) => r.placeId === FX.places.c)!;
    expect(cRow.siteId).toBeNull();
  });

  it("zone スコープ: ゾーン3は fx_place_a/b/c を含む（sites に無い地点も。b05 の zone lookup は place_source_ref だけを見るため）", async () => {
    const spec: CellSpec = {
      series: [FX.series.ssMean, FX.series.ssPoint],
      scope: { kind: "zone", zone: 3 },
      grain: "day",
      imputation: "zero",
    };
    const { rows } = await queryCells(fx.db, spec);
    const placeIds = new Set(rows.map((r) => r.placeId));
    expect(placeIds).toEqual(new Set([FX.places.a, FX.places.b, FX.places.c]));
  });

  it("places スコープ: 指定した place_id だけ", async () => {
    const spec: CellSpec = {
      series: [FX.series.ssMean],
      scope: { kind: "places", placeIds: [FX.places.a] },
      grain: "day",
      stats: ["mean"],
      imputation: "zero",
    };
    const { rows } = await queryCells(fx.db, spec);
    expect(rows.every((r) => r.placeId === FX.places.a)).toBe(true);
    expect(rows.every((r) => r.siteId === FX.sites.a)).toBe(true);
  });

  it("places スコープ: 空配列は0行", async () => {
    const spec: CellSpec = {
      series: [FX.series.ssMean],
      scope: { kind: "places", placeIds: [] },
      grain: "day",
      imputation: "zero",
    };
    const { rows, truncated } = await queryCells(fx.db, spec);
    expect(rows).toHaveLength(0);
    expect(truncated).toBe(false);
  });
});

describe("queryCells: variableId / series", () => {
  it("variableId 指定は全系列（obsStat: mean と point の両方）を返す（キューブの stat 列は常に mean/min/max/sum で、point という値は現れない）", async () => {
    const spec: CellSpec = {
      variableId: FX.variables.ss,
      scope: { kind: "all_sites" },
      grain: "day",
      imputation: "zero",
    };
    const { rows } = await queryCells(fx.db, spec);
    expect(rows.every((r) => r.stat === "mean")).toBe(true);
    const obsStats = new Set(rows.map((r) => r.series.obsStat));
    expect(obsStats).toEqual(new Set(["mean", "point"]));
  });

  it("series 指定は指定した組だけに絞る", async () => {
    const spec: CellSpec = {
      series: [FX.series.ssPoint],
      scope: { kind: "all_sites" },
      grain: "day",
      imputation: "zero",
    };
    const { rows } = await queryCells(fx.db, spec);
    expect(rows.every((r) => r.series.obsStat === "point")).toBe(true);
    expect(rows).toHaveLength(2);
  });

  it("variableId も series も無いと例外", async () => {
    const spec = { scope: { kind: "all_sites" }, grain: "day", imputation: "zero" } as CellSpec;
    await expect(queryCells(fx.db, spec)).rejects.toThrow(/variableId か series/);
  });
});

describe("queryCells/summarize: variableId + water/places スコープ（バインドパラメータの積み順。Issue #48 PR-1 code-review #1）", () => {
  // `variableId` 指定（WHERE 句）と `water`/`places` スコープ（JOIN 句）を同時に使うと、
  // JOIN 用と WHERE 用のパラメータが場当たりの順で積まれていた場合に SQL 文字列上の
  // `?` の出現順とずれる（`water` は絞り込みが常に偽になり黙って0行、`places` は
  // `json_each(?)` に variableId の文字列が渡って例外になる）。`series` 指定（JOIN 句のみ）
  // では発現しないため、既存テストは全て `series` 指定で書かれていて気づかれていなかった。

  it("queryCells: variableId + water（境川（１）は fx_site_a/b の2地点）", async () => {
    const spec: CellSpec = {
      variableId: FX.variables.ss,
      scope: { kind: "water", municipality: FX.municipality },
      grain: "day",
      stats: ["mean"],
      imputation: "zero",
    };
    const { rows } = await queryCells(fx.db, spec);
    const siteIds = new Set(rows.map((r) => r.siteId));
    expect(siteIds).toEqual(new Set([FX.sites.a, FX.sites.b]));
    expect(rows).toHaveLength(5); // fx_place_a の3日 + fx_place_b の2日
  });

  it("queryCells: variableId + places（指定した place_id だけ、JSON パースエラーにならない）", async () => {
    const spec: CellSpec = {
      variableId: FX.variables.ss,
      scope: { kind: "places", placeIds: [FX.places.a] },
      grain: "day",
      stats: ["mean"],
      imputation: "zero",
    };
    const { rows } = await queryCells(fx.db, spec);
    expect(rows.every((r) => r.placeId === FX.places.a)).toBe(true);
    expect(rows).toHaveLength(3);
  });

  it("summarize month_of_year: variableId + places（fx_place_a/b の日セル5件がすべて1月に集計される）", async () => {
    const spec: CellSpec = {
      variableId: FX.variables.ss,
      scope: { kind: "places", placeIds: [FX.places.a, FX.places.b] },
      grain: "day",
      stats: ["mean"],
      imputation: "zero",
    };
    const { rows } = await summarize(fx.db, spec, "month_of_year");
    expect(rows).toHaveLength(1);
    expect(rows[0].month).toBe(1);
    expect(rows[0].n).toBe(5);
    // fx_place_a の3日目（不検出）は value_zero も NULL なので平均・最小に入らない（Issue #61）。
    expect(rows[0].avg).toBeCloseTo((10 + 8 + 15 + 17) / 4, 6);
    expect(rows[0].min).toBe(8);
    expect(rows[0].max).toBe(17);
  });

  it("summarize zone: variableId + places（fx_place_a/b はゾーン3、nSites=2・n=5）", async () => {
    const spec: CellSpec = {
      variableId: FX.variables.ss,
      scope: { kind: "places", placeIds: [FX.places.a, FX.places.b] },
      grain: "day",
      stats: ["mean"],
      imputation: "zero",
    };
    const { rows } = await summarize(fx.db, spec, "zone");
    const zone3 = rows.filter((r) => r.zone === 3);
    expect(zone3).toHaveLength(1);
    expect(zone3[0].nSites).toBe(2);
    expect(zone3[0].n).toBe(5);
    expect(zone3[0].avg).toBeCloseTo((10 + 8 + 15 + 17) / 4, 6); // 不検出日は value_zero でも除外（Issue #61）
  });

  it("summarize zone_month_of_year: variableId + water（fx_site_a/b、zone=3・month=1）", async () => {
    const spec: CellSpec = {
      variableId: FX.variables.ss,
      scope: { kind: "water", municipality: FX.municipality },
      grain: "day",
      stats: ["mean"],
      imputation: "zero",
    };
    const { rows } = await summarize(fx.db, spec, "zone_month_of_year");
    expect(rows).toHaveLength(1);
    expect(rows[0].zone).toBe(3);
    expect(rows[0].month).toBe(1);
    expect(rows[0].nSites).toBe(2);
    expect(rows[0].n).toBe(5);
  });

  it("summarize zone_month_of_year: imputation='both' は avgZero/avgLod を1回のSQLで返す（Issue #48 PR-2 /simplify #11）", async () => {
    const spec: CellSpec = {
      variableId: FX.variables.ss,
      scope: { kind: "water", municipality: FX.municipality },
      grain: "day",
      imputation: "both",
    };
    const { rows } = await summarize(fx.db, spec, "zone_month_of_year");
    expect(rows).toHaveLength(1);
    expect(rows[0].nSites).toBe(2);
    expect(rows[0].n).toBe(5);
    expect(rows[0].avg).toBeNull();
    expect(rows[0].avgZero).toBeCloseTo((10 + 8 + 15 + 17) / 4, 6); // fx_site_a 3日目は不検出で value_zero も NULL（Issue #61）
    expect(rows[0].avgLod).toBeCloseTo((10 + 6 + 15 + 17) / 4, 6); // fx_site_a 3日目は不検出で無視される
  });

  it("summarize place: variableId + places（fx_place_a の年セル1件）", async () => {
    const spec: CellSpec = {
      variableId: FX.variables.ss,
      scope: { kind: "places", placeIds: [FX.places.a] },
      grain: "year",
      inputGrain: "day",
      imputation: "zero",
    };
    const { rows } = await summarize(fx.db, spec, "place");
    expect(rows).toHaveLength(1);
    expect(rows[0].placeId).toBe(FX.places.a);
    expect(rows[0].siteId).toBe(FX.sites.a);
    expect(rows[0].n).toBe(3);
    expect(rows[0].avg).toBe(9.0); // (10 + 8) / 2。不検出日は value_zero でも除外（Issue #61）
  });

  it("summarize series: variableId + water（fx_site_a/b の3系列組に分かれる）", async () => {
    const spec: CellSpec = {
      variableId: FX.variables.ss,
      scope: { kind: "water", municipality: FX.municipality },
      grain: ["year", "fiscal_year"],
      stats: ["mean"],
      imputation: "zero",
    };
    const { rows } = await summarize(fx.db, spec, "series");
    expect(rows).toHaveLength(3); // a:mean/day, b:point/day, a:mean/fiscal_year
  });
});

describe("queryCells: grain / inputGrain / period", () => {
  it("grain='year' は暦年セル1件（input_grain='day' = v1 の kind daily 相当）", async () => {
    const spec: CellSpec = {
      series: [FX.series.ssMean],
      scope: { kind: "site", siteId: FX.sites.a },
      grain: "year",
      inputGrain: "day",
      imputation: "zero",
    };
    const { rows } = await queryCells(fx.db, spec);
    expect(rows).toHaveLength(1);
    expect(rows[0].periodStart).toBe("2024-01-01");
    expect(rows[0].n).toBe(3);
  });

  it("grain='fiscal_year' + inputGrain='same' は年度セル1件", async () => {
    const spec: CellSpec = {
      series: [FX.series.ssAnnual],
      scope: { kind: "site", siteId: FX.sites.a },
      grain: "fiscal_year",
      inputGrain: "same",
      imputation: "zero",
    };
    const { rows } = await queryCells(fx.db, spec);
    expect(rows).toHaveLength(1);
    expect(rows[0].periodStart).toBe("2024-04-01");
    expect(rows[0].value).toBe(11.0);
  });

  it("period.from/to で日セルを絞れる", async () => {
    const spec: CellSpec = {
      series: [FX.series.ssMean],
      scope: { kind: "site", siteId: FX.sites.a },
      grain: "day",
      period: { from: "2024-01-02", to: "2024-01-02" },
      imputation: "zero",
    };
    const { rows } = await queryCells(fx.db, spec);
    expect(rows).toHaveLength(1);
    expect(rows[0].periodStart).toBe("2024-01-02");
  });
});

describe("queryCells: imputation（value_zero/value_lod、検閲・不検出）", () => {
  it("zero は value_zero を使う（不検出日は NULL。Issue #61 で 0 から変更）", async () => {
    const spec: CellSpec = {
      series: [FX.series.ssMean],
      scope: { kind: "site", siteId: FX.sites.a },
      grain: "day",
      period: { from: "2024-01-03", to: "2024-01-03" },
      imputation: "zero",
    };
    const { rows } = await queryCells(fx.db, spec);
    expect(rows[0].value).toBeNull();
    expect(rows[0].valueZero).toBeNull();
    expect(rows[0].valueLod).toBeNull();
    expect(rows[0].nNotDetected).toBe(1);
  });

  it("lod は value_lod を使う（不検出日は NULL）", async () => {
    const spec: CellSpec = {
      series: [FX.series.ssMean],
      scope: { kind: "site", siteId: FX.sites.a },
      grain: "day",
      period: { from: "2024-01-03", to: "2024-01-03" },
      imputation: "lod",
    };
    const { rows } = await queryCells(fx.db, spec);
    expect(rows[0].value).toBeNull();
  });

  it("検閲セル（2日目）は value_zero と value_lod が異なる", async () => {
    const spec: CellSpec = {
      series: [FX.series.ssMean],
      scope: { kind: "site", siteId: FX.sites.a },
      grain: "day",
      period: { from: "2024-01-02", to: "2024-01-02" },
      imputation: "both",
    };
    const { rows } = await queryCells(fx.db, spec);
    expect(rows[0].valueZero).toBe(8.0);
    expect(rows[0].valueLod).toBe(6.0);
    expect(rows[0].nCensored).toBe(1);
  });
});

describe("summarize: month_of_year（climatology）", () => {
  it("既定（avg）: 水質日セルの月別平均・最小・最大", async () => {
    const spec: CellSpec = {
      series: [FX.series.ssMean],
      scope: { kind: "site", siteId: FX.sites.a },
      grain: "day",
      imputation: "zero",
    };
    const { rows } = await summarize(fx.db, spec, "month_of_year");
    expect(rows).toHaveLength(1);
    expect(rows[0].month).toBe(1);
    expect(rows[0].n).toBe(3);
    expect(rows[0].avg).toBeCloseTo((10 + 8) / 2, 6); // 3日目（不検出）は value_zero も NULL で除外（Issue #61）
    expect(rows[0].min).toBe(8);
    expect(rows[0].max).toBe(10);
  });

  it("sum_per_year（雨量の月別平年値）: SUM(v)/COUNT(DISTINCT 年)", async () => {
    const spec: CellSpec = {
      series: [FX.series.rainSum],
      scope: { kind: "all_sites" },
      grain: "day",
      stats: ["sum"],
      imputation: "zero",
    };
    const { rows } = await summarize(fx.db, spec, "month_of_year", { measure: "sum_per_year" });
    const byMonth = new Map(rows.map((r) => [r.month, r]));
    expect(byMonth.get(1)!.avg).toBeCloseTo(5.0, 6); // (5+0)/1年
    expect(byMonth.get(2)!.avg).toBeCloseTo(12.0, 6); // 12/1年
  });

  it("imputation='both': avgZero/avgLod を1回のSQLで返す（min/max は常に value_lod 基準。Issue #48 PR-2 /simplify #11。zero/lod の2回叩きを撤去）", async () => {
    const spec: CellSpec = {
      series: [FX.series.ssMean],
      scope: { kind: "site", siteId: FX.sites.a },
      grain: "day",
      imputation: "both",
    };
    const { rows } = await summarize(fx.db, spec, "month_of_year");
    expect(rows).toHaveLength(1);
    expect(rows[0].month).toBe(1);
    expect(rows[0].n).toBe(3);
    expect(rows[0].avg).toBeNull();
    expect(rows[0].avgZero).toBeCloseTo((10 + 8) / 2, 6); // 3日目は不検出（value_zero も NULL）で無視される（Issue #61）
    expect(rows[0].avgLod).toBeCloseTo((10 + 6) / 2, 6); // 3日目は不検出（value_lod NULL）で無視される
    expect(rows[0].min).toBe(6);
    expect(rows[0].max).toBe(10);
  });

  it("imputation='both' かつ measure='sum_per_year' は例外（雨量は imputation='zero' 固定で呼ぶため未対応）", async () => {
    const spec: CellSpec = {
      series: [FX.series.rainSum],
      scope: { kind: "all_sites" },
      grain: "day",
      stats: ["sum"],
      imputation: "both",
    };
    await expect(summarize(fx.db, spec, "month_of_year", { measure: "sum_per_year" })).rejects.toThrow(/sum_per_year/);
  });
});

describe("summarize: zone / zone_month_of_year", () => {
  it("zone: mean と point の2系列を混ぜて渡すとゾーン内で合算される（design §3.3「系列の混ぜ方」）", async () => {
    const spec: CellSpec = {
      series: [FX.series.ssMean, FX.series.ssPoint],
      scope: { kind: "all_sites" },
      grain: "day",
      imputation: "zero",
    };
    const { rows } = await summarize(fx.db, spec, "zone");
    // fx_place_a(mean,3日) + fx_place_c(mean,1日) + fx_place_b(point,2日) が
    // 同じゾーン3・grain='day'・input_grain='day'・year=2024 のグループに混ざる。
    const zone3 = rows.filter((r) => r.zone === 3);
    expect(zone3).toHaveLength(1);
    expect(zone3[0].nSites).toBe(3);
    expect(zone3[0].n).toBe(3 + 1 + 2);
  });

  it("imputation='both': avgZero/avgLod と nCensored/nNotDetected を1回のSQLで返す（Issue #48 PR-2 統合後修正A #4。zero/lod の2回叩きを撤去）", async () => {
    const spec: CellSpec = {
      series: [FX.series.ssMean],
      scope: { kind: "all_sites" },
      grain: "day",
      imputation: "both",
    };
    const { rows } = await summarize(fx.db, spec, "zone");
    const zone3 = rows.filter((r) => r.zone === 3);
    expect(zone3).toHaveLength(1);
    expect(zone3[0].n).toBe(3 + 1); // fx_place_a(3日) + fx_place_c(1日)
    expect(zone3[0].avg).toBeNull(); // 'both' のときは avgZero/avgLod を見る
    expect(zone3[0].avgZero).toBeCloseTo((10 + 8 + 5) / 3, 6); // 3日目は value_zero も NULL（不検出。Issue #61）
    expect(zone3[0].avgLod).toBeCloseTo((10 + 6 + 5) / 3, 6); // 3日目は value_lod NULL（不検出）なので AVG から除外
    expect(zone3[0].nCensored).toBe(2); // fx_place_a の2日目（検閲）・3日目（不検出も censored=1 で記録）
    expect(zone3[0].nNotDetected).toBe(1); // fx_place_a の3日目のみ
  });

  it("zone_month_of_year", async () => {
    const spec: CellSpec = {
      series: [FX.series.ssMean],
      scope: { kind: "all_sites" },
      grain: "day",
      stats: ["mean"],
      imputation: "zero",
    };
    const { rows } = await summarize(fx.db, spec, "zone_month_of_year");
    expect(rows).toHaveLength(1);
    expect(rows[0].zone).toBe(3);
    expect(rows[0].month).toBe(1);
    expect(rows[0].nSites).toBe(2); // fx_place_a, fx_place_c
  });

  it("回帰: scope: {kind:'zone'} で呼んでも二重 JOIN の別名が衝突しない（Issue #48 PR-1 統合で発見）", async () => {
    // `buildScopeSql` の "zone" スコープ自身も地点→ゾーンの JOIN（`pr`/`zref`）を
    // 持つため、`summarizeZone`/`summarizeZoneMonth` が同じ別名で独自の JOIN を
    // 足すと "ambiguous column name" で落ちていた（実測。design の全テストは
    // `scope: {kind:'all_sites'}` で呼んでいたため気づかれていなかった）。
    const specYear: CellSpec = {
      series: [FX.series.ssMean],
      scope: { kind: "zone" },
      grain: "day",
      stats: ["mean"],
      imputation: "zero",
    };
    const { rows: yearRows } = await summarize(fx.db, specYear, "zone");
    const zone3 = yearRows.filter((r) => r.zone === 3);
    expect(zone3).toHaveLength(1);
    expect(zone3[0].nSites).toBe(2); // fx_place_a, fx_place_c（site スコープの JOIN で絞られる）

    const specMonth: CellSpec = {
      series: [FX.series.ssMean],
      scope: { kind: "zone" },
      grain: "day",
      stats: ["mean"],
      imputation: "zero",
    };
    const { rows: monthRows } = await summarize(fx.db, specMonth, "zone_month_of_year");
    expect(monthRows.filter((r) => r.zone === 3)).toHaveLength(1);
  });
});

describe("summarize: place（v1 site_var・longitudinal 相当）", () => {
  it("1つの系列・1地点の年セルを AVG する", async () => {
    const spec: CellSpec = {
      series: [FX.series.ssMean],
      scope: { kind: "site", siteId: FX.sites.a },
      grain: "year",
      inputGrain: "day",
      imputation: "zero",
    };
    const { rows } = await summarize(fx.db, spec, "place");
    expect(rows).toHaveLength(1);
    expect(rows[0].placeId).toBe(FX.places.a);
    expect(rows[0].siteId).toBe(FX.sites.a);
    expect(rows[0].n).toBe(3);
    expect(rows[0].yFrom).toBe(2024);
    expect(rows[0].yTo).toBe(2024);
  });
});

describe("summarize: imputation='both' は AVG(v) を単一の value 列で計算する by（place）では例外", () => {
  // zone・zone_month_of_year・month_of_year は avg_zero/avg_lod を1回の SQL で
  // 両方計算する形に対応済み（Issue #48 PR-2 統合後修正A #4・/simplify #11）。
  // place（summarizePlace）と series（summarizeSeries とは別の意味で non-applicable）
  // のうち、place だけが単一の value 式のまま（`v1_projection.sqlite` の
  // `longitudinal_highlight` 相当で avg 列が1つしか無い）なので、今も例外にする。
  it("place", async () => {
    const spec: CellSpec = {
      series: [FX.series.ssMean],
      scope: { kind: "site", siteId: FX.sites.a },
      grain: "year",
      imputation: "both",
    };
    await expect(summarize(fx.db, spec, "place")).rejects.toThrow(/both/);
  });
});

describe("summarize: series（v1 var_catalog の系列版）", () => {
  it("series 自体は AVG(v) を計算しないので imputation='both' でも例外にならない", async () => {
    const spec: CellSpec = {
      variableId: FX.variables.ss,
      scope: { kind: "all_sites" },
      grain: ["year", "fiscal_year"],
      imputation: "both",
    };
    await expect(summarize(fx.db, spec, "series")).resolves.not.toThrow();
  });

  it("mean/day 系列は n_daily に、mean/fiscal_year 系列は n_annual に分かれる", async () => {
    const spec: CellSpec = {
      variableId: FX.variables.ss,
      scope: { kind: "all_sites" },
      grain: ["year", "fiscal_year"],
      stats: ["mean"],
      imputation: "zero",
    };
    const { rows } = await summarize(fx.db, spec, "series");
    const daily = rows.find((r) => r.inputGrain === "day");
    const annual = rows.find((r) => r.inputGrain === "fiscal_year");
    expect(daily).toBeDefined();
    expect(daily!.nDaily).toBeGreaterThan(0);
    expect(daily!.nAnnual).toBe(0);
    expect(annual).toBeDefined();
    expect(annual!.nAnnual).toBeGreaterThan(0);
    expect(annual!.nDaily).toBe(0);
  });
});

describe("queryCells/summarize: limit/truncated（Issue #48 PR-1 §論点B）", () => {
  it("queryCells: 上限ちょうど（3件中 limit=3）は truncated=false で全件返す", async () => {
    const spec: CellSpec = {
      series: [FX.series.ssMean],
      scope: { kind: "site", siteId: FX.sites.a },
      grain: "day",
      stats: ["mean"],
      imputation: "zero",
      limit: 3,
    };
    const { rows, truncated } = await queryCells(fx.db, spec);
    expect(rows).toHaveLength(3);
    expect(truncated).toBe(false);
  });

  it("queryCells: 上限超過（3件中 limit=2）は先頭2件だけ返し truncated=true", async () => {
    const spec: CellSpec = {
      series: [FX.series.ssMean],
      scope: { kind: "site", siteId: FX.sites.a },
      grain: "day",
      stats: ["mean"],
      imputation: "zero",
      limit: 2,
    };
    const { rows, truncated } = await queryCells(fx.db, spec);
    expect(rows).toHaveLength(2);
    expect(rows.map((r) => r.periodStart)).toEqual(["2024-01-01", "2024-01-02"]);
    expect(truncated).toBe(true);
  });

  it("queryCells: limit を省略すると DEFAULT_CELL_LIMIT が使われ、フィクスチャの行数では truncated=false", async () => {
    const spec: CellSpec = {
      series: [FX.series.ssMean],
      scope: { kind: "site", siteId: FX.sites.a },
      grain: "day",
      stats: ["mean"],
      imputation: "zero",
    };
    const { rows, truncated } = await queryCells(fx.db, spec);
    expect(rows).toHaveLength(3);
    expect(truncated).toBe(false);
  });

  it("summarize(by:'series'): 上限ちょうど（3件中 limit=3）は truncated=false", async () => {
    const spec: CellSpec = {
      variableId: FX.variables.ss,
      scope: { kind: "water", municipality: FX.municipality },
      grain: ["year", "fiscal_year"],
      stats: ["mean"],
      imputation: "zero",
      limit: 3,
    };
    const { rows, truncated } = await summarize(fx.db, spec, "series");
    expect(rows).toHaveLength(3);
    expect(truncated).toBe(false);
  });

  it("summarize(by:'series'): 上限超過（3件中 limit=2）は先頭2件だけ返し truncated=true", async () => {
    const spec: CellSpec = {
      variableId: FX.variables.ss,
      scope: { kind: "water", municipality: FX.municipality },
      grain: ["year", "fiscal_year"],
      stats: ["mean"],
      imputation: "zero",
      limit: 2,
    };
    const { rows, truncated } = await summarize(fx.db, spec, "series");
    expect(rows).toHaveLength(2);
    expect(truncated).toBe(true);
  });
});

describe("yearSeries（PR-2 §2.1。representativeSeries + queryCells のピボット）", () => {
  it("basis='day'（既定）: fx_site_a の暦年セル1件（mean/min/max をピボット、n/n_censored/unitId は1つ）", async () => {
    const { rows, truncated } = await yearSeries(fx.db, {
      variableId: FX.variables.ss,
      scope: { kind: "site", siteId: FX.sites.a },
      imputation: "zero",
    });
    expect(truncated).toBe(false);
    expect(rows).toHaveLength(1);
    const r = rows[0];
    expect(r.grain).toBe("year");
    expect(r.periodStart).toBe("2024-01-01");
    expect(r.year).toBe(2024);
    expect(r.n).toBe(3);
    expect(r.nCensored).toBe(2);
    expect(r.unitId).toBe(FX.units.mgPerL);
    expect(r.value.mean).toBeCloseTo(9.0, 6); // value_zero（不検出日は除外。Issue #61）
    expect(r.valueZero.mean).toBeCloseTo(9.0, 6);
    expect(r.valueLod.mean).toBeCloseTo(8.0, 6);
  });

  it("basis='day' の既定は representativeSeries を basisOf の優先順位（day 優先）で絞る: water スコープは fx_site_a(mean/day)・fx_site_b(point/day) の2件になる", async () => {
    const { rows } = await yearSeries(fx.db, {
      variableId: FX.variables.ss,
      scope: { kind: "water", municipality: FX.municipality },
      imputation: "zero",
    });
    const siteIds = rows.map((r) => r.siteId).sort();
    expect(siteIds).toEqual([FX.sites.a, FX.sites.b].sort());
  });

  it("basis='fiscal_year': fx_site_a の年度セル1件", async () => {
    const { rows } = await yearSeries(fx.db, {
      variableId: FX.variables.ss,
      basis: "fiscal_year",
      scope: { kind: "site", siteId: FX.sites.a },
      imputation: "zero",
    });
    expect(rows).toHaveLength(1);
    expect(rows[0].grain).toBe("fiscal_year");
    expect(rows[0].periodStart).toBe("2024-04-01");
    expect(rows[0].value.mean).toBeCloseTo(11.0, 6);
  });

  it("imputation='both': value は3つとも null、valueZero/valueLod だけ埋まる", async () => {
    const { rows } = await yearSeries(fx.db, {
      variableId: FX.variables.ss,
      scope: { kind: "site", siteId: FX.sites.a },
      imputation: "both",
    });
    expect(rows[0].value).toEqual({ mean: null, min: null, max: null });
    expect(rows[0].valueZero.mean).toBeCloseTo(9.0, 6);
    expect(rows[0].valueLod.mean).toBeCloseTo(8.0, 6);
  });

  it("basis はセルの性質: 該当するセルが無ければ0行（例外にしない。Issue #48 PR-2 統合後修正A #1）", async () => {
    // water.ss は fiscal_year の登録系列があるが、grain='year'・input_grain='year'
    // （basis='year'）のセルはフィクスチャに無い。系列自体は存在する（representativeSeries
    // が空にならない）ので、`variableId` の誤りとは区別され、単に0行になる——basis の
    // 有無は登録ではなく実際のセルから決まる、という設計どおり。
    const { rows } = await yearSeries(fx.db, {
      variableId: FX.variables.ss,
      basis: "year",
      scope: { kind: "site", siteId: FX.sites.a },
      imputation: "zero",
    });
    expect(rows).toHaveLength(0);
  });

  it("存在しない variableId/stat の組は例外（representativeSeriesOrThrow）", async () => {
    await expect(
      yearSeries(fx.db, {
        variableId: "common:variable:no.such.variable",
        scope: { kind: "site", siteId: FX.sites.a },
        imputation: "zero",
      }),
    ).rejects.toThrow(/該当する系列が無い/);
  });

  it("Issue #48 PR-2 統合後修正A #1: value_grain='day' の系列内に input_grain='fiscal_year' のセルがある地点でも basis='fiscal_year' で出る（実測: 厚木系中津川 BOD）", async () => {
    const { rows } = await yearSeries(fx.db, {
      variableId: FX.variables.bod,
      basis: "fiscal_year",
      scope: { kind: "site", siteId: FX.sites.a },
      imputation: "zero",
    });
    expect(rows).toHaveLength(1);
    expect(rows[0].grain).toBe("fiscal_year");
    expect(rows[0].periodStart).toBe("2023-04-01");
    expect(rows[0].value.mean).toBeCloseTo(3.0, 6);
  });

  it("stat に非代表統計量を渡すとその系列だけで問い合わせる（BOD 75%値 = p75/fiscal_year、実データ）", async () => {
    // フィクスチャに BOD 75%値 のセルは無いので0行になるが、例外にならないこと
    // （`representativeSeries`/`seriesForBasis` が正しく解決できることの確認）。
    const { rows } = await yearSeries(fx.db, {
      variableId: FX.variables.bod,
      stat: "p75",
      basis: "fiscal_year",
      scope: { kind: "site", siteId: FX.sites.a },
      imputation: "zero",
    });
    expect(rows).toHaveLength(0);
  });
});

describe("pivotYearCells（Issue #48 PR-2 code-review #3: キーに系列を含め、代表系列が同居したら例外）", () => {
  function cell(overrides: Partial<CellRow>): CellRow {
    return {
      placeId: FX.places.a,
      siteId: FX.sites.a,
      series: FX.series.ssMean,
      inputGrain: "day",
      grain: "year",
      periodStart: "2024-01-01",
      periodEnd: "2024-12-31",
      stat: "mean",
      value: 1,
      valueZero: 1,
      valueLod: 1,
      n: 10,
      nCensored: 0,
      nNotDetected: 0,
      nPlaces: 1,
      ...overrides,
    };
  }

  it("同じ系列の mean/min/max は1つの YearPoint にピボットされる", () => {
    const rows = pivotYearCells([
      cell({ stat: "mean", value: 5 }),
      cell({ stat: "min", value: 1 }),
      cell({ stat: "max", value: 9 }),
    ]);
    expect(rows).toHaveLength(1);
    expect(rows[0].value).toEqual({ mean: 5, min: 1, max: 9 });
  });

  it("別の地点・別の期間の系列は別の YearPoint（衝突しない）", () => {
    const rows = pivotYearCells([
      cell({ placeId: FX.places.a, periodStart: "2024-01-01" }),
      cell({ placeId: FX.places.b, periodStart: "2024-01-01" }),
      cell({ placeId: FX.places.a, periodStart: "2025-01-01" }),
    ]);
    expect(rows).toHaveLength(3);
  });

  it("同じ地点・期間・grain に2つ以上の代表系列が同居すると例外にする（実測では0件の不変条件。黙って選ばない）", () => {
    const rows = [
      cell({ series: FX.series.ssMean, stat: "mean", value: 5 }),
      cell({ series: FX.series.ssPoint, stat: "mean", value: 7 }),
    ];
    expect(() => pivotYearCells(rows)).toThrow(/複数の代表系列/);
  });
});

describe("monthSeries / daySeries（basis='day' の変数だけに対応）", () => {
  it("monthSeries: fx_site_a の月セル1件", async () => {
    const { rows } = await monthSeries(fx.db, {
      variableId: FX.variables.ss,
      scope: { kind: "site", siteId: FX.sites.a },
      imputation: "zero",
    });
    expect(rows).toHaveLength(1);
    expect(rows[0].periodStart).toBe("2024-01-01");
    expect(rows[0].value).toBeCloseTo(9.0, 6);
    expect(rows[0].n).toBe(3);
    expect(rows[0].nCensored).toBe(2);
  });

  it("daySeries: fx_site_a の日セル3件（imputation='lod' は3日目が null）", async () => {
    const { rows } = await daySeries(fx.db, {
      variableId: FX.variables.ss,
      scope: { kind: "site", siteId: FX.sites.a },
      imputation: "lod",
    });
    expect(rows).toHaveLength(3);
    expect(rows.map((r) => r.periodStart)).toEqual(["2024-01-01", "2024-01-02", "2024-01-03"]);
    expect(rows[2].value).toBeNull(); // 不検出日（value_lod NULL）
  });

  it("basis='day' でない変数（land.max_subsidence=year）は monthSeries/daySeries どちらも例外", async () => {
    const opt = { variableId: "common:variable:land.max_subsidence", scope: { kind: "all_sites" } as const, imputation: "zero" as const };
    await expect(monthSeries(fx.db, opt)).rejects.toThrow(/basis='day'/);
    await expect(daySeries(fx.db, opt)).rejects.toThrow(/basis='day'/);
  });
});

describe("rainDaily / rainMonthlyClim（RAIN、/10 しない）", () => {
  it("rainDaily: フィクスチャの3日分をそのままの値で返す（v1 の /10 はしない）", async () => {
    const { rows } = await rainDaily(fx.db);
    expect(rows).toHaveLength(3);
    const byDay = new Map(rows.map((r) => [r.periodStart, r]));
    expect(byDay.get("2024-01-01")!.value).toBeCloseTo(5.0, 6);
    expect(byDay.get("2024-02-15")!.value).toBeCloseTo(12.0, 6);
  });

  it("rainDaily: period で絞れる", async () => {
    const { rows } = await rainDaily(fx.db, { period: { from: "2024-02-01" } });
    expect(rows).toHaveLength(1);
    expect(rows[0].periodStart).toBe("2024-02-15");
  });

  it("rainMonthlyClim: SUM(v)/COUNT(DISTINCT 年) の月別平年値", async () => {
    const { rows } = await rainMonthlyClim(fx.db);
    const byMonth = new Map(rows.map((r) => [r.month, r]));
    expect(byMonth.get(1)!.avg).toBeCloseTo(5.0, 6); // (5+0)/1年
    expect(byMonth.get(2)!.avg).toBeCloseTo(12.0, 6); // 12/1年
  });
});
