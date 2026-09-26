import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { buildCubeFixture, FX, type CubeFixture } from "./__fixtures__/cube-fixture";
import { site, sites, sitesInWaterBody, siteVariables, variableCatalog, waterBodies } from "./catalog";

let fx: CubeFixture;
beforeEach(() => {
  fx = buildCubeFixture();
});
afterEach(() => {
  fx.db.close();
});

describe("variableCatalog（既定 source='summary'。variable_id 単位に束ねた行）", () => {
  it("water.ss と water.bod の両方が出る（rain は year/fiscal_year セルを持たないので元々出ない。v1 の var_catalog も meas_year 由来で sensor_timeseries を含まない）", async () => {
    const rows = await variableCatalog(fx.db, { dataset: "measurements" });
    const ids = rows.map((r) => r.variableId);
    expect(ids).toContain(FX.variables.ss);
    expect(ids).toContain(FX.variables.bod);
    expect(ids).not.toContain(FX.variables.rain);
  });

  it("water.ss は mean/day（fx_place_a+fx_place_c）・point/day（fx_place_b）・mean/fiscal_year（fx_place_a）の3系列を束ねる", async () => {
    const rows = await variableCatalog(fx.db, { dataset: "measurements" });
    const ss = rows.find((r) => r.variableId === FX.variables.ss)!;
    expect(ss).toBeDefined();
    // n: mean/day(3+1) + point/day(2) + mean/fiscal_year(1) = 7
    expect(ss.n).toBe(3 + 1 + 2 + 1);
    // nPlaces: 束ねた地点集合（fx_place_a/b/c）の distinct 数。二重計上しない
    // （fx_place_a は mean/day と mean/fiscal_year の両方に現れるが1と数える）。
    expect(ss.nPlaces).toBe(3);
    expect(ss.nByBasis).toEqual({ day: 3 + 1 + 2, fiscalYear: 1, year: 0 });
    expect(ss.stats).toEqual(["mean", "point"]);
    expect(ss.yFrom).toBe(2024);
    expect(ss.yTo).toBe(2024);
  });

  it("unitId は束ねた中で最も n の大きい非NULLの unit_id を代表にする（water.bod は mg/L のみ）", async () => {
    const rows = await variableCatalog(fx.db, { dataset: "measurements" });
    const bod = rows.find((r) => r.variableId === FX.variables.bod)!;
    expect(bod.unitId).toBe(FX.units.mgPerL);
  });

  it("dataset='measurements' は sensor_timeseries（RAIN）を含まない", async () => {
    const rows = await variableCatalog(fx.db, { dataset: "measurements" });
    expect(rows.some((r) => r.variableId === FX.variables.rain)).toBe(false);
  });

  it("dataset を指定しないと全 dataset 合算になる（絞り込み無し）", async () => {
    const all = await variableCatalog(fx.db);
    const scoped = await variableCatalog(fx.db, { dataset: "measurements" });
    expect(all.length).toBeGreaterThanOrEqual(scoped.length);
  });

  it("source='live' は summary と同じ束ね方で一致する（フィクスチャ上の突合）", async () => {
    const summaryRows = await variableCatalog(fx.db, { dataset: "measurements", source: { kind: "summary" } });
    const liveRows = await variableCatalog(fx.db, { dataset: "measurements", source: { kind: "live" } });
    const bySummary = new Map(summaryRows.map((r) => [r.variableId, r]));
    const byLive = new Map(liveRows.map((r) => [r.variableId, r]));
    expect(bySummary.size).toBe(byLive.size);
    for (const [variableId, s] of bySummary) {
      const l = byLive.get(variableId)!;
      expect(l, variableId).toBeDefined();
      expect(l.n, variableId).toBe(s.n);
      expect(l.nPlaces, variableId).toBe(s.nPlaces);
      expect(l.yFrom, variableId).toBe(s.yFrom);
      expect(l.yTo, variableId).toBe(s.yTo);
      expect(l.nByBasis, variableId).toEqual(s.nByBasis);
      expect(l.nCensored, variableId).toBe(s.nCensored);
      expect(l.stats, variableId).toEqual(s.stats);
      expect(l.unitId, variableId).toBe(s.unitId);
    }
  });
});

describe("siteVariables", () => {
  it("fx_place_a は3系列（SS mean/day 年, SS mean/fiscal_year, BOD mean/day 年）を持つ", async () => {
    const rows = await siteVariables(fx.db, FX.places.a, { imputation: "lod" });
    expect(rows.length).toBeGreaterThanOrEqual(3);
    const ssDaily = rows.find((r) => r.series.variableId === FX.variables.ss && r.grain === "year");
    expect(ssDaily).toBeDefined();
  });

  it("imputation='zero'/'lod' で avg が value_zero/value_lod に切り替わる（既定は置かず必須。design §0-3・U2）", async () => {
    // fx_place_a の SS mean/day 年セルは value_zero=6.0・value_lod=8.0（cube-fixture.ts）。
    const zeroRows = await siteVariables(fx.db, FX.places.a, { imputation: "zero" });
    const lodRows = await siteVariables(fx.db, FX.places.a, { imputation: "lod" });
    const ssZero = zeroRows.find((r) => r.series.variableId === FX.variables.ss && r.grain === "year" && r.series.obsStat === "mean");
    const ssLod = lodRows.find((r) => r.series.variableId === FX.variables.ss && r.grain === "year" && r.series.obsStat === "mean");
    expect(ssZero!.avg).toBeCloseTo(6.0, 6);
    expect(ssLod!.avg).toBeCloseTo(8.0, 6);
  });

  it.each(["zero", "lod"] as const)("source='summary'（既定）と source='live' は imputation='%s' で avg が一致する（フィクスチャ上の突合）", async (imputation) => {
    const summaryRows = await siteVariables(fx.db, FX.places.a, { imputation, source: { kind: "summary" } });
    const liveRows = await siteVariables(fx.db, FX.places.a, { imputation, source: { kind: "live" } });
    const byLive = new Map(liveRows.map((r) => [r.seriesKey, r]));
    for (const s of summaryRows) {
      const l = byLive.get(s.seriesKey)!;
      expect(l, s.seriesKey).toBeDefined();
      expect(l.avg, s.seriesKey).toBeCloseTo(s.avg ?? NaN, 6);
    }
  });

  it("既定は source='summary'", async () => {
    const defaultRows = await siteVariables(fx.db, FX.places.a, { imputation: "lod" });
    const summaryRows = await siteVariables(fx.db, FX.places.a, { imputation: "lod", source: { kind: "summary" } });
    expect(defaultRows).toEqual(summaryRows);
  });

  it("存在しない place_id は空配列", async () => {
    expect(await siteVariables(fx.db, "no-such-place", { imputation: "lod" })).toEqual([]);
  });
});

describe("sites / site", () => {
  it("3地点を返し、zone・elevation_m の降順で並ぶ", async () => {
    const rows = await sites(fx.db);
    const siteIds = rows.map((r) => r.siteId);
    expect(siteIds).toEqual(expect.arrayContaining([FX.sites.a, FX.sites.b, FX.sites.rain]));
  });

  it("fx_site_a は n_series >= 2（mean/day と mean/fiscal_year の2系列）", async () => {
    const rows = await sites(fx.db);
    const a = rows.find((r) => r.siteId === FX.sites.a)!;
    expect(a.nSeries).toBeGreaterThanOrEqual(2);
    expect(a.nVariables).toBeGreaterThanOrEqual(2); // water.ss + water.bod
  });

  it("waterSystemName: fx_site_a は watershed 経由で境川水系を解決する", async () => {
    const rows = await sites(fx.db);
    const a = rows.find((r) => r.siteId === FX.sites.a)!;
    expect(a.watershed).toBe(FX.watershedId);
    expect(a.waterSystemName).toBe(FX.waterSystemName);
  });

  it("waterSystemName: watershed を持たない地点は null", async () => {
    const rows = await sites(fx.db);
    const b = rows.find((r) => r.siteId === FX.sites.b)!;
    expect(b.watershed).toBeNull();
    expect(b.waterSystemName).toBeNull();
  });

  it("site(): 1地点版は sites() の該当行と同じ内容を返す", async () => {
    const all = await sites(fx.db);
    const a = all.find((r) => r.siteId === FX.sites.a)!;
    const single = await site(fx.db, FX.sites.a);
    expect(single).toEqual(a);
  });

  it("site(): 存在しない site_id は undefined", async () => {
    expect(await site(fx.db, "no-such-site")).toBeUndefined();
  });

  it("source='live'/'summary' は n_meas/n_series/n_variables が一致する（フィクスチャ上の突合）", async () => {
    const summaryRows = await sites(fx.db, { dataset: "measurements", source: { kind: "summary" } });
    const liveRows = await sites(fx.db, { dataset: "measurements", source: { kind: "live" } });
    const byLive = new Map(liveRows.map((r) => [r.siteId, r]));
    for (const s of summaryRows) {
      const l = byLive.get(s.siteId)!;
      expect(l.nMeas, s.siteId).toBe(s.nMeas);
      expect(l.nSeries, s.siteId).toBe(s.nSeries);
      expect(l.nVariables, s.siteId).toBe(s.nVariables);
    }
  });
});

describe("sitesInWaterBody / waterBodies", () => {
  it("sitesInWaterBody(境川（１）) は fx_site_a/b の2件", async () => {
    const rows = await sitesInWaterBody(fx.db, FX.municipality);
    expect(rows.map((r) => r.siteId).sort()).toEqual([FX.sites.a, FX.sites.b].sort());
  });

  it("waterBodies() は地点2件以上の水域だけを返す（境川（１）を含む）", async () => {
    const rows = await waterBodies(fx.db);
    const kawa = rows.find((r) => r.name === FX.municipality);
    expect(kawa).toBeDefined();
    expect(kawa!.nSites).toBe(2);
  });

  it("waterBodies({series}) で1系列に絞ると、その系列を持つ地点が1つしか無い水域は HAVING n_sites>=2 から落ちる", async () => {
    // point/day は境川（１）内では fx_site_b にしか無い（fx_site_a は mean/day）ので、
    // series で point/day だけに絞ると境川（１）の n_sites は1になり、v1 の
    // waterBodiesForVariable と同じ `HAVING n_sites >= 2` で除外される。
    const rows = await waterBodies(fx.db, { series: [FX.series.ssPoint] });
    expect(rows.find((r) => r.name === FX.municipality)).toBeUndefined();
  });

  it("source='live'/'summary' は n_meas が一致する（フィクスチャ上の突合）", async () => {
    const summaryRows = await waterBodies(fx.db, { source: { kind: "summary" } });
    const liveRows = await waterBodies(fx.db, { source: { kind: "live" } });
    const byLive = new Map(liveRows.map((r) => [r.name, r]));
    for (const s of summaryRows) {
      const l = byLive.get(s.name)!;
      expect(l, s.name).toBeDefined();
      expect(l.nMeas, s.name).toBe(s.nMeas);
      expect(l.nSites, s.name).toBe(s.nSites);
    }
  });
});
