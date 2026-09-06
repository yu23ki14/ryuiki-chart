#!/usr/bin/env node
/**
 * 派生 DB に空間集計を足す。
 * - watershed_meta: 国土数値情報 W12 流域界（377面）の属性
 * - landuse_watershed: 流域別 土地利用面積 2006 / 2016（10年の変化）
 * - org_watershed / org_watershed_year: 生物観察レコードを流域ポリゴンに点内包判定で割り当てた集計
 *
 * organism_records.site_id は全件 NULL なので、流域との対応は緯度経度からしか作れない。
 * ここで作る対応は「W12ポリゴン(1977年版)への点内包判定の結果」であって、
 * 原本にある属性ではない。画面ではその旨を明示すること。
 */
import Database from "better-sqlite3";
import fs from "node:fs";
import path from "node:path";
import readline from "node:readline";
import { fileURLToPath } from "node:url";
import { parseCsvRows } from "./lib/csv.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(__dirname, "..", "..");
const DB_DIR = path.join(REPO, "data", "db");
const PROCESSED = path.join(REPO, "data", "processed");
const OUT = path.join(DB_DIR, "derived.sqlite");

const t0 = Date.now();
const log = (...a) => console.log(`[${((Date.now() - t0) / 1000).toFixed(1)}s]`, ...a);

const db = new Database(OUT);
db.pragma("journal_mode = WAL");
db.pragma("synchronous = OFF");
db.exec(`ATTACH DATABASE '${path.join(DB_DIR, "ryuiki.sqlite").replace(/'/g, "''")}' AS r`);

/* ---------------- 1. 流域メタ ---------------- */
const wsRows = [];
{
  const jsonl = fs.readFileSync(path.join(PROCESSED, "nlni_w12_watersheds.jsonl"), "utf8").trim().split("\n");
  for (const line of jsonl) {
    const o = JSON.parse(line);
    wsRows.push(o);
  }
}
db.exec(`DROP TABLE IF EXISTS watershed_meta;
CREATE TABLE watershed_meta (
  watershed_id TEXT PRIMARY KEY, water_system_code TEXT, water_system_name TEXT,
  water_system_category TEXT, main_rivers TEXT, area_km2 REAL,
  centroid_lat REAL, centroid_lon REAL, data_year INTEGER, source_ref TEXT
);`);
{
  const ins = db.prepare(
    `INSERT OR REPLACE INTO watershed_meta VALUES (@watershed_id,@water_system_code_old,@water_system_name_ja_estimated,
     @water_system_category_ja,@main_river_names_ja,@area_km2,@centroid_lat,@centroid_lon,@data_year,@source_ref)`,
  );
  db.transaction(() => {
    for (const o of wsRows)
      ins.run({
        watershed_id: o.watershed_id,
        water_system_code_old: o.water_system_code_old ?? null,
        water_system_name_ja_estimated: o.water_system_name_ja_estimated || null,
        water_system_category_ja: o.water_system_category_ja ?? null,
        main_river_names_ja: o.main_river_names_ja ?? null,
        area_km2: o.area_km2 ?? null,
        centroid_lat: o.centroid_lat ?? null,
        centroid_lon: o.centroid_lon ?? null,
        data_year: o.data_year ?? null,
        source_ref: o.source_ref ?? null,
      });
  })();
  log(`watershed_meta ${wsRows.length}`);
}

/* ---------------- 2. 土地利用（流域別・2006/2016） ---------------- */
db.exec(`DROP TABLE IF EXISTS landuse_watershed;
CREATE TABLE landuse_watershed (
  watershed_id TEXT, year INTEGER, landuse_code TEXT, landuse_name TEXT,
  n_cells INTEGER, area_km2 REAL
);`);
{
  const csvText = fs.readFileSync(path.join(PROCESSED, "nlni_l03b_landuse_by_watershed.csv"), "utf8");
  const csv = parseCsvRows(csvText);
  const head = csv[0];
  const idx = Object.fromEntries(head.map((h, i) => [h, i]));
  const ins = db.prepare(`INSERT INTO landuse_watershed VALUES (?,?,?,?,?,?)`);
  db.transaction(() => {
    for (let i = 1; i < csv.length; i++) {
      const c = csv[i];
      ins.run(
        c[idx.watershed_id],
        Number(c[idx.data_year]),
        c[idx.landuse_code_raw],
        c[idx.landuse_name_ja],
        Number(c[idx.n_cells]),
        Number(c[idx.area_km2]),
      );
    }
  })();
  db.exec(`CREATE INDEX ix_lw ON landuse_watershed(watershed_id, year);`);
  log(`landuse_watershed ${csv.length - 1}`);
}

// 2006 → 2016 の変化を横持ちに
db.exec(`DROP TABLE IF EXISTS landuse_change;
CREATE TABLE landuse_change AS
SELECT watershed_id, landuse_name,
       SUM(CASE WHEN year=2006 THEN area_km2 ELSE 0 END) AS km2_2006,
       SUM(CASE WHEN year=2016 THEN area_km2 ELSE 0 END) AS km2_2016,
       SUM(CASE WHEN year=2016 THEN area_km2 ELSE 0 END)
         - SUM(CASE WHEN year=2006 THEN area_km2 ELSE 0 END) AS delta_km2
FROM landuse_watershed GROUP BY watershed_id, landuse_name;
CREATE INDEX ix_lc ON landuse_change(watershed_id);`);
log("landuse_change");

/* ---------------- 3. 点内包判定 ---------------- */
// ポリゴンを読み、0.02度グリッドに bbox で登録してから点ごとに候補だけ判定する
const geo = JSON.parse(fs.readFileSync(path.join(PROCESSED, "nlni_w12_watersheds.geojson"), "utf8"));
log(`geojson features ${geo.features.length}`);

const CELL = 0.02;
const grid = new Map(); // "gx:gy" -> polygon index[]
const polys = [];
for (const f of geo.features) {
  const id = f.properties.watershed_id;
  const rings = [];
  if (f.geometry.type === "Polygon") rings.push(f.geometry.coordinates);
  else if (f.geometry.type === "MultiPolygon") rings.push(...f.geometry.coordinates);
  else continue;
  let minx = Infinity, miny = Infinity, maxx = -Infinity, maxy = -Infinity;
  for (const poly of rings)
    for (const ring of poly)
      for (const [x, y] of ring) {
        if (x < minx) minx = x;
        if (x > maxx) maxx = x;
        if (y < miny) miny = y;
        if (y > maxy) maxy = y;
      }
  const pi = polys.length;
  polys.push({ id, rings, bbox: [minx, miny, maxx, maxy] });
  for (let gx = Math.floor(minx / CELL); gx <= Math.floor(maxx / CELL); gx++)
    for (let gy = Math.floor(miny / CELL); gy <= Math.floor(maxy / CELL); gy++) {
      const k = gx + ":" + gy;
      let a = grid.get(k);
      if (!a) grid.set(k, (a = []));
      a.push(pi);
    }
}
log(`index built: ${polys.length} polygons, ${grid.size} cells`);

function pointInRing(x, y, ring) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const xi = ring[i][0], yi = ring[i][1], xj = ring[j][0], yj = ring[j][1];
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}
function pointInPoly(x, y, p) {
  const [minx, miny, maxx, maxy] = p.bbox;
  if (x < minx || x > maxx || y < miny || y > maxy) return false;
  for (const poly of p.rings) {
    if (!pointInRing(x, y, poly[0])) continue;
    let inHole = false;
    for (let h = 1; h < poly.length; h++) if (pointInRing(x, y, poly[h])) { inHole = true; break; }
    if (!inHole) return true;
  }
  return false;
}
const memo = new Map(); // 0.001度に丸めた座標 -> watershed_id | null
function locate(lon, lat) {
  const key = Math.round(lon * 1000) + ":" + Math.round(lat * 1000);
  if (memo.has(key)) return memo.get(key);
  const cands = grid.get(Math.floor(lon / CELL) + ":" + Math.floor(lat / CELL));
  let hit = null;
  if (cands) for (const pi of cands) if (pointInPoly(lon, lat, polys[pi])) { hit = polys[pi].id; break; }
  memo.set(key, hit);
  return hit;
}

/* 生物レコードを流域に割り当てて集計 */
const rows = db
  .prepare(
    `SELECT lon, lat, CAST(substr(observed_on,1,4) AS INT) AS year, scientific_name, is_alien,
            COALESCE(red_list_category,'') AS rl
     FROM r.organism_records
     WHERE lat IS NOT NULL AND lon IS NOT NULL AND observed_on IS NOT NULL AND LENGTH(observed_on) >= 4`,
  )
  .raw(true);

const agg = new Map(); // ws|year -> {n, alien, rl, species:Set}
let assigned = 0, total = 0;
for (const [lon, lat, year, sci, alien, rl] of rows.iterate()) {
  total++;
  const ws = locate(lon, lat);
  if (!ws) continue;
  assigned++;
  const k = ws + "|" + year;
  let a = agg.get(k);
  if (!a) agg.set(k, (a = { n: 0, alien: 0, rl: 0, species: new Set() }));
  a.n++;
  if (alien) a.alien++;
  if (rl) a.rl++;
  if (sci) a.species.add(sci);
  if (total % 200000 === 0) log(`  ${total} 点処理 (割当 ${assigned})`);
}
log(`point-in-polygon done: ${assigned}/${total} 割当 (${((assigned / total) * 100).toFixed(1)}%), memo ${memo.size}`);

db.exec(`DROP TABLE IF EXISTS org_watershed_year;
CREATE TABLE org_watershed_year (
  watershed_id TEXT, year INTEGER, n INTEGER, species_n INTEGER, alien_n INTEGER, redlist_n INTEGER
);`);
{
  const ins = db.prepare(`INSERT INTO org_watershed_year VALUES (?,?,?,?,?,?)`);
  db.transaction(() => {
    for (const [k, a] of agg) {
      const [ws, y] = k.split("|");
      ins.run(ws, Number(y), a.n, a.species.size, a.alien, a.rl);
    }
  })();
  db.exec(`CREATE INDEX ix_owy ON org_watershed_year(watershed_id, year);
           DROP TABLE IF EXISTS org_watershed;
           CREATE TABLE org_watershed AS
           SELECT watershed_id, SUM(n) AS n, SUM(alien_n) AS alien_n, SUM(redlist_n) AS redlist_n,
                  MIN(year) AS y_from, MAX(year) AS y_to
           FROM org_watershed_year GROUP BY watershed_id;
           CREATE INDEX ix_ow ON org_watershed(watershed_id);`);
  log(`org_watershed_year ${agg.size}`);
}

/* 流域ごとの通算種数（年をまたいだユニーク種）は別途 */
db.exec(`DROP TABLE IF EXISTS watershed_rollup;
CREATE TABLE watershed_rollup AS
SELECT w.watershed_id, w.water_system_name, w.area_km2,
       w.centroid_lat, w.centroid_lon,
       COALESCE(o.n,0) AS org_n, COALESCE(o.alien_n,0) AS org_alien_n,
       COALESCE(o.redlist_n,0) AS org_redlist_n,
       (SELECT COUNT(*) FROM r.sites s WHERE s.watershed = w.watershed_id) AS site_n,
       (SELECT COUNT(*) FROM r.sites s JOIN site_var v ON v.site_id = s.site_id
         WHERE s.watershed = w.watershed_id) AS site_var_n,
       (SELECT SUM(area_km2) FROM landuse_watershed l WHERE l.watershed_id = w.watershed_id AND l.year = 2016
          AND l.landuse_name = '建物用地') AS built_km2_2016,
       (SELECT SUM(area_km2) FROM landuse_watershed l WHERE l.watershed_id = w.watershed_id AND l.year = 2006
          AND l.landuse_name = '建物用地') AS built_km2_2006,
       (SELECT SUM(area_km2) FROM landuse_watershed l WHERE l.watershed_id = w.watershed_id AND l.year = 2016
          AND l.landuse_name = '森林') AS forest_km2_2016,
       (SELECT SUM(area_km2) FROM landuse_watershed l WHERE l.watershed_id = w.watershed_id AND l.year = 2006
          AND l.landuse_name = '森林') AS forest_km2_2006,
       (SELECT SUM(area_km2) FROM landuse_watershed l WHERE l.watershed_id = w.watershed_id AND l.year = 2016
          AND l.landuse_name = '田') AS paddy_km2_2016,
       (SELECT SUM(area_km2) FROM landuse_watershed l WHERE l.watershed_id = w.watershed_id AND l.year = 2006
          AND l.landuse_name = '田') AS paddy_km2_2006
FROM watershed_meta w LEFT JOIN org_watershed o USING (watershed_id);
CREATE INDEX ix_wr ON watershed_rollup(watershed_id);`);
log("watershed_rollup");

db.close();
console.log("→", OUT, (fs.statSync(OUT).size / 1e6).toFixed(1), "MB");
