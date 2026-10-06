/**
 * serving-diff の v1 側 oracle（Issue #48 PR-4）。`web/src/lib/queries.ts`（PR-3b 時点）の
 * v1 関数を **import 行以外は無変更で** 移したもの。v1 の表（derived/ryuiki/cells）を読む。
 * 画面・API・AI はここを import しない（`v1-references.test.ts` が `web/src` の v1 表参照を
 * ゼロに保つ）。品質・介入・意思決定・機器の関数と Tier 1 は serving-diff の対象外なので移していない。
 * PR-5 で v1 側ごと消える。
 */
import { query, queryOne, queryChunked, ph } from "../v1-db-shim";

/* ------------------------------ 地点 ------------------------------ */

export interface SiteRow {
  site_id: string;
  name: string | null;
  watershed: string | null;
  zone: number | null;
  lat: number;
  lon: number;
  elevation_m: number | null;
  municipality: string | null;
  operator: string | null;
  treatment: string | null;
  established_on: string | null;
  source_id: string | null;
  source_ref: string | null;
  water_system_name: string | null;
  n_meas: number;
  n_var: number;
}

export async function listSites(): Promise<SiteRow[]> {
  return query<SiteRow>(`
    SELECT s.site_id, s.name, s.watershed, s.zone, s.lat, s.lon, s.elevation_m,
           s.municipality, s.operator, s.treatment, s.established_on, s.source_id, s.source_ref,
           w.water_system_name,
           COALESCE(v.n, 0) AS n_meas, COALESCE(v.k, 0) AS n_var
    FROM sites s
    LEFT JOIN watershed_meta w ON w.watershed_id = s.watershed
    LEFT JOIN (SELECT site_id, SUM(n) AS n, COUNT(DISTINCT variable) AS k FROM site_var GROUP BY site_id) v
      ON v.site_id = s.site_id
    ORDER BY s.zone, s.elevation_m DESC
  `);
}

export interface SiteVariable {
  variable: string;
  kind: string;
  n: number;
  y_from: number;
  y_to: number;
  avg: number;
  unit: string | null;
}

export async function siteVariables(siteId: string): Promise<SiteVariable[]> {
  return query<SiteVariable>(
    `SELECT variable, kind, n, y_from, y_to, avg, unit FROM site_var
     WHERE site_id = ? ORDER BY n DESC`,
    [siteId],
  );
}

/* --------------------------- 水域グループ --------------------------- */

export interface WaterBody {
  name: string;
  n_sites: number;
  elev_min: number | null;
  elev_max: number | null;
  zone_min: number | null;
  zone_max: number | null;
  n_meas: number;
  y_from: number | null;
  y_to: number | null;
}

/** 測定値を持つ地点が2つ以上ある「水域・地域」。地点間比較の入口になる。 */
export async function listWaterBodies(): Promise<WaterBody[]> {
  return query<WaterBody>(`
    SELECT s.municipality AS name,
           COUNT(DISTINCT s.site_id) AS n_sites,
           MIN(s.elevation_m) AS elev_min, MAX(s.elevation_m) AS elev_max,
           MIN(s.zone) AS zone_min, MAX(s.zone) AS zone_max,
           SUM(v.n) AS n_meas, MIN(v.y_from) AS y_from, MAX(v.y_to) AS y_to
    FROM sites s
    JOIN (SELECT site_id, SUM(n) AS n, MIN(y_from) AS y_from, MAX(y_to) AS y_to
          FROM site_var GROUP BY site_id) v ON v.site_id = s.site_id
    WHERE s.municipality IS NOT NULL AND s.municipality <> ''
    GROUP BY s.municipality
    HAVING n_sites >= 2
    ORDER BY n_meas DESC
  `);
}

export async function sitesInWaterBody(name: string): Promise<SiteRow[]> {
  return query<SiteRow>(
    `SELECT s.site_id, s.name, s.watershed, s.zone, s.lat, s.lon, s.elevation_m,
            s.municipality, s.operator, s.treatment, s.established_on, s.source_id, s.source_ref,
            NULL AS water_system_name,
            COALESCE(v.n,0) AS n_meas, COALESCE(v.k,0) AS n_var
     FROM sites s
     JOIN (SELECT site_id, SUM(n) AS n, COUNT(DISTINCT variable) AS k FROM site_var GROUP BY site_id) v
       ON v.site_id = s.site_id
     WHERE s.municipality = ?
     ORDER BY s.elevation_m DESC`,
    [name],
  );
}

/* ------------------------------ 測定値 ------------------------------ */

export interface VarCatalogRow {
  variable: string;
  unit: string | null;
  n: number;
  n_sites: number;
  y_from: number;
  y_to: number;
  n_daily: number;
  n_annual: number;
  n_censored: number;
}

export async function variableCatalog(): Promise<VarCatalogRow[]> {
  return query<VarCatalogRow>(`SELECT * FROM var_catalog ORDER BY n DESC`);
}

export interface YearPoint {
  site_id: string;
  year: number;
  n: number;
  avg: number;
  min: number;
  max: number;
  n_censored: number;
  unit: string | null;
}

export async function yearSeries(variable: string, siteIds: string[], kind: "daily" | "annual"): Promise<YearPoint[]> {
  const rows = await queryChunked<YearPoint>(siteIds, (ids) => ({
    sql: `SELECT site_id, year, n, avg, min, max, n_censored, unit FROM meas_year
          WHERE variable = ? AND kind = ? AND site_id IN (${ph(ids)})`,
    params: [variable, kind, ...ids],
  }));
  // 分割して投げるので ORDER BY は効かない。並べ直す。
  return rows.sort((a, b) => a.site_id.localeCompare(b.site_id) || a.year - b.year);
}

export interface MonthPoint {
  site_id: string;
  ym: string;
  year: number;
  month: number;
  n: number;
  avg: number;
}

export async function monthSeries(variable: string, siteIds: string[]): Promise<MonthPoint[]> {
  const rows = await queryChunked<MonthPoint>(siteIds, (ids) => ({
    sql: `SELECT site_id, ym, year, month, n, avg FROM meas_month
          WHERE variable = ? AND site_id IN (${ph(ids)})`,
    params: [variable, ...ids],
  }));
  return rows.sort((a, b) => a.site_id.localeCompare(b.site_id) || a.ym.localeCompare(b.ym));
}

export interface DayPoint {
  site_id: string;
  d: string;
  value: number;
  n_censored: number;
}

export async function daySeries(variable: string, siteIds: string[], from?: string, to?: string): Promise<DayPoint[]> {
  let where = "";
  const tail: unknown[] = [];
  if (from) {
    where += " AND d >= ?";
    tail.push(from);
  }
  if (to) {
    where += " AND d <= ?";
    tail.push(to);
  }
  const rows = await queryChunked<DayPoint>(siteIds, (ids) => ({
    sql: `SELECT site_id, d, value, n_censored FROM meas_daily
          WHERE variable = ? AND site_id IN (${ph(ids)})${where}`,
    params: [variable, ...ids, ...tail],
  }));
  return rows.sort((a, b) => a.site_id.localeCompare(b.site_id) || a.d.localeCompare(b.d));
}

export interface ZonePoint {
  zone: number;
  year: number;
  n_sites: number;
  n: number;
  avg: number;
  unit: string | null;
}

export async function zoneSeries(variable: string, kind: "daily" | "annual"): Promise<ZonePoint[]> {
  return query<ZonePoint>(
    `SELECT zone, year, n_sites, n, avg, unit FROM zone_year
     WHERE variable = ? AND kind = ? ORDER BY zone, year`,
    [variable, kind],
  );
}

export async function zoneClimatology(variable: string) {
  return query<{ zone: number; month: number; n: number; avg: number; unit: string | null }>(
    `SELECT zone, month, n, avg, unit FROM zone_clim WHERE variable = ? ORDER BY zone, month`,
    [variable],
  );
}

export async function climatology(variable: string) {
  return query<{ month: number; n: number; avg: number; min: number; max: number; unit: string | null }>(
    `SELECT month, n, avg, min, max, unit FROM meas_clim WHERE variable = ? ORDER BY month`,
    [variable],
  );
}

/* ------------------------------ 降雨 ------------------------------ */

export async function rainMonthlyClim() {
  return query<{ month: number; mm: number }>(`
    SELECT CAST(substr(d,6,2) AS INT) AS month,
           ROUND(SUM(mm) / COUNT(DISTINCT substr(d,1,4)), 1) AS mm
    FROM rain_daily GROUP BY month ORDER BY month`);
}

/* --------------------------- レッドリスト --------------------------- */

export async function redlistVersions() {
  return query<{ list_name: string; list_year: number; n: number }>(
    `SELECT list_name, list_year, COUNT(*) AS n FROM redlist_assessments
     GROUP BY list_name, list_year ORDER BY list_year`,
  );
}

/* ------------------------------ 流域 ------------------------------ */

export interface WatershedRow {
  watershed_id: string;
  water_system_name: string | null;
  area_km2: number;
  centroid_lat: number;
  centroid_lon: number;
  org_n: number;
  org_alien_n: number;
  org_redlist_n: number;
  site_n: number;
  built_km2_2006: number | null;
  built_km2_2016: number | null;
  forest_km2_2006: number | null;
  forest_km2_2016: number | null;
  paddy_km2_2006: number | null;
  paddy_km2_2016: number | null;
}

export async function watershedRollup(): Promise<WatershedRow[]> {
  return query<WatershedRow>(`SELECT * FROM watershed_rollup`);
}

export interface DocSeriesMeta {
  doc_id: string;
  table_id: string;
  row_key: string;
  label: string;
  page_no: number;
  n_years: number;
  y_from: number;
  y_to: number;
  unit: string | null;
  doc_title: string;
  publisher: string;
  url: string;
  license: string;
  n_warnings: number;
}

export async function docSeriesList(minYears = 4): Promise<DocSeriesMeta[]> {
  return query<DocSeriesMeta>(
    `SELECT * FROM doc_series_meta WHERE n_years >= ? ORDER BY n_years DESC, doc_id, table_id`,
    [minYears],
  );
}

export async function docSeriesPoints(docId: string, tableId: string, rowKey: string) {
  return query<{ fiscal_year: number; value: number; unit: string | null; page_no: number }>(
    `SELECT fiscal_year, value, unit, page_no FROM doc_series
     WHERE doc_id = ? AND table_id = ? AND row_key = ? ORDER BY fiscal_year`,
    [docId, tableId, rowKey],
  );
}

export async function overviewStats() {
  return queryOne<{
    n_sites: number;
    n_meas: number;
    n_org: number;
    n_species: number;
    n_events: number;
    n_sensor: number;
    n_sources: number;
    n_watersheds: number;
    y_from: number;
    y_to: number;
  }>(`
    SELECT
      (SELECT COUNT(*) FROM sites) AS n_sites,
      (SELECT COUNT(*) FROM measurements) AS n_meas,
      (SELECT COUNT(*) FROM organism_records) AS n_org,
      (SELECT COUNT(*) FROM species2) AS n_species,
      (SELECT COUNT(*) FROM events) AS n_events,
      (SELECT COUNT(*) FROM sensor_timeseries) AS n_sensor,
      (SELECT COUNT(*) FROM source_registry) AS n_sources,
      (SELECT COUNT(*) FROM watershed_meta) AS n_watersheds,
      (SELECT MIN(y_from) FROM var_catalog) AS y_from,
      (SELECT MAX(y_to) FROM var_catalog) AS y_to
  `);
}

/* ============================ 生物（正規化後） ============================ */

export async function taxonGroupYears() {
  return query<{ year: number; taxon_group: string; n: number; mesh_n: number }>(`
    SELECT year, taxon_group, SUM(n) AS n, MAX(mesh_n) AS mesh_n
    FROM org_group_year WHERE year BETWEEN 1990 AND 2026
    GROUP BY year, taxon_group ORDER BY year`);
}

export async function effortYears() {
  return query<{ year: number; n: number; species_n: number; mesh_n: number; n_inat: number; n_gbif: number }>(
    `SELECT * FROM effort_year WHERE year BETWEEN 1990 AND 2026 ORDER BY year`,
  );
}

export interface Species2 {
  binom: string;
  taxon_group: string;
  cls: string | null;
  family: string | null;
  en_name: string;
  red_list_category: string;
  n: number;
  y_from: number;
  y_to: number;
  n_years: number;
  mesh_n: number;
}

export async function speciesList(group: string | null, limit = 200): Promise<Species2[]> {
  if (group) {
    return query<Species2>(
      `SELECT * FROM species2 WHERE taxon_group = ? ORDER BY n DESC LIMIT ?`,
      [group, limit],
    );
  }
  return query<Species2>(`SELECT * FROM species2 ORDER BY n DESC LIMIT ?`, [limit]);
}

/**
 * 分類群の中でのシェア（‰）で前後2期間を比べる。
 * 生の件数の比較は観察努力の差をそのまま写してしまうので使わない。
 */
export async function speciesShareTrend(group: string, aFrom: number, aTo: number, bFrom: number, bTo: number) {
  return query<{
    binom: string;
    en_name: string;
    n_a: number;
    n_b: number;
    total_a: number;
    total_b: number;
  }>(
    `WITH t AS (
       SELECT SUM(CASE WHEN y.year BETWEEN ? AND ? THEN y.n ELSE 0 END) AS ta,
              SUM(CASE WHEN y.year BETWEEN ? AND ? THEN y.n ELSE 0 END) AS tb
       FROM species_year2 y JOIN species2 s USING (binom)
       WHERE s.taxon_group = ?
     )
     SELECT s.binom, s.en_name,
            SUM(CASE WHEN y.year BETWEEN ? AND ? THEN y.n ELSE 0 END) AS n_a,
            SUM(CASE WHEN y.year BETWEEN ? AND ? THEN y.n ELSE 0 END) AS n_b,
            (SELECT ta FROM t) AS total_a, (SELECT tb FROM t) AS total_b
     FROM species_year2 y JOIN species2 s USING (binom)
     WHERE s.taxon_group = ?
     GROUP BY s.binom
     HAVING n_a >= 40 AND n_b >= 20`,
    [aFrom, aTo, bFrom, bTo, group, aFrom, aTo, bFrom, bTo, group],
  );
}

export async function speciesYears(binoms: string[]) {
  const rows = await queryChunked<{ binom: string; year: number; n: number; mesh_n: number }>(
    binoms,
    (bs) => ({
      sql: `SELECT binom, year, n, mesh_n FROM species_year2
            WHERE binom IN (${ph(bs)}) AND year BETWEEN 1990 AND 2026`,
      params: bs,
    }),
  );
  return rows.sort((a, b) => a.year - b.year);
}

export async function speciesMonths(binoms: string[]) {
  const rows = await queryChunked<{ binom: string; month: number; n: number }>(binoms, (bs) => ({
    sql: `SELECT binom, month, n FROM species_month WHERE binom IN (${ph(bs)})`,
    params: bs,
  }));
  return rows.sort((a, b) => a.month - b.month);
}

export async function speciesMeshYears(binom: string) {
  return query<{ year: number; mlat: number; mlon: number; n: number }>(
    `SELECT year, mlat, mlon, n FROM species_mesh_year WHERE binom = ? ORDER BY year`,
    [binom],
  );
}

export async function iasSpecies() {
  return query<{
    ias_category: string;
    binom: string;
    name_ja: string | null;
    taxon_group: string;
    en_name: string;
    n: number;
    mesh_n: number;
    y_from: number;
    y_to: number;
    n_since_2020: number;
  }>(`SELECT * FROM ias_species ORDER BY n DESC`);
}

export async function meshAll() {
  return query<{ mlat: number; mlon: number; n: number; rl_n: number; species_n: number; rl_species_n: number }>(`
    SELECT a.mlat, a.mlon, a.n, a.rl_n, s.species_n, s.rl_species_n
    FROM mesh_all a JOIN mesh_species s ON s.mlat = a.mlat AND s.mlon = a.mlon`);
}

export async function meshByYear(year: number) {
  return query<{ mlat: number; mlon: number; n: number; species_n: number; rl_n: number }>(
    `SELECT mlat, mlon, n, species_n, rl_n FROM mesh_year WHERE year = ?`,
    [year],
  );
}

/* --------------------------- レッドリスト版間 --------------------------- */

export async function redlistCategories() {
  return query<{ label: string; code: string; rank: number }>(
    `SELECT DISTINCT label, code, rank FROM redlist_map ORDER BY rank DESC`,
  );
}

export async function redlistFlows(listYear: number, group?: string) {
  const params: unknown[] = [listYear];
  let g = "";
  if (group) {
    g = " AND taxon_group_ja = ?";
    params.push(group);
  }
  return query<{ prev_label: string; cur_label: string; direction: string; n: number }>(
    `SELECT prev_label, cur_label, direction, COUNT(*) AS n FROM redlist_change
     WHERE list_year = ? AND prev_label IS NOT NULL AND cur_label IS NOT NULL${g}
     GROUP BY prev_label, cur_label, direction ORDER BY n DESC`,
    params,
  );
}

export async function redlistSpecies(listYear: number, direction?: string, group?: string, limit = 300) {
  const params: unknown[] = [listYear];
  let w = "";
  if (direction) {
    w += " AND direction = ?";
    params.push(direction);
  }
  if (group) {
    w += " AND taxon_group_ja = ?";
    params.push(group);
  }
  params.push(limit);
  return query<{
    vernacular_name_ja: string;
    scientific_name: string | null;
    family_ja: string | null;
    taxon_group_ja: string;
    prev_label: string;
    cur_label: string;
    prev_rank: number;
    cur_rank: number;
    direction: string;
    national_category_ja: string | null;
  }>(
    `SELECT vernacular_name_ja, scientific_name, family_ja, taxon_group_ja,
            prev_label, cur_label, prev_rank, cur_rank, direction, national_category_ja
     FROM redlist_change
     WHERE list_year = ? AND prev_label IS NOT NULL AND cur_label IS NOT NULL${w}
     ORDER BY (cur_rank - prev_rank) DESC, vernacular_name_ja LIMIT ?`,
    params,
  );
}

export async function redlistSummary() {
  return query<{ list_year: number; list_name: string; taxon_group_ja: string; direction: string; n: number }>(`
    SELECT list_year, list_name, taxon_group_ja, direction, COUNT(*) AS n
    FROM redlist_change GROUP BY list_year, list_name, taxon_group_ja, direction
    ORDER BY list_year, taxon_group_ja`);
}

/** ある項目のデータを実際に持つ「水域・地域」だけを返す（選択肢の絞り込み用） */
export async function waterBodiesForVariable(variable: string) {
  return query<{ name: string; n_sites: number; n: number; y_from: number; y_to: number; elev_max: number | null }>(
    `SELECT s.municipality AS name,
            COUNT(DISTINCT v.site_id) AS n_sites, SUM(v.n) AS n,
            MIN(v.y_from) AS y_from, MAX(v.y_to) AS y_to, MAX(s.elevation_m) AS elev_max
     FROM site_var v JOIN sites s USING (site_id)
     WHERE v.variable = ? AND s.municipality IS NOT NULL AND s.municipality <> ''
     GROUP BY s.municipality
     HAVING n_sites >= 2
     ORDER BY n_sites DESC, n DESC`,
    [variable],
  );
}

/** 一本の川を下るときの水質の変わり方（既定は境川） */
export async function longitudinalHighlight(water = "境川（１）", variable = "生物化学的酸素要求量 BOD") {
  return query<{ site_id: string; name: string; elevation_m: number; zone: number; avg: number; n: number; unit: string | null }>(
    `SELECT s.site_id, s.name, s.elevation_m, s.zone,
            AVG(y.avg) AS avg, SUM(y.n) AS n, MAX(y.unit) AS unit
     FROM meas_year y JOIN sites s USING (site_id)
     WHERE y.variable = ? AND y.kind = 'daily' AND s.municipality = ? AND y.year >= 2020
     GROUP BY s.site_id ORDER BY s.elevation_m DESC`,
    [variable, water],
  );
}

/** 土地利用が最も動いた流域 */
export async function landuseHighlight(limit = 8) {
  return query<{ watershed_id: string; water_system_name: string | null; delta: number; area_km2: number }>(
    `SELECT watershed_id, water_system_name,
            (built_km2_2016 - built_km2_2006) AS delta, area_km2
     FROM watershed_rollup
     WHERE built_km2_2006 IS NOT NULL AND built_km2_2016 IS NOT NULL
     ORDER BY delta DESC LIMIT ?`,
    [limit],
  );
}

export async function biotaTotals() {
  return queryOne<{ records: number; species: number; mesh: number; gbif: number; inat: number }>(`
    SELECT
      (SELECT COUNT(*) FROM organism_records) AS records,
      (SELECT COUNT(*) FROM species2) AS species,
      (SELECT COUNT(*) FROM mesh_all) AS mesh,
      (SELECT COUNT(*) FROM organism_records WHERE source_id='gbif_kanagawa_occurrences') AS gbif,
      (SELECT COUNT(*) FROM organism_records WHERE source_id='inaturalist_kanagawa') AS inat`);
}
