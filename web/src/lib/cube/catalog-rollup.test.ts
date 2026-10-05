import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { RFX, buildRollupFixture, type RollupFixture } from "./__fixtures__/rollup-fixture";
import { landuseHighlight, overviewCounts, watershedRollup } from "./catalog";
import type { CubeDb, SqlParam } from "./db";

let fx: RollupFixture;
beforeAll(() => {
  fx = buildRollupFixture();
});
afterAll(() => fx.db.close());

describe("overviewCounts", () => {
  it("sites・sources は表を数え、watersheds は place_kind=watershed、variables は DISTINCT variable_id、年は MIN/MAX", async () => {
    expect(await overviewCounts(fx.db)).toEqual({ sites: 4, sources: 2, watersheds: 5, variables: 3, yFrom: 1973, yTo: 2026 });
  });
});

describe("watershedRollup", () => {
  it("全流域を watershed_id 順に返し、名前・面積・重心は place から", async () => {
    const r = await watershedRollup(fx.db);
    expect(r.watersheds.map((w) => w.watershedId)).toEqual(Object.values(RFX.ws));
    expect(r.watersheds[0]).toMatchObject({ watershedId: RFX.ws.w1, waterSystemName: "多摩川", areaKm2: 20, centroidLat: 35.5, centroidLon: 139.5 });
    expect(r.watersheds[1].waterSystemName).toBeNull();
  });

  it("site_n は within・子が site だけ（grid・overlaps・親が流域でない行は数えない）", async () => {
    const r = await watershedRollup(fx.db);
    expect(r.watersheds.map((w) => w.siteN)).toEqual([2, 1, 0, 0, 0]);
  });

  it("org_* は watershedOccurrence から。記録の無い流域は 0。流域外は outsideWatershed", async () => {
    const r = await watershedRollup(fx.db);
    expect(r.watersheds[0]).toMatchObject({ orgN: 100, orgRedlistN: 7, orgAlienN: 3 });
    expect(r.watersheds[3]).toMatchObject({ orgN: 40, orgRedlistN: 0, orgAlienN: 1 });
    expect(r.watersheds[2]).toMatchObject({ orgN: 0, orgRedlistN: 0, orgAlienN: 0 });
    expect(r.outsideWatershed).toEqual({ n: 9 });
  });

  it("土地利用は year・mean のセルだけ。無い版・無い指標・土地利用の無い流域は null", async () => {
    const r = await watershedRollup(fx.db);
    expect(r.landuseYears).toEqual({ from: 2006, to: 2016 });
    const [w1, w2, w3] = r.watersheds;
    expect(w1.built).toEqual({ from: 10, to: 12 }); // stat=max(999)・grain=month(888) は拾わない
    expect(w1.forest).toEqual({ from: 5, to: 4 });
    expect(w1.paddy).toEqual({ from: 1, to: 0.5 });
    expect(w2.built).toEqual({ from: null, to: 3 });
    expect(w2.forest).toEqual({ from: null, to: null });
    expect(w3.built).toEqual({ from: null, to: null });
  });

  it("版の年は定数ではなくデータから取る（2011/2021 の版でも同じ形）", async () => {
    const other = buildRollupFixture({ years: [2011, 2021] });
    try {
      const r = await watershedRollup(other.db);
      expect(r.landuseYears).toEqual({ from: 2011, to: 2021 });
      expect(r.watersheds[0].built).toEqual({ from: 10, to: 12 });
    } finally {
      other.db.close();
    }
  });

  it("土地利用のセルが1つも無ければ landuseYears は null", async () => {
    const other = buildRollupFixture();
    try {
      other.raw.exec(`DELETE FROM observation_agg`);
      const r = await watershedRollup(other.db);
      expect(r.landuseYears).toBeNull();
      expect(r.watersheds).toHaveLength(5);
      expect(r.watersheds[0].built).toEqual({ from: null, to: null });
    } finally {
      other.db.close();
    }
  });
});

describe("landuseHighlight", () => {
  it("建物用地の増加の降順、同点は watershed_id 順。両方の版が無い流域は除く", async () => {
    const h = await landuseHighlight(fx.db);
    expect(h.map((x) => [x.watershedId, x.delta])).toEqual([
      [RFX.ws.w4, 7],
      [RFX.ws.w1, 2],
      [RFX.ws.w5, 2],
    ]);
    expect(h[0]).toEqual({ watershedId: RFX.ws.w4, waterSystemName: "境川", delta: 7, areaKm2: 16 });
  });

  it("limit で切る（既定 8）", async () => {
    expect(await landuseHighlight(fx.db, 1)).toHaveLength(1);
    expect(await landuseHighlight(fx.db)).toHaveLength(3);
  });
});

/**
 * EXPLAIN の固定（§4.1）。第3索引 `ix_observation_agg_*` が計画を壊さないよう、土地利用の引きは
 * `ix_observation_agg_place_variable_grain` を明示し、place 側を外側にして全走査しない。
 */
describe("EXPLAIN QUERY PLAN の固定（土地利用の引き）", () => {
  it("observation_agg は ix_observation_agg_place_variable_grain を使い、全走査しない", async () => {
    const seen: { sql: string; params: readonly SqlParam[] }[] = [];
    const db: CubeDb = {
      kind: "sqlite",
      async all(sql, params = []) {
        seen.push({ sql, params });
        return fx.db.all(sql, params);
      },
    };
    await watershedRollup(db);
    const queries = seen.filter((q) => /observation_agg/.test(q.sql));
    expect(queries).toHaveLength(1);
    expect(queries[0].sql).toMatch(/INDEXED BY ix_observation_agg_place_variable_grain/);
    const plan = (
      fx.raw.prepare(`EXPLAIN QUERY PLAN ${queries[0].sql}`).all(...(queries[0].params as unknown[])) as { detail: string }[]
    ).map((r) => r.detail);
    const obsPlan = plan.filter((d) => /observation_agg/.test(d));
    expect(obsPlan.some((d) => /USING (COVERING )?INDEX ix_observation_agg_place_variable_grain/.test(d))).toBe(true);
    expect(obsPlan.some((d) => /^SCAN .*observation_agg(?! USING)/.test(d) || /^SCAN o\b(?! USING)/.test(d))).toBe(false);
  });
});
