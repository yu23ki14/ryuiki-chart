/**
 * 地域で絞る（Issue #93 §4 A1）: 観測セル・provenance・水域・カタログ・概況・タイムシリーズ。
 * 出典の地域（`SOURCE_REGION`）は担当 D の生成物。ここでは同じ値をモックで固定する（マニフェスト由来の実値）。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/registry/generated-source", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/registry/generated-source")>()),
  SOURCE_REGION: {
    atsugi_river_water_quality: "jp-14",
    env_kousui_annual_kanagawa: "jp-14",
    env_kousui_sample_kanagawa: "jp-14",
    env_kousui_annual_amami: "jp-46",
    env_kousui_sample_amami: "jp-46",
    jma_monthly_kanagawa: "jp-14",
    jma_monthly_amami: "jp-46",
    gbif_kanagawa_occurrences: "jp-14",
    inaturalist_kanagawa: "jp-14",
    gbif_amami_occurrences: "jp-46",
    inaturalist_amami: "jp-46",
  },
}));

import type { CubeDb, SqlParam } from "./db";
import { buildCubeFixture, FX, seedSummaryFromObsAgg, type CubeFixture } from "./__fixtures__/cube-fixture";
import { createRegionTables, seedPlaceRegion, seedVariableCatalogByRegion } from "./__fixtures__/region-fixture";
import { overviewCounts, siteSeriesCells, sites, sitesInWaterBody, variableCatalog, waterBodies } from "./catalog";
import { facetsForOccurrence, caveatsForFacets } from "./caveats";
import { buildEnvelope, buildZoneEnvelope } from "./envelope";
import { queryCells, summarize, type CellSpec } from "./observation";
import { freshnessForSeries } from "./source-meta";
import { timeseries } from "./timeseries";
import type { RegionId } from "@/lib/region";

const AM = {
  water: "奄美の川",
  siteA: "fx_site_am1",
  siteB: "fx_site_am2",
  placeA: "fx_place_am1",
  placeB: "fx_place_am2",
} as const;

let fx: CubeFixture;

/** 奄美（jp-46）の2地点を足す。BOD と SS の年・日セル。 */
function addAmami(raw: CubeFixture["raw"]): void {
  const site = raw.prepare(
    `INSERT INTO sites (site_id, name, name_en, watershed, zone, lat, lon, elevation_m, municipality, muni_code, treatment, established_on, operator, source_id, source_ref, is_synthetic)
     VALUES (?,?,NULL,NULL,1,28.3,129.5,?,?,NULL,NULL,NULL,NULL,NULL,NULL,0)`,
  );
  site.run(AM.siteA, "奄美A", 20, AM.water);
  site.run(AM.siteB, "奄美B", 10, AM.water);
  const place = raw.prepare(
    `INSERT INTO place (place_id, region_id, place_kind, name_ja, lat, lon, elevation_m, status) VALUES (?,'jp-46','site',?,28.3,129.5,NULL,'ok')`,
  );
  place.run(AM.placeA, "奄美A");
  place.run(AM.placeB, "奄美B");
  const psr = raw.prepare(`INSERT INTO place_source_ref (place_id, external_key, key_space) VALUES (?,?,'site_id')`);
  psr.run(AM.placeA, AM.siteA);
  psr.run(AM.placeB, AM.siteB);
  const obs = raw.prepare(
    `INSERT INTO observation_agg
       (region_id, place_id, place_kind, variable_id, obs_stat, unit_id, value_grain, period_start, period_end, grain, input_grain, stat,
        value_zero, value_lod, n, n_censored, n_not_detected, n_places, built_from, spec_version)
     VALUES (?,?,'site',?,?,?, 'day', ?, ?, ?, 'day','mean', ?, ?, 1,0,0,1,'fixture','fixture@1')`,
  );
  // BOD は point/day（env_kousui_sample_{kanagawa,amami} が共有する系列キー）。SS は mean/day。
  for (const p of [AM.placeA, AM.placeB]) {
    for (const [v, st] of [[FX.variables.bod, "point"], [FX.variables.ss, "mean"]] as const) {
      obs.run("jp-46", p, v, st, FX.units.mgPerL, "2024-01-01", "2024-01-01", "day", 1.5, 1.5);
      obs.run("jp-46", p, v, st, FX.units.mgPerL, "2024-01-01", "2024-12-31", "year", 1.5, 1.5);
    }
  }
  // 神奈川にも同じ BOD point/day の系列（fx_place_b。`bodMean` は fx_place_a の atsugi 系列で別キー）
  for (const [g, s, e] of [["day", "2024-01-01", "2024-01-01"], ["year", "2024-01-01", "2024-12-31"]] as const) {
    obs.run("jp-14", FX.places.b, FX.variables.bod, "point", FX.units.mgPerL, s, e, g, 2.5, 2.5);
  }
  createRegionTables(raw);
  seedPlaceRegion(raw);
  raw.exec(`DELETE FROM summary_variable_catalog; DELETE FROM summary_place_variable;`);
  seedSummaryFromObsAgg(raw);
  seedVariableCatalogByRegion(raw);
}

beforeEach(() => {
  fx = buildCubeFixture();
  addAmami(fx.raw);
});
afterEach(() => {
  fx.db.close();
});

/** 発行した SQL とパラメータを記録する CubeDb。 */
function spyDb(db: CubeDb): CubeDb & { calls: { sql: string; params: readonly SqlParam[] }[] } {
  const calls: { sql: string; params: readonly SqlParam[] }[] = [];
  return {
    kind: db.kind,
    calls,
    async all(sql, params = []) {
      calls.push({ sql, params });
      return db.all(sql, params);
    },
  } as CubeDb & { calls: { sql: string; params: readonly SqlParam[] }[] };
}

const bodPoint = { ...FX.series.bodMean, obsStat: "point" };
const bodSeries = [FX.series.bodMean, bodPoint];
const bodSpec = (region?: RegionId): CellSpec => ({
  series: bodSeries,
  scope: { kind: "all_sites" },
  region,
  grain: ["day", "year"],
  imputation: "lod",
});

describe("queryCells の region", () => {
  it("region 未指定は WHERE に region_id の条件もパラメータも足さない", async () => {
    const db = spyDb(fx.db);
    await queryCells(db, bodSpec());
    const { sql, params } = db.calls[0]!;
    expect(sql).not.toContain("region_id = ?");
    expect(params).not.toContain("jp-46");
    expect(params).not.toContain("jp-14");
  });

  it("region 指定で `obs.region_id = ?` が WHERE に入り、jp-14 の行は 0・jp-46 だけ返る。和は全体に一致する", async () => {
    const all = (await queryCells(fx.db, bodSpec())).rows;
    const k = (await queryCells(fx.db, bodSpec("jp-14"))).rows;
    const a = (await queryCells(fx.db, bodSpec("jp-46"))).rows;
    expect(a.length).toBeGreaterThan(0);
    expect(k.length).toBeGreaterThan(0);
    expect(k.length + a.length).toBe(all.length);
    expect(a.every((r) => r.regionId === "jp-46" && [AM.placeA, AM.placeB].includes(r.placeId as never))).toBe(true);
    expect(k.every((r) => r.regionId === "jp-14")).toBe(true);
  });

  it("どの行も持たない地域（不明な値）は例外にせず 0 行", async () => {
    const r = await queryCells(fx.db, bodSpec("jp-99" as RegionId));
    expect(r.rows).toEqual([]);
  });

  it("summarize も region で絞られる（place 集計）", async () => {
    const spec = (region?: RegionId): CellSpec => ({ ...bodSpec(region), grain: "year" });
    const all = (await summarize(fx.db, spec(), "place")).rows;
    const a = (await summarize(fx.db, spec("jp-46"), "place")).rows;
    const k = (await summarize(fx.db, spec("jp-14"), "place")).rows;
    expect(a.map((r) => r.placeId).sort()).toEqual([AM.placeA, AM.placeB]);
    expect(a.length + k.length).toBe(all.length);
  });
});

describe("provenance は行の地域と出典の地域が一致するものだけ（§3-6）", () => {
  const ids = (e: { provenance: { source_id: string }[] }) => e.provenance.map((p) => p.source_id).sort();

  it("BOD: jp-14 の行は神奈川の出典だけ、jp-46 の行は奄美の出典だけ", async () => {
    const k = (await queryCells(fx.db, bodSpec("jp-14"))).rows;
    const a = (await queryCells(fx.db, bodSpec("jp-46"))).rows;
    const ek = buildEnvelope(bodSpec("jp-14"), k);
    const ea = buildEnvelope(bodSpec("jp-46"), a);
    expect(ids(ek)).not.toContain("env_kousui_annual_amami");
    expect(ids(ek)).not.toContain("env_kousui_sample_amami");
    expect(ids(ek)).toEqual(expect.arrayContaining(["atsugi_river_water_quality", "env_kousui_sample_kanagawa"]));
    expect(ids(ea)).toEqual(["env_kousui_sample_amami"]);
    // n_rows は帰属した行の数
    for (const p of ea.provenance) expect(p.n_rows).toBe(a.length);
  });

  it("全体でも行ごとに帰属する（神奈川の行に奄美の出典を、奄美の行に神奈川の出典を付けない）", async () => {
    const all = (await queryCells(fx.db, bodSpec())).rows;
    const nK = all.filter((r) => r.regionId === "jp-14").length;
    const nA = all.filter((r) => r.regionId === "jp-46").length;
    const by = new Map(buildEnvelope(bodSpec(), all).provenance.map((p) => [p.source_id, p.n_rows]));
    expect(by.get("env_kousui_sample_amami")).toBe(nA);
    // 神奈川の point/day の行は BOD の point 系列、atsugi は mean 系列の行
    const nKPoint = all.filter((r) => r.regionId === "jp-14" && r.series.obsStat === "point").length;
    const nKMean = all.filter((r) => r.regionId === "jp-14" && r.series.obsStat === "mean").length;
    expect(by.get("env_kousui_sample_kanagawa")).toBe(nKPoint);
    expect(by.get("atsugi_river_water_quality")).toBe(nKMean);
    expect(nK).toBe(nKPoint + nKMean);
  });

  it("行の地域が不明（null）なら絞らない", async () => {
    const row = (await queryCells(fx.db, bodSpec("jp-14"))).rows.find((r) => r.series.obsStat === "point");
    const env = buildEnvelope(bodSpec(), [{ ...row!, regionId: null }]);
    expect(ids(env)).toEqual(expect.arrayContaining(["env_kousui_sample_amami", "env_kousui_sample_kanagawa"]));
  });

  it("ゾーン集計の封筒は spec.region で出典を絞る", () => {
    const spec = { ...bodSpec("jp-46"), series: [bodPoint, { ...bodPoint, obsStat: "mean", valueGrain: "fiscal_year" }] };
    expect(ids(buildZoneEnvelope(spec, []))).toEqual(["env_kousui_annual_amami", "env_kousui_sample_amami"]);
    expect(ids(buildZoneEnvelope({ ...spec, region: undefined }, []))).toContain("env_kousui_annual_kanagawa");
  });

  it("freshnessForSeries は region で絞る", () => {
    const f = (r?: RegionId) => freshnessForSeries([bodPoint], {}, r).map((x) => x.source_id);
    expect(f("jp-46")).toEqual(["env_kousui_sample_amami"]);
    expect(f("jp-14")).toEqual(["env_kousui_sample_kanagawa"]);
    expect(f().sort()).toEqual(["env_kousui_sample_amami", "env_kousui_sample_kanagawa"]);
  });
});

describe("facetsForOccurrence の region", () => {
  it("sourceIds 省略時は地域の出典の注記だけ（sourceIds を渡したときは渡した出典のまま）", () => {
    const refs = (region?: RegionId) => facetsForOccurrence({ places: [], region }).map((f) => f.ref);
    expect(refs("jp-14").join(" ")).not.toContain("gbif_amami_occurrences");
    expect(refs("jp-46").join(" ")).not.toContain("gbif_kanagawa_occurrences");
    expect(refs("jp-46").join(" ")).toContain("gbif_amami_occurrences");
    expect(refs().join(" ")).toContain("gbif_kanagawa_occurrences");
    expect(facetsForOccurrence({ places: [], region: "jp-46", sourceIds: ["gbif_kanagawa_occurrences"] })).toHaveLength(1);
    expect(caveatsForFacets(facetsForOccurrence({ places: [], region: "jp-46" })).length).toBeGreaterThanOrEqual(0);
  });
});

describe("カタログ・水域・概況", () => {
  it("sites: 地域で絞られ、和が全体に一致する", async () => {
    const all = await sites(fx.db);
    const k = await sites(fx.db, { region: "jp-14" });
    const a = await sites(fx.db, { region: "jp-46" });
    expect(a.map((s) => s.siteId).sort()).toEqual([AM.siteA, AM.siteB]);
    // fx_site_c は `sites` に行が無い。a・b・rain が神奈川
    expect(k.map((s) => s.siteId)).not.toContain(AM.siteA);
    expect(k.length + a.length).toBe(all.length);
  });

  it("sitesInWaterBody: 別の地域の水域は 0 件", async () => {
    expect((await sitesInWaterBody(fx.db, AM.water, { region: "jp-46" })).length).toBe(2);
    expect(await sitesInWaterBody(fx.db, AM.water, { region: "jp-14" })).toEqual([]);
    expect((await sitesInWaterBody(fx.db, FX.municipality, { region: "jp-14" })).length).toBeGreaterThan(0);
    expect(await sitesInWaterBody(fx.db, FX.municipality, { region: "jp-46" })).toEqual([]);
  });

  it("waterBodies: 地域の水域だけ。地点数の和が全体に一致", async () => {
    const all = await waterBodies(fx.db);
    const k = await waterBodies(fx.db, { region: "jp-14" });
    const a = await waterBodies(fx.db, { region: "jp-46" });
    expect(a.map((w) => w.name)).toEqual([AM.water]);
    expect(k.map((w) => w.name)).not.toContain(AM.water);
    const sum = (ws: { nSites: number }[]) => ws.reduce((s, w) => s + w.nSites, 0);
    expect(sum(k) + sum(a)).toBe(sum(all));
    // series 指定と併用しても params がずれない
    const bod = await waterBodies(fx.db, { series: [bodPoint], region: "jp-46" });
    expect(bod.map((w) => w.name)).toEqual([AM.water]);
  });

  it("variableCatalog: 地域で絞られ、n の和が全体に一致する", async () => {
    const tot = (rows: { n: number }[]) => rows.reduce((s, r) => s + r.n, 0);
    const all = await variableCatalog(fx.db);
    const k = await variableCatalog(fx.db, { region: "jp-14" });
    const a = await variableCatalog(fx.db, { region: "jp-46" });
    expect(tot(k) + tot(a)).toBe(tot(all));
    expect(a.map((r) => r.variableId).sort()).toEqual([FX.variables.bod, FX.variables.ss].sort());
    // live 経路でも同じ
    const live = await variableCatalog(fx.db, { region: "jp-46", source: { kind: "live" } });
    expect(tot(live)).toBe(tot(a));
    // dataset と併用（params の順）
    // （フィクスチャの variable_alias に BOD の point 系列は無いので、dataset 指定では SS だけ）
    const ssOnly = tot(a.filter((r) => r.variableId === FX.variables.ss));
    const ds = await variableCatalog(fx.db, { region: "jp-46", dataset: "measurements" });
    expect(tot(ds)).toBe(ssOnly);
    const dsLive = await variableCatalog(fx.db, { region: "jp-46", dataset: "measurements", source: { kind: "live" } });
    expect(tot(dsLive)).toBe(ssOnly);
  });

  it("overviewCounts: 地点数・指標数・期間が地域のもの。出典数は絞らない", async () => {
    const all = await overviewCounts(fx.db);
    const k = await overviewCounts(fx.db, "jp-14");
    const a = await overviewCounts(fx.db, "jp-46");
    expect(a.sites).toBe(2);
    expect(k.sites + a.sites).toBe(all.sites);
    expect(a.variables).toBe(2);
    expect(a.sources).toBe(all.sources);
    expect(k.sources).toBe(all.sources);
    expect(a.yFrom).toBe(2024);
  });

  it("region 未指定の overviewCounts は新しい表を引かない", async () => {
    const db = spyDb(fx.db);
    await overviewCounts(db);
    expect(db.calls[0]!.sql).not.toContain("_by_region");
    expect(db.calls[0]!.sql).not.toContain("place_region");
  });

  it("place_region に無い地域は 0 件（例外にしない）", async () => {
    expect(await sites(fx.db, { region: "jp-99" as RegionId })).toEqual([]);
    expect(await waterBodies(fx.db, { region: "jp-99" as RegionId })).toEqual([]);
    expect(await variableCatalog(fx.db, { region: "jp-99" as RegionId })).toEqual([]);
    const o = await overviewCounts(fx.db, "jp-99" as RegionId);
    expect([o.sites, o.watersheds, o.variables]).toEqual([0, 0, 0]);
    expect(await siteSeriesCells(fx.db, { dataset: "measurements" })).not.toEqual([]);
  });
});

describe("timeseries() の region", () => {
  it("水域スコープ: 奄美の水域は jp-46 の地点だけ。封筒の time_zone は絞った地域", async () => {
    const r = await timeseries(fx.db, { variableId: FX.variables.bod, scope: { type: "water", name: AM.water }, grain: "year", region: "jp-46" });
    expect(r.sites?.map((s) => s.siteId).sort()).toEqual([AM.siteA, AM.siteB]);
    expect(r.points.length).toBeGreaterThan(0);
    expect((r.envelope!.query as { region?: string }).region).toBe("jp-46");
    expect(r.envelope!.time_zone.region_id).toBe("jp-46");
    // 神奈川の出典（env_kousui_*_kanagawa・atsugi）は載らない
    expect(r.envelope!.provenance.map((p) => p.source_id).filter((id) => !id.endsWith("_amami"))).toEqual([]);
  });

  it("別の地域の水域を指すと点も地点も空", async () => {
    const r = await timeseries(fx.db, { variableId: FX.variables.bod, scope: { type: "water", name: AM.water }, grain: "year", region: "jp-14" });
    expect(r.sites).toEqual([]);
    expect(r.points).toEqual([]);
  });

  it("region 省略は従来どおり（時刻帯は既定のまま）", async () => {
    const r = await timeseries(fx.db, { variableId: FX.variables.bod, scope: { type: "water", name: AM.water }, grain: "year" });
    expect(r.points.length).toBeGreaterThan(0);
    expect(r.envelope!.time_zone.region_id).toBe("jp-14");
  });
});
