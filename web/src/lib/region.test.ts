import { describe, expect, it } from "vitest";
import { REGION_TIME } from "@/lib/registry/generated-client";
import { REGIONS, parseRegion, regionLabel, regionOf } from "./region";

describe("region", () => {
  it("REGIONS の id 集合は registry の region と一致する", () => {
    expect(REGIONS.map((r) => r.id).sort()).toEqual(REGION_TIME.map((r) => r.regionId).sort());
  });
  it("parseRegion: 既知の値以外は all", () => {
    expect(parseRegion("jp-46")).toBe("jp-46");
    expect(parseRegion("jp-14")).toBe("jp-14");
    expect(parseRegion("all")).toBe("all");
    for (const bad of ["", "xx", undefined, null, ["jp-46"], 3]) expect(parseRegion(bad)).toBe("all");
  });
  it("regionOf / regionLabel", () => {
    expect(regionOf("all")).toBeUndefined();
    expect(regionOf("jp-46")).toBe("jp-46");
    expect(regionLabel("all")).toBe("全体");
    expect(regionLabel("jp-46")).toBe("奄美大島");
    expect(regionLabel("jp-14")).toBe("神奈川県");
  });
});
