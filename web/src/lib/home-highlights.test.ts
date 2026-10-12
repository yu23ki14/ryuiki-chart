import { describe, expect, it } from "vitest";
import { compareSeaStations, summarizeCoralByYear } from "./home-highlights";

describe("summarizeCoralByYear", () => {
  it("'<5'（数値 NULL）は平均に入れず belowLimit に数える", () => {
    const out = summarizeCoralByYear([
      { fiscal_year: 2005, cover_pct: 30, cover_pct_raw: "30", bleach_all_pct: 0, bleach_all_pct_raw: "0" },
      { fiscal_year: 2005, cover_pct: 50, cover_pct_raw: "50", bleach_all_pct: 10, bleach_all_pct_raw: "10" },
      { fiscal_year: 2005, cover_pct: null, cover_pct_raw: "<5", bleach_all_pct: null, bleach_all_pct_raw: "<5" },
      { fiscal_year: 2004, cover_pct: 10, cover_pct_raw: "10", bleach_all_pct: 0, bleach_all_pct_raw: "0" },
      { fiscal_year: null, cover_pct: 99, cover_pct_raw: "99", bleach_all_pct: 99, bleach_all_pct_raw: "99" },
    ]);
    expect(out.map((r) => r.year)).toEqual([2004, 2005]);
    expect(out[1]).toEqual({ year: 2005, spots: 3, measured: 2, belowLimit: 1, coverMean: 40, bleachN: 2, bleachBelowLimit: 1, bleachMean: 5 });
  });
  it("数値が1つも無い年は平均 null", () => {
    const [r] = summarizeCoralByYear([{ fiscal_year: 2010, cover_pct: null, cover_pct_raw: "<5", bleach_all_pct: null, bleach_all_pct_raw: "<5" }]);
    expect(r.coverMean).toBeNull();
    expect(r.bleachMean).toBeNull();
    expect(r.belowLimit).toBe(1);
    expect(r.bleachBelowLimit).toBe(1);
  });
});

describe("compareSeaStations", () => {
  it("基準点（数字順）→ 監視点（いろは順）", () => {
    const names = ["監視点ト", "基準点４", "監視点ロ", "監視点イ", "基準点１", "監視点ハ", "基準点２"];
    expect([...names].sort(compareSeaStations)).toEqual([
      "基準点１", "基準点２", "基準点４", "監視点イ", "監視点ロ", "監視点ハ", "監視点ト",
    ]);
  });
  it("半角の数字も全角と同じ順に並ぶ", () => {
    expect(["基準点2", "基準点１", "基準点4"].sort(compareSeaStations)).toEqual(["基準点１", "基準点2", "基準点4"]);
  });
  it("接尾辞が空・複数文字・未知の名前は末尾（名前順）", () => {
    const unknown = ["基準点12", "基準点", "監視点イロ", "その他"];
    const out = [...unknown, "監視点イ", "基準点２"].sort(compareSeaStations);
    expect(out.slice(0, 2)).toEqual(["基準点２", "監視点イ"]);
    expect(out.slice(2)).toEqual([...unknown].sort((a, b) => a.localeCompare(b, "ja")));
  });
});
