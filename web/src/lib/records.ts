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
  /** 実列でない出力列（別名 → SQL 式。例 `note_rowid` → `notes.rowid`）。`cols` に載せる。実在検査の対象外。 */
  exprs?: Record<string, string>;
  /** 出典の列の式（既定は `<table>.source_id`）。place 由来の sites は版（source_edition）から引く。 */
  sourceExpr?: string;
  /** 常に付ける JOIN 句と条件（定数。別表の列を `exprs` で引く表だけ）。 */
  baseJoin?: string;
  baseWhere?: string;
  /** 返す算出列（別名 → SQL 式。`join` の別名を参照してよい）。`cols` には含めない。選ぶか並べたときだけ `join` を付ける。 */
  computed?: Record<string, string>;
  /** `computed` が使う JOIN 句（定数）。 */
  join?: string;
}

/**
 * 表ごとの許可リスト。実在列との突き合わせは `records.test.ts`（schema.ts の DDL と比べる）。
 *
 * 注: 設計書 §3.2 の `taxa`・`redlist_assessments`・`protocols`・`events` は D1 に無い
 * （マイグレーション 0010 で DROP 済み）。レッドリスト・外来種の評価は D1 では
 * `taxon_assessment`（語彙レジストリの表）が持つので、それを引く。
 */
export const RECORD_TABLES = {
  /*
   * 地点は語彙レジストリの `place`（place_kind='site'）の全地点。旧表 `sites`（5 出典・352 地点）には観測局
   * （soramame・平塚/相模原の大気・横浜の水位・地盤沈下・厚木の水質）が無かったため、place から引く。
   * `site_id` は place_source_ref（key_space='site_id'）の external_key で、`get_observations` の
   * `scope={type:'site', siteId}` にそのまま渡せる（cube の buildScopeSql が同じ列で照合する）。
   * 出典は place_source_ref の版（source_edition.source_id）。旧 `sites` にある地点だけ、流域・zone・
   * 自治体・管理者などの列が LEFT JOIN で付く（観測局は NULL。地点と流域・zone の紐付けは Issue #86）。
   */
  sites: {
    table: RECORD_SET_TABLES.sites,
    pk: "site_id",
    search: ["name", "name_en"],
    sourceExpr: "se.source_id",
    baseJoin:
      "JOIN place_source_ref psr ON psr.place_id = place.place_id AND psr.key_space = 'site_id' " +
      "JOIN source_edition se ON se.edition_id = psr.source_edition_id " +
      "LEFT JOIN sites ls ON ls.site_id = psr.external_key",
    baseWhere: "place.place_kind = 'site'",
    exprs: {
      site_id: "psr.external_key",
      name: "place.name_ja",
      name_en: "ls.name_en",
      watershed: "ls.watershed",
      zone: "ls.zone",
      municipality: "ls.municipality",
      muni_code: "ls.muni_code",
      operator: "ls.operator",
      established_on: "ls.established_on",
      source_id: "se.source_id",
      source_ref: "ls.source_ref",
    },
    cols: [
      "site_id", "place_id", "name", "name_en", "watershed", "zone", "lat", "lon", "elevation_m", "municipality", "muni_code",
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
    // cells・notes をそれぞれ 1 回だけ集計して結合する（文書ごとの相関サブクエリにしない）。
    join:
      "LEFT JOIN (SELECT doc_id, COUNT(*) AS n FROM cells GROUP BY doc_id) cc ON cc.doc_id = documents.doc_id " +
      "LEFT JOIN (SELECT doc_id, COUNT(*) AS n, SUM(blocks_timeseries = 1) AS nb FROM notes GROUP BY doc_id) nn ON nn.doc_id = documents.doc_id",
    computed: { n_cells: "COALESCE(cc.n, 0)", n_notes: "COALESCE(nn.n, 0)", n_blocking: "COALESCE(nn.nb, 0)" },
    sourceless: true,
  },
  document_notes: {
    table: "notes",
    // note_id は 207 行中 30 行が NULL（schema.ts）。主キーに使えないので rowid を note_rowid として行に出し、
    // それで並べる・ページングする・id 指定する（id に渡す値は行の note_rowid）。
    pk: "note_rowid",
    exprs: { note_rowid: "notes.rowid" },
    search: ["text", "doc_id"],
    cols: ["note_rowid", "note_id", "doc_id", "table_ids", "kind", "text", "page", "blocks_timeseries", "reason"],
    sourceless: true,
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

/** 表定義を `RecordTable` として引く（as const の狭い型から選択的フィールドを安全に読む）。 */
const TABLES: Readonly<Record<keyof typeof RECORD_TABLES, RecordTable>> = RECORD_TABLES;

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
  "地点（record_set=sites）は大気・水位・水質・地盤沈下などの観測局を含む全地点で、行の site_id は get_observations の scope={type:'site', siteId} にそのまま渡せる。" +
  "watershed・zone・municipality・operator などは従来の地点表にある地点だけ値が入り、観測局は null（地点と流域・zone の紐付けは未整備）。" +
  "行政文書の一覧（record_set=documents。抽出セル数 n_cells・注記数 n_notes・比較注意 n_blocking つき）と注記（record_set=document_notes。" +
  "q は本文と doc_id に効く。id は行の note_rowid）は出典に紐付かないので source_id を付けず record_set だけで引く（行の publisher・url・license が出典）。" +
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

/** 入力から引く表と出典を決める。出典に紐付かない表（sourceless）は record_set 単独で、sourceId は undefined。 */
function resolveTarget(
  a: Pick<RecordsInput, "source_id" | "record_set">,
  fail: (msg: string) => Error,
): { set: RecordSetName; sourceId: string | undefined } {
  if (a.record_set !== undefined && TABLES[a.record_set].sourceless) {
    if (a.source_id !== undefined) throw fail(`record_set '${a.record_set}' は出典に紐付かない。source_id を付けず record_set だけで引く`);
    return { set: a.record_set, sourceId: undefined };
  }
  if (a.source_id === undefined) throw fail("source_id が必要（documents・document_notes 以外の record_set は出典単位で読む）");
  const tables = recordSetsOf(a.source_id) as readonly RecordSetName[];
  if (tables.length === 0) throw fail(`source_id '${a.source_id}' は get_records の対象ではない`);
  if (a.record_set === undefined) {
    if (tables.length === 1) return { set: tables[0], sourceId: a.source_id };
    throw fail(`出典 ${a.source_id} は記録の集合が複数ある。record_set を ${tables.join(" / ")} から指定する`);
  }
  if (!tables.includes(a.record_set)) {
    throw fail(`出典 ${a.source_id} に記録の集合 '${a.record_set}' は無い。record_set は ${tables.join(" / ")} から選ぶ`);
  }
  return { set: a.record_set, sourceId: a.source_id };
}

/** 入力から引く表を決める（`resolveTarget` の record_set だけ）。 */
export function resolveRecordTable(
  a: Pick<RecordsInput, "source_id" | "record_set">,
  fail: (msg: string) => Error = (m) => new RecordsInputError(m),
): RecordSetName {
  return resolveTarget(a, fail).set;
}

/** 複合の値を持つ表だけ。`|` 区切りの要素の完全一致（LIKE の部分一致にしない）。 */
const COMPOSITE_SOURCE_MATCH = (srcExpr: string) => `instr('|' || ${srcExpr} || '|', ?) > 0`;

export interface QueryRecordsOptions {
  /** 入力エラーの例外を作る（MCP は `McpInputError`）。省略時は `RecordsInputError`。 */
  onInputError?: (msg: string) => Error;
}

/* ------------------------------------------------------------------ */
/* SELECT の組み立て（`queryRecords`・`readRecordSet` が共有する唯一の場所）  */
/* ------------------------------------------------------------------ */

const DEFAULT_LIMIT = 100;

/** 行数の上限を決める。NaN・非有限・0 以下は既定値、上限超は上限に丸める。 */
export function clampLimit(v: unknown, def = DEFAULT_LIMIT, max = RECORDS_MAX_ROWS): number {
  const n = typeof v === "number" ? v : Number(v);
  if (!Number.isFinite(n) || n < 1) return def;
  return Math.min(Math.floor(n), max);
}

interface SelectSpec {
  set: RecordSetName;
  /** 出典付きの表では `anySource` でない限り必須（出典で必ず絞る）。sourceless の表では無視。 */
  sourceId?: string;
  /** 出典を問わず読む（画面・API の読み出しだけ）。 */
  anySource?: boolean;
  /** 完全一致（`cols` の列だけ）。 */
  eq?: readonly { col: string; value: SqlParam }[];
  id?: string;
  after?: string;
  q?: string;
  /** 並び（`cols`/算出列の別名だけ）。主キーは最後のタイブレークとして常に足す（決定的な並び）。 */
  order?: readonly { col: string; desc?: boolean }[];
  /** 返す列（`cols`/算出列の別名の部分集合。省略は全部）。算出列を選ばなければ JOIN も付けない。 */
  select?: readonly string[];
  geometry?: boolean;
  /** 行数。null は上限なし（呼び出し側が全件を意図するとき）。省略は `defaultLimit`。 */
  limit?: number | null;
  defaultLimit?: number;
  maxLimit?: number;
  /** true なら limit+1 行を読む（切り詰め判定用）。 */
  probe?: boolean;
  offset?: number;
}

function buildSelect(s: SelectSpec): { sql: string; params: SqlParam[]; limit: number | null; geomCol: string | null } {
  const def = TABLES[s.set];
  const t = def.table;
  const computed = def.computed ?? {};
  const known = new Set<string>([...def.cols, ...Object.keys(computed)]);
  const check = (c: string) => {
    if (!known.has(c)) throw new Error(`${t}.${c} は許可リストに無い`);
    return c;
  };
  const exprOf = (c: string) => computed[c] ?? def.exprs?.[c] ?? `${t}.${c}`; // 検索列・並び・条件・選択列で共通
  const picked = (s.select ?? [...def.cols, ...Object.keys(computed)]).map(check);
  const geomCol = s.geometry ? (def.geometry ?? null) : null;
  if (s.geometry && !geomCol) throw new Error(`表 ${t} にジオメトリは無い`);
  const order = [...(s.order ?? []).map((o) => ({ ...o, col: check(o.col) }))];
  if (!order.some((o) => o.col === def.pk)) order.push({ col: def.pk });

  const conds: string[] = def.baseWhere ? [def.baseWhere] : [];
  const params: SqlParam[] = [];
  if (!def.sourceless && !s.anySource) {
    if (s.sourceId === undefined) throw new Error(`表 ${t} は出典で絞る必要がある`);
    const srcExpr = def.sourceExpr ?? `${t}.source_id`;
    conds.push(def.compositeSource ? COMPOSITE_SOURCE_MATCH(srcExpr) : `${srcExpr} = ?`);
    params.push(def.compositeSource ? `|${s.sourceId}|` : s.sourceId);
  }
  for (const e of s.eq ?? []) {
    if (!def.cols.includes(e.col)) throw new Error(`${t}.${e.col} は許可リストに無い`);
    conds.push(`${exprOf(e.col)} = ?`);
    params.push(e.value);
  }
  if (s.id !== undefined) {
    conds.push(`${exprOf(def.pk)} = ?`);
    params.push(s.id);
  }
  if (s.after !== undefined) {
    conds.push(`${exprOf(def.pk)} > ?`);
    params.push(s.after);
  }
  if (s.q !== undefined) {
    conds.push(`(${def.search.map((c) => `${exprOf(c)} LIKE ? ESCAPE '\\'`).join(" OR ")})`);
    const p = likeParam(s.q);
    for (let i = 0; i < def.search.length; i++) params.push(p);
  }
  const usesJoin = [...picked, ...order.map((o) => o.col)].some((c) => c in computed);
  const selects = [...picked.map((c) => `${exprOf(c)} AS ${c}`), ...(geomCol ? [`${t}.${geomCol} AS ${geomCol}`] : [])];
  const limit = s.limit === null ? null : clampLimit(s.limit, s.defaultLimit, s.maxLimit);
  let sql =
    `SELECT ${selects.join(", ")} FROM ${t}${def.baseJoin ? ` ${def.baseJoin}` : ""}${usesJoin && def.join ? ` ${def.join}` : ""}` +
    `${conds.length ? ` WHERE ${conds.join(" AND ")}` : ""}` +
    ` ORDER BY ${order.map((o) => `${exprOf(o.col)}${o.desc ? " DESC NULLS LAST" : ""}`).join(", ")}`;
  if (limit !== null) {
    sql += " LIMIT ? OFFSET ?";
    params.push(limit + (s.probe ? 1 : 0), s.offset ?? 0);
  }
  return { sql, params, limit, geomCol };
}

export async function queryRecords(db: CubeDb, a: RecordsInput, opt: QueryRecordsOptions = {}): Promise<RecordsResult> {
  const fail = opt.onInputError ?? ((m: string) => new RecordsInputError(m));
  const { set, sourceId } = resolveTarget(a, fail);
  const def = TABLES[set];
  const table = def.table;
  if (a.include_geometry) {
    if (!def.geometry) throw fail(`表 ${table} にジオメトリは無い。include_geometry は使えない`);
    if (a.id === undefined) throw fail("include_geometry は id を指定した 1 件のときだけ使える（一覧では応答が大きくなる）");
  }
  if (a.q !== undefined && def.search.length === 0) throw fail(`表 ${table} は q（部分一致）に対応していない`);
  if (a.after !== undefined && a.offset) throw fail("after と offset は併用できない（深いページは after だけを使う）");

  const offset = a.offset ?? 0;
  const { sql, params, limit, geomCol } = buildSelect({
    set, sourceId, id: a.id, after: a.after, q: a.q, geometry: a.include_geometry, limit: a.limit, offset, probe: true,
  });
  const lim = limit ?? DEFAULT_LIMIT; // limit は null にならない（a.limit は undefined か数）
  const raw = await db.all(sql, params);
  const truncated = raw.length > lim;
  const page = raw.slice(0, lim);
  const rows: RecordsResult["rows"] = geomCol ? page.map((r) => ({ ...r, [geomCol]: parseGeometry(r[geomCol]) })) : page;
  const last = truncated ? page[page.length - 1]?.[def.pk] : undefined;
  return {
    source_id: sourceId ?? null,
    record_set: set,
    table,
    rows,
    limit: lim,
    offset,
    truncated,
    next_after: last === undefined || last === null ? null : String(last),
    n_total: a.id === undefined && a.q === undefined ? await totalOf(db, set, sourceId) : null,
  };
}

/**
 * q・id なしのときの行数。出典付きの表は事前計算（リクエスト時に count しない）。
 * 出典に紐付かない表（行政文書。数百行以下）だけ、表全体の count(*) を 1 回数える。
 */
async function totalOf(db: CubeDb, set: RecordSetName, sourceId: string | undefined): Promise<number | null> {
  if (sourceId !== undefined) return sourceAccess(sourceId)?.recordSetRows[set] ?? null;
  const r = await db.all(`SELECT COUNT(*) AS n FROM ${TABLES[set].table}`, []);
  return Number(r[0]?.n ?? 0);
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
/* 画面・API 用の読み出し（`get_records` と同じ RECORD_TABLES の列定義・同じ builder）  */
/* ------------------------------------------------------------------ */

export interface ReadRecordOptions {
  eq?: SelectSpec["eq"];
  order: NonNullable<SelectSpec["order"]>;
  select?: SelectSpec["select"];
  /** 行数。null は全件。数（NaN・負・0 は既定値、上限超は丸める）。 */
  limit?: number | null;
  defaultLimit?: number;
  maxLimit?: number;
  /** ジオメトリ列（`geometry_geojson`）も文字列のまま返す。 */
  withGeometry?: boolean;
}

/**
 * 出典を問わず台帳表を読む（地図 API・行政文書の画面）。SQL は `queryRecords` と同じ builder。
 * 戻りの行の型 `T` は呼び出し側が選んだ列に合わせて宣言する（ここが唯一のキャスト）。
 * ジオメトリは `parseGeometry` せず文字列で返す（呼び出し側が壊れた値を落とす）。
 */
export async function readRecordSet<T = Record<string, string | number | null>>(
  db: CubeDb,
  set: RecordSetName,
  opt: ReadRecordOptions,
): Promise<T[]> {
  const { sql, params } = buildSelect({
    set, anySource: true, eq: opt.eq, order: opt.order, select: opt.select, geometry: opt.withGeometry,
    limit: opt.limit ?? null, defaultLimit: opt.defaultLimit, maxLimit: opt.maxLimit,
  });
  return (await db.all(sql, params)) as unknown as T[];
}

export interface DocumentRow {
  doc_id: string;
  title: string | null;
  publisher: string | null;
  url: string | null;
  n_pages: number | null;
  fiscal_year: number | null;
  license: string | null;
  n_cells: number;
  n_notes: number;
  n_blocking: number;
}

/** 抽出元の行政文書の一覧（抽出セルの多い順）。`/api/documents` と `/sources` が使う。 */
export function documentsList(db: CubeDb): Promise<DocumentRow[]> {
  return readRecordSet<DocumentRow>(db, "documents", {
    select: ["doc_id", "title", "publisher", "url", "n_pages", "fiscal_year", "license", "n_cells", "n_notes", "n_blocking"],
    order: [{ col: "n_cells", desc: true }],
  });
}

export interface DocNote {
  note_id: string | null;
  kind: string | null;
  text: string | null;
  page: number | null;
  blocks_timeseries: number | null;
  reason: string | null;
}

/** 1 文書の注記（時系列を妨げるものを先に、ページ順）。 */
export function docNotes(db: CubeDb, docId: string): Promise<DocNote[]> {
  return readRecordSet<DocNote>(db, "document_notes", {
    eq: [{ col: "doc_id", value: docId }],
    select: ["note_id", "kind", "text", "page", "blocks_timeseries", "reason"],
    order: [{ col: "blocks_timeseries", desc: true }, { col: "page" }],
  });
}

export interface BlockingNote {
  doc_id: string;
  doc_title: string | null;
  kind: string | null;
  page: number | null;
  reason: string | null;
  text: string | null;
}

/**
 * 時系列の比較を妨げる注記（種別・文書・ページ順）。文書名は呼び出し側が持つ一覧から付ける
 * （documents を読み直さない。`documentsList` の結果を渡す）。文書の無い注記は落とす（旧実装は内部結合）。
 */
export async function blockingNotes(db: CubeDb, docs: readonly Pick<DocumentRow, "doc_id" | "title">[]): Promise<BlockingNote[]> {
  const title = new Map(docs.map((d) => [d.doc_id, d.title]));
  const rows = await readRecordSet<Omit<BlockingNote, "doc_title">>(db, "document_notes", {
    eq: [{ col: "blocks_timeseries", value: 1 }],
    select: ["doc_id", "kind", "page", "reason", "text"],
    order: [{ col: "kind" }, { col: "doc_id" }, { col: "page" }],
  });
  return rows.filter((r) => title.has(r.doc_id)).map((r) => ({ ...r, doc_title: title.get(r.doc_id) ?? null }));
}
