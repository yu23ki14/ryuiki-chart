/**
 * 概況・流域・土地利用（`catalog.ts` の `overviewCounts`/`watershedRollup`/`landuseHighlight`、
 * Issue #48 PR-4 §3.3）のテスト用フィクスチャ。in-memory に migrations を当て、`place`・
 * `place_source_ref`・`place_relation`・`sites`・`source_registry`・`observation_agg`（土地利用）・
 * `summary_variable_catalog`・`summary_watershed_occurrence` を手書きで入れる。
 * 面積は 2 進で正確な値（0.5 等）だけを使う（`delta` を `toBe` で比べられる）。
 */
import Database from "better-sqlite3";
import { applyMigrations, wrapSqlite } from "./cube-fixture";
import type { CubeDb } from "../db";

export interface RollupFixture {
  db: CubeDb & { close(): void };
  raw: Database.Database;
}

const PLACE = (id: string) => `common:place:watershed.nlni.${id}`;
export const RFX = {
  ws: { w1: "83030-0001", w2: "83030-0002", w3: "83030-0003", w4: "83030-0004", w5: "83030-0005" },
  place: PLACE,
  built: "common:variable:landuse.building_land",
  forest: "common:variable:landuse.forest",
  paddy: "common:variable:landuse.paddy",
} as const;

interface Lu {
  ws: string;
  variable: string;
  year: number;
  value: number;
  stat?: string;
  grain?: string;
}

export function buildRollupFixture(opts: { years?: [number, number] } = {}): RollupFixture {
  const [y0, y1] = opts.years ?? [2006, 2016];
  const raw = new Database(":memory:");
  applyMigrations(raw);

  const place = raw.prepare(
    `INSERT INTO place (place_id, region_id, place_kind, name_ja, lat, lon, elevation_m, area_km2, definition_ref, status)
     VALUES (?,?,?,?,?,?,NULL,?,NULL,NULL)`,
  );
  const ref = raw.prepare(`INSERT INTO place_source_ref (place_id, external_key, key_space) VALUES (?,?,?)`);
  const watersheds: [string, string | null, number, number, number][] = [
    [RFX.ws.w1, "多摩川", 20, 35.5, 139.5],
    [RFX.ws.w2, null, 8, 35.6, 139.6],
    [RFX.ws.w3, "鶴見川", 4, 35.4, 139.4],
    [RFX.ws.w4, "境川", 16, 35.3, 139.3],
    [RFX.ws.w5, "相模川", 12, 35.2, 139.2],
  ];
  for (const [id, name, area, lat, lon] of watersheds) {
    place.run(PLACE(id), "kanagawa", "watershed", name, lat, lon, area);
    ref.run(PLACE(id), id, "watershed_id");
  }
  // 流域でない place（数えてはいけない）
  place.run("fx:site:1", "kanagawa", "site", "地点1", 35, 139, null);
  place.run("fx:site:2", "kanagawa", "site", "地点2", 35, 139, null);
  place.run("fx:site:3", "kanagawa", "site", "地点3", 35, 139, null);
  place.run("fx:grid:1", "kanagawa", "grid01", null, 35, 139, null);
  place.run("fx:zone:1", "kanagawa", "zone", "ゾーン", null, null, null);

  const rel = raw.prepare(`INSERT INTO place_relation (parent_id, child_id, relation, fraction, basis) VALUES (?,?,?,1.0,NULL)`);
  rel.run(PLACE(RFX.ws.w1), "fx:site:1", "within");
  rel.run(PLACE(RFX.ws.w1), "fx:site:2", "within");
  rel.run(PLACE(RFX.ws.w2), "fx:site:3", "within");
  rel.run(PLACE(RFX.ws.w1), "fx:grid:1", "within"); // 子が site でない
  rel.run("fx:zone:1", "fx:site:1", "within"); // 親が流域でない（流域の行には出ない）
  rel.run(PLACE(RFX.ws.w3), "fx:site:3", "overlaps"); // within でない

  const site = raw.prepare(
    `INSERT INTO sites (site_id, name, name_en, watershed, zone, lat, lon, elevation_m, municipality, muni_code, treatment, established_on, operator, source_id, source_ref, is_synthetic)
     VALUES (?,?,NULL,NULL,1,35,139,1,'x',NULL,NULL,NULL,NULL,NULL,NULL,0)`,
  );
  for (const s of ["fx:site:1", "fx:site:2", "fx:site:3", "fx:site:4"]) site.run(s, s);
  const source = raw.prepare(
    `INSERT INTO source_registry (source_id, name, publisher, url, category, access_method, format, license, redistributable, fetched_at, record_count, notes)
     VALUES (?,?,NULL,NULL,NULL,NULL,NULL,'x',1,NULL,NULL,NULL)`,
  );
  source.run("s1", "出典1");
  source.run("s2", "出典2");

  // 土地利用（year・mean が対象。stat=max・grain=month は引いてはいけない）
  const lu: Lu[] = [
    { ws: RFX.ws.w1, variable: RFX.built, year: y0, value: 10 },
    { ws: RFX.ws.w1, variable: RFX.built, year: y1, value: 12 },
    { ws: RFX.ws.w1, variable: RFX.forest, year: y0, value: 5 },
    { ws: RFX.ws.w1, variable: RFX.forest, year: y1, value: 4 },
    { ws: RFX.ws.w1, variable: RFX.paddy, year: y0, value: 1 },
    { ws: RFX.ws.w1, variable: RFX.paddy, year: y1, value: 0.5 },
    { ws: RFX.ws.w1, variable: RFX.built, year: y1, value: 999, stat: "max" },
    { ws: RFX.ws.w1, variable: RFX.built, year: y1, value: 888, grain: "month" },
    // w2: 新しい版だけ（delta が出ない）
    { ws: RFX.ws.w2, variable: RFX.built, year: y1, value: 3 },
    // w3: 土地利用なし
    // w4: 増加最大
    { ws: RFX.ws.w4, variable: RFX.built, year: y0, value: 1 },
    { ws: RFX.ws.w4, variable: RFX.built, year: y1, value: 8 },
    // w5: w1 と同点（2）。watershed_id 順で w1 が先
    { ws: RFX.ws.w5, variable: RFX.built, year: y0, value: 2 },
    { ws: RFX.ws.w5, variable: RFX.built, year: y1, value: 4 },
  ];
  const obs = raw.prepare(
    `INSERT INTO observation_agg
       (region_id, place_id, place_kind, variable_id, obs_stat, unit_id, value_grain, period_start, period_end, grain, input_grain, stat,
        value_zero, value_lod, n, n_censored, n_not_detected, n_places, built_from, spec_version)
     VALUES ('kanagawa',?,'watershed',?,'sum','common:unit:km2','year',?,?,?,'year',?,?,?,1,0,0,1,'fixture','fixture@1')`,
  );
  for (const r of lu) obs.run(PLACE(r.ws), r.variable, `${r.year}-01-01`, `${r.year}-12-31`, r.grain ?? "year", r.stat ?? "mean", r.value, r.value);
  // 別の指標（土地利用でない）は引かない
  obs.run(PLACE(RFX.ws.w1), "common:variable:landuse.beach", `${y1}-01-01`, `${y1}-12-31`, "year", "mean", 77, 77);

  // 概況: variable_id 3 種、年 1973〜2026
  const cat = raw.prepare(
    `INSERT INTO summary_variable_catalog (variable_id, obs_stat, unit_id, value_grain, grain, input_grain, n, n_places, y_from, y_to, n_censored, n_not_detected, built_from, spec_version)
     VALUES (?,?,NULL,'day','year','day',1,1,?,?,0,0,'fixture','fixture@1')`,
  );
  cat.run("common:variable:water.ss", "mean", 1990, 2026);
  cat.run("common:variable:water.ss", "point", 1973, 2000); // 同じ variable_id（数え直さない）
  cat.run("common:variable:water.bod", "mean", 1995, 2020);
  cat.run("common:variable:weather.precipitation", null, 2001, 2025);

  // org_*: w1 だけ記録あり。place_id NULL は流域に解決できない記録
  const occ = raw.prepare(
    `INSERT INTO summary_watershed_occurrence (place_id, n, n_red_list, n_alien, n_taxa, y_from, y_to, built_from, spec_version)
     VALUES (?,?,?,?,1,2000,2020,'fixture','fixture@1')`,
  );
  occ.run(PLACE(RFX.ws.w1), 100, 7, 3);
  occ.run(PLACE(RFX.ws.w4), 40, 0, 1);
  occ.run(null, 9, 1, 2);

  return { db: wrapSqlite(raw), raw };
}
