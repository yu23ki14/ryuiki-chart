/**
 * 出典ごとの台帳表の明細を引く共通の実装（`get_records`。docs/plans/MCP_SOURCE_ACCESS.md §3）。
 * MCP（`lib/mcp/tools-records.ts`）と AI（`lib/ai/tools.ts`）が同じ関数を呼ぶ。
 *
 * - 任意 SQL ではない。出典（enum）× 宣言済みの表 × 許可リストの列だけ。SQL は `RECORD_TABLES` の
 *   定義から固定の形で組み立て、表名・列名は定数だけ（入力から組み立てない）。`SELECT *` は書かない。
 * - 出典で必ず絞る（行政文書の `documents`/`document_notes` だけは出典に紐付かないので record_set 単独。`sourceless`）。既定は `source_id = ?`（索引が効く）。複合 source_id（`a|b`）を持つ表（`compositeSource`）だけ、
 *   `|` で区切った要素の完全一致で照合する（LIKE の部分一致にしない）。どちらの出典で絞っても、その行が返る。
 * - ページングは `after`（直前の最後の主キー。keyset）が深くても速い。`offset` は残すが浅いページ向け。
 * - ライセンス・座標の精度で行を除外・加工しない（ADR-0028）。
 * - 件数は `count(*)` しない。`limit+1` 行を読み、ここで切って truncated・next_after を決める。
 *   `q`・`id` なしのときの n_total は事前計算（`sourceAccess().recordSetRows`）。
 * - ジオメトリ（`geometry_geojson`）は一覧では返さない。`id` 指定の 1 件だけ `include_geometry` で返す。
 * - バインドは常に数個（D1 の 100 個制限に当たらない）。
 */
import { z } from "zod";
import type { CubeDb, SqlParam } from "@/lib/cube/db";
import { idText, likeParam, likeText } from "@/lib/query-params";
import { RECORD_SET_TABLES, RECORD_SOURCE_IDS as GENERATED_RECORD_SOURCE_IDS } from "@/lib/registry/generated-source";
import { sourceAccess } from "@/lib/cube/source-meta";

export const RECORDS_MAX_ROWS = 500;

/** `z.enum` に渡す形（空でない配列）。 */
export const RECORD_SOURCE_IDS = GENERATED_RECORD_SOURCE_IDS as unknown as [string, ...string[]];

export interface RecordTable {
  /** 実表の名前（入力には出さない。入力は記録の集合名 `record_set`）。 */
  table: string;
  /** 主キー列。並びは常に主キー昇順（ページングの重複・欠落を防ぐ）。 */
  pk: string;
  /** `q`（部分一致）の対象列。空なら `q` は使えない。 */
  search: readonly string[];
  /** 返す列（許可リスト）。`source_id` を含む。ジオメトリ列は含めない。 */
  cols: readonly string[];
  /** `include_geometry` で `id` 指定の 1 件だけ返す列。 */
  geometry?: string;
  /** `source_id` に `a|b` の複合値が入りうる表。true のときだけ区切りの完全一致で照合する（索引は効かない）。 */
  compositeSource?: boolean;
  /**
   * 出典の列を持たない表（行政文書。`documents`/`notes` に `source_id` は無い）。true の record_set は
   * `source_id` を受けず（渡すと入力エラー）、record_set 単独で引く。理由は RECORD_TABLES の `documents` のコメント。
   */
  sourceless?: boolean;
  /** 返す算出列（別名 → SQL 式）。表名・列名は定数だけ。`cols` には含めない（実在列ではない）。 */
  computed?: Record<string, string>;
  /** 主キーが実列でない（`rowid`）。`cols` の実在検査から外す。 */
  pkIsRowid?: boolean;
  /** `doc_id` 入力で絞れる表（完全一致）。 */
  docIdFilter?: boolean;
  /** `blocking_only` 入力で絞る述語（`blocks_timeseries = 1`）。 */
  blockingPredicate?: string;
}

/**
 * 表ごとの許可リスト。実在列との突き合わせは `records.test.ts`（schema.ts の DDL と比べる）。
 *
 * 注: 設計書 §3.2 の `taxa`・`redlist_assessments`・`protocols`・`events` は D1 に無い
 * （マイグレーション 0010 で DROP 済み）。レッドリスト・外来種の評価は D1 では
 * `taxon_assessment`（語彙レジストリの表）が持つので、それを引く。
 */
export const RECORD_TABLES = {
  sites: {
    table: RECORD_SET_TABLES.sites,
    pk: "site_id",
    search: ["name", "name_en"],
    // 除外: geohash, treatment, is_synthetic
    cols: [
      "site_id", "name", "name_en", "watershed", "zone", "lat", "lon", "elevation_m", "municipality", "muni_code",
      "operator", "established_on", "source_id", "source_ref",
    ],
  },
  protected_areas: {
    table: RECORD_SET_TABLES.protected_areas,
    pk: "area_id",
    search: ["name_ja"],
    cols: [
      "area_id", "name_ja", "category_ja", "category_code", "municipality_ja", "area_ha", "area_ha_raw", "designated_on",
      "designated_on_raw", "lat", "lon", "watershed", "zone", "note_ja", "source_id", "source_ref",
    ],
  },
  vegetation: {
    table: RECORD_SET_TABLES.vegetation,
    pk: "feature_id",
    search: ["legend_name_ja"],
    cols: [
      "feature_id", "legend_code", "legend_name_ja", "veg_division_ja", "naturalness", "naturalness_class_ja", "survey_year",
      "block_ja", "area_m2", "centroid_lat", "centroid_lon", "watershed", "source_id", "source_ref",
    ],
    geometry: "geometry_geojson",
  },
  river_segments: {
    table: RECORD_SET_TABLES.river_segments,
    pk: "feature_id",
    search: ["name_ja"],
    cols: [
      "feature_id", "name_ja", "section_type", "prefecture_ja", "length_m", "start_lat", "start_lon", "end_lat", "end_lon",
      "source_id", "source_ref",
    ],
    geometry: "geometry_geojson",
  },
  mammal_mesh: {
    table: RECORD_SET_TABLES.mammal_mesh,
    pk: "id",
    search: ["species_ja", "species"],
    cols: ["id", "mesh_code", "species", "species_ja", "survey_label", "survey_year", "confirmed", "lat", "lon", "source_id", "source_ref"],
  },
  sightings: {
    table: RECORD_SET_TABLES.sightings,
    pk: "sighting_id",
    search: ["species_ja", "locality_ja"],
    cols: [
      "sighting_id", "species_ja", "fiscal_year", "observed_on", "observed_on_raw", "observed_time_raw", "individual_count",
      "individual_count_raw", "situation_ja", "locality_ja", "area_kind_ja", "municipality_ja", "lat", "lon", "is_preliminary",
      "note_ja", "source_id", "source_ref",
    ],
  },
  /*
   * 行政文書（cells.sqlite 由来の D1 表 `documents`/`notes`）。出典の列を持たず、access.yaml の出典にも
   * 結び付かない（文書は PDF 1 本＝1 doc_id で、`source_registry` の出典とは 1 対 1 でも入れ子でもない。
   * doc_id の接頭辞から出典を推測すると静かに外れる）。そこで `sourceless` とし、record_set 単独で引く。
   * 「出典単位で読む」契約は、各行の `publisher`/`url`/`license` が出典情報を持つことで満たす。
   * 表名は access.yaml の record_sets に無いので（出典に紐付かない表は宣言の対象外）ここに直書きする。
   */
  documents: {
    table: "documents",
    pk: "doc_id",
    search: ["title", "publisher"],
    cols: ["doc_id", "title", "publisher", "url", "n_pages", "fiscal_year", "license", "fetched_at"],
    computed: {
      n_cells: "(SELECT COUNT(*) FROM cells x WHERE x.doc_id = documents.doc_id)",
      n_notes: "(SELECT COUNT(*) FROM notes n WHERE n.doc_id = documents.doc_id)",
      n_blocking: "(SELECT COUNT(*) FROM notes n WHERE n.doc_id = documents.doc_id AND n.blocks_timeseries = 1)",
    },
    sourceless: true,
  },
  document_notes: {
    table: "notes",
    // note_id は 207 行中 30 行が NULL（schema.ts）。主キーに使えないので rowid で並べる・ページングする。
    pk: "rowid",
    pkIsRowid: true,
    search: ["text"],
    cols: ["rowid", "note_id", "doc_id", "table_ids", "kind", "text", "page", "blocks_timeseries", "reason"],
    sourceless: true,
    docIdFilter: true,
    blockingPredicate: "blocks_timeseries = 1",
  },
  assessments: {
    table: RECORD_SET_TABLES.assessments,
    pk: "assessment_id",
    search: ["scientific_name_raw", "vernacular_name_ja_raw", "vernacular_name_ja_resolved"],
    cols: [
      "assessment_id", "list_id", "list_year", "taxon_id", "scientific_name_raw", "vernacular_name_ja_raw",
      "vernacular_name_ja_resolved", "taxon_group_ja", "taxon_subgroup_ja", "family_ja", "category_raw", "category_code",
      "prev_category_raw", "prev_category_code", "national_category_raw", "origin", "source_id", "in_scope", "binom", "scope_reason",
    ],
  },
} as const satisfies Record<string, RecordTable>;

export type RecordSetName = keyof typeof RECORD_TABLES;
export const RECORD_SET_NAMES = Object.keys(RECORD_TABLES) as [RecordSetName, ...RecordSetName[]];

/** 出典 → `get_records` で引ける record_set（生成物 `SOURCE_ACCESS` の `tables`。宣言の正は registry/source/access.yaml）。 */
export function recordSetsOf(sourceId: string): readonly string[] {
  return sourceAccess(sourceId)?.tables ?? [];
}

/** MCP・AI 共通の入力（z.tuple は使わない）。出典と表の組み合わせの検査は `queryRecords` が行う。 */
export const recordsInputSchema = z.object({
  source_id: z.enum(RECORD_SOURCE_IDS).optional().describe("出典（documents・document_notes 以外は必須。使える出典と record_set の組はツールの説明にある）"),
  record_set: z.enum(RECORD_SET_NAMES).optional().describe("記録の集合（sites・protected_areas・vegetation・river_segments・mammal_mesh・sightings・assessments・documents・document_notes）。出典に集合が複数あるときだけ必須（1つなら省略可）。documents・document_notes は出典に紐付かないので source_id なしでこれだけ指定する"),
  doc_id: idText("document_notes だけ。文書 ID の完全一致で絞る").optional(),
  blocking_only: z.boolean().optional().describe("document_notes だけ。true なら時系列比較を妨げる注記（blocks_timeseries=1）だけ"),
  id: idText("主キーの完全一致（1 件取り）").optional(),
  q: likeText("表ごとの検索列（名称・和名・学名など）の部分一致").optional(),
  include_geometry: z
    .boolean()
    .optional()
    .describe("true なら geometry_geojson も返す（植生・河川のみ。id を指定した 1 件のときだけ許す。一覧では返さない）"),
  limit: z.number().int().min(1).max(RECORDS_MAX_ROWS).optional().describe(`返す行数の上限（既定 100、最大 ${RECORDS_MAX_ROWS}）`),
  after: idText("直前のページの最後の主キー（結果の next_after をそのまま渡す）。主キー昇順でその次から読む。深いページでは offset より after を使う（offset とは併用できない）").optional(),
  offset: z.number().int().min(0).optional().describe("読み飛ばす行数（浅いページ向け。深いページは after を使う。既定 0）"),
});
export type RecordsInput = z.infer<typeof recordsInputSchema>;

/** 説明文に載せる「出典 → record_set」の一覧（生成物から。AI には describe_catalog が無いので説明文に持たせる）。 */
function sourceSetList(): string {
  return RECORD_SOURCE_IDS.map((id) => `${id}=${recordSetsOf(id).join("+")}`).join("、");
}

export const RECORDS_DESCRIPTION =
  "出典（source_id）を指定して、台帳表の明細をそのまま取る。観測値・出現記録ではない地点・保護区・植生・河川・" +
  "哺乳類メッシュ・クマ出没・レッドリスト／外来種の評価など。任意 SQL ではなく、出典ごとに宣言された表だけ。" +
  "主キー昇順。id で 1 件、q で名称・和名・学名の部分一致。植生・河川のジオメトリは id 指定の 1 件だけ include_geometry で返す。" +
  "結果が truncated のときは next_after を after に渡して続きを取る（深いページは offset より速い）。" +
  "ライセンスや座標で行を除外・加工しない。利用条件は provenance の出典情報を見る。" +
  "行政文書の一覧（record_set=documents。抽出セル数 n_cells・注記数 n_notes・比較注意 n_blocking つき）と注記（record_set=document_notes。" +
  "doc_id・blocking_only で絞れる）は出典に紐付かないので source_id を付けず record_set だけで引く（行の publisher・url・license が出典）。" +
  `使える出典と record_set（複数あるときは record_set を指定）: ${sourceSetList()}。`;

/** 入力の組み合わせの誤り。`queryRecords` の `onInputError` で呼び出し側の例外（MCP は McpInputError）に変えられる。 */
export class RecordsInputError extends Error {}

export interface RecordsResult {
  /** 出典に紐付かない record_set（documents・document_notes）では null。 */
  source_id: string | null;
  record_set: RecordSetName;
  /** 実表名（AI の provenance 用）。 */
  table: string;
  /** 最大 limit 行（超える分はここで切って truncated を立てる）。 */
  rows: Record<string, string | number | null | object>[];
  limit: number;
  offset: number;
  truncated: boolean;
  /** truncated のときだけ。次のページの `after` に渡す、最後の行の主キー。 */
  next_after: string | null;
  /** `q`・`id` なしのときだけ。その出典のその record_set の行数（事前計算。リクエスト時に count しない）。 */
  n_total: number | null;
}

/** 入力から引く表を決める。出典に無い表・複数表で省略は入力エラー。出典に紐付かない表（sourceless）は record_set 単独。 */
export function resolveRecordTable(
  a: Pick<RecordsInput, "source_id" | "record_set">,
  fail: (msg: string) => Error = (m) => new RecordsInputError(m),
): RecordSetName {
  if (a.record_set !== undefined && isSourceless(a.record_set)) {
    if (a.source_id !== undefined) throw fail(`record_set '${a.record_set}' は出典に紐付かない。source_id を付けず record_set だけで引く`);
    return a.record_set;
  }
  if (a.source_id === undefined) throw fail("source_id が必要（documents・document_notes 以外の record_set は出典単位で読む）");
  const tables = recordSetsOf(a.source_id).filter((t) => !isSourceless(t)) as readonly RecordSetName[];
  if (tables.length === 0) throw fail(`source_id '${a.source_id}' は get_records の対象ではない`);
  if (a.record_set === undefined) {
    if (tables.length === 1) return tables[0];
    throw fail(`出典 ${a.source_id} は記録の集合が複数ある。record_set を ${tables.join(" / ")} から指定する`);
  }
  if (!tables.includes(a.record_set)) {
    throw fail(`出典 ${a.source_id} に記録の集合 '${a.record_set}' は無い。record_set は ${tables.join(" / ")} から選ぶ`);
  }
  return a.record_set;
}

function isSourceless(set: string): boolean {
  return Boolean((RECORD_TABLES as Record<string, RecordTable>)[set]?.sourceless);
}

/** 複合の値を持つ表だけ。`|` 区切りの要素の完全一致（LIKE の部分一致にしない）。 */
const COMPOSITE_SOURCE_MATCH = `instr('|' || source_id || '|', ?) > 0`;

export interface QueryRecordsOptions {
  /** 入力エラーの例外を作る（MCP は `McpInputError`）。省略時は `RecordsInputError`。 */
  onInputError?: (msg: string) => Error;
}

export async function queryRecords(db: CubeDb, a: RecordsInput, opt: QueryRecordsOptions = {}): Promise<RecordsResult> {
  const fail = opt.onInputError ?? ((m: string) => new RecordsInputError(m));
  const set = resolveRecordTable(a, fail);
  const def: RecordTable = RECORD_TABLES[set];
  const table = def.table;
  if (a.include_geometry) {
    if (!def.geometry) throw fail(`表 ${table} にジオメトリは無い。include_geometry は使えない`);
    if (a.id === undefined) throw fail("include_geometry は id を指定した 1 件のときだけ使える（一覧では応答が大きくなる）");
  }
  if (a.q !== undefined && def.search.length === 0) throw fail(`表 ${table} は q（部分一致）に対応していない`);
  if (a.after !== undefined && a.offset) throw fail("after と offset は併用できない（深いページは after だけを使う）");

  const limit = a.limit ?? 100;
  const offset = a.offset ?? 0;
  if (a.doc_id !== undefined && !def.docIdFilter) throw fail(`表 ${table} は doc_id で絞れない（document_notes だけ）`);
  if (a.blocking_only && !def.blockingPredicate) throw fail(`表 ${table} は blocking_only で絞れない（document_notes だけ）`);
  const conds: string[] = [];
  const params: SqlParam[] = [];
  if (!def.sourceless) {
    conds.push(def.compositeSource ? COMPOSITE_SOURCE_MATCH : "source_id = ?");
    params.push(def.compositeSource ? `|${a.source_id}|` : (a.source_id as string));
  }
  if (a.doc_id !== undefined) {
    conds.push("doc_id = ?");
    params.push(a.doc_id);
  }
  if (a.blocking_only && def.blockingPredicate) conds.push(def.blockingPredicate);
  if (a.id !== undefined) {
    conds.push(`${def.pk} = ?`);
    params.push(a.id);
  }
  if (a.after !== undefined) {
    conds.push(`${def.pk} > ?`);
    params.push(a.after);
  }
  if (a.q !== undefined) {
    conds.push(`(${def.search.map((c) => `${c} LIKE ? ESCAPE '\\'`).join(" OR ")})`);
    const p = likeParam(a.q);
    for (let i = 0; i < def.search.length; i++) params.push(p);
  }
  const geomCol = a.include_geometry && def.geometry ? def.geometry : null;
  const cols = geomCol ? [...def.cols, geomCol] : [...def.cols];
  const selects = [...cols, ...Object.entries(def.computed ?? {}).map(([k, expr]) => `${expr} AS ${k}`)];
  const where = conds.length ? `WHERE ${conds.join(" AND ")}` : "";
  const sql = `SELECT ${selects.join(", ")} FROM ${table} ${where} ORDER BY ${def.pk} LIMIT ? OFFSET ?`;
  const raw = await db.all(sql, [...params, limit + 1, offset]);
  const truncated = raw.length > limit;
  const page = raw.slice(0, limit);
  const rows: RecordsResult["rows"] = geomCol ? page.map((r) => ({ ...r, [geomCol]: parseGeometry(r[geomCol]) })) : page;
  const last = truncated ? page[page.length - 1]?.[def.pk] : undefined;
  const nTotal =
    a.id === undefined && a.q === undefined && a.source_id !== undefined
      ? (sourceAccess(a.source_id)?.recordSetRows[set] ?? null)
      : null;
  return {
    source_id: a.source_id ?? null,
    record_set: set,
    table,
    rows,
    limit,
    offset,
    truncated,
    next_after: last === undefined || last === null ? null : String(last),
    n_total: nTotal,
  };
}

function parseGeometry(v: string | number | null | undefined): object | string | number | null {
  if (typeof v !== "string") return v ?? null;
  try {
    return JSON.parse(v) as object;
  } catch {
    return v; // 壊れた値は黙って捨てず、そのまま返す
  }
}

/* ------------------------------------------------------------------ */
/* 画面・API 用の読み出し（`get_records` と同じ RECORD_TABLES の列定義を共有する）  */
/* ------------------------------------------------------------------ */

/** 全ページを読み切る（行数の少ない表だけ。`next_after` で続ける）。 */
async function queryAllRecords(db: CubeDb, a: RecordsInput): Promise<RecordsResult["rows"]> {
  const out: RecordsResult["rows"] = [];
  let after: string | undefined;
  for (;;) {
    const r = await queryRecords(db, { ...a, limit: RECORDS_MAX_ROWS, after });
    out.push(...r.rows);
    if (!r.truncated || r.next_after === null) return out;
    after = r.next_after;
  }
}

export interface MapReadOptions {
  /** 完全一致で絞る列（`cols` にある列だけ）。 */
  eq?: { col: string; value: string };
  /** 並び順（`cols` にある列だけ。desc は NULL を最後に）。 */
  orderBy: readonly { col: string; desc?: boolean }[];
  limit?: number;
  /** ジオメトリ列（`geometry_geojson`）も文字列のまま返す。 */
  withGeometry?: boolean;
}

/**
 * 地図用に、出典を問わず台帳表を読む（`/api/geo/{protected-areas,vegetation,river-segments}`）。
 * 表名・列は `RECORD_TABLES` のもの。列名・並び順は定数を渡し、`cols` に無い列は例外にする。
 * ジオメトリは `parseGeometry` せず文字列で返す（呼び出し側が壊れた値を落とす）。
 */
export async function readRecordSet(
  db: CubeDb,
  set: RecordSetName,
  opt: MapReadOptions,
): Promise<Record<string, string | number | null>[]> {
  const def: RecordTable = RECORD_TABLES[set];
  const known = new Set<string>(def.cols);
  const geom = opt.withGeometry ? def.geometry : undefined;
  if (opt.withGeometry && !geom) throw new Error(`表 ${def.table} にジオメトリは無い`);
  for (const c of [...opt.orderBy.map((o) => o.col), ...(opt.eq ? [opt.eq.col] : [])]) {
    if (!known.has(c)) throw new Error(`${def.table}.${c} は許可リストに無い`);
  }
  const cols = geom ? [...def.cols, geom] : [...def.cols];
  const where = opt.eq ? `WHERE ${opt.eq.col} = ?` : "";
  const order = opt.orderBy.map((o) => `${o.col}${o.desc ? " DESC NULLS LAST" : ""}`).join(", ");
  const params: SqlParam[] = opt.eq ? [opt.eq.value] : [];
  const limit = opt.limit !== undefined ? "LIMIT ?" : "";
  if (opt.limit !== undefined) params.push(opt.limit);
  return (await db.all(`SELECT ${cols.join(", ")} FROM ${def.table} ${where} ORDER BY ${order} ${limit}`, params)) as Record<
    string,
    string | number | null
  >[];
}

export interface DocumentRow {
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
}

/** 抽出元の行政文書の一覧（抽出セルの多い順）。`/api/documents` と `/sources` が使う。 */
export async function documentsList(db: CubeDb): Promise<DocumentRow[]> {
  const rows = await queryAllRecords(db, { record_set: "documents" });
  return rows
    .map((r) => ({
      doc_id: r.doc_id, title: r.title, publisher: r.publisher, url: r.url, n_pages: r.n_pages,
      fiscal_year: r.fiscal_year, license: r.license, n_cells: r.n_cells, n_notes: r.n_notes, n_blocking: r.n_blocking,
    }) as DocumentRow)
    .sort((x, y) => y.n_cells - x.n_cells);
}

export interface DocNote {
  note_id: string | null;
  kind: string;
  text: string;
  page: number;
  blocks_timeseries: number;
  reason: string;
}

/** 1 文書の注記（時系列を妨げるものを先に、ページ順）。 */
export async function docNotes(db: CubeDb, docId: string): Promise<DocNote[]> {
  const rows = await queryAllRecords(db, { record_set: "document_notes", doc_id: docId });
  return rows
    .map((r) => ({ note_id: r.note_id, kind: r.kind, text: r.text, page: r.page, blocks_timeseries: r.blocks_timeseries, reason: r.reason }) as DocNote)
    .sort((x, y) => y.blocks_timeseries - x.blocks_timeseries || x.page - y.page);
}

export interface BlockingNote {
  doc_id: string;
  doc_title: string;
  kind: string;
  page: number;
  reason: string;
  text: string;
}

/** 時系列の比較を妨げる注記（種別・文書・ページ順）。文書名は documents から付ける。 */
export async function blockingNotes(db: CubeDb): Promise<BlockingNote[]> {
  const [notes, docs] = await Promise.all([
    queryAllRecords(db, { record_set: "document_notes", blocking_only: true }),
    queryAllRecords(db, { record_set: "documents" }),
  ]);
  const title = new Map(docs.map((d) => [String(d.doc_id), String(d.title ?? "")]));
  const cmp = (x: string, y: string) => (x < y ? -1 : x > y ? 1 : 0);
  return notes
    .filter((n) => title.has(String(n.doc_id))) // 旧実装は documents との内部結合
    .map((n) => ({ doc_id: n.doc_id, doc_title: title.get(String(n.doc_id)), kind: n.kind, page: n.page, reason: n.reason, text: n.text }) as BlockingNote)
    .sort((x, y) => cmp(x.kind, y.kind) || cmp(x.doc_id, y.doc_id) || x.page - y.page);
}
