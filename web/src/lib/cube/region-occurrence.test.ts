/**
 * 地域で絞る（Issue #93 §4 A2）: 出現系（種のカタログ・努力量・合計・メッシュ・流域・IAS）とレッドリスト。
 * `*_by_region` は `__fixtures__/region-fixture.ts` が `occurrence_agg` から導出する（和が全体に一致することで加法性を確かめる）。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/registry/generated-source", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/registry/generated-source")>()),
  SOURCE_REGION: {
    gbif_kanagawa_occurrences: "jp-14",
    inaturalist_kanagawa: "jp-14",
    gbif_amami_occurrences: "jp-46",
    inaturalist_amami: "jp-46",
  },
}));

import type { CubeDb, SqlParam } from "./db";
import { redlistBundle, redlistFlows, redlistSpecies, redlistSummary } from "./assessment";
import {
  effortYears,
  gridCatalog,
  iasSpecies,
  occurrenceTotals,
  speciesCatalog,
  taxonGroupYears,
  watershedOccurrence,
} from "./catalog";
import { buildOccurrenceFixture, FX_VOCAB, FXO, seedSummaries, TWIN_MARK, type OccurrenceFixture } from "./__fixtures__/occurrence-fixture";
import { createRegionTables, seedOccurrenceByRegion, seedPlaceRegion } from "./__fixtures__/region-fixture";
import { meshByYear, speciesCatalogCounts, speciesMeshYears, speciesMonths, speciesShareTrend, speciesYears, watershedYears } from "./occurrence";
import type { RegionId } from "@/lib/region";

const GBIF_A = "gbif_amami_occurrences";
const INAT_A = "inaturalist_amami";
const AG1 = "common:place:grid01.2800_12900";
const AG2 = "common:place:grid01.2801_12901";
const AWS = "common:place:watershed.nlni.99999-0001";
const TAXON = { a: "common:taxon:fx_a", c: "common:taxon:fx_c", d: "common:taxon:fx_d", e: "common:taxon:fx_e" };

let fx: OccurrenceFixture;

/** 奄美（jp-46）の出現を足し、全体の summary を作り直して地域別を導出する。 */
function addAmami(raw: OccurrenceFixture["raw"]): void {
  raw.prepare(
    `INSERT INTO taxon (taxon_id, scientific_name, canonical_binomial, "class", family, rank, taxon_group, vernacular_name_ja, vernacular_name_en, vernacular_ja_basis)
     VALUES (?, 'Fxe eps', 'Fxe eps', 'Aves', 'FamE', 'species', 'FxBird', 'イプシロン鳥', NULL, 'taxa')`,
  ).run(TAXON.e);
  const oc = raw.prepare(
    `INSERT INTO occurrence_agg (region_id, source_id, place_id, place_kind, taxon_id, grain, period_start, period_end, n, n_red_list, n_alien, built_from, spec_version)
     VALUES ('jp-46',?,?,?,?,?,?,?,?,?,?,?,'fixture@1')`,
  );
  const cell = (src: string, place: string | null, kind: string, taxon: string, grain: string, start: string, n: number, red = 0, alien = 0, twin = false) =>
    oc.run(src, place, kind, taxon, grain, start, start, n, red, alien, twin ? TWIN_MARK : "fixture:region-test");
  const grids = [
    [GBIF_A, AG1, TAXON.a, "year", "2000-01-01", 70],
    [GBIF_A, AG2, TAXON.a, "year", "2021-01-01", 25],
    [GBIF_A, AG1, TAXON.a, "month", "2019-07-01", 90],
    [INAT_A, AG1, TAXON.e, "year", "2021-01-01", 120],
    [INAT_A, AG2, TAXON.e, "year", "2000-01-01", 10],
    [INAT_A, AG1, TAXON.c, "year", "2022-01-01", 5],
    [INAT_A, AG2, TAXON.d, "year", "2022-01-01", 4],
  ] as const;
  for (const [src, place, taxon, grain, start, n] of grids) {
    const alien = taxon === TAXON.d ? n : 0;
    cell(src, place, "grid01", taxon, grain, start, n, 0, alien);
    if (grain !== "month") cell(src, null, "watershed", taxon, grain, start, n, 0, alien, true); // 座標のある記録の双子
  }
  cell(GBIF_A, AWS, "watershed", TAXON.a, "year", "2020-01-01", 8, 2);
  // 座標なし（流域に解決できない）記録
  cell(GBIF_A, null, "watershed", TAXON.a, "year", "2021-01-01", 3);

  raw.exec(`
    DELETE FROM summary_taxon_catalog; DELETE FROM summary_watershed_occurrence; DELETE FROM summary_species_catalog;
    DELETE FROM summary_group_year; DELETE FROM summary_effort_year; DELETE FROM summary_grid_catalog;
  `);
  seedSummaries(raw);
  createRegionTables(raw);
  seedPlaceRegion(raw);
  seedOccurrenceByRegion(raw);
}

beforeEach(() => {
  fx = buildOccurrenceFixture();
  // 既存フィクスチャの地域は 'kanagawa'。実データと同じ 'jp-14' にそろえる
  fx.raw.exec(`UPDATE occurrence_agg SET region_id = 'jp-14'`);
  addAmami(fx.raw);
});
afterEach(() => {
  fx.db.close();
});

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

const R14: RegionId = "jp-14";
const R46: RegionId = "jp-46";
const NONE = "jp-99" as RegionId;

describe("region 未指定は既存の表だけを引く", () => {
  it("*_by_region・place_region を一切 SQL に出さない", async () => {
    const db = spyDb(fx.db);
    await speciesCatalog(db, { limit: 5 });
    await occurrenceTotals(db);
    await effortYears(db);
    await taxonGroupYears(db);
    await gridCatalog(db);
    await watershedOccurrence(db);
    await iasSpecies(db);
    await speciesYears(db, [FXO.binoms.alpha]);
    await speciesMonths(db, [FXO.binoms.alpha]);
    await speciesMeshYears(db, FXO.binoms.alpha);
    await speciesShareTrend(db, FXO.groups.bird, { from: 2000, to: 2004 }, { from: 2010, to: 2014 });
    await meshByYear(db, 2021);
    await watershedYears(db);
    await speciesCatalogCounts(db, [FXO.binoms.alpha]);
    for (const c of db.calls) {
      expect(c.sql).not.toContain("_by_region");
      expect(c.sql).not.toContain("place_region");
      expect(c.sql).not.toContain("region_id");
    }
  });
});

describe("事前集計表を読む関数: 地域別の和が全体に一致する", () => {
  it("occurrenceTotals: records は加法、species は地域ごとの種数", async () => {
    const all = await occurrenceTotals(fx.db);
    const k = await occurrenceTotals(fx.db, R14);
    const a = await occurrenceTotals(fx.db, R46);
    expect(a.records).toBeGreaterThan(0);
    expect(k.records + a.records).toBe(all.records);
    expect(k.gbif + a.gbif).toBe(all.gbif);
    expect(k.inat + a.inat).toBe(all.inat);
    expect(k.grids + a.grids).toBe(all.grids);
    // 奄美の種: alpha・gamma・delta・epsilon。alpha などは両地域に居るので、和は全体より大きい
    expect(a.species).toBe(4);
    expect(k.species + a.species).toBeGreaterThan(all.species);
    expect(a.gbif).toBe(70 + 25 + 8 + 3); // 奄美の GBIF（流域系列の n。双子込みで年セルの和）
  });

  it("speciesCatalog: 地域の種だけ。加法の測度は和が全体に一致する", async () => {
    const all = await speciesCatalog(fx.db, { limit: 1000 });
    const k = await speciesCatalog(fx.db, { limit: 1000, region: R14 });
    const a = await speciesCatalog(fx.db, { limit: 1000, region: R46 });
    const names = (rows: { binom: string }[]) => rows.map((r) => r.binom);
    expect(names(a)).toContain("Fxe eps");
    expect(names(k)).not.toContain("Fxe eps");
    for (const g of all) {
      const nSum = (k.find((r) => r.binom === g.binom)?.n ?? 0) + (a.find((r) => r.binom === g.binom)?.n ?? 0);
      expect(nSum).toBe(g.n);
    }
    // group・search・limit を併用しても params がずれない
    const bird = await speciesCatalog(fx.db, { region: R46, group: FXO.groups.bird, search: "eps", limit: 3 });
    expect(names(bird)).toEqual(["Fxe eps"]);
    // 並び順は n DESC
    expect(a.map((r) => r.n)).toEqual([...a.map((r) => r.n)].sort((x, y) => y - x));
  });

  it("speciesCatalog({ region, sourceIds }): occurrence_agg を直接集計し、地域と出典の積で絞る", async () => {
    const hit = await speciesCatalog(fx.db, { region: R46, sourceIds: [GBIF_A, INAT_A] });
    expect(hit.map((r) => r.binom)).toContain("Fxe eps");
    const viaTable = await speciesCatalog(fx.db, { region: R46, limit: 1000 });
    expect(new Map(hit.map((r) => [r.binom, r.n]))).toEqual(new Map(viaTable.map((r) => [r.binom, r.n])));
    // 地域と出典が食い違えば空
    expect(await speciesCatalog(fx.db, { region: R14, sourceIds: [GBIF_A, INAT_A] })).toEqual([]);
    // 未指定の地域 + sourceIds は従来どおり
    expect((await speciesCatalog(fx.db, { sourceIds: [GBIF_A] })).map((r) => r.binom)).toContain(FXO.binoms.alpha);
  });

  it("effortYears: n は加法、nGbif/nInat は地域の出典だけ", async () => {
    const all = await effortYears(fx.db, { from: 1990, to: 2026 });
    const k = await effortYears(fx.db, { from: 1990, to: 2026, region: R14 });
    const a = await effortYears(fx.db, { from: 1990, to: 2026, region: R46 });
    const sum = (rows: { n: number }[]) => rows.reduce((s, r) => s + r.n, 0);
    expect(sum(k) + sum(a)).toBe(sum(all));
    expect(a.reduce((s, r) => s + r.nGbif, 0)).toBe(70 + 25 + 8 + 3);
    expect(k.every((r) => r.nGbif >= 0)).toBe(true);
    expect(sum(a)).toBe(a.reduce((s, r) => s + r.nGbif + r.nInat, 0));
  });

  it("taxonGroupYears: 出典で絞られる（表は変えない）", async () => {
    const tot = (rows: { n: number }[]) => rows.reduce((s, r) => s + r.n, 0);
    const all = await taxonGroupYears(fx.db, { from: 1990, to: 2026 });
    const k = await taxonGroupYears(fx.db, { from: 1990, to: 2026, region: R14 });
    const a = await taxonGroupYears(fx.db, { from: 1990, to: 2026, region: R46 });
    expect(tot(k) + tot(a)).toBe(tot(all));
    expect(tot(a)).toBeGreaterThan(0);
  });

  it("gridCatalog・watershedOccurrence: place_region で絞る（流域外の行は地域に帰属しない）", async () => {
    const all = await gridCatalog(fx.db);
    const k = await gridCatalog(fx.db, R14);
    const a = await gridCatalog(fx.db, R46);
    expect(a.map((g) => g.placeId).sort()).toEqual([AG1, AG2]);
    expect(k.length + a.length).toBe(all.length);

    const wAll = await watershedOccurrence(fx.db);
    const wK = await watershedOccurrence(fx.db, R14);
    const wA = await watershedOccurrence(fx.db, R46);
    expect(wA.watersheds.map((w) => w.placeId)).toEqual([AWS]);
    expect(wA.outsideWatershed).toBeNull();
    expect(wK.watersheds.length + wA.watersheds.length).toBe(wAll.watersheds.length);
  });

  it("iasSpecies: 件数は地域のもの", async () => {
    const all = await iasSpecies(fx.db);
    const k = await iasSpecies(fx.db, R14);
    const a = await iasSpecies(fx.db, R46);
    const delta = (rows: typeof all) => rows.filter((r) => r.binom === "Fxd delta");
    expect(delta(a).length).toBeGreaterThan(0);
    expect(delta(k).reduce((s, r) => s + r.n, 0) + delta(a).reduce((s, r) => s + r.n, 0)).toBe(delta(all).reduce((s, r) => s + r.n, 0));
    // 2020 年以降の件数も地域のもの
    expect(delta(a)[0]!.nSince).toBe(4);
    expect(delta(all)[0]!.nSince).toBe(delta(k)[0]!.nSince + 4);
  });

  it("地域が空・place_region に無い地域は 0 行（例外にしない）", async () => {
    expect(await speciesCatalog(fx.db, { region: NONE })).toEqual([]);
    expect(await effortYears(fx.db, { region: NONE })).toEqual([]);
    expect(await occurrenceTotals(fx.db, NONE)).toEqual({ records: 0, species: 0, grids: 0, gbif: 0, inat: 0 });
    expect(await gridCatalog(fx.db, NONE)).toEqual([]);
    expect(await watershedOccurrence(fx.db, NONE)).toEqual({ watersheds: [], outsideWatershed: null });
    expect(await iasSpecies(fx.db, NONE)).toEqual([]);
  });
});

describe("種ごとの問い合わせ: o.region_id の残差条件", () => {
  it("speciesYears: 和が全体に一致し、奄美は奄美の出典の件数だけ", async () => {
    const all = await speciesYears(fx.db, [FXO.binoms.alpha], { from: 1990, to: 2026 });
    const k = await speciesYears(fx.db, [FXO.binoms.alpha], { from: 1990, to: 2026, region: R14 });
    const a = await speciesYears(fx.db, [FXO.binoms.alpha], { from: 1990, to: 2026, region: R46 });
    const tot = (rows: { n: number }[]) => rows.reduce((s, r) => s + r.n, 0);
    expect(tot(k) + tot(a)).toBe(tot(all));
    expect(a.map((r) => r.year)).toEqual([2000, 2020, 2021]);
    // sourceIds との併用
    const both = await speciesYears(fx.db, [FXO.binoms.alpha], { from: 1990, to: 2026, region: R46, sourceIds: [GBIF_A] });
    expect(tot(both)).toBe(tot(a));
  });

  it("speciesMonths・speciesMeshYears・speciesCatalogCounts: 足切りは地域の件数で判定する", async () => {
    const m = await speciesMonths(fx.db, [FXO.binoms.alpha], { region: R46 });
    expect(m).toEqual([{ binom: FXO.binoms.alpha, month: 7, n: 90 }]);
    const mk = await speciesMonths(fx.db, [FXO.binoms.alpha], { region: R14 });
    expect(mk.find((r) => r.month === 3)?.n).toBe(40);
    // 奄美の alpha は座標あり 70+25+90=185 ≥ 80、神奈川の beta は奄美に居ないので足切りの前に空
    const mesh = await speciesMeshYears(fx.db, FXO.binoms.alpha, { region: R46 });
    expect(mesh.length).toBeGreaterThan(0);
    expect(await speciesMeshYears(fx.db, FXO.binoms.beta, { region: R46 })).toEqual([]);
    const c = await speciesCatalogCounts(fx.db, [FXO.binoms.alpha, "Fxe eps"], { region: R46 });
    expect(c.get(FXO.binoms.alpha)?.n).toBe(70 + 25 + 8 + 3);
    expect(c.has("Fxe eps")).toBe(true);
    expect((await speciesCatalogCounts(fx.db, ["Fxe eps"], { region: R14 })).size).toBe(0);
  });

  it("speciesShareTrend: 奄美の期間 A/B だけ", async () => {
    const rows = await speciesShareTrend(fx.db, FXO.groups.bird, { from: 2000, to: 2004 }, { from: 2020, to: 2024 }, { region: R46 });
    // alpha: A=70, B=25（足切り n_a>=40 かつ n_b>=20）。epsilon: A=10 で足切り
    expect(rows.map((r) => r.binom)).toEqual([FXO.binoms.alpha]);
    expect(rows[0]).toMatchObject({ nA: 70, nB: 25 });
    expect(rows[0]!.totalA).toBe(70 + 10);
  });

  it("meshByYear・watershedYears: 地域のグリッド・流域だけ", async () => {
    const tot = (rows: { n: number }[]) => rows.reduce((s, r) => s + r.n, 0);
    const all = await meshByYear(fx.db, 2021);
    const k = await meshByYear(fx.db, 2021, { region: R14 });
    const a = await meshByYear(fx.db, 2021, { region: R46 });
    expect(tot(k) + tot(a)).toBe(tot(all));
    expect(a.length).toBe(2);
    const w = await watershedYears(fx.db, { region: R46 });
    expect(w.every((r) => r.placeId === AWS)).toBe(true);
    // placeId・sourceIds と併用
    expect(await watershedYears(fx.db, { region: R14, placeId: AWS })).toEqual([]);
  });
});

describe("レッドリスト: 全体と jp-14 は神奈川の版、jp-46 は鹿児島県の版", () => {
  it("redlistSummary", async () => {
    const lists = (rows: { listName: string }[]) => [...new Set(rows.map((r) => r.listName))].sort();
    const all = await redlistSummary(fx.db, FX_VOCAB);
    expect(lists(all)).toEqual(["RL2020", "RL2026"]);
    expect(await redlistSummary(fx.db, FX_VOCAB, R14)).toEqual(all);
    expect(lists(await redlistSummary(fx.db, FX_VOCAB, R46))).toEqual(["KG2014"]);
  });

  it("redlistFlows・redlistSpecies・redlistBundle が region を受ける", async () => {
    expect(await redlistFlows(fx.db, 2020, undefined, FX_VOCAB, R14)).toEqual(await redlistFlows(fx.db, 2020, undefined, FX_VOCAB));
    expect(await redlistFlows(fx.db, 2020, undefined, FX_VOCAB, R46)).toEqual([]);
    expect((await redlistSpecies(fx.db, 2014, undefined, undefined, 300, FX_VOCAB, R46)).map((r) => r.scientificName)).toEqual(["Fxk kappa"]);
    expect(await redlistSpecies(fx.db, 2014, undefined, undefined, 300, FX_VOCAB)).toEqual([]);
    const b = await redlistBundle(fx.db, 2014, { region: R46 }, FX_VOCAB);
    expect(b.summary.map((r) => r.listName)).toEqual(["KG2014"]);
    expect(b.species.length).toBe(1);
    const bAll = await redlistBundle(fx.db, 2020, {}, FX_VOCAB);
    expect(bAll.summary.some((r) => r.listName === "KG2014")).toBe(false);
  });
});
