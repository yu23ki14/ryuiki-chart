import "server-only";
import { query } from "./db";

/*
 * 残す表（cells/notes/documents/source_registry と Tier 1 の台帳）だけを読む問い合わせ。
 * v1 の派生表を読む関数は Issue #48 PR-4 で撤去した（serving-diff の oracle は
 * web/scripts/lib/serving/v1-queries.ts）。
 */

/* --------------------------- 行政文書 --------------------------- */

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
