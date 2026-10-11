/**
 * 地域で絞る（Issue #93 §4 A2）: 流域ロールアップ・土地利用ハイライト（`place_region` で流域を絞る）。
 */
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { landuseHighlight, overviewCounts, watershedRollup } from "./catalog";
import { buildRollupFixture, RFX, type RollupFixture } from "./__fixtures__/rollup-fixture";
import { createRegionTables, seedPlaceRegion } from "./__fixtures__/region-fixture";

const W6 = "99999-0001";
let fx: RollupFixture;

beforeEach(() => {
  fx = buildRollupFixture({ years: [2006, 2016] });
  const raw = fx.raw;
  // 奄美の流域 w6（建物 1 → 5）。既存の流域はすべて jp-14
  raw.prepare(
    `INSERT INTO place (place_id, region_id, place_kind, name_ja, lat, lon, elevation_m, area_km2, definition_ref, status) VALUES (?,NULL,'watershed','奄美川',28.3,129.5,NULL,8,NULL,NULL)`,
  ).run(RFX.place(W6));
  raw.prepare(`INSERT INTO place_source_ref (place_id, external_key, key_space) VALUES (?,?,'watershed_id')`).run(RFX.place(W6), W6);
  const obs = raw.prepare(
    `INSERT INTO observation_agg
       (region_id, place_id, place_kind, variable_id, obs_stat, unit_id, value_grain, period_start, period_end, grain, input_grain, stat,
        value_zero, value_lod, n, n_censored, n_not_detected, n_places, built_from, spec_version)
     VALUES ('jp-46',?,'watershed',?,'sum','common:unit:km2','year',?,?,'year','year','mean',?,?,1,0,0,1,'fixture','fixture@1')`,
  );
  obs.run(RFX.place(W6), RFX.built, "2010-01-01", "2010-12-31", 1, 1);
  obs.run(RFX.place(W6), RFX.built, "2012-01-01", "2012-12-31", 5, 5);
  raw.prepare(
    `INSERT INTO summary_watershed_occurrence (place_id, n, n_red_list, n_alien, n_taxa, y_from, y_to, built_from, spec_version) VALUES (?,?,?,?,1,2000,2020,'fixture','fixture@1')`,
  ).run(RFX.place(W6), 55, 5, 1);
  createRegionTables(raw);
  seedPlaceRegion(raw);
  // 観測・出現の行を持たない流域（w3 など）も神奈川に属する（実データでは b13 がこれを `place` から補う）
  raw.exec(
    `INSERT INTO place_region (place_id, region_id, built_from, spec_version)
     SELECT place_id, 'jp-14', 'fixture', 'fixture@1' FROM place
     WHERE place_kind = 'watershed' AND place_id NOT IN (SELECT place_id FROM place_region)`,
  );
});
afterEach(() => {
  fx.db.close();
});

describe("watershedRollup の region", () => {
  it("奄美: 奄美の流域だけ。org_* と土地利用の版の年も奄美のもの", async () => {
    const a = await watershedRollup(fx.db, "jp-46");
    expect(a.watersheds.map((w) => w.watershedId)).toEqual([W6]);
    expect(a.watersheds[0]).toMatchObject({ orgN: 55, orgRedlistN: 5 });
    expect(a.landuseYears).toEqual({ from: 2010, to: 2012 });
    expect(a.outsideWatershed).toBeNull();
  });

  it("神奈川: 奄美の流域を含まない。流域数の和が全体に一致する", async () => {
    const all = await watershedRollup(fx.db);
    const k = await watershedRollup(fx.db, "jp-14");
    const a = await watershedRollup(fx.db, "jp-46");
    expect(k.watersheds.map((w) => w.watershedId)).not.toContain(W6);
    expect(k.watersheds.length + a.watersheds.length).toBe(all.watersheds.length);
    // 神奈川の版の年は奄美の年に引きずられない
    expect(k.landuseYears).toEqual({ from: 2006, to: 2016 });
  });

  it("region 未指定は従来どおり（奄美の流域も含む全流域）", async () => {
    const all = await watershedRollup(fx.db);
    expect(all.watersheds.map((w) => w.watershedId)).toContain(W6);
  });
});

describe("landuseHighlight・overviewCounts の region", () => {
  it("landuseHighlight: 地域の流域だけ", async () => {
    const a = await landuseHighlight(fx.db, 8, "jp-46");
    expect(a.map((r) => r.watershedId)).toEqual([W6]);
    expect(a[0]!.delta).toBe(4);
    const k = await landuseHighlight(fx.db, 8, "jp-14");
    expect(k.map((r) => r.watershedId)).not.toContain(W6);
  });

  it("overviewCounts.watersheds は place_region の地域の流域数", async () => {
    const all = await overviewCounts(fx.db);
    const k = await overviewCounts(fx.db, "jp-14");
    const a = await overviewCounts(fx.db, "jp-46");
    expect(a.watersheds).toBe(1);
    expect(k.watersheds + a.watersheds).toBe(all.watersheds);
  });
});
