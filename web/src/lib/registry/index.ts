import "server-only";
import { query, queryOne, queryChunked, ph } from "@/lib/db";

/**
 * レジストリの D1 読み出し層（docs/plans/PHASE_A.md §A-7）。
 *
 * `taxon`（41,324件）・`place`（4,960件）・`cells.notes` 由来の caveat（207件、原文引用つき）は
 * 量が多く、または生成物（`../registry/generated.ts`）に載せる必要が無いため、ここから
 * D1 越しに直接引く。`variable` / `variable_alias` / 注記14件 / 和名54件は
 * `generated.ts`（クライアント安全・同期）に既にあるので、ここでは扱わない
 * （`./lookup.ts` を使う）。
 *
 * `server-only`。`web/src/lib/ai/tools.ts` のようなサーバ側からだけ呼ぶ。
 * `IN (...)` は `queryChunked`（D1 のバインドパラメータ1クエリ100個制限）を必ず使う。
 */

/* ------------------------------------------------------------------ */
/* taxon                                                              */
/* ------------------------------------------------------------------ */

export interface TaxonRow {
  taxon_id: string;
  scientific_name: string | null;
  rank: string | null;
  gbif_taxon_key: string | null;
  vernacular_name_ja: string | null;
  status: string | null;
  accepted_taxon_id: string | null;
}

const TAXON_COLUMNS =
  "taxon_id, scientific_name, rank, gbif_taxon_key, vernacular_name_ja, status, accepted_taxon_id";

export async function getTaxonById(taxonId: string): Promise<TaxonRow | undefined> {
  return queryOne<TaxonRow>(`SELECT ${TAXON_COLUMNS} FROM taxon WHERE taxon_id = ?`, [taxonId]);
}

/**
 * GBIF taxon_key から `common:taxon:gbif.<key>` を引く。
 * `organism_records` の99.9%はこの経路で `taxon_id` に解決できる（PHASE_A.md §A-4）。
 */
export async function getTaxonByGbifKey(gbifKey: string | number): Promise<TaxonRow | undefined> {
  return queryOne<TaxonRow>(`SELECT ${TAXON_COLUMNS} FROM taxon WHERE gbif_taxon_key = ?`, [String(gbifKey)]);
}

/**
 * 学名（2語）から taxon を引く。1つの学名に複数の taxon（GBIF 由来と taxa 由来の
 * 未照合レコードなど）が対応することがあるので配列を返す。
 */
export async function getTaxaByScientificNames(scientificNames: readonly string[]): Promise<TaxonRow[]> {
  return queryChunked<TaxonRow>(scientificNames, (names) => ({
    sql: `SELECT ${TAXON_COLUMNS} FROM taxon WHERE scientific_name IN (${ph(names)})`,
    params: names,
  }));
}

/* ------------------------------------------------------------------ */
/* place                                                              */
/* ------------------------------------------------------------------ */

export interface PlaceRow {
  place_id: string;
  region_id: string | null;
  place_kind: string | null;
  name_ja: string | null;
  lat: number | null;
  lon: number | null;
  elevation_m: number | null;
  area_km2: number | null;
  definition_ref: string | null;
  status: string | null;
}

const PLACE_COLUMNS =
  "place_id, region_id, place_kind, name_ja, lat, lon, elevation_m, area_km2, definition_ref, status";

export async function getPlaceById(placeId: string): Promise<PlaceRow | undefined> {
  return queryOne<PlaceRow>(`SELECT ${PLACE_COLUMNS} FROM place WHERE place_id = ?`, [placeId]);
}

export async function getPlacesByKind(placeKind: string): Promise<PlaceRow[]> {
  return query<PlaceRow>(`SELECT ${PLACE_COLUMNS} FROM place WHERE place_kind = ?`, [placeKind]);
}

/**
 * v1 の出典側識別子（`sites.site_id` / `watershed_meta.watershed_id` 等）から place を引く。
 * 「v1 を動かさずに並走させる」ための接続点（PHASE_A.md §A-3）。
 */
export async function getPlaceByExternalKey(externalKey: string, sourceId?: string): Promise<PlaceRow | undefined> {
  const row = sourceId
    ? await queryOne<{ place_id: string }>(
        `SELECT place_id FROM place_source_ref WHERE external_key = ? AND source_id = ?`,
        [externalKey, sourceId],
      )
    : await queryOne<{ place_id: string }>(`SELECT place_id FROM place_source_ref WHERE external_key = ?`, [
        externalKey,
      ]);
  if (!row) return undefined;
  return getPlaceById(row.place_id);
}

/* ------------------------------------------------------------------ */
/* caveat（cells.notes 由来。generated.ts に無い207件）                  */
/* ------------------------------------------------------------------ */

export interface CaveatRow {
  caveat_id: string;
  severity: string | null;
  kind: string | null;
  title_ja: string | null;
  body_ja: string | null;
  quote: string | null;
}

const CAVEAT_COLUMNS = "caveat_id, severity, kind, title_ja, body_ja, quote";

export async function getCaveatById(caveatId: string): Promise<CaveatRow | undefined> {
  return queryOne<CaveatRow>(`SELECT ${CAVEAT_COLUMNS} FROM caveat WHERE caveat_id = ?`, [caveatId]);
}

/**
 * 行政文書（`cells.sqlite` の `notes` 由来）に付随する注記を doc_id で引く。
 * `title_ja` は無く、`quote` に原文からの抜粋が入る（ADR-0013「原文は引用のみ、要約しない」）。
 * `caveatsForTables()`（`../lookup.ts`）の対象外（scope_kind='cell'/'cell_table'はそちらに含めない）。
 */
export async function getCaveatsForDocument(docId: string): Promise<CaveatRow[]> {
  const scopes = await query<{ caveat_id: string }>(
    `SELECT caveat_id FROM caveat_scope WHERE scope_kind = 'cell' AND scope_ref = ?`,
    [docId],
  );
  const ids = [...new Set(scopes.map((s) => s.caveat_id))];
  if (ids.length === 0) return [];
  return queryChunked<CaveatRow>(ids, (chunk) => ({
    sql: `SELECT ${CAVEAT_COLUMNS} FROM caveat WHERE caveat_id IN (${ph(chunk)})`,
    params: chunk,
  }));
}
