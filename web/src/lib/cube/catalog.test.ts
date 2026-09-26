import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { buildCubeFixture, FX, type CubeFixture } from "./__fixtures__/cube-fixture";
import { sites, sitesInWaterBody, siteVariables, variableCatalog, waterBodies } from "./catalog";

let fx: CubeFixture;
beforeEach(() => {
  fx = buildCubeFixture();
});
afterEach(() => {
  fx.db.close();
});

describe("variableCatalog", () => {
  it("dataset を指定しないと water.ss と water.bod の両方が出る（rain は year/fiscal_year セルを持たないので元々出ない。v1 の var_catalog も meas_year 由来で sensor_timeseries を含まない）", async () => {
    const rows = await variableCatalog(fx.db);
    const seriesKeys = rows.map((r) => r.seriesKey);
    expect(seriesKeys).toContain(FX.series.ssMean.variableId + "|day|mean|");
    expect(rows.some((r) => r.series.variableId === FX.variables.bod)).toBe(true);
  });

  it("dataset='measurements' は sensor_timeseries（RAIN）を含まない", async () => {
    const rows = await variableCatalog(fx.db, { dataset: "measurements" });
    expect(rows.some((r) => r.series.variableId === FX.variables.rain)).toBe(false);
    expect(rows.some((r) => r.series.variableId === FX.variables.ss)).toBe(true);
  });

  it("mean/day 系列の n はゾーン内の site 分（fx_place_a + fx_place_c）を合算する", async () => {
    const rows = await variableCatalog(fx.db, { dataset: "measurements" });
    const meanDay = rows.find((r) => r.series.variableId === FX.variables.ss && r.series.obsStat === "mean" && r.inputGrain === "day");
    expect(meanDay).toBeDefined();
    expect(meanDay!.n).toBe(3 /* fx_place_a 年セル */ + 1 /* fx_place_c 年セルなし→スキップ */);
  });
});

describe("siteVariables", () => {
  it("fx_place_a は3系列（SS mean/day 年, SS mean/fiscal_year, BOD mean/day 年）を持つ", async () => {
    const rows = await siteVariables(fx.db, FX.places.a);
    expect(rows.length).toBeGreaterThanOrEqual(3);
    const ssDaily = rows.find((r) => r.series.variableId === FX.variables.ss && r.grain === "year");
    expect(ssDaily).toBeDefined();
    expect(ssDaily!.avg).toBeCloseTo(6.0, 6);
  });

  it("存在しない place_id は空配列", async () => {
    expect(await siteVariables(fx.db, "no-such-place")).toEqual([]);
  });
});

describe("sites", () => {
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
});
