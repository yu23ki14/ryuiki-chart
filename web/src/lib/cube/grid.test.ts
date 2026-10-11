import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { placeIdOfWatershedId, watershedIdOfPlaceId } from "./grid";

// scripts/registry/common.py の watershed_place_id と同じ入出力の表。Python 側のテスト
// （scripts/tests/test_registry_place_amami.py）も同じ JSON を読む（Issue #94 D1）。
const CASES: { watershed_id: string; place_id: string }[] = JSON.parse(
  readFileSync(path.resolve(__dirname, "../../../../scripts/tests/fixtures/watershed_id_cases.json"), "utf8"),
);
const TABLE: [string, string][] = CASES.map((c) => [c.place_id, c.watershed_id]);

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
