import { describe, expect, it } from "vitest";
import { placeIdOfWatershedId, watershedIdOfPlaceId } from "./grid";

// scripts/registry/common.py と同じ入出力の表（Issue #94 D1）
const TABLE: [string, string][] = [
  ["common:place:watershed.nlni.83030-0016", "83030-0016"],
  ["common:place:watershed.dem.amami-001", "dem-amami-001"],
  ["common:place:watershed.dem.amami-071", "dem-amami-071"],
];

describe("流域の ID 変換", () => {
  it.each(TABLE)("%s ⇔ %s", (placeId, wsId) => {
    expect(watershedIdOfPlaceId(placeId)).toBe(wsId);
    expect(placeIdOfWatershedId(wsId)).toBe(placeId);
  });
  it("知らない名前空間・別の kind は null", () => {
    expect(watershedIdOfPlaceId("common:place:watershed.foo.x")).toBeNull();
    expect(watershedIdOfPlaceId("common:place:grid01.3520_13900")).toBeNull();
  });
});
