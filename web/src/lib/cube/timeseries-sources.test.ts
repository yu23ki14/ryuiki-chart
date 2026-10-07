import { describe, expect, it } from "vitest";
import type { CubeDb } from "./db";
import { buildScopeSql } from "./sql";
import { representativeSeries, representativeSeriesForSources } from "./series";
import { timeseries, TimeseriesInputError } from "./timeseries";

/** 出典を指定した時系列（センサー・土地利用。measurements 以外の dataset）。実データではなく registry の系列で引く。 */
describe("representativeSeriesForSources", () => {
  it("センサー系列（毎時）は measurements の既定では引けず、出典を指定すると引ける", () => {
    const v = "common:variable:air.no2";
    expect(representativeSeries(v).every((s) => s.dataset === "measurements")).toBe(true);
    const s = representativeSeriesForSources(v, ["soramame_hourly_kanagawa"]);
    expect(s).toHaveLength(1);
    expect(s[0]).toMatchObject({ dataset: "sensor_timeseries", valueGrain: "hour", obsStat: null });
    expect(s[0].sourceIds).toContain("soramame_hourly_kanagawa");
  });

  it("土地利用は measurements でも sensor でもない dataset。出典の指定で引ける（代表系列が無いので全系列にフォールバック）", () => {
    const s = representativeSeriesForSources("common:variable:landuse.paddy", ["nlni_l03b_landuse_by_watershed"]);
    expect(s.length).toBeGreaterThan(0);
    expect(s.every((x) => x.valueGrain === "year" && x.obsStat === "sum")).toBe(true);
    expect(representativeSeries("common:variable:landuse.paddy")).toEqual([]);
  });

  it("出典が登録されていない系列は返さない", () => {
    expect(representativeSeriesForSources("common:variable:air.no2", ["atsugi_river_water_quality"])).toEqual([]);
  });
});

describe("timeseries の入力の組み合わせ", () => {
  const db = {} as CubeDb; // 入力エラーは問い合わせの前に投げる
  const base = { variableId: "common:variable:air.no2", scope: { type: "zone" as const }, grain: "month" as const };

  it("毎時の系列と日次の系列（別の出典）が混ざる指定は入力エラー", async () => {
    await expect(timeseries(db, { ...base, sourceIds: ["soramame_hourly_kanagawa", "hiratsuka_taiki"] })).rejects.toThrow(TimeseriesInputError);
  });

  it("毎時の系列に fiscal_year は無い", async () => {
    await expect(timeseries(db, { ...base, grain: "fiscal_year", sourceIds: ["soramame_hourly_kanagawa"] })).rejects.toThrow(TimeseriesInputError);
  });
});

describe("流域スコープ（土地利用）", () => {
  it("place_kind は watershed に絞り、placeId があれば place_id で絞る。site の JOIN は付けない", () => {
    const all = buildScopeSql({ kind: "watershed" });
    expect(all.wheres).toContain("obs.place_kind = 'watershed'");
    expect(all.joins).toEqual([]);
    const one = buildScopeSql({ kind: "watershed", placeId: "w1" });
    expect(one.wheres).toContain("obs.place_id = ?");
    expect(one.whereParams).toEqual(["w1"]);
  });
  it("他のスコープは従来どおり site", () => {
    expect(buildScopeSql({ kind: "all_sites" }).wheres).toContain("obs.place_kind = 'site'");
  });
});
