/**
 * 文書の数値系列（v1 `doc_series`/`doc_series_meta` の置き換え。Issue #48 PR-4 §3.1）。
 * キューブにせず、`cells`/`notes`/`documents`（D1 に残す原本表）から問い合わせ時に引く。
 */
import type { CubeDb } from "./db";

export { DOC_SERIES_WHERE } from "./doc-series-where";

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

/** 行キーの表示名＝最後の `|` の後ろ（空なら `row_key` 全体）。API が返し、UI は再計算しない。 */
export function rowKeyLabel(_rowKey: string): string {
  throw new Error("rowKeyLabel: not implemented");
}

/** `n_years >= minYears`（既定 3）。`n_years DESC, doc_id, table_id` 順。 */
export async function docSeriesList(_db: CubeDb, _opt?: { minYears?: number }): Promise<DocSeriesMeta[]> {
  throw new Error("docSeriesList: not implemented");
}

/** `fiscal_year` 昇順。 */
export async function docSeriesPoints(
  _db: CubeDb,
  _docId: string,
  _tableId: string,
  _rowKey: string,
): Promise<DocSeriesPoint[]> {
  throw new Error("docSeriesPoints: not implemented");
}
