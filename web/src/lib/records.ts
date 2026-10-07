/**
 * 出典ごとの台帳表の明細を引く共通の実装（`get_records`。docs/plans/MCP_SOURCE_ACCESS.md §3）。
 * MCP（`lib/mcp/tools-records.ts`）と AI（`lib/ai/tools.ts`）が同じ関数を呼ぶ。
 *
 * - 任意 SQL ではない。出典（enum）× 宣言済みの表 × 許可リストの列だけ。SQL は `RECORD_TABLES` の
 *   定義から固定の形で組み立て、表名・列名は定数だけ（入力から組み立てない）。`SELECT *` は書かない。
 * - 出典で必ず絞る。複合 source_id（`a|b`）は `|` で区切った要素の完全一致で照合する（LIKE の部分一致にしない）。
 *   どちらの出典で絞っても、その行が返る。
 * - ライセンス・座標の精度で行を除外・加工しない（ADR-0028）。
 * - 件数は `count(*)` しない。`limit+1` 行を読み、呼び出し側が切って truncated を決める。
 * - ジオメトリ（`geometry_geojson`）は一覧では返さない。`id` 指定の 1 件だけ `include_geometry` で返す。
 * - バインドは常に数個（D1 の 100 個制限に当たらない）。
 */
import { z } from "zod";
import type { CubeDb, SqlParam } from "@/lib/cube/db";
import { idText, likeParam, likeText } from "@/lib/edna";

export const RECORDS_MAX_ROWS = 500;

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
    table: "sites",
    pk: "site_id",
    search: ["name", "name_en"],
    // 除外: geohash, treatment, is_synthetic
    cols: [
      "site_id", "name", "name_en", "watershed", "zone", "lat", "lon", "elevation_m", "municipality", "muni_code",
      "operator", "established_on", "source_id", "source_ref",
    ],
  },
  protected_areas: {
    table: "protected_areas",
    pk: "area_id",
    search: ["name_ja"],
    cols: [
      "area_id", "name_ja", "category_ja", "category_code", "municipality_ja", "area_ha", "area_ha_raw", "designated_on",
      "designated_on_raw", "lat", "lon", "watershed", "zone", "note_ja", "source_id", "source_ref",
    ],
  },
  vegetation: {
    table: "vegetation_polygons",
    pk: "feature_id",
    search: ["legend_name_ja"],
    cols: [
      "feature_id", "legend_code", "legend_name_ja", "veg_division_ja", "naturalness", "naturalness_class_ja", "survey_year",
      "block_ja", "area_m2", "centroid_lat", "centroid_lon", "watershed", "source_id", "source_ref",
    ],
    geometry: "geometry_geojson",
  },
  river_segments: {
    table: "river_segments",
    pk: "feature_id",
    search: ["name_ja"],
    cols: [
      "feature_id", "name_ja", "section_type", "prefecture_ja", "length_m", "start_lat", "start_lon", "end_lat", "end_lon",
      "source_id", "source_ref",
    ],
    geometry: "geometry_geojson",
  },
  mammal_mesh: {
    table: "mammal_mesh",
    pk: "id",
    search: ["species_ja", "species"],
    cols: ["id", "mesh_code", "species", "species_ja", "survey_label", "survey_year", "confirmed", "lat", "lon", "source_id", "source_ref"],
  },
  sightings: {
    table: "wildlife_sightings",
    pk: "sighting_id",
    search: ["species_ja", "locality_ja"],
    cols: [
      "sighting_id", "species_ja", "fiscal_year", "observed_on", "observed_on_raw", "observed_time_raw", "individual_count",
      "individual_count_raw", "situation_ja", "locality_ja", "area_kind_ja", "municipality_ja", "lat", "lon", "is_preliminary",
      "note_ja", "source_id", "source_ref",
    ],
  },
  assessments: {
    table: "taxon_assessment",
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

/**
 * 出典 → `get_records` で引ける表。統合時に `generated-source.ts` の `SOURCE_ACCESS`/`RECORD_SOURCE_IDS`
 * （担当 A）から読む形に差し替え、A の `tables` と一致することをテストする（設計 §5.3）。
 */
export const RECORD_SOURCES: Readonly<Record<string, readonly RecordSetName[]>> = {
  dams_kanagawa: ["sites"],
  env_kousui_stations_kanagawa: ["sites"],
  jma_stations_kanagawa: ["sites"],
  moni1000_sites: ["sites"],
  sagami_livecams: ["sites"],
  hadano_preserved_trees: ["protected_areas"],
  hiratsuka_parks: ["protected_areas"],
  kanagawa_green_conservation: ["protected_areas"],
  kanagawa_natural_parks: ["protected_areas"],
  biodic_veg2024_kanagawa: ["vegetation"],
  biodic_mammal_mesh_kanagawa: ["mammal_mesh"],
  geoshape_sagami_river: ["river_segments"],
  kanagawa_kuma_sightings: ["sightings"],
  kanagawa_redlist: ["assessments"],
  kanagawa_rdb2022_plants: ["assessments"],
  moe_ias_list: ["assessments"],
};
export const RECORD_SOURCE_IDS = Object.keys(RECORD_SOURCES) as [string, ...string[]];

/** MCP・AI 共通の入力（z.tuple は使わない）。出典と表の組み合わせの検査は `queryRecords` が行う。 */
export const recordsInputSchema = z.object({
  source_id: z.enum(RECORD_SOURCE_IDS).describe("出典（必須。describe_catalog の records_tables が空でない出典）"),
  record_set: z.enum(RECORD_SET_NAMES).optional().describe("記録の集合（sites・protected_areas・vegetation・river_segments・mammal_mesh・sightings・assessments）。出典に集合が複数あるときだけ必須（1つなら省略可）"),
  id: idText("主キーの完全一致（1 件取り）").optional(),
  q: likeText("表ごとの検索列（名称・和名・学名など）の部分一致").optional(),
  include_geometry: z
    .boolean()
    .optional()
    .describe("true なら geometry_geojson も返す（植生・河川のみ。id を指定した 1 件のときだけ許す。一覧では返さない）"),
  limit: z.number().int().min(1).max(RECORDS_MAX_ROWS).optional().describe(`返す行数の上限（既定 100、最大 ${RECORDS_MAX_ROWS}）`),
  offset: z.number().int().min(0).optional().describe("読み飛ばす行数（ページング。結果が truncated のとき offset を進めて続きを取る。既定 0）"),
});
export type RecordsInput = z.infer<typeof recordsInputSchema>;

export const RECORDS_DESCRIPTION =
  "出典（source_id）を指定して、台帳表の明細をそのまま取る。観測値・出現記録ではない地点・保護区・植生・河川・" +
  "哺乳類メッシュ・クマ出没・レッドリスト／外来種の評価など。任意 SQL ではなく、出典ごとに宣言された表だけ。" +
  "主キー昇順。id で 1 件、q で名称・和名・学名の部分一致。植生・河川のジオメトリは id 指定の 1 件だけ include_geometry で返す。" +
  "ライセンスや座標で行を除外・加工しない。利用条件は provenance の出典情報を見る。";

/** 入力の組み合わせの誤り（MCP 側が `McpInputError` に包む）。 */
export class RecordsInputError extends Error {}

export interface RecordsResult {
  source_id: string;
  record_set: RecordSetName;
  /** 実表名（AI の provenance 用）。 */
  table: string;
  /** 最大 limit+1 行（呼び出し側が切って truncated を決める。他のツールと同じ流儀）。 */
  rows: Record<string, string | number | null | object>[];
  limit: number;
  offset: number;
  /** `q`・`id` なしのとき、行数が出典全体の件数と同じ意味になる（呼び出し側が事前計算の n を付ける判断に使う）。 */
  unfiltered: boolean;
}

/** 入力から引く表を決める。出典に無い表・複数表で省略は入力エラー。 */
export function resolveRecordTable(a: Pick<RecordsInput, "source_id" | "record_set">): RecordSetName {
  const tables = RECORD_SOURCES[a.source_id];
  if (!tables) throw new RecordsInputError(`source_id '${a.source_id}' は get_records の対象ではない`);
  if (a.record_set === undefined) {
    if (tables.length === 1) return tables[0];
    throw new RecordsInputError(`出典 ${a.source_id} は記録の集合が複数ある。record_set を ${tables.join(" / ")} から指定する`);
  }
  if (!tables.includes(a.record_set)) {
    throw new RecordsInputError(`出典 ${a.source_id} に記録の集合 '${a.record_set}' は無い。record_set は ${tables.join(" / ")} から選ぶ`);
  }
  return a.record_set;
}

/** `|` 区切りの複合 source_id を要素の完全一致で照合する。LIKE の部分一致（前方一致の取り違え）にしない。 */
const SOURCE_MATCH = `instr('|' || source_id || '|', ?) > 0`;

export async function queryRecords(db: CubeDb, a: RecordsInput): Promise<RecordsResult> {
  const set = resolveRecordTable(a);
  const def: RecordTable = RECORD_TABLES[set];
  const table = def.table;
  if (a.include_geometry) {
    if (!def.geometry) throw new RecordsInputError(`表 ${table} にジオメトリは無い。include_geometry は使えない`);
    if (a.id === undefined) throw new RecordsInputError("include_geometry は id を指定した 1 件のときだけ使える（一覧では応答が大きくなる）");
  }
  if (a.q !== undefined && def.search.length === 0) throw new RecordsInputError(`表 ${table} は q（部分一致）に対応していない`);

  const limit = a.limit ?? 100;
  const offset = a.offset ?? 0;
  const conds: string[] = [SOURCE_MATCH];
  const params: SqlParam[] = [`|${a.source_id}|`];
  if (a.id !== undefined) {
    conds.push(`${def.pk} = ?`);
    params.push(a.id);
  }
  if (a.q !== undefined) {
    conds.push(`(${def.search.map((c) => `${c} LIKE ? ESCAPE '\\'`).join(" OR ")})`);
    const p = likeParam(a.q);
    for (let i = 0; i < def.search.length; i++) params.push(p);
  }
  const geomCol = a.include_geometry && def.geometry ? def.geometry : null;
  const cols = geomCol ? [...def.cols, geomCol] : [...def.cols];
  const sql = `SELECT ${cols.join(", ")} FROM ${table} WHERE ${conds.join(" AND ")} ORDER BY ${def.pk} LIMIT ? OFFSET ?`;
  const raw = await db.all(sql, [...params, limit + 1, offset]);
  const rows: RecordsResult["rows"] = geomCol ? raw.map((r) => ({ ...r, [geomCol]: parseGeometry(r[geomCol]) })) : raw;
  return { source_id: a.source_id, record_set: set, table, rows, limit, offset, unfiltered: a.id === undefined && a.q === undefined };
}

function parseGeometry(v: string | number | null | undefined): object | string | number | null {
  if (typeof v !== "string") return v ?? null;
  try {
    return JSON.parse(v) as object;
  } catch {
    return v; // 壊れた値は黙って捨てず、そのまま返す
  }
}
