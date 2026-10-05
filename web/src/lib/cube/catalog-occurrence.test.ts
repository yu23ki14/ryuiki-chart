import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { buildOccurrenceFixture, FXO, type OccurrenceFixture } from "./__fixtures__/occurrence-fixture";
import {
  effortYears,
  gridCatalog,
  iasSpecies,
  occurrenceTotals,
  speciesCatalog,
  taxonGroupYears,
  watershedOccurrence,
} from "./catalog";
import { gridCellOfPlaceId, placeIdOfWatershedId, watershedIdOfPlaceId } from "./grid";

let fx: OccurrenceFixture;
beforeEach(() => {
  fx = buildOccurrenceFixture();
});
afterEach(() => fx.db.close());

const { alpha, beta, gamma, delta, named } = FXO.binoms;

describe("speciesCatalog", () => {
  it("n 降順・binom 昇順。列は summary_species_catalog のまま", async () => {
    const rows = await speciesCatalog(fx.db);
    expect(rows.map((r) => [r.binom, r.n])).toEqual([
      [alpha, 236],
      [beta, 86],
      [delta, 20],
      [gamma, 10],
      [named, 3],
    ]);
    expect(rows[0]).toEqual({
      binom: alpha, taxonGroup: "FxBird", class: "Aves", family: "FamA",
      n: 236, nRedList: 62, nAlien: 0, nPlaces: 2, yFrom: 1950, yTo: 2021, nYears: 5,
    });
  });
  it("group と limit", async () => {
    expect((await speciesCatalog(fx.db, { group: "FxPlant" })).map((r) => r.binom)).toEqual([delta, gamma, named]);
    expect((await speciesCatalog(fx.db, { limit: 1 })).length).toBe(1);
  });
});

describe("taxonGroupYears / effortYears", () => {
  it("taxonGroupYears: mesh_n は source 別 n_places の MAX。taxon_id NULL は '未判定'", async () => {
    const rows = await taxonGroupYears(fx.db);
    expect(rows.filter((r) => r.year === 2000)).toEqual([{ year: 2000, taxonGroup: "FxBird", n: 105, meshN: 2 }]);
    expect(rows.filter((r) => r.year === 2022)).toEqual([
      { year: 2022, taxonGroup: "FxPlant", n: 33, meshN: 2 },
      { year: 2022, taxonGroup: "未判定", n: 7, meshN: 1 },
    ]);
    expect(rows.some((r) => r.year < 1990)).toBe(false);
    expect((await taxonGroupYears(fx.db, { from: 1950, to: 1950 })).map((r) => r.n)).toEqual([2]);
  });
  it("effortYears: n_inat/n_gbif は source 別の SUM", async () => {
    const rows = await effortYears(fx.db);
    expect(rows.map((r) => r.year)).toEqual([2000, 2005, 2010, 2021, 2022]);
    expect(rows[0]).toEqual({ year: 2000, n: 105, speciesN: 2, meshN: 2, nInat: 55, nGbif: 50 });
    expect(rows.at(-1)).toEqual({ year: 2022, n: 40, speciesN: 3, meshN: 2, nInat: 40, nGbif: 0 });
  });
});

describe("gridCatalog / occurrenceTotals", () => {
  it("gridCatalog: 窓（1970〜）を焼いた n/rl_n と、窓なしの種数", async () => {
    expect(await gridCatalog(fx.db)).toEqual([
      { placeId: FXO.places.g1, mlat: 3520, mlon: 13900, n: 196, rlN: 0, speciesN: 4, rlSpeciesN: 0 },
      { placeId: FXO.places.g2, mlat: 3521, mlon: 13901, n: 164, rlN: 60, speciesN: 3, rlSpeciesN: 1 },
    ]);
  });
  it("occurrenceTotals", async () => {
    expect(await occurrenceTotals(fx.db)).toEqual({ records: 362, species: 5, grids: 2, gbif: 236, inat: 126 });
  });
});

describe("watershedOccurrence", () => {
  it("流域ごとの n/alien/redlist と、流域外（place_id NULL）を別に返す", async () => {
    expect(await watershedOccurrence(fx.db)).toEqual({
      watersheds: [{ watershedId: "83030-0001", placeId: FXO.places.ws1, orgN: 35, orgAlienN: 20, orgRedlistN: 5 }],
      outsideWatershed: { n: 3, nRedList: 0, nAlien: 0 },
    });
  });
});

describe("iasSpecies", () => {
  it("taxon_assessment.binom で結合。記録の無い種・in_scope=0 は出さず、(category, binom) ごとに返す", async () => {
    const rows = await iasSpecies(fx.db);
    expect(rows.map((r) => [r.iasCategory, r.binom])).toEqual([
      ["その他の総合対策外来種", delta],
      ["総合対策外来種", delta],
    ]);
    expect(rows[0]).toMatchObject({ n: 20, meshN: 1, yFrom: 2022, yTo: 2022, nSince2020: 20, nameJa: "デルタ", taxonGroup: "FxPlant" });
  });
});

describe("place_id 変換", () => {
  it("グリッド", () => {
    expect(gridCellOfPlaceId("common:place:grid01.3520_13900")).toEqual({ mlat: 3520, mlon: 13900 });
    expect(gridCellOfPlaceId("common:place:watershed.nlni-1")).toBeNull();
  });
  it("流域は往復できる", () => {
    expect(watershedIdOfPlaceId("common:place:watershed.nlni-83030-0016")).toBe("83030-0016");
    expect(placeIdOfWatershedId("83030-0016")).toBe("common:place:watershed.nlni-83030-0016");
    expect(watershedIdOfPlaceId("common:place:grid01.3520_13900")).toBeNull();
  });
});
