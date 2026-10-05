/**
 * `doc_series`（`documents.ts`）の入力条件。`schema.ts` の部分索引 `ix_cells_series` の `WHERE` と
 * `documents.ts` の問い合わせの `WHERE` が**一字一句**同じになるよう1か所に置く
 * （SQLite は部分索引の述語が問い合わせの WHERE に含意されるときだけ索引を使う。PR-4 §3.1）。
 *
 * 依存を持たない（`schema.ts` が drizzle-kit から相対 import で読むため、`@/` エイリアスも
 * 他モジュールも import しない）。列名は修飾しない（問い合わせの表エイリアスを付けない）。
 */
export const DOC_SERIES_WHERE =
  "superseded = 0 AND is_total = 0 AND value_type IN ('int','float') AND value IS NOT NULL AND fiscal_year IS NOT NULL AND row_key IS NOT NULL AND row_key <> ''";
