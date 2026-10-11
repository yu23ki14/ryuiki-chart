/**
 * 地域で絞る（Issue #93）のテスト用部品。`place_region` と `summary_*_by_region` の5表を
 * `docs/plans/REGION_FILTER.md` §3-3 の DDL で自前に作り、キューブ（`observation_agg`/`occurrence_agg`）の
 * 行から b13 と同じ考え方で導出する（手書きの数値を別に持たない）。
 * 担当 D の drizzle マイグレーションを待たない（`CREATE TABLE IF NOT EXISTS`）。
 */
import type Database from "better-sqlite3";

const META = `'fixture:region-fixture', 'fixture@1'`;

export function createRegionTables(db: Database.Database): void {
  db.exec(`
    CREATE TABLE IF NOT EXISTS place_region (
      place_id text NOT NULL, region_id text NOT NULL, built_from text, spec_version text);
    CREATE INDEX IF NOT EXISTS ix_place_region_place ON place_region (place_id);
    CREATE INDEX IF NOT EXISTS ix_place_region_region_place ON place_region (region_id, place_id);
    CREATE TABLE IF NOT EXISTS summary_species_catalog_by_region (
      region_id text NOT NULL, binom text NOT NULL, taxon_group text, "class" text, family text,
      n integer NOT NULL, n_located integer NOT NULL DEFAULT 0, n_red_list integer NOT NULL, n_alien integer NOT NULL, n_places integer NOT NULL,
      y_from integer, y_to integer, n_years integer NOT NULL, built_from text NOT NULL, spec_version text NOT NULL);
    CREATE TABLE IF NOT EXISTS summary_taxon_catalog_by_region (
      region_id text NOT NULL, taxon_id text, n integer NOT NULL, n_red_list integer NOT NULL, n_alien integer NOT NULL, n_places integer NOT NULL,
      y_from integer, y_to integer, n_years integer NOT NULL, built_from text NOT NULL, spec_version text NOT NULL);
    CREATE TABLE IF NOT EXISTS summary_effort_year_by_region (
      region_id text NOT NULL, year integer NOT NULL, n integer NOT NULL, n_binom integer NOT NULL, n_places integer NOT NULL,
      built_from text NOT NULL, spec_version text NOT NULL);
    CREATE TABLE IF NOT EXISTS summary_variable_catalog_by_region (
      region_id text NOT NULL, variable_id text, obs_stat text, unit_id text, value_grain text, grain text, input_grain text,
      n integer NOT NULL, n_places integer NOT NULL, y_from integer, y_to integer, n_censored integer NOT NULL, n_not_detected integer NOT NULL,
      built_from text NOT NULL, spec_version text NOT NULL);
  `);
}

/** `place_region`: 観測・出現のキューブの (place_id, region_id) の和集合。1つの place が2地域に出たら例外（b13 と同じ）。 */
export function seedPlaceRegion(db: Database.Database): void {
  db.exec(`DELETE FROM place_region`);
  db.exec(`
    INSERT INTO place_region (place_id, region_id, built_from, spec_version)
    SELECT DISTINCT place_id, region_id, ${META} FROM (
      SELECT place_id, region_id FROM observation_agg WHERE place_id IS NOT NULL AND region_id IS NOT NULL
      UNION
      SELECT place_id, region_id FROM occurrence_agg WHERE place_id IS NOT NULL AND region_id IS NOT NULL
    )`);
  const dup = db.prepare(`SELECT place_id FROM place_region GROUP BY place_id HAVING COUNT(*) > 1`).all();
  if (dup.length) throw new Error(`place_region: 複数の地域に出る place: ${JSON.stringify(dup)}`);
}

/** `summary_variable_catalog_by_region`: `summary_variable_catalog` と同じ定義に `region_id` を足したもの。 */
export function seedVariableCatalogByRegion(db: Database.Database): void {
  db.exec(`DELETE FROM summary_variable_catalog_by_region`);
  db.exec(`
    INSERT INTO summary_variable_catalog_by_region
      (region_id, variable_id, obs_stat, unit_id, value_grain, grain, input_grain, n, n_places, y_from, y_to, n_censored, n_not_detected, built_from, spec_version)
    SELECT region_id, variable_id, obs_stat, unit_id, value_grain, grain, input_grain,
           SUM(n), COUNT(DISTINCT place_id),
           MIN(CAST(substr(period_start,1,4) AS INTEGER)), MAX(CAST(substr(period_start,1,4) AS INTEGER)),
           SUM(n_censored), SUM(n_not_detected), ${META}
    FROM observation_agg
    WHERE place_kind = 'site' AND grain IN ('year','fiscal_year') AND stat = 'mean' AND region_id IS NOT NULL
    GROUP BY region_id, variable_id, obs_stat, unit_id, value_grain, grain, input_grain`);
}

const YEAR_FAMILY = `o.place_kind = 'grid01' AND o.grain IN ('year','survey_period')`;
const YEAR_BOTH = `o.place_kind IN ('grid01','watershed') AND o.grain IN ('year','survey_period')`;
const IF_WS = (col: string) => `SUM(CASE WHEN o.place_kind = 'watershed' THEN ${col} ELSE 0 END)`;
const PLACES_GRID = `COUNT(DISTINCT CASE WHEN o.place_kind = 'grid01' THEN o.place_id END)`;

/** 種・taxon・努力量の地域別（`occurrence-fixture.ts` の `seedSummaries` と同じ式に `region_id` で GROUP BY を足したもの）。 */
export function seedOccurrenceByRegion(db: Database.Database): void {
  db.exec(`DELETE FROM summary_species_catalog_by_region; DELETE FROM summary_taxon_catalog_by_region; DELETE FROM summary_effort_year_by_region;`);
  db.exec(`
    INSERT INTO summary_species_catalog_by_region
      (region_id, binom, taxon_group, "class", family, n, n_located, n_red_list, n_alien, n_places, y_from, y_to, n_years, built_from, spec_version)
    SELECT o.region_id, t.canonical_binomial, MAX(t.taxon_group), MAX(t."class"), MAX(t.family),
           ${IF_WS("o.n")}, SUM(CASE WHEN o.place_kind = 'grid01' THEN o.n ELSE 0 END), ${IF_WS("o.n_red_list")}, ${IF_WS("o.n_alien")}, ${PLACES_GRID},
           MIN(CAST(substr(o.period_start,1,4) AS INTEGER)), MAX(CAST(substr(o.period_start,1,4) AS INTEGER)),
           COUNT(DISTINCT substr(o.period_start,1,4)), ${META}
    FROM occurrence_agg o JOIN taxon t ON t.taxon_id = o.taxon_id
    WHERE ${YEAR_BOTH} AND t.canonical_binomial IS NOT NULL GROUP BY o.region_id, t.canonical_binomial;

    INSERT INTO summary_taxon_catalog_by_region (region_id, taxon_id, n, n_red_list, n_alien, n_places, y_from, y_to, n_years, built_from, spec_version)
    SELECT o.region_id, o.taxon_id, SUM(o.n), SUM(o.n_red_list), SUM(o.n_alien), COUNT(DISTINCT o.place_id),
           MIN(CAST(substr(o.period_start,1,4) AS INTEGER)), MAX(CAST(substr(o.period_start,1,4) AS INTEGER)),
           COUNT(DISTINCT substr(o.period_start,1,4)), ${META}
    FROM occurrence_agg o WHERE ${YEAR_FAMILY} GROUP BY o.region_id, o.taxon_id;

    INSERT INTO summary_effort_year_by_region (region_id, year, n, n_binom, n_places, built_from, spec_version)
    SELECT o.region_id, CAST(substr(o.period_start,1,4) AS INTEGER), ${IF_WS("o.n")}, COUNT(DISTINCT t.canonical_binomial), ${PLACES_GRID}, ${META}
    FROM occurrence_agg o LEFT JOIN taxon t ON t.taxon_id = o.taxon_id
    WHERE ${YEAR_BOTH} GROUP BY o.region_id, 2;
  `);
}
