import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/registry/generated-source", () => ({
  SOURCE_REGION: { a_k: "jp-14", b_a: "jp-46" },
}));

import { placeRegionJoin, regionPred, sourceRegion, sourcesOfRegion } from "./region";

describe("cube/region", () => {
  it("regionPred", () => {
    expect(regionPred("obs", undefined)).toEqual({ sql: "", params: [] });
    expect(regionPred("obs", "jp-46")).toEqual({ sql: "obs.region_id = ?", params: ["jp-46"] });
  });
  it("placeRegionJoin", () => {
    expect(placeRegionJoin("s", undefined)).toEqual({ joins: [], params: [] });
    const j = placeRegionJoin("s", "jp-14");
    expect(j.joins).toHaveLength(1);
    expect(j.joins[0]).toContain("place_region");
    expect(j.params).toEqual(["jp-14"]);
  });
  it("sourceRegion / sourcesOfRegion: 未宣言は常に含める", () => {
    expect(sourceRegion("a_k")).toBe("jp-14");
    expect(sourceRegion("zzz")).toBeUndefined();
    const ids = ["a_k", "b_a", "common"] as const;
    expect(sourcesOfRegion(ids, undefined)).toEqual(["a_k", "b_a", "common"]);
    expect(sourcesOfRegion(ids, "jp-14")).toEqual(["a_k", "common"]);
    expect(sourcesOfRegion(ids, "jp-46")).toEqual(["b_a", "common"]);
  });
});
