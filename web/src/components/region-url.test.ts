import { describe, expect, it, vi } from "vitest";

// 担当 A の lib/region.ts と同じ契約（設計書 §3-1）の最小の差し替え。
vi.mock("@/lib/region", () => {
  const KNOWN = ["jp-14", "jp-46"];
  return {
    REGION_ALL: "all",
    parseRegion: (raw: unknown) => (typeof raw === "string" && KNOWN.includes(raw) ? raw : "all"),
  };
});

import { regionFromSearch, searchWithRegion, withRegion } from "./region-url";

describe("withRegion", () => {
  it("'all' は URL を変えない（現状と同じ URL）", () => {
    expect(withRegion("/map", "all")).toBe("/map");
    expect(withRegion("/biota?tab=ias", "all")).toBe("/biota?tab=ias");
    expect(withRegion("/api/biota?kind=effort", "all")).toBe("/api/biota?kind=effort");
  });
  it("地域を ? か & でつなぐ", () => {
    expect(withRegion("/map", "jp-46")).toBe("/map?region=jp-46");
    expect(withRegion("/api/biota?kind=effort", "jp-46")).toBe("/api/biota?kind=effort&region=jp-46");
  });
  it("既存の region は置き換え、'all' なら消す。他のクエリは保つ", () => {
    expect(withRegion("/timeseries?region=jp-14&variable=x", "jp-46")).toBe("/timeseries?region=jp-46&variable=x");
    expect(withRegion("/timeseries?region=jp-14&variable=x", "all")).toBe("/timeseries?variable=x");
    expect(withRegion("/timeseries?region=jp-14", "all")).toBe("/timeseries");
  });
  it("ハッシュを保つ", () => {
    expect(withRegion("/sources#a", "jp-14")).toBe("/sources?region=jp-14#a");
  });
  it("空文字（useJson の取得しない合図）はそのまま", () => {
    expect(withRegion("", "jp-46")).toBe("");
  });
});

describe("searchWithRegion", () => {
  it("他のクエリを保ったまま region だけ差し替える", () => {
    expect(searchWithRegion("tab=ias&group=%E9%B3%A5%E9%A1%9E", "jp-46")).toBe("tab=ias&group=%E9%B3%A5%E9%A1%9E&region=jp-46");
    expect(searchWithRegion("?region=jp-14&tab=ias", "jp-46")).toBe("region=jp-46&tab=ias");
  });
  it("'all' で region を消す", () => {
    expect(searchWithRegion("region=jp-46&tab=ias", "all")).toBe("tab=ias");
    expect(searchWithRegion("region=jp-46", "all")).toBe("");
    expect(searchWithRegion("", "all")).toBe("");
  });
});

describe("regionFromSearch", () => {
  it("既知の地域を返し、不正・未指定・null は 'all'", () => {
    expect(regionFromSearch(new URLSearchParams("region=jp-46"))).toBe("jp-46");
    expect(regionFromSearch(new URLSearchParams("region=xx"))).toBe("all");
    expect(regionFromSearch(new URLSearchParams(""))).toBe("all");
    expect(regionFromSearch(null)).toBe("all");
  });
});
