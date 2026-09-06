#!/usr/bin/env node
/**
 * 生物レコードの正規化と集計を派生 DB に作る。
 *
 * 原本の癖への対処（すべて data 探索で確認した事実に基づく）:
 *  - iNaturalist の 165,332 件は kingdom/class/phylum が全て NULL。
 *    学名の先頭2語（二名法キー）で GBIF 側の分類を引き当てて補完する（96%回復）。
 *  - 魚類は class に存在しない（Actinopterygii が無く NULL になっている）。
 *    phylum='Chordata' かつ class が空/軟骨魚系のものを魚類とする。
 *  - is_alien フラグは同一種内で不整合。外来種は taxa.ias_category を二名法で
 *    結合して判定する。国内由来外来種のエントリが誤ヒットする種は明示除外。
 *  - 件数の経年変化は観察努力そのもの。分類群内シェアとメッシュ占有率を併せて持つ。
 */
import Database from "better-sqlite3";
import path from "node:path";
import fs from "node:fs";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DB_DIR = path.resolve(__dirname, "..", "..", "data", "db");
const OUT = path.join(DB_DIR, "derived.sqlite");

const t0 = Date.now();
const log = (...a) => console.log(`[${((Date.now() - t0) / 1000).toFixed(1)}s]`, ...a);

const db = new Database(OUT);
db.pragma("journal_mode = WAL");
db.pragma("synchronous = OFF");
db.pragma("cache_size = -400000");
db.pragma("temp_store = MEMORY");
db.exec(`ATTACH DATABASE '${path.join(DB_DIR, "ryuiki.sqlite").replace(/'/g, "''")}' AS r`);

const run = (label, sql) => {
  const s = Date.now();
  db.exec(sql);
  log(`${label} (${((Date.now() - s) / 1000).toFixed(1)}s)`);
};

/** 学名から二名法キー（先頭2語）を取る SQL 式 */
const BINOM = (col) => `
  CASE WHEN instr(${col},' ')=0 THEN ${col}
    ELSE substr(${col},1,instr(${col},' ')-1)||' '||
      CASE WHEN instr(substr(${col},instr(${col},' ')+1),' ')=0
           THEN substr(${col},instr(${col},' ')+1)
           ELSE substr(substr(${col},instr(${col},' ')+1),1,
                instr(substr(${col},instr(${col},' ')+1),' ')-1) END
  END`;

/** 日本語の分類群名。魚類が class で取れないことへの対処を含む。 */
const TAXON_GROUP = `
  CASE
    WHEN cls='Aves'                                 THEN '鳥類'
    WHEN cls='Mammalia'                             THEN '哺乳類'
    WHEN cls IN ('Squamata','Testudines')           THEN '爬虫類'
    WHEN cls='Amphibia'                             THEN '両生類'
    WHEN phy='Chordata' AND (cls IS NULL OR cls='' OR cls IN ('Elasmobranchii','Myxini','Holocephali'))
                                                    THEN '魚類'
    WHEN cls='Insecta'                              THEN '昆虫類'
    WHEN cls='Arachnida'                            THEN 'クモ・ダニ類'
    WHEN cls IN ('Malacostraca','Maxillopoda','Ostracoda','Branchiopoda') THEN '甲殻類'
    WHEN cls IN ('Gastropoda','Bivalvia','Cephalopoda','Polyplacophora')  THEN '貝類・軟体動物'
    WHEN cls IN ('Magnoliopsida','Liliopsida')      THEN '被子植物'
    WHEN cls IN ('Polypodiopsida','Lycopodiopsida') THEN 'シダ植物'
    WHEN cls IN ('Pinopsida','Cycadopsida','Ginkgoopsida','Gnetopsida') THEN '裸子植物'
    WHEN cls IN ('Bryopsida','Jungermanniopsida','Marchantiopsida','Polytrichopsida',
                 'Sphagnopsida','Anthocerotopsida','Andreaeopsida')      THEN 'コケ植物'
    WHEN kdm='Fungi'                                THEN '菌類'
    WHEN kdm='Plantae'                              THEN 'その他植物・藻類'
    WHEN kdm='Animalia'                             THEN 'その他無脊椎動物'
    ELSE '未判定' END`;

/* ---------------- 1. 正規化テーブル ---------------- */

run(
  "org_norm",
  `DROP TABLE IF EXISTS org_norm;
   CREATE TABLE org_norm AS
   WITH b AS (
     SELECT record_id, source_id,
            observed_on,
            CAST(substr(observed_on,1,4) AS INT) AS yr,
            CASE WHEN length(observed_on) >= 7 THEN CAST(substr(observed_on,6,2) AS INT) END AS mo,
            scientific_name, vernacular_name, lower(taxon_rank) AS rank_l,
            NULLIF(class,'') AS class0, NULLIF(kingdom,'') AS kingdom0, NULLIF(phylum,'') AS phylum0,
            NULLIF("order",'') AS ord, NULLIF(family,'') AS family,
            lat, lon, red_list_category, license_class, is_alien,
            ${BINOM("scientific_name")} AS binom
     FROM r.organism_records
     WHERE observed_on IS NOT NULL AND length(observed_on) >= 4
   ),
   bc AS (
     SELECT binom, class0 AS class, kingdom0 AS kingdom FROM (
       SELECT binom, class0, kingdom0, ROW_NUMBER() OVER (PARTITION BY binom ORDER BY COUNT(*) DESC) rn
       FROM b WHERE class0 IS NOT NULL GROUP BY binom, class0, kingdom0) WHERE rn=1
   ),
   gc AS (
     SELECT g, class FROM (
       SELECT substr(binom,1,CASE WHEN instr(binom,' ')>0 THEN instr(binom,' ')-1 ELSE length(binom) END) g,
              class0 AS class, ROW_NUMBER() OVER (
                PARTITION BY substr(binom,1,CASE WHEN instr(binom,' ')>0 THEN instr(binom,' ')-1 ELSE length(binom) END)
                ORDER BY COUNT(*) DESC) rn
       FROM b WHERE class0 IS NOT NULL GROUP BY g, class0) WHERE rn=1
   ),
   bp AS (
     SELECT binom, phylum FROM (
       SELECT binom, phylum0 AS phylum, ROW_NUMBER() OVER (PARTITION BY binom ORDER BY COUNT(*) DESC) rn
       FROM b WHERE phylum0 IS NOT NULL GROUP BY binom, phylum0) WHERE rn=1
   ),
   j AS (
     SELECT b.*,
            COALESCE(b.class0, bc.class, gc.class) AS cls,
            COALESCE(b.kingdom0, bc.kingdom) AS kdm,
            COALESCE(b.phylum0, bp.phylum) AS phy
     FROM b
     LEFT JOIN bc ON bc.binom = b.binom
     LEFT JOIN gc ON gc.g = substr(b.binom,1,CASE WHEN instr(b.binom,' ')>0 THEN instr(b.binom,' ')-1 ELSE length(b.binom) END)
     LEFT JOIN bp ON bp.binom = b.binom
   )
   SELECT record_id, source_id, yr, mo, binom, scientific_name, vernacular_name, rank_l,
          cls, kdm, phy, ord, family, lat, lon,
          CAST(FLOOR(lat*100) AS INT) AS mlat, CAST(FLOOR(lon*100) AS INT) AS mlon,
          red_list_category, license_class, is_alien,
          ${TAXON_GROUP} AS taxon_group
   FROM j;
   CREATE INDEX ix_on_binom ON org_norm(binom, yr);
   CREATE INDEX ix_on_grp ON org_norm(taxon_group, yr);
   CREATE INDEX ix_on_mesh ON org_norm(mlat, mlon);
   CREATE INDEX ix_on_yr ON org_norm(yr);`,
);

/* ---------------- 2. 集計 ---------------- */

run(
  "org_group_year",
  `DROP TABLE IF EXISTS org_group_year;
   CREATE TABLE org_group_year AS
   SELECT yr AS year, taxon_group, source_id,
          COUNT(*) AS n, COUNT(DISTINCT binom) AS species_n,
          COUNT(DISTINCT mlat||'_'||mlon) AS mesh_n
   FROM org_norm WHERE yr BETWEEN 1970 AND 2026
   GROUP BY yr, taxon_group, source_id;
   CREATE INDEX ix_ogy ON org_group_year(year);`,
);

run(
  "effort_year",
  `DROP TABLE IF EXISTS effort_year;
   CREATE TABLE effort_year AS
   SELECT yr AS year, COUNT(*) AS n, COUNT(DISTINCT binom) AS species_n,
          COUNT(DISTINCT mlat||'_'||mlon) AS mesh_n,
          SUM(CASE WHEN source_id='inaturalist_kanagawa' THEN 1 ELSE 0 END) AS n_inat,
          SUM(CASE WHEN source_id='gbif_kanagawa_occurrences' THEN 1 ELSE 0 END) AS n_gbif
   FROM org_norm WHERE yr BETWEEN 1970 AND 2026 GROUP BY yr;`,
);

run(
  "species2",
  `DROP TABLE IF EXISTS species2;
   CREATE TABLE species2 AS
   SELECT binom,
          MAX(taxon_group) AS taxon_group, MAX(cls) AS cls, MAX(family) AS family,
          MAX(COALESCE(NULLIF(vernacular_name,''),'')) AS en_name,
          MAX(COALESCE(red_list_category,'')) AS red_list_category,
          COUNT(*) AS n, MIN(yr) AS y_from, MAX(yr) AS y_to,
          COUNT(DISTINCT yr) AS n_years,
          COUNT(DISTINCT mlat||'_'||mlon) AS mesh_n
   FROM org_norm WHERE binom IS NOT NULL AND binom <> ''
   GROUP BY binom;
   CREATE INDEX ix_sp2 ON species2(n DESC);
   CREATE INDEX ix_sp2_g ON species2(taxon_group, n DESC);`,
);

run(
  "species_year2",
  `DROP TABLE IF EXISTS species_year2;
   CREATE TABLE species_year2 AS
   SELECT binom, yr AS year, COUNT(*) AS n,
          COUNT(DISTINCT mlat||'_'||mlon) AS mesh_n
   FROM org_norm WHERE binom IS NOT NULL AND binom <> '' AND yr BETWEEN 1970 AND 2026
   GROUP BY binom, yr;
   CREATE INDEX ix_sy2 ON species_year2(binom, year);`,
);

run(
  "species_month",
  `DROP TABLE IF EXISTS species_month;
   CREATE TABLE species_month AS
   SELECT binom, mo AS month, COUNT(*) AS n
   FROM org_norm WHERE mo IS NOT NULL AND yr >= 2018 AND binom IN (SELECT binom FROM species2 WHERE n >= 80)
   GROUP BY binom, mo;
   CREATE INDEX ix_spm ON species_month(binom);`,
);

// メッシュ集計（年別・通年）
run(
  "mesh_year",
  `DROP TABLE IF EXISTS mesh_year;
   CREATE TABLE mesh_year AS
   SELECT mlat, mlon, yr AS year, COUNT(*) AS n, COUNT(DISTINCT binom) AS species_n,
          SUM(CASE WHEN red_list_category <> '' AND red_list_category IS NOT NULL THEN 1 ELSE 0 END) AS rl_n
   FROM org_norm WHERE lat IS NOT NULL AND yr BETWEEN 1970 AND 2026
   GROUP BY mlat, mlon, yr;
   CREATE INDEX ix_my2 ON mesh_year(year);`,
);

run(
  "mesh_all",
  `DROP TABLE IF EXISTS mesh_all;
   CREATE TABLE mesh_all AS
   SELECT mlat, mlon, SUM(n) AS n, SUM(rl_n) AS rl_n,
          MIN(year) AS y_from, MAX(year) AS y_to
   FROM mesh_year GROUP BY mlat, mlon;
   DROP TABLE IF EXISTS mesh_species;
   CREATE TABLE mesh_species AS
   SELECT mlat, mlon, COUNT(DISTINCT binom) AS species_n,
          COUNT(DISTINCT CASE WHEN red_list_category <> '' THEN binom END) AS rl_species_n
   FROM org_norm GROUP BY mlat, mlon;`,
);

// 主要種のメッシュ×年（侵入拡大アニメーション用）。n>=80 の種に限る。
run(
  "species_mesh_year",
  `DROP TABLE IF EXISTS species_mesh_year;
   CREATE TABLE species_mesh_year AS
   SELECT binom, yr AS year, mlat, mlon, COUNT(*) AS n
   FROM org_norm
   WHERE binom IN (SELECT binom FROM species2 WHERE n >= 80) AND yr BETWEEN 1970 AND 2026
   GROUP BY binom, yr, mlat, mlon;
   CREATE INDEX ix_smy ON species_mesh_year(binom, year);`,
);

/* ---------------- 3. 外来種（taxa.ias_category 由来） ---------------- */

run(
  "ias_species",
  `DROP TABLE IF EXISTS ias_species;
   CREATE TABLE ias_species AS
   WITH ias AS (
     SELECT DISTINCT ${BINOM("scientific_name")} AS binom, ias_category,
            MAX(vernacular_name_ja) AS name_ja
     FROM r.taxa WHERE ias_category IS NOT NULL AND ias_category <> ''
     GROUP BY binom, ias_category
   )
   SELECT i.ias_category, o.binom, i.name_ja,
          MAX(o.taxon_group) AS taxon_group,
          MAX(COALESCE(NULLIF(o.vernacular_name,''),'')) AS en_name,
          COUNT(*) AS n, COUNT(DISTINCT o.mlat||'_'||o.mlon) AS mesh_n,
          MIN(o.yr) AS y_from, MAX(o.yr) AS y_to,
          SUM(CASE WHEN o.yr >= 2020 THEN 1 ELSE 0 END) AS n_since_2020
   FROM org_norm o JOIN ias i ON i.binom = o.binom
   WHERE o.binom NOT IN (
     -- 国内由来外来種（別地域の個体群）のエントリが二名法で誤ヒットするもの。除外する。
     'Nyctereutes procyonoides','Plantago asiatica','Trypoxylus dichotomus',
     'Morus australis','Apis mellifera','Cervus nippon','Rumex japonicus')
   GROUP BY i.ias_category, o.binom;
   CREATE INDEX ix_ias ON ias_species(n DESC);`,
);

/* ---------------- 4. レッドリスト版間比較 ---------------- */

run(
  "redlist_map",
  `DROP TABLE IF EXISTS redlist_map;
   CREATE TABLE redlist_map (raw TEXT PRIMARY KEY, label TEXT, code TEXT, rank INTEGER);
   INSERT INTO redlist_map (raw,label,code,rank) VALUES
   ('絶滅','絶滅','EX',70),('絶滅（EX）','絶滅','EX',70),('絶滅種','絶滅','EX',70),
   ('絶滅/情報不足','絶滅','EX',70),('絶滅／情報不足','絶滅','EX',70),
   ('野生絶滅','野生絶滅','EW',65),('野生絶滅（EW）','野生絶滅','EW',65),('野生絶滅/情報不足','野生絶滅','EW',65),
   ('絶滅危惧ⅠA類','絶滅危惧IA類','CR',60),('絶滅危惧ⅠＡ類','絶滅危惧IA類','CR',60),
   ('絶滅危惧IA類','絶滅危惧IA類','CR',60),('絶滅危惧ⅠA類（CR）','絶滅危惧IA類','CR',60),
   ('絶滅危惧ⅠＡ類（CR）','絶滅危惧IA類','CR',60),('絶滅危惧IA類（CR）','絶滅危惧IA類','CR',60),
   ('絶滅危惧BⅠＡ類','絶滅危惧IA類','CR',60),
   ('絶滅危惧Ⅰ類','絶滅危惧I類','CR+EN',55),('絶滅危惧Ⅰ類（CR+EN）','絶滅危惧I類','CR+EN',55),
   ('絶滅危惧I類（CR+EN）','絶滅危惧I類','CR+EN',55),
   ('絶滅危惧ⅠB類','絶滅危惧IB類','EN',50),('絶滅危惧ⅠＢ類','絶滅危惧IB類','EN',50),
   ('絶滅危惧IB類','絶滅危惧IB類','EN',50),('絶滅危惧ⅠB類（EN）','絶滅危惧IB類','EN',50),
   ('絶滅危惧ⅠＢ類（EN）','絶滅危惧IB類','EN',50),('絶滅危惧IB類（EN）','絶滅危惧IB類','EN',50),
   ('絶滅危惧Ⅱ類','絶滅危惧II類','VU',40),('絶滅危惧II類','絶滅危惧II類','VU',40),
   ('絶滅危惧Ⅱ類（VU）','絶滅危惧II類','VU',40),('絶滅危惧II類（VU）','絶滅危惧II類','VU',40),
   ('絶滅危B惧Ⅱ類','絶滅危惧II類','VU',40),
   ('絶滅のおそれのある地域個体群','地域個体群','LP',35),('絶滅のおそれのある地域個体群（LP）','地域個体群','LP',35),
   ('準絶滅危惧','準絶滅危惧','NT',30),('準絶滅危惧（NT）','準絶滅危惧','NT',30),
   ('準絶滅危惧/情報不足','準絶滅危惧','NT',30),('減少種','準絶滅危惧','NT',30),
   ('希少種','希少種（2006年版）','RA',25),
   ('注目種','注目種','AT',20),('要注意種','注目種','AT',20),
   ('情報不足','情報不足','DD',10),('情報不足（DD）','情報不足','DD',10),
   ('情報不足Ａ','情報不足','DD',10),('情報不足Ｂ','情報不足','DD',10),
   ('不明種','情報不足','DD',10),('消息不明種','情報不足','DD',10);`,
);

run(
  "redlist_change",
  `DROP TABLE IF EXISTS redlist_change;
   CREATE TABLE redlist_change AS
   WITH n AS (
     SELECT assessment_id, list_name, list_year, taxon_group_ja, taxon_subgroup_ja,
            family_ja, vernacular_name_ja, scientific_name, national_category_ja,
            replace(replace(replace(replace(category_ja,      char(10),''),char(13),''),' ',''),'　','') AS c_raw,
            replace(replace(replace(replace(category_prev_ja, char(10),''),char(13),''),' ',''),'　','') AS p_raw
     FROM r.redlist_assessments
   )
   SELECT n.assessment_id, n.list_name, n.list_year, n.taxon_group_ja, n.taxon_subgroup_ja,
          n.family_ja, n.vernacular_name_ja, n.scientific_name, n.national_category_ja,
          pm.label AS prev_label, pm.code AS prev_code, pm.rank AS prev_rank,
          cm.label AS cur_label,  cm.code AS cur_code,  cm.rank AS cur_rank,
          CASE WHEN pm.rank IS NULL THEN '前回記載なし'
               WHEN cm.rank > pm.rank THEN '悪化'
               WHEN cm.rank < pm.rank THEN '改善'
               ELSE '横ばい' END AS direction
   FROM n
   LEFT JOIN redlist_map pm ON pm.raw = n.p_raw
   LEFT JOIN redlist_map cm ON cm.raw = n.c_raw;
   CREATE INDEX ix_rc ON redlist_change(list_year, direction);`,
);

log("biota tables done");

// 使わなくなった旧集計を落とす
db.exec(`DROP TABLE IF EXISTS org_year; DROP TABLE IF EXISTS org_species_year;
         DROP TABLE IF EXISTS org_species; DROP TABLE IF EXISTS org_grid;
         DROP TABLE IF EXISTS org_grid_all;`);
db.exec("VACUUM");
db.close();
console.log("→", OUT, (fs.statSync(OUT).size / 1e6).toFixed(1), "MB");
