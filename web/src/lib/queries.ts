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

