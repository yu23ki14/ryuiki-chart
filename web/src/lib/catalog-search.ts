/**
 * 外部ポータルの目録を引く共通の実装（`find_datasets`。docs/plans/MCP_EXTERNAL_CATALOG.md §4）。
 * MCP（`lib/mcp/tools-find-datasets.ts`）と AI（`lib/ai/tools.ts`）が同じ関数を呼ぶ。
 *
 * - 値は返さない。「どんなデータがあるか（定義）」と「最新を取りに行く URL」だけ。目録（`external_dataset`/`external_resource`）は
 *   収穫時点（`fetched_at`）の写しで、最新の更新日・資源 URL は `urls.api_package_show`（CKAN の package_show）が正。
 *   Worker からは外部ポータルを叩かない（更新日を補正しない。利用側が api_url で確かめる）。
 * - 任意 SQL ではない。SQL は固定の形で、表名・列名は定数だけ（入力から組み立てない）。`SELECT *` は書かない。
 * - ライセンスで行を除外しない（ADR-0028）。ライセンスが空の行は license: null（不明）で返す。
 * - 列の定義（`data_definition.columns`）は、見出しを検出できたものだけ根拠つきで返す。無いものは not_extracted（推測しない）。
 * - 資源の取得は `json_each(?)`（バインド 1 個）。`IN (...)` に生の一覧を並べない（D1 のバインド 100 個制限）。
 */
import { z } from "zod";
import type { CubeDb, SqlParam } from "@/lib/cube/db";
import { likeParam, likeText } from "@/lib/query-params";
import { FIND_DATASET_SOURCE_IDS as GENERATED_SOURCE_IDS, SOURCE_META } from "@/lib/registry/generated-source";

export const FIND_DATASETS_MAX_ROWS = 100;
/** `include_resources: true` を許す `limit` の上限（資源は 1 データセットに最大 450 件ほどあり、一覧では応答が大きくなる）。 */
export const FIND_DATASETS_RESOURCES_MAX_LIMIT = 10;
const Q_MAX_TERMS = 3;

/** `z.enum` に渡す形（空でない配列）。生成物は `registry/source/access.yaml` の `catalog` を宣言した出典。 */
export const FIND_DATASET_SOURCE_IDS = GENERATED_SOURCE_IDS as unknown as [string, ...string[]];

/** 形式（資源の `format` は大文字。`SHP,CSV` のようにカンマ区切りが混ざるので要素で照合する）。 */
export const FIND_DATASET_FORMATS = ["CSV", "XLSX", "XLS", "PDF", "ZIP", "SHP", "GEOJSON", "JSON", "HTML", "TXT", "XML"] as const;

/** MCP・AI 共通の入力（z.tuple は使わない）。組み合わせの検査は `queryDatasets` が行う。 */
export const findDatasetsInputSchema = z.object({
  q: likeText("題名・説明・タグ・分野の部分一致。空白区切りは AND（3 語まで）").optional(),
  source_id: z.enum(FIND_DATASET_SOURCE_IDS).optional().describe("出典で絞る（ポータル単位。describe_catalog what='sources' で queryable_via に find_datasets があるもの）"),
  organization: likeText("提供組織名の部分一致（例: 厚木市）").optional(),
  format: z.enum(FIND_DATASET_FORMATS).optional().describe("資源に 1 つでもこの形式を含むデータセット（SHP,CSV のような複数形式は要素ごとに照合）"),
  modified_since: z
    .string()
    .regex(/^\d{4}-\d{2}-\d{2}$/, "YYYY-MM-DD で指定する")
    .optional()
    .describe("metadata_modified がこの日以降。収穫時点（fetched_at）の値で比べる。最新の更新日は api_package_show で確かめる"),
  id: z.string().trim().min(1).max(300).optional().describe("dataset_key の完全一致（1 件取り。資源を全件返す）"),
  include_resources: z.boolean().optional().describe(`資源（直リンク・形式・サイズ）も返す。既定 false（資源の数と形式別の件数だけ）。limit が ${FIND_DATASETS_RESOURCES_MAX_LIMIT} 以下のときだけ`),
  limit: z.number().int().min(1).max(FIND_DATASETS_MAX_ROWS).optional().describe(`返す件数の上限（既定 20、最大 ${FIND_DATASETS_MAX_ROWS}）`),
  offset: z.number().int().min(0).optional().describe("読み飛ばす件数（ページング。並びは metadata_modified の新しい順・dataset_key 昇順で固定）"),
});
export type FindDatasetsInput = z.infer<typeof findDatasetsInputSchema>;

/** 出典 ID → 「ID=名称」の一覧（説明文用。生成物から）。 */
function sourceList(): string {
  return FIND_DATASET_SOURCE_IDS.map((id) => `${id}=${SOURCE_META.find((m) => m.sourceId === id)?.nameJa ?? id}`).join("、");
}

export const FIND_DATASETS_DESCRIPTION =
  "外部オープンデータポータル（CKAN: 神奈川県・相模原市・BODIK・横浜市、e-Stat の統計表）の目録を検索する。" +
  "ここに値は無い。「どんなデータセットがあるか（題名・説明・提供組織・ライセンス・形式・列の見出し）」と、" +
  "「最新を取りに行く URL」（urls.api_package_show・urls.page・資源の direct_url）を返す。" +
  "値が要るときは、返した URL を利用者側で開く。" +
  "目録は収穫日（fetched_at）時点の写しで、metadata_modified・資源のサイズ・URL は古いことがある" +
  "（月単位で更新される）。最新は CKAN の api_package_show（package_show の result.metadata_modified と result.resources[]）で確かめる。" +
  "列の見出し（data_definition.columns）は、検出できたものだけ根拠つきで返す。status が not_extracted なら不明（直リンクのファイルを開いて確認する）。" +
  "ライセンスが空のデータセットは license: null（不明）で返す（除外しない）。" +
  "q・source_id・organization・format・modified_since・id のどれか 1 つ以上が要る。資源の一覧は id（1 件取り）か include_resources（limit 10 以下）で返す。" +
  `使える出典: ${sourceList()}。`;

/** 入力の組み合わせの誤り。`onInputError` で呼び出し側の例外（MCP は McpInputError）に変えられる。 */
export class FindDatasetsInputError extends Error {}

export interface QueryDatasetsOptions {
  onInputError?: (msg: string) => Error;
}

const COLS = [
  "ds.dataset_key", "ds.source_id", "ds.portal", "ds.title", "ds.description", "ds.description_truncated", "ds.organization",
  "ds.license", "ds.license_url", "ds.groups", "ds.tags", "ds.n_resources", "ds.metadata_modified", "ds.page_url", "ds.api_url", "ds.fetched_at",
] as const;

interface DatasetRow {
  dataset_key: string;
  source_id: string;
  portal: string;
  title: string;
  description: string | null;
  description_truncated: number;
  organization: string | null;
  license: string | null;
  license_url: string | null;
  groups: string | null;
  tags: string | null;
  n_resources: number;
  metadata_modified: string | null;
  page_url: string;
  api_url: string | null;
  fetched_at: string;
}

interface ResourceRow {
  dataset_key: string;
  resource_key: string;
  name: string | null;
  format: string | null;
  size: number | null;
  last_modified: string | null;
  direct_url: string | null;
  page_url: string | null;
  sheets_json: string | null;
}

interface FormatRow {
  dataset_key: string;
  format: string | null;
  n: number;
  n_with_header: number;
}

export interface Sheet {
  sheet: string | null;
  n_rows: number | null;
  n_cols: number | null;
  header: string[] | null;
  header_basis?: string;
  header_truncated?: boolean;
  units?: string[];
}

/** 列の定義の根拠（見出しの出どころ）。ポータルごとに 1 つ。 */
const COLUMNS_BASIS: Record<string, string> = {
  ckan: "converted_csv_first_row",
  estat: "harvested_indicators",
};

const HOW_TO_LATEST: Record<string, string> = {
  ckan:
    "最新の資源 URL・更新日は urls.api_package_show（package_show）の result.resources[] と result.metadata_modified。" +
    "ここの値は fetched_at 時点",
  estat:
    "直リンク（資源の direct_url）は appId・ログイン不要。e-Stat API（api.e-stat.go.jp）を使うなら appId の登録が要る（本システムは API を使わない）。" +
    "新しい版（statInfId が変わる）は e-Stat の検索ページ（access.search_url）で探す。ここの値は fetched_at 時点",
};

export interface DatasetOut {
  dataset_key: string;
  source_id: string;
  title: string;
  description: string | null;
  description_truncated: boolean;
  organization: string | null;
  license: string | null;
  license_url: string | null;
  tags: string[];
  groups: string[];
  n_resources: number;
  formats: Record<string, number>;
  metadata_modified: string | null;
  fetched_at: string;
  urls: {
    api_package_show: string | null;
    page: string;
    resources?: { name: string | null; format: string | null; size: number | null; last_modified: string | null; direct_url: string | null; page_url: string | null }[];
  };
  data_definition: {
    columns: { status: "available" | "not_extracted"; basis: string | null; note: string };
    sheets?: (Sheet & { resource_key: string })[];
  };
  access: { auth: "none" | "appId_for_api_only"; how_to_get_latest: string; search_url?: string | null };
}

export interface DatasetsResult {
  rows: DatasetOut[];
  /** 返した行に出てくる出典（provenance 用）。 */
  source_ids: string[];
  limit: number;
  offset: number;
  truncated: boolean;
  /** `q` なしのときだけ（同じ絞り込みの件数）。`q` ありは数えない（`limit+1` 件読んで truncated を決める）。 */
  n_total: number | null;
}

const split = (v: string | null) => (v ? v.split("|").filter(Boolean) : []);

function parseSheets(json: string | null): Sheet[] {
  if (!json) return [];
  try {
    const v = JSON.parse(json) as unknown;
    return Array.isArray(v) ? (v as Sheet[]) : [];
  } catch {
    return []; // 壊れた値は捨てる（列の定義が無い扱い。推測しない）
  }
}

/** 入力の検査と WHERE の組み立て。 */
function buildWhere(a: FindDatasetsInput, fail: (m: string) => Error): { where: string; params: SqlParam[] } {
  if (a.q === undefined && a.source_id === undefined && a.organization === undefined && a.format === undefined && a.modified_since === undefined && a.id === undefined) {
    throw fail("q・source_id・organization・format・modified_since・id のどれか 1 つ以上を指定する（全件取りはできない）");
  }
  const conds: string[] = [];
  const params: SqlParam[] = [];
  if (a.source_id !== undefined) {
    conds.push("ds.source_id = ?");
    params.push(a.source_id);
  }
  if (a.id !== undefined) {
    conds.push("ds.dataset_key = ?");
    params.push(a.id);
  }
  if (a.organization !== undefined) {
    conds.push("ds.organization LIKE ? ESCAPE '\\'");
    params.push(likeParam(a.organization));
  }
  if (a.modified_since !== undefined) {
    if (Number.isNaN(Date.parse(`${a.modified_since}T00:00:00Z`))) throw fail(`modified_since '${a.modified_since}' は日付として読めない（YYYY-MM-DD）`);
    conds.push("ds.metadata_modified >= ?");
    params.push(a.modified_since);
  }
  if (a.q !== undefined) {
    const terms = a.q.split(/\s+/).filter(Boolean);
    if (terms.length > Q_MAX_TERMS) throw fail(`q の語は ${Q_MAX_TERMS} つまで（空白区切りは AND。いま ${terms.length} 語）`);
    for (const t of terms) {
      conds.push("(ds.title LIKE ? ESCAPE '\\' OR ds.description LIKE ? ESCAPE '\\' OR ds.tags LIKE ? ESCAPE '\\' OR ds.groups LIKE ? ESCAPE '\\')");
      const p = likeParam(t);
      params.push(p, p, p, p);
    }
  }
  if (a.format !== undefined) {
    // カンマ区切りの要素で照合する（部分一致にしない: HTML が XHTML 等に当たらない）
    conds.push("EXISTS (SELECT 1 FROM external_resource r WHERE r.dataset_key = ds.dataset_key AND instr(',' || r.format || ',', ?) > 0)");
    params.push(`,${a.format},`);
  }
  return { where: conds.join(" AND "), params };
}

export async function queryDatasets(db: CubeDb, a: FindDatasetsInput, opt: QueryDatasetsOptions = {}): Promise<DatasetsResult> {
  const fail = opt.onInputError ?? ((m: string) => new FindDatasetsInputError(m));
  const limit = a.limit ?? 20;
  const offset = a.offset ?? 0;
  const withResources = a.id !== undefined || a.include_resources === true;
  if (a.include_resources && limit > FIND_DATASETS_RESOURCES_MAX_LIMIT && a.id === undefined) {
    throw fail(`include_resources は limit が ${FIND_DATASETS_RESOURCES_MAX_LIMIT} 以下のときだけ使える（資源の一覧は大きい。いま limit=${limit}）`);
  }
  const { where, params } = buildWhere(a, fail);

  const sql = `SELECT ${COLS.join(", ")} FROM external_dataset ds WHERE ${where} ORDER BY ds.metadata_modified DESC, ds.dataset_key ASC LIMIT ? OFFSET ?`;
  const raw = await db.all<DatasetRow>(sql, [...params, limit + 1, offset]);
  const truncated = raw.length > limit;
  const page = raw.slice(0, limit);

  let nTotal: number | null = null;
  if (a.q === undefined) {
    const c = await db.all<{ n: number }>(`SELECT count(*) AS n FROM external_dataset ds WHERE ${where}`, params);
    nTotal = c[0]?.n ?? 0;
  }

  const keys = JSON.stringify(page.map((r) => r.dataset_key));
  const resources = new Map<string, ResourceRow[]>();
  const formats = new Map<string, FormatRow[]>();
  if (page.length > 0) {
    if (withResources) {
      const rs = await db.all<ResourceRow>(
        "SELECT dataset_key, resource_key, name, format, size, last_modified, direct_url, page_url, sheets_json FROM external_resource " +
          "WHERE dataset_key IN (SELECT value FROM json_each(?)) ORDER BY dataset_key, resource_key",
        [keys],
      );
      for (const r of rs) (resources.get(r.dataset_key) ?? resources.set(r.dataset_key, []).get(r.dataset_key)!).push(r);
    } else {
      const fs = await db.all<FormatRow>(
        "SELECT r.dataset_key AS dataset_key, r.format AS format, count(*) AS n, " +
          "sum(EXISTS (SELECT 1 FROM json_each(r.sheets_json) j WHERE json_type(j.value, '$.header') = 'array')) AS n_with_header " +
          "FROM external_resource r WHERE r.dataset_key IN (SELECT value FROM json_each(?)) GROUP BY r.dataset_key, r.format",
        [keys],
      );
      for (const r of fs) (formats.get(r.dataset_key) ?? formats.set(r.dataset_key, []).get(r.dataset_key)!).push(r);
    }
  }

  const rows = page.map((d) => toOut(d, withResources ? (resources.get(d.dataset_key) ?? []) : null, formats.get(d.dataset_key) ?? []));
  return { rows, source_ids: [...new Set(page.map((r) => r.source_id))], limit, offset, truncated, n_total: nTotal };
}

function addFormat(into: Record<string, number>, format: string | null, n: number) {
  const parts = format ? format.split(",").map((s) => s.trim()).filter(Boolean) : [];
  if (parts.length === 0) into.unspecified = (into.unspecified ?? 0) + n;
  for (const p of parts) into[p] = (into[p] ?? 0) + n;
}

function toOut(d: DatasetRow, res: ResourceRow[] | null, fmt: FormatRow[]): DatasetOut {
  const formats: Record<string, number> = {};
  let nWithHeader = 0;
  let sheets: (Sheet & { resource_key: string })[] | undefined;
  if (res) {
    sheets = [];
    for (const r of res) {
      addFormat(formats, r.format, 1);
      const ss = parseSheets(r.sheets_json);
      if (ss.some((s) => Array.isArray(s.header))) nWithHeader += 1;
      for (const s of ss) sheets.push({ resource_key: r.resource_key, ...s });
    }
  } else {
    for (const f of fmt) {
      addFormat(formats, f.format, f.n);
      nWithHeader += f.n_with_header ?? 0;
    }
  }
  const available = nWithHeader > 0;
  const meta = SOURCE_META.find((m) => m.sourceId === d.source_id);
  const out: DatasetOut = {
    dataset_key: d.dataset_key,
    source_id: d.source_id,
    title: d.title,
    description: d.description,
    description_truncated: d.description_truncated === 1,
    organization: d.organization,
    license: d.license,
    license_url: d.license_url,
    tags: split(d.tags),
    groups: split(d.groups),
    n_resources: d.n_resources,
    formats,
    metadata_modified: d.metadata_modified,
    fetched_at: d.fetched_at,
    urls: {
      api_package_show: d.api_url,
      page: d.page_url,
      ...(res
        ? { resources: res.map((r) => ({ name: r.name, format: r.format, size: r.size, last_modified: r.last_modified, direct_url: r.direct_url, page_url: r.page_url })) }
        : {}),
    },
    data_definition: {
      columns: available
        ? {
            status: "available",
            basis: COLUMNS_BASIS[d.portal] ?? null,
            note: "見出しを検出できた資源だけ列名を返す（意味・単位・型は元データに無いので返さない）。見出しの無い資源は直リンクのファイルを開いて確認する",
          }
        : { status: "not_extracted", basis: null, note: "見出しを取り出していない。直リンクのファイルを開いて確認する" },
      ...(sheets ? { sheets } : {}),
    },
    access: {
      auth: d.portal === "estat" ? "appId_for_api_only" : "none",
      how_to_get_latest: HOW_TO_LATEST[d.portal] ?? HOW_TO_LATEST.ckan,
      ...(d.portal === "estat" ? { search_url: meta?.homepageUrl ?? null } : {}),
    },
  };
  return out;
}
