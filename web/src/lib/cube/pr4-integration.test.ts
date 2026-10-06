/**
 * 実 DB 統合テスト（Issue #48 PR-4）。原本のある手元だけで実行する（`describe.skipIf`、
 * `integration.test.ts` と同じ流儀）。
 *
 *   - `watershedRollup`: v1 `watershed_rollup`（`derived.sqlite`）と **全 377 流域・全列で差 0**
 *     （`org_*` を除く。`org_*` は PR-3b の宣言済み差分〔日付なし記録の除外〕があるので、
 *     `watershedOccurrence` と一致することで見る）。
 *   - `docSeriesList`: 414 系列（D1=A。v1 の 470 から値が割れる 56 系列が消える）。
 *   - `overviewCounts`・`landuseHighlight`: v1 と一致。
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import Database from "better-sqlite3";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import type { CubeDb } from "./db";
import { sqliteCubeDb } from "./db-sqlite";
import { landuseHighlight, overviewCounts, watershedOccurrence, watershedRollup } from "./catalog";
import { docSeriesList, docSeriesPoints } from "./documents";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DB_DIR = path.resolve(__dirname, "..", "..", "..", "..", "data", "db");
const P = (f: string) => path.join(DB_DIR, f);
const hasRealDb = ["v2.sqlite", "registry.sqlite", "ryuiki.sqlite", "cells.sqlite", "derived.sqlite"].every((f) => fs.existsSync(P(f)));

describe.skipIf(!hasRealDb)("実DB統合テスト（PR-4）: lib/cube と v1 の突合", () => {
  let cube: CubeDb & { close(): void };
  let v1: Database.Database;

  beforeAll(() => {
    cube = sqliteCubeDb({ v2: P("v2.sqlite"), registry: P("registry.sqlite"), ryuiki: P("ryuiki.sqlite"), cells: P("cells.sqlite") });
    v1 = new Database(P("derived.sqlite"), { readonly: true, fileMustExist: true });
  });
  afterAll(() => {
    cube.close();
    v1.close();
  });

  it("watershedRollup: 377 流域・全列（org_* 以外）が v1 watershed_rollup と一致", async () => {
    const r = await watershedRollup(cube);
    const rows = v1.prepare(`SELECT * FROM watershed_rollup ORDER BY watershed_id`).all() as Record<string, number | string | null>[];
    expect(r.watersheds).toHaveLength(377);
    expect(rows).toHaveLength(377);
    expect(r.landuseYears).toEqual({ from: 2006, to: 2016 });

    const diffs: string[] = [];
    rows.forEach((v, i) => {
      const w = r.watersheds[i];
      const pairs: [string, unknown, unknown][] = [
        ["watershed_id", v.watershed_id, w.watershedId],
        ["water_system_name", v.water_system_name, w.waterSystemName],
        ["area_km2", v.area_km2, w.areaKm2],
        ["centroid_lat", v.centroid_lat, w.centroidLat],
        ["centroid_lon", v.centroid_lon, w.centroidLon],
        ["site_n", v.site_n, w.siteN],
        ["built_km2_2006", v.built_km2_2006, w.built.from],
        ["built_km2_2016", v.built_km2_2016, w.built.to],
        ["forest_km2_2006", v.forest_km2_2006, w.forest.from],
        ["forest_km2_2016", v.forest_km2_2016, w.forest.to],
        ["paddy_km2_2006", v.paddy_km2_2006, w.paddy.from],
        ["paddy_km2_2016", v.paddy_km2_2016, w.paddy.to],
      ];
      for (const [k, a, b] of pairs) if ((a ?? null) !== (b ?? null)) diffs.push(`${v.watershed_id}.${k}: v1=${a} v2=${b}`);
    });
    expect(diffs).toEqual([]);
    expect(r.watersheds.reduce((s, w) => s + w.siteN, 0)).toBe(278);
  });

  it("watershedRollup の org_* は watershedOccurrence（PR-3b）と一致。記録の無い流域は 0", async () => {
    const [r, occ] = await Promise.all([watershedRollup(cube), watershedOccurrence(cube)]);
    const byId = new Map(occ.watersheds.map((w) => [w.watershedId, w]));
    for (const w of r.watersheds) {
      const o = byId.get(w.watershedId);
      expect([w.orgN, w.orgAlienN, w.orgRedlistN]).toEqual([o?.orgN ?? 0, o?.orgAlienN ?? 0, o?.orgRedlistN ?? 0]);
    }
    expect(r.outsideWatershed).toEqual(occ.outsideWatershed ? { n: occ.outsideWatershed.n } : null);
  });

  it("landuseHighlight(8) は v1 と同じ 8 流域・同じ順・同じ delta", async () => {
    const mine = await landuseHighlight(cube, 8);
    const old = v1
      .prepare(
        `SELECT watershed_id, water_system_name, (built_km2_2016 - built_km2_2006) AS delta, area_km2
         FROM watershed_rollup WHERE built_km2_2006 IS NOT NULL AND built_km2_2016 IS NOT NULL
         ORDER BY delta DESC LIMIT 8`,
      )
      .all() as { watershed_id: string; water_system_name: string | null; delta: number; area_km2: number }[];
    expect(mine.map((x) => [x.watershedId, x.waterSystemName, x.delta, x.areaKm2])).toEqual(
      old.map((x) => [x.watershed_id, x.water_system_name, x.delta, x.area_km2]),
    );
  });

  it("overviewCounts: sites・sources・watersheds・年の範囲は v1 overviewStats と同じ。variables は 75", async () => {
    const o = await overviewCounts(cube);
    const n = (sql: string) => (v1.prepare(sql).get() as { n: number }).n;
    const ryuiki = new Database(P("ryuiki.sqlite"), { readonly: true, fileMustExist: true });
    try {
      expect(o.sites).toBe((ryuiki.prepare(`SELECT COUNT(*) AS n FROM sites`).get() as { n: number }).n);
      expect(o.sources).toBe((ryuiki.prepare(`SELECT COUNT(*) AS n FROM source_registry`).get() as { n: number }).n);
    } finally {
      ryuiki.close();
    }
    expect(o.watersheds).toBe(n(`SELECT COUNT(*) AS n FROM watershed_meta`));
    expect(o.yFrom).toBe(n(`SELECT MIN(y_from) AS n FROM var_catalog`));
    expect(o.yTo).toBe(n(`SELECT MAX(y_to) AS n FROM var_catalog`));
    expect(o.variables).toBe(75);
  });

  it("docSeriesList: 414 系列（v1 の 470 から、値が割れる 56 系列が消える）。実測 75ms", async () => {
    const t = Date.now();
    const list = await docSeriesList(cube);
    expect(Date.now() - t).toBeLessThan(2000);
    expect(list).toHaveLength(414);
    const v1n = (v1.prepare(`SELECT COUNT(*) AS n FROM doc_series_meta`).get() as { n: number }).n;
    expect(v1n).toBe(470);
    // 並びは n_years DESC, doc_id, table_id, row_key
    for (let i = 1; i < list.length; i++) expect(list[i - 1].nYears).toBeGreaterThanOrEqual(list[i].nYears);
    // 点の数の合計は meta の n_years の合計と一致（meta は点から作る）
    const pts = await docSeriesPoints(cube, list[0].docId, list[0].tableId, list[0].rowKey);
    expect(pts).toHaveLength(list[0].nYears);
  });
});
