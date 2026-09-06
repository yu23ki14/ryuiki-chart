#!/usr/bin/env node
/**
 * 派生集計 DB (`data/db/derived.sqlite`) を作る。
 *
 * 原本 (ryuiki.sqlite / cells.sqlite) は一切変更しない。読むだけ。
 * ここで作るのは「原本から機械的に再生成できる集計」だけで、
 * 新しい事実は一切足さない（値の補完・推測をしない）。
 *
 *   node scripts/build-derived.mjs
 */
import Database from "better-sqlite3";
import fs from "node:fs";
import path from "node:path";
import readline from "node:readline";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(__dirname, "..", "..");
const DB_DIR = path.join(REPO, "data", "db");
const PROCESSED = path.join(REPO, "data", "processed");
const OUT = path.join(DB_DIR, "derived.sqlite");

const t0 = Date.now();
const log = (...a) => console.log(`[${((Date.now() - t0) / 1000).toFixed(1)}s]`, ...a);

if (fs.existsSync(OUT)) fs.rmSync(OUT);
for (const suffix of ["-wal", "-shm"]) if (fs.existsSync(OUT + suffix)) fs.rmSync(OUT + suffix);

const db = new Database(OUT);
db.pragma("journal_mode = WAL");
db.pragma("synchronous = OFF");
db.exec(`ATTACH DATABASE '${path.join(DB_DIR, "ryuiki.sqlite").replace(/'/g, "''")}' AS r`);
db.exec(`ATTACH DATABASE '${path.join(DB_DIR, "cells.sqlite").replace(/'/g, "''")}' AS c`);

const run = (label, sql) => {
  const s = Date.now();
  db.exec(sql);
  log(`${label} (${((Date.now() - s) / 1000).toFixed(1)}s)`);
};

/* ================================================================== */
/* 1. 測定値                                                          */
/* ================================================================== */

// 日次: 同一 site+date+variable の重複行を平均で1点に潰す。
// 定量下限未満 (value_raw が '<...') の行数も持ち、フロントで中抜き描画する。
run(
  "meas_daily",
  `CREATE TABLE meas_daily AS
   SELECT site_id, variable,
          measured_on AS d,
          AVG(value) AS value,
          COUNT(*) AS n_raw,
          SUM(CASE WHEN value_raw LIKE '<%' THEN 1 ELSE 0 END) AS n_censored,
          MAX(unit) AS unit
   FROM r.measurements
   WHERE LENGTH(measured_on) = 10 AND value IS NOT NULL
   GROUP BY site_id, variable, measured_on;
   CREATE INDEX ix_md ON meas_daily(variable, site_id, d);
   CREATE INDEX ix_md_site ON meas_daily(site_id, variable, d);`,
);

// 年次: 日次を年に畳んだものと、原本にある「年度集計値」(LENGTH=4) を kind で区別して持つ。
run(
  "meas_year",
  `CREATE TABLE meas_year AS
   SELECT site_id, variable, 'daily' AS kind, CAST(substr(d,1,4) AS INT) AS year,
          COUNT(*) AS n, AVG(value) AS avg, MIN(value) AS min, MAX(value) AS max,
          SUM(n_censored) AS n_censored, MAX(unit) AS unit
   FROM meas_daily GROUP BY site_id, variable, year
   UNION ALL
   SELECT site_id, variable, 'annual', CAST(measured_on AS INT),
          COUNT(*), AVG(value), MIN(value), MAX(value),
          SUM(CASE WHEN value_raw LIKE '<%' THEN 1 ELSE 0 END), MAX(unit)
   FROM r.measurements
   WHERE LENGTH(measured_on) = 4 AND value IS NOT NULL
   GROUP BY site_id, variable, measured_on;
   CREATE INDEX ix_my ON meas_year(variable, kind, year);
   CREATE INDEX ix_my_site ON meas_year(site_id, variable, kind, year);`,
);

run(
  "meas_month",
  `CREATE TABLE meas_month AS
   SELECT site_id, variable, substr(d,1,7) AS ym,
          CAST(substr(d,1,4) AS INT) AS year, CAST(substr(d,6,2) AS INT) AS month,
          COUNT(*) AS n, AVG(value) AS avg, MAX(unit) AS unit
   FROM meas_daily GROUP BY site_id, variable, ym;
   CREATE INDEX ix_mm ON meas_month(variable, ym);
   CREATE INDEX ix_mm_site ON meas_month(site_id, variable, ym);`,
);

// 月別平年（季節性）
run(
  "meas_clim",
  `CREATE TABLE meas_clim AS
   SELECT variable, CAST(substr(d,6,2) AS INT) AS month,
          COUNT(*) AS n, AVG(value) AS avg,
          MIN(value) AS min, MAX(value) AS max, MAX(unit) AS unit
   FROM meas_daily GROUP BY variable, month;`,
);

// ゾーン別（Ridge to Reef）。zone が付いている地点だけ。
run(
  "zone_year",
  `CREATE TABLE zone_year AS
   SELECT s.zone, y.variable, y.kind, y.year,
          COUNT(DISTINCT y.site_id) AS n_sites, SUM(y.n) AS n,
          AVG(y.avg) AS avg, MAX(y.unit) AS unit
   FROM meas_year y JOIN r.sites s USING (site_id)
   WHERE s.zone IS NOT NULL
   GROUP BY s.zone, y.variable, y.kind, y.year;
   CREATE INDEX ix_zy ON zone_year(variable, kind, year);`,
);

run(
  "zone_clim",
  `CREATE TABLE zone_clim AS
   SELECT s.zone, m.variable, m.month, COUNT(DISTINCT m.site_id) AS n_sites,
          SUM(m.n) AS n, AVG(m.avg) AS avg, MAX(m.unit) AS unit
   FROM meas_month m JOIN r.sites s USING (site_id)
   WHERE s.zone IS NOT NULL
   GROUP BY s.zone, m.variable, m.month;`,
);

// 変数カタログ（画面の選択肢の元）
run(
  "var_catalog",
  `CREATE TABLE var_catalog AS
   SELECT variable,
          MAX(unit) AS unit,
          SUM(n) AS n,
          COUNT(DISTINCT site_id) AS n_sites,
          MIN(year) AS y_from, MAX(year) AS y_to,
          SUM(CASE WHEN kind='daily' THEN n ELSE 0 END) AS n_daily,
          SUM(CASE WHEN kind='annual' THEN n ELSE 0 END) AS n_annual,
          SUM(n_censored) AS n_censored
   FROM meas_year GROUP BY variable;`,
);

// 地点 × 変数（地点カルテで「この地点は何を測っているか」）
run(
  "site_var",
  `CREATE TABLE site_var AS
   SELECT site_id, variable, kind, SUM(n) AS n, MIN(year) AS y_from, MAX(year) AS y_to,
          AVG(avg) AS avg, MAX(unit) AS unit
   FROM meas_year GROUP BY site_id, variable, kind;
   CREATE INDEX ix_sv ON site_var(site_id);
   CREATE INDEX ix_sv_var ON site_var(variable);`,
);

/* ================================================================== */
/* 2. センサー時系列                                                  */
/* ================================================================== */

// 相模原の雨量は 0.1mm 単位（原本に unit の記載がないので、ここで mm に直したことを明示する）
run(
  "rain_daily",
  `CREATE TABLE rain_daily AS
   SELECT substr(phenomenon_time,1,10) AS d,
          ROUND(SUM(result)/10.0, 2) AS mm, COUNT(*) AS n_hours
   FROM r.sensor_timeseries
   WHERE datastream = 'RAIN' AND result IS NOT NULL
   GROUP BY d;
   CREATE INDEX ix_rain ON rain_daily(d);`,
);

run(
  "sensor_daily",
  `CREATE TABLE sensor_daily AS
   SELECT site_id, datastream, substr(phenomenon_time,1,10) AS d,
          COUNT(*) AS n, AVG(result) AS avg, MIN(result) AS min, MAX(result) AS max,
          MAX(unit) AS unit
   FROM r.sensor_timeseries
   WHERE LENGTH(phenomenon_time) >= 10 AND result IS NOT NULL
   GROUP BY site_id, datastream, d;
   CREATE INDEX ix_sd ON sensor_daily(datastream, d);`,
);

// 時刻 × 月 のヒートマップ用（光化学オキシダントの日変化・季節変化）
run(
  "sensor_hour_month",
  `CREATE TABLE sensor_hour_month AS
   SELECT datastream,
          CAST(substr(phenomenon_time,6,2) AS INT) AS month,
          CAST(substr(phenomenon_time,12,2) AS INT) AS hour,
          COUNT(*) AS n, AVG(result) AS avg, MAX(result) AS max
   FROM r.sensor_timeseries
   WHERE LENGTH(phenomenon_time) >= 13 AND result IS NOT NULL
   GROUP BY datastream, month, hour;`,
);

/* ================================================================== */
/* 3. 生物レコード                                                    */
/* ================================================================== */

run(
  "org_year",
  `CREATE TABLE org_year AS
   SELECT CAST(substr(observed_on,1,4) AS INT) AS year,
          COALESCE(NULLIF(kingdom,''),'(不明)') AS kingdom,
          COALESCE(NULLIF(class,''),'(不明)') AS class,
          source_id,
          COUNT(*) AS n, COUNT(DISTINCT scientific_name) AS species_n,
          SUM(is_alien) AS alien_n
   FROM r.organism_records
   WHERE observed_on IS NOT NULL AND LENGTH(observed_on) >= 4
   GROUP BY year, kingdom, class, source_id;
   CREATE INDEX ix_oy ON org_year(year);`,
);

run(
  "org_species_year",
  `CREATE TABLE org_species_year AS
   SELECT scientific_name,
          CAST(substr(observed_on,1,4) AS INT) AS year,
          COUNT(*) AS n,
          MAX(COALESCE(NULLIF(vernacular_name,''), '')) AS vernacular_name,
          MAX(COALESCE(NULLIF(class,''), '')) AS class,
          MAX(COALESCE(NULLIF(kingdom,''), '')) AS kingdom,
          MAX(is_alien) AS is_alien,
          MAX(COALESCE(red_list_category,'')) AS red_list_category
   FROM r.organism_records
   WHERE scientific_name IS NOT NULL AND scientific_name <> ''
     AND observed_on IS NOT NULL AND LENGTH(observed_on) >= 4
   GROUP BY scientific_name, year;
   CREATE INDEX ix_osy ON org_species_year(scientific_name);
   CREATE INDEX ix_osy_y ON org_species_year(year);`,
);

run(
  "org_species",
  `CREATE TABLE org_species AS
   SELECT scientific_name,
          MAX(vernacular_name) AS vernacular_name,
          MAX(class) AS class, MAX(kingdom) AS kingdom,
          MAX(is_alien) AS is_alien, MAX(red_list_category) AS red_list_category,
          SUM(n) AS n, MIN(year) AS y_from, MAX(year) AS y_to,
          COUNT(*) AS n_years
   FROM org_species_year GROUP BY scientific_name;
   CREATE INDEX ix_os_n ON org_species(n DESC);`,
);

// 0.01度メッシュ（約 1.1km × 0.9km）
run(
  "org_grid",
  `CREATE TABLE org_grid AS
   SELECT CAST(FLOOR(lon*100) AS INT) AS gx, CAST(FLOOR(lat*100) AS INT) AS gy,
          CAST(substr(observed_on,1,4) AS INT) AS year,
          COUNT(*) AS n, COUNT(DISTINCT scientific_name) AS species_n,
          SUM(is_alien) AS alien_n
   FROM r.organism_records
   WHERE lat IS NOT NULL AND lon IS NOT NULL
     AND lon BETWEEN 138.8 AND 140.0 AND lat BETWEEN 35.0 AND 35.8
     AND observed_on IS NOT NULL AND LENGTH(observed_on) >= 4
   GROUP BY gx, gy, year;
   CREATE INDEX ix_og ON org_grid(year);`,
);

run(
  "org_grid_all",
  `CREATE TABLE org_grid_all AS
   SELECT gx, gy, SUM(n) AS n, SUM(alien_n) AS alien_n,
          MIN(year) AS y_from, MAX(year) AS y_to
   FROM org_grid GROUP BY gx, gy;`,
);

/* ================================================================== */
/* 4. 品質・ガバナンス                                                */
/* ================================================================== */

run(
  "quality_monthly",
  `CREATE TABLE quality_monthly AS
   SELECT substr(occurred_at,1,7) AS ym,
          SUM(CASE WHEN from_stage IS NULL AND to_stage='暫定' THEN 1 ELSE 0 END) AS submitted,
          SUM(CASE WHEN from_stage='暫定'  AND to_stage='検証済' THEN 1 ELSE 0 END) AS verified,
          SUM(CASE WHEN from_stage='検証済' AND to_stage='公開済' THEN 1 ELSE 0 END) AS published,
          SUM(CASE WHEN from_stage='暫定'  AND to_stage='暫定'  THEN 1 ELSE 0 END) AS returned
   FROM r.quality_transitions GROUP BY ym ORDER BY ym;`,
);

/* ================================================================== */
/* 5. 行政文書の指標系列（cells.sqlite）                              */
/* ================================================================== */

// 4年以上の年度がそろっている数値系列だけを取り出す。
// row_key は表によって行見出しと列見出しが連結されているため、
// 末尾トークン（'|' の後ろ）を表示用ラベルとして別に持つ。
run(
  "doc_series",
  `CREATE TABLE doc_series AS
   WITH num AS (
     SELECT doc_id, table_id, page_no, row_key, col_key, fiscal_year,
            CAST(value AS REAL) AS v, unit
     FROM c.cells
     WHERE superseded = 0 AND is_total = 0
       AND value_type IN ('int','float') AND value IS NOT NULL
       AND fiscal_year IS NOT NULL AND row_key IS NOT NULL AND row_key <> ''
   )
   SELECT doc_id, table_id, page_no, row_key,
          CASE WHEN instr(row_key,'|') > 0
               THEN substr(row_key, length(row_key) - length(replace(substr(row_key, instr(row_key,'|')+1), '|', '')) + 1)
               ELSE row_key END AS label,
          fiscal_year, AVG(v) AS value, COUNT(*) AS n_cells, MAX(unit) AS unit
   FROM num
   GROUP BY doc_id, table_id, row_key, fiscal_year;
   CREATE INDEX ix_ds ON doc_series(doc_id, table_id, row_key);`,
);

run(
  "doc_series_meta",
  `CREATE TABLE doc_series_meta AS
   SELECT s.doc_id, s.table_id, s.row_key, MAX(s.label) AS label, MAX(s.page_no) AS page_no,
          COUNT(*) AS n_years, MIN(s.fiscal_year) AS y_from, MAX(s.fiscal_year) AS y_to,
          MAX(s.unit) AS unit, MIN(s.value) AS v_min, MAX(s.value) AS v_max,
          d.title AS doc_title, d.publisher, d.url, d.license,
          (SELECT COUNT(*) FROM c.notes n WHERE n.doc_id = s.doc_id AND n.blocks_timeseries = 1) AS n_warnings
   FROM doc_series s JOIN c.documents d ON d.doc_id = s.doc_id
   GROUP BY s.doc_id, s.table_id, s.row_key
   HAVING n_years >= 3;
   CREATE INDEX ix_dsm ON doc_series_meta(n_years DESC);`,
);

log("core tables done");
db.close();
console.log("→", OUT, (fs.statSync(OUT).size / 1e6).toFixed(1), "MB");
