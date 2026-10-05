/**
 * 文書の数値系列（v1 `doc_series`/`doc_series_meta` の置き換え。Issue #48 PR-4 §3.1）。
 * キューブにせず、`cells`/`notes`/`documents`（D1 に残す原本表）から問い合わせ時に引く。
 */
import type { CubeDb } from "./db";
import { DOC_SERIES_WHERE } from "./doc-series-where";

export { DOC_SERIES_WHERE };

export interface DocSeriesMeta {
  docId: string;
  tableId: string;
  rowKey: string;
  label: string;
  pageNo: number | null;
  nYears: number;
  yFrom: number;
  yTo: number;
  unit: string | null;
  docTitle: string | null;
  publisher: string | null;
  url: string | null;
  license: string | null;
  nWarnings: number;
}

export interface DocSeriesPoint {
  fiscalYear: number;
  value: number;
  unit: string | null;
  pageNo: number | null;
}

/**
 * 行キーの表示名＝最後の `|` の後ろを trim したもの（空なら `row_key` 全体）。
 * API が `label` として返し、UI は再計算しない（label を作る場所はここ1つ）。
 * v1 は最初の `|` の次から末尾の `|` までを切り出していた（`PHASE_B_DOCUMENTS.md` §3 ①）。
 */
export function rowKeyLabel(rowKey: string): string {
  const i = rowKey.lastIndexOf("|");
  if (i < 0) return rowKey;
  const tail = rowKey.slice(i + 1).trim();
  return tail === "" ? rowKey : tail;
}

type DocRow = Record<string, string | number | null>;

/**
 * 点（`(doc, table, row_key, fiscal_year)` ごと）。**値が割れる年は点にしない**（D1=A。
 * 同じ年に別の値のセルが複数あると v1 はそれを平均して「どの観測値でもない数」にしていた。
 * 値が同じ重複は1点）。`page_no`/`unit` は GROUP BY 外の裸列にせず MIN/MAX で決める
 * （走査順に依らない。v1 の ④）。
 *
 * `INDEXED BY` は付けない: 部分索引 `ix_cells_series` は `cells.sqlite`（原本）には無く
 * （D1 にだけある）、述語が `DOC_SERIES_WHERE` と一致すれば SQLite が自動で選ぶ。
 */
function pointsCte(extraWhere = ""): string {
  return `
  pts AS (
    SELECT doc_id, table_id, row_key, fiscal_year,
           MIN(CAST(value AS REAL)) AS value,
           MIN(page_no) AS page_no,
           MAX(unit) AS unit
    FROM cells
    WHERE ${DOC_SERIES_WHERE}${extraWhere}
    GROUP BY doc_id, table_id, row_key, fiscal_year
    HAVING MIN(CAST(value AS REAL)) = MAX(CAST(value AS REAL))
  )`;
}

const POINTS_CTE = pointsCte();

/**
 * `n_warnings`: 時系列を止める注記（`blocks_timeseries=1`）のうち、文書全体にかかるもの
 * （`table_ids` が NULL・空・`'[]'`）と、この表を名指しするものの件数（v1 は doc 単位で数えていた。②）。
 */
const WARNINGS_SQL = `(SELECT COUNT(*) FROM notes n
     WHERE n.doc_id = m.doc_id AND n.blocks_timeseries = 1
       AND (n.table_ids IS NULL OR n.table_ids = '' OR n.table_ids = '[]'
            OR EXISTS (SELECT 1 FROM json_each(n.table_ids) j WHERE j.value = m.table_id)))`;

/** `n_years >= minYears`（既定 3）。`n_years DESC, doc_id, table_id, row_key` 順。 */
export async function docSeriesList(db: CubeDb, opt: { minYears?: number } = {}): Promise<DocSeriesMeta[]> {
  const rows = await db.all<DocRow>(
    `WITH ${POINTS_CTE},
     m AS (
       SELECT doc_id, table_id, row_key, MAX(page_no) AS page_no, COUNT(*) AS n_years,
              MIN(fiscal_year) AS y_from, MAX(fiscal_year) AS y_to, MAX(unit) AS unit
       FROM pts
       GROUP BY doc_id, table_id, row_key
       HAVING COUNT(*) >= ?
     )
     SELECT m.doc_id, m.table_id, m.row_key, m.page_no, m.n_years, m.y_from, m.y_to, m.unit,
            dd.title AS doc_title, dd.publisher, dd.url, dd.license,
            ${WARNINGS_SQL} AS n_warnings
     FROM m JOIN documents dd ON dd.doc_id = m.doc_id
     ORDER BY m.n_years DESC, m.doc_id, m.table_id, m.row_key`,
    [opt.minYears ?? 3],
  );
  return rows.map((r) => ({
    docId: r.doc_id as string,
    tableId: r.table_id as string,
    rowKey: r.row_key as string,
    label: rowKeyLabel(r.row_key as string),
    pageNo: r.page_no as number | null,
    nYears: r.n_years as number,
    yFrom: r.y_from as number,
    yTo: r.y_to as number,
    unit: r.unit as string | null,
    docTitle: r.doc_title as string | null,
    publisher: r.publisher as string | null,
    url: r.url as string | null,
    license: r.license as string | null,
    nWarnings: r.n_warnings as number,
  }));
}

/** 1系列の点（`fiscal_year` 昇順）。値が割れる年は含まれない（`docSeriesList` の `nYears` と同じ集合）。 */
export async function docSeriesPoints(
  db: CubeDb,
  docId: string,
  tableId: string,
  rowKey: string,
): Promise<DocSeriesPoint[]> {
  const rows = await db.all<DocRow>(
    // 系列を CTE の中で絞る（部分索引 ix_cells_series の先頭3列 doc_id/table_id/row_key が効く）。
    `WITH ${pointsCte(" AND doc_id = ? AND table_id = ? AND row_key = ?")}
     SELECT fiscal_year, value, unit, page_no FROM pts
     ORDER BY fiscal_year`,
    [docId, tableId, rowKey],
  );
  return rows.map((r) => ({
    fiscalYear: r.fiscal_year as number,
    value: r.value as number,
    unit: r.unit as string | null,
    pageNo: r.page_no as number | null,
  }));
}
