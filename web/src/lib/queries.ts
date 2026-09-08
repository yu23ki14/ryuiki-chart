import "server-only";
import { query, queryOne, queryChunked, ph } from "./db";
import { QUALITY_STAGES } from "./quality";

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

export async function getSite(siteId: string): Promise<SiteRow | undefined> {
  return queryOne<SiteRow>(
    `SELECT s.*, w.water_system_name,
            COALESCE(v.n,0) AS n_meas, COALESCE(v.k,0) AS n_var
     FROM sites s
     LEFT JOIN watershed_meta w ON w.watershed_id = s.watershed
     LEFT JOIN (SELECT site_id, SUM(n) AS n, COUNT(DISTINCT variable) AS k FROM site_var GROUP BY site_id) v
       ON v.site_id = s.site_id
     WHERE s.site_id = ?`,
    [siteId],
  );
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

export async function rainDaily(from: string, to: string) {
  return query<{ d: string; mm: number }>(
    `SELECT d, mm FROM rain_daily WHERE d >= ? AND d <= ? ORDER BY d`,
    [from, to],
  );
}

export async function rainMonthlyClim() {
  return query<{ month: number; mm: number }>(`
    SELECT CAST(substr(d,6,2) AS INT) AS month,
           ROUND(SUM(mm) / COUNT(DISTINCT substr(d,1,4)), 1) AS mm
    FROM rain_daily GROUP BY month ORDER BY month`);
}

export async function rainTopDays(limit = 10) {
  return query<{ d: string; mm: number }>(
    `SELECT d, mm FROM rain_daily ORDER BY mm DESC LIMIT ?`,
    [limit],
  );
}

export async function sensorHourMonth(datastream: string) {
  return query<{ month: number; hour: number; n: number; avg: number; max: number }>(
    `SELECT month, hour, n, avg, max FROM sensor_hour_month WHERE datastream = ? ORDER BY month, hour`,
    [datastream],
  );
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

export async function landuseChange(watershedId: string) {
  return query<{ landuse_name: string; km2_2006: number; km2_2016: number; delta_km2: number }>(
    `SELECT landuse_name, km2_2006, km2_2016, delta_km2 FROM landuse_change
     WHERE watershed_id = ? ORDER BY km2_2016 DESC`,
    [watershedId],
  );
}

/* --------------------------- 品質・ガバナンス --------------------------- */
// `measurements.quality_stage` 等が取りうる3値（暫定→検証済→公開済）は `@/lib/quality` の
// QUALITY_STAGES/QualityStage を正とする。以下の SQL の to_stage/from_stage 判定はこの3値・
// 順序を前提にしているので、文字列を直書きせずここから引く（queries.ts は server-only だが、
// quality.ts は server-only ではないので import できる。docs/plans/PHASE_B_INTAKE.md #6）。
const [STAGE_PROVISIONAL, STAGE_VERIFIED, STAGE_PUBLISHED] = QUALITY_STAGES;

export async function qualityMonthly() {
  return query<{ ym: string; submitted: number; verified: number; published: number; returned: number }>(
    `SELECT * FROM quality_monthly ORDER BY ym`,
  );
}

export async function qualityByActor() {
  return query<{ actor: string; pass: number; reject: number; publish: number }>(`
    SELECT actor,
           SUM(CASE WHEN note LIKE '%合格%' THEN 1 ELSE 0 END) AS pass,
           SUM(CASE WHEN note LIKE '%差し戻し%' THEN 1 ELSE 0 END) AS reject,
           SUM(CASE WHEN to_stage='${STAGE_PUBLISHED}' THEN 1 ELSE 0 END) AS publish
    FROM quality_transitions WHERE actor LIKE 'OBS-%' GROUP BY actor ORDER BY actor`);
}

export async function interventions() {
  return query<{
    intervention_id: string;
    site_id: string;
    kind: string;
    parcel: string;
    quantity: number;
    quantity_unit: string;
    started_on: string;
    finished_on: string;
    operator: string;
    site_name: string | null;
    lat: number | null;
    lon: number | null;
  }>(`
    SELECT i.*, s.name AS site_name, s.lat, s.lon
    FROM interventions i LEFT JOIN sites s USING (site_id) ORDER BY i.started_on`);
}

export async function decisions() {
  return query<{
    decision_id: string;
    meeting_name: string;
    meeting_date: string;
    presented_data: string;
    decided: string;
    stalled_item_resolved: number;
    participants: string;
    site_name: string | null;
    lat: number | null;
    lon: number | null;
  }>(`
    SELECT d.*, s.name AS site_name, s.lat, s.lon
    FROM decisions d
    LEFT JOIN sites s ON s.site_id = json_extract(d.presented_data, '$.site_id')
    ORDER BY d.meeting_date`);
}

export async function observerStats() {
  return query<{ role: string; org: string; n_people: number; n_events: number }>(`
    SELECT o.role, o.org, COUNT(DISTINCT o.observer_id) AS n_people, COUNT(eo.event_id) AS n_events
    FROM observers o LEFT JOIN event_observers eo USING (observer_id)
    GROUP BY o.role, o.org ORDER BY o.role, n_events DESC`);
}

export async function instrumentStats() {
  return query<{ kind: string; n: number; uncalibrated: number }>(`
    SELECT kind, COUNT(*) AS n, SUM(uncalibrated_flag) AS uncalibrated
    FROM instruments GROUP BY kind ORDER BY n DESC`);
}

/* --------------------------- 行政文書 --------------------------- */

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

export async function docNotes(docId: string) {
  return query<{ note_id: string; kind: string; text: string; page: number; blocks_timeseries: number; reason: string }>(
    `SELECT note_id, kind, text, page, blocks_timeseries, reason FROM notes
     WHERE doc_id = ? ORDER BY blocks_timeseries DESC, page`,
    [docId],
  );
}

export async function documentsList() {
  return query<{
    doc_id: string;
    title: string;
    publisher: string;
    url: string;
    n_pages: number;
    fiscal_year: number | null;
    license: string;
    n_cells: number;
    n_notes: number;
    n_blocking: number;
  }>(`
    SELECT d.doc_id, d.title, d.publisher, d.url, d.n_pages, d.fiscal_year, d.license,
           (SELECT COUNT(*) FROM cells x WHERE x.doc_id = d.doc_id) AS n_cells,
           (SELECT COUNT(*) FROM notes n WHERE n.doc_id = d.doc_id) AS n_notes,
           (SELECT COUNT(*) FROM notes n WHERE n.doc_id = d.doc_id AND n.blocks_timeseries = 1) AS n_blocking
    FROM documents d ORDER BY n_cells DESC`);
}

export async function blockingNotes() {
  return query<{
    doc_id: string;
    doc_title: string;
    kind: string;
    page: number;
    reason: string;
    text: string;
  }>(`
    SELECT n.doc_id, d.title AS doc_title, n.kind, n.page, n.reason, n.text
    FROM notes n JOIN documents d USING (doc_id)
    WHERE n.blocks_timeseries = 1 ORDER BY n.kind, n.doc_id, n.page`);
}

/* ------------------------------ 出典 ------------------------------ */

export async function sourceRegistry() {
  return query<{
    source_id: string;
    name: string;
    publisher: string;
    url: string;
    category: string;
    license: string;
    redistributable: number;
    record_count: number;
    format: string;
    notes: string;
  }>(`SELECT * FROM source_registry ORDER BY record_count DESC`);
}

/* ------------------------------ 概況 ------------------------------ */

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

/** 同一の地点・日・項目を2人で測った記録（ペア測定）。測定者間の一致率を見るための素材。 */
export async function pairedMeasurements() {
  return query<{
    site_id: string;
    site_name: string | null;
    measured_on: string;
    variable: string;
    v1: number;
    v2: number;
    diff: number;
    unit: string | null;
  }>(`
    WITH p AS (
      -- 同じ地点・日・項目に2行あり、少なくとも一方が「ペア測定」として記録されているもの。
      -- 実データの重複は採水時刻を落としたことによるもので、ペア測定ではないため合成分に限る。
      SELECT m.site_id, m.measured_on, m.variable, MAX(m.unit) AS unit,
             MIN(m.value) AS v1, MAX(m.value) AS v2, COUNT(*) AS c,
             SUM(CASE WHEN m.method LIKE '%ペア測定%' THEN 1 ELSE 0 END) AS n_pair
      FROM measurements m
      WHERE m.is_synthetic = 1 AND m.value IS NOT NULL
      GROUP BY m.site_id, m.measured_on, m.variable
      HAVING c >= 2 AND n_pair >= 1
    )
    SELECT p.*, s.name AS site_name, (p.v2 - p.v1) AS diff
    FROM p LEFT JOIN sites s USING (site_id)
    ORDER BY (p.v2 - p.v1) DESC`);
}

export async function qualityTotals() {
  return queryOne<{ submitted: number; verified: number; published: number; returned: number; targets: number }>(`
    SELECT
      SUM(CASE WHEN from_stage IS NULL AND to_stage='${STAGE_PROVISIONAL}' THEN 1 ELSE 0 END) AS submitted,
      SUM(CASE WHEN from_stage='${STAGE_PROVISIONAL}' AND to_stage='${STAGE_VERIFIED}' THEN 1 ELSE 0 END) AS verified,
      SUM(CASE WHEN from_stage='${STAGE_VERIFIED}' AND to_stage='${STAGE_PUBLISHED}' THEN 1 ELSE 0 END) AS published,
      SUM(CASE WHEN from_stage='${STAGE_PROVISIONAL}' AND to_stage='${STAGE_PROVISIONAL}' THEN 1 ELSE 0 END) AS returned,
      COUNT(DISTINCT target_id) AS targets
    FROM quality_transitions`);
}

export async function instrumentList() {
  return query<{
    instrument_id: string;
    kind: string;
    model: string | null;
    calibrated_on: string | null;
    uncalibrated_flag: number;
    calibration_note: string | null;
  }>(`SELECT * FROM instruments ORDER BY uncalibrated_flag DESC, kind, instrument_id`);
}

export async function protocolList() {
  return query<{ protocol_id: string; name: string; domain: string; steps_json: string; url: string }>(
    `SELECT protocol_id, name, domain, steps_json, url FROM protocols ORDER BY protocol_id`,
  );
}

/* ------------------------------ 概況の見どころ ------------------------------ */

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

/* ------------------------------------------------------------------ */
/* Tier 1 追加ソース（docs/UNDATAFIED_TIERS.md）                        */
/* ------------------------------------------------------------------ */

export interface ProtectedAreaRow {
  area_id: string;
  name_ja: string | null;
  category_ja: string | null;
  category_code: string | null;
  municipality_ja: string | null;
  area_ha: number | null;
  designated_on: string | null;
  lat: number | null;
  lon: number | null;
  watershed: string | null;
  zone: number | null;
  note_ja: string | null;
  source_id: string | null;
  source_ref: string | null;
}

/** 保護区・緑地・保存樹木の台帳。category_code で絞れる。 */
export async function protectedAreas(categoryCode?: string, limit = 1000) {
  const where = categoryCode ? "WHERE category_code = ?" : "";
  const params = categoryCode ? [categoryCode, limit] : [limit];
  return query<ProtectedAreaRow>(
    `SELECT area_id, name_ja, category_ja, category_code, municipality_ja, area_ha,
            designated_on, lat, lon, watershed, zone, note_ja, source_id, source_ref
     FROM protected_areas ${where}
     ORDER BY category_code, area_ha DESC NULLS LAST, name_ja
     LIMIT ?`,
    params,
  );
}

/** 区分ごとの件数と面積合計。台帳の全体像を1クエリで返す。 */
export async function protectedAreaSummary() {
  return query<{
    category_code: string;
    category_ja: string | null;
    n: number;
    n_with_coords: number;
    total_ha: number | null;
    source_id: string | null;
  }>(`
    SELECT category_code,
           MIN(category_ja) AS category_ja,
           COUNT(*) AS n,
           SUM(CASE WHEN lat IS NOT NULL THEN 1 ELSE 0 END) AS n_with_coords,
           ROUND(SUM(area_ha), 1) AS total_ha,
           MIN(source_id) AS source_id
    FROM protected_areas
    GROUP BY category_code
    ORDER BY n DESC
  `);
}

/** ツキノワグマ等の出没・目撃記録。年度・種で絞れる。 */
export async function wildlifeSightings(fiscalYear?: number, limit = 800) {
  const where = fiscalYear ? "WHERE fiscal_year = ?" : "";
  const params = fiscalYear ? [fiscalYear, limit] : [limit];
  return query<{
    sighting_id: string;
    species_ja: string | null;
    fiscal_year: number | null;
    observed_on: string | null;
    observed_on_raw: string | null;
    observed_time_raw: string | null;
    individual_count: number | null;
    situation_ja: string | null;
    locality_ja: string | null;
    area_kind_ja: string | null;
    is_preliminary: number | null;
    source_ref: string | null;
  }>(
    `SELECT sighting_id, species_ja, fiscal_year, observed_on, observed_on_raw, observed_time_raw,
            individual_count, situation_ja, locality_ja, area_kind_ja, is_preliminary, source_ref
     FROM wildlife_sightings ${where}
     ORDER BY observed_on DESC NULLS LAST, sighting_id
     LIMIT ?`,
    params,
  );
}

/** 年度 × 状況（目撃/痕跡/捕殺）の集計。速報値の年度が混ざる点に注意。 */
export async function wildlifeSightingSummary() {
  return query<{
    fiscal_year: number;
    species_ja: string | null;
    situation_ja: string | null;
    n: number;
    individuals: number | null;
    is_preliminary: number | null;
  }>(`
    SELECT fiscal_year, species_ja, situation_ja,
           COUNT(*) AS n,
           SUM(individual_count) AS individuals,
           MAX(is_preliminary) AS is_preliminary
    FROM wildlife_sightings
    WHERE fiscal_year IS NOT NULL
    GROUP BY fiscal_year, species_ja, situation_ja
    ORDER BY fiscal_year, situation_ja
  `);
}

/** 中大型哺乳類のメッシュ分布。地図に出す用。 */
export async function mammalMesh(species?: string, surveyLabel?: string) {
  const cond: string[] = ["confirmed = 1"];
  const params: unknown[] = [];
  if (species) {
    cond.push("species = ?");
    params.push(species);
  }
  if (surveyLabel) {
    cond.push("survey_label = ?");
    params.push(surveyLabel);
  }
  return query<{
    mesh_code: string;
    species: string;
    species_ja: string | null;
    survey_label: string | null;
    survey_year: number | null;
    lat: number | null;
    lon: number | null;
  }>(
    `SELECT mesh_code, species, species_ja, survey_label, survey_year, lat, lon
     FROM mammal_mesh WHERE ${cond.join(" AND ")}`,
    params,
  );
}

/** どの種のどの調査年次が入っているかの一覧。UI の選択肢に使う。 */
export async function mammalMeshIndex() {
  return query<{
    species: string;
    species_ja: string | null;
    survey_label: string;
    survey_year: number | null;
    n_confirmed: number;
    n_mesh: number;
  }>(`
    SELECT species, MIN(species_ja) AS species_ja, survey_label, survey_year,
           SUM(confirmed) AS n_confirmed, COUNT(*) AS n_mesh
    FROM mammal_mesh
    GROUP BY species, survey_label, survey_year
    ORDER BY species, survey_year NULLS FIRST, survey_label
  `);
}

/** 植生凡例ごとの面積集計。面積は近似値である点に注意（vegetation_polygons のコメント参照）。 */
export async function vegetationSummary(limit = 60) {
  return query<{
    legend_code: string | null;
    legend_name_ja: string | null;
    veg_division_ja: string | null;
    naturalness: number | null;
    n: number;
    area_ha: number | null;
  }>(
    `SELECT legend_code, MIN(legend_name_ja) AS legend_name_ja,
            MIN(veg_division_ja) AS veg_division_ja, MIN(naturalness) AS naturalness,
            COUNT(*) AS n, ROUND(SUM(area_m2) / 10000.0, 1) AS area_ha
     FROM vegetation_polygons
     GROUP BY legend_code
     ORDER BY area_ha DESC NULLS LAST
     LIMIT ?`,
    [limit],
  );
}

/** 植生自然度ごとの面積。ブナ林の衰退のような話に効く粗い指標。 */
export async function vegetationNaturalness() {
  return query<{
    naturalness: number | null;
    naturalness_class_ja: string | null;
    n: number;
    area_ha: number | null;
  }>(`
    SELECT naturalness, MIN(naturalness_class_ja) AS naturalness_class_ja,
           COUNT(*) AS n, ROUND(SUM(area_m2) / 10000.0, 1) AS area_ha
    FROM vegetation_polygons
    GROUP BY naturalness
    ORDER BY naturalness
  `);
}

/**
 * 植生ポリゴンの形状。全件返すと重いので凡例か件数で必ず絞る。
 * geometry は取り込み時に simplify 済み。
 */
export async function vegetationShapes(legendCode?: string, limit = 1500) {
  const where = legendCode ? "WHERE legend_code = ?" : "";
  const params = legendCode ? [legendCode, limit] : [limit];
  return query<{
    feature_id: string;
    legend_code: string | null;
    legend_name_ja: string | null;
    naturalness: number | null;
    area_m2: number | null;
    geometry_geojson: string | null;
  }>(
    `SELECT feature_id, legend_code, legend_name_ja, naturalness, area_m2, geometry_geojson
     FROM vegetation_polygons ${where}
     ORDER BY area_m2 DESC
     LIMIT ?`,
    params,
  );
}

/** 相模川水系の流路。prefecture で絞れる（山梨県側だけ見る用）。 */
export async function riverSegments(prefecture?: string) {
  const where = prefecture ? "WHERE prefecture_ja = ?" : "";
  const params = prefecture ? [prefecture] : [];
  return query<{
    feature_id: string;
    name_ja: string | null;
    section_type: string | null;
    prefecture_ja: string | null;
    length_m: number | null;
    geometry_geojson: string | null;
  }>(
    `SELECT feature_id, name_ja, section_type, prefecture_ja, length_m, geometry_geojson
     FROM river_segments ${where}
     ORDER BY length_m DESC`,
    params,
  );
}

/** 県別の本数・延長。既存の県単位データに山梨県側が無かったことを示すのに使う。 */
export async function riverSegmentSummary() {
  return query<{ prefecture_ja: string | null; n: number; length_km: number | null }>(`
    SELECT prefecture_ja, COUNT(*) AS n, ROUND(SUM(length_m) / 1000.0, 1) AS length_km
    FROM river_segments
    GROUP BY prefecture_ja
    ORDER BY n DESC
  `);
}
