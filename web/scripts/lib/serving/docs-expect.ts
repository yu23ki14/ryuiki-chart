/**
 * 文書系列の3規則（`classify.ts` の `DocsExpectations`）が「独立に組んだ中間点」として使う期待値を、
 * `cells.sqlite`（`cells`/`notes`）から**別の SQL で**作る（Issue #48 PR-4、
 * `docs/plans/V2_SERVING_PR4.md` §5.2）。説明の鎖は「v1 →(規則)→ ここの再計算 →(=)→ v2」。
 *
 * **`@/lib/cube` を import しない**: 画面と v2 アダプタが通る関数（`lib/cube/documents.ts`）で期待値を
 * 作ると、v2 が間違っても期待値も同じく間違って「説明できた」ことになる（PR-2 §8.4 の再発防止）。
 * `docs-expect.test.ts` がこのファイルのソースに `lib/cube` の import が無いことを機械的に確かめる。
 *
 * v1 の式（`label` の `instr/replace`・入力条件）は `scripts/build-derived.mjs` の
 * `doc_series` の SQL をそのまま写している（書き直さない）。v1 の label はその式を SQLite で評価する。
 * v2 の label は `lastIndexOf('|')`（`rowKeyLabel`）の JS 再実装、警告は `table_ids` の JSON を JS で解く。
 *
 * 読み取り専用。`ids`（回す問い合わせ id）に doc 系が無ければ何も読まない。
 */
import Database from "better-sqlite3";
import { docPointKey, docSeriesKey, type DocSeriesExpect, type DocsExpectations } from "./classify";

/** 文書系列の問い合わせ id（imputation にも v1互換キューブにも依らない）。 */
export const DOC_QUERY_IDS: ReadonlySet<string> = new Set(["doc_series_meta", "doc_series_points"]);

/** PR-4 で足した 4＋1 の問い合わせ id のうち、imputation・合成データに依らないもの（zero 再実行・v1compat を省く）。 */
export const PR4_QUERY_IDS: ReadonlySet<string> = new Set([
  ...DOC_QUERY_IDS,
  "overview_counts",
  "landuse_highlight",
]);

export function docsNeeded(ids: Iterable<string>): boolean {
  for (const id of ids) if (DOC_QUERY_IDS.has(id)) return true;
  return false;
}

/** v1 の `doc_series` と同じ入力条件（`scripts/build-derived.mjs`）。 */
const NUM_CELLS_SQL = `
  SELECT c.doc_id, c.table_id, c.page_no, c.row_key, c.fiscal_year,
         CAST(c.value AS REAL) AS v,
         CASE WHEN instr(c.row_key,'|') > 0
              THEN substr(c.row_key, length(c.row_key) - length(replace(substr(c.row_key, instr(c.row_key,'|')+1), '|', '')) + 1)
              ELSE c.row_key END AS v1_label
  FROM cells c
  WHERE c.superseded = 0 AND c.is_total = 0
    AND c.value_type IN ('int','float') AND c.value IS NOT NULL
    AND c.fiscal_year IS NOT NULL AND c.row_key IS NOT NULL AND c.row_key <> ''
`;

/** v2 の label（最後の `|` の後ろ。空なら row_key 全体）。`lib/cube/documents.ts` の `rowKeyLabel` の独立な再実装。 */
export function expectedRowKeyLabel(rowKey: string): string {
  const i = rowKey.lastIndexOf("|");
  const tail = i >= 0 ? rowKey.slice(i + 1) : rowKey;
  return tail === "" ? rowKey : tail;
}

interface NoteRow {
  doc_id: string;
  table_ids: string | null;
}

/** `table_ids`（JSON 配列文字列）。NULL・''・'[]' は文書全体にかかる注記（null を返す）。 */
export function parseNoteTableIds(raw: string | null): Set<string> | null {
  if (raw === null || raw.trim() === "" || raw.trim() === "[]") return null;
  try {
    const arr = JSON.parse(raw) as unknown;
    if (!Array.isArray(arr) || arr.length === 0) return null;
    return new Set(arr.map((x) => String(x)));
  } catch {
    return null;
  }
}

interface GroupAcc {
  values: Set<number>;
  pageNo: number | null;
}

interface SeriesAcc {
  v1Label: string;
  groups: Map<number, GroupAcc>; // fiscal_year → group
}

/** `cells.sqlite` を開いた接続から期待値を作る（テストはメモリ DB を渡す）。 */
export function buildDocsExpectations(db: Database.Database): DocsExpectations {
  const rows = db.prepare(NUM_CELLS_SQL).all() as {
    doc_id: string;
    table_id: string;
    page_no: number | null;
    row_key: string;
    fiscal_year: number;
    v: number;
    v1_label: string;
  }[];

  const bySeries = new Map<string, { docId: string; tableId: string; acc: SeriesAcc }>();
  const yearDistinct = new Map<string, number>();
  for (const r of rows) {
    const sk = docSeriesKey(r.doc_id, r.table_id, r.row_key);
    let s = bySeries.get(sk);
    if (!s) {
      s = { docId: r.doc_id, tableId: r.table_id, acc: { v1Label: r.v1_label, groups: new Map() } };
      bySeries.set(sk, s);
    }
    let g = s.acc.groups.get(r.fiscal_year);
    if (!g) {
      g = { values: new Set(), pageNo: null };
      s.acc.groups.set(r.fiscal_year, g);
    }
    g.values.add(r.v);
    if (r.page_no !== null && (g.pageNo === null || r.page_no > g.pageNo)) g.pageNo = r.page_no;
  }

  // 警告: v1 は doc 単位の COUNT(*)、v2 は文書全体にかかる注記＋当該 table_id を含む注記。
  const notes = db
    .prepare(`SELECT doc_id, table_ids FROM notes WHERE blocks_timeseries = 1`)
    .all() as NoteRow[];
  const v1WarnByDoc = new Map<string, number>();
  const notesByDoc = new Map<string, (Set<string> | null)[]>();
  for (const n of notes) {
    v1WarnByDoc.set(n.doc_id, (v1WarnByDoc.get(n.doc_id) ?? 0) + 1);
    const list = notesByDoc.get(n.doc_id) ?? [];
    list.push(parseNoteTableIds(n.table_ids));
    notesByDoc.set(n.doc_id, list);
  }

  const series = new Map<string, DocSeriesExpect>();
  for (const [sk, { docId, tableId, acc }] of bySeries) {
    const rowKey = sk.split("\u0000")[2];
    const all: { year: number; pageNo: number | null }[] = [];
    const good: { year: number; pageNo: number | null }[] = [];
    for (const [year, g] of acc.groups) {
      yearDistinct.set(docPointKey(docId, tableId, rowKey, year), g.values.size);
      all.push({ year, pageNo: g.pageNo });
      if (g.values.size === 1) good.push({ year, pageNo: g.pageNo });
    }
    const maxPage = (xs: { pageNo: number | null }[]): number | null =>
      xs.reduce<number | null>((m, x) => (x.pageNo !== null && (m === null || x.pageNo > m) ? x.pageNo : m), null);
    const years = (xs: { year: number }[]) => xs.map((x) => x.year);
    let v2Warnings = 0;
    for (const ids of notesByDoc.get(docId) ?? []) if (ids === null || ids.has(tableId)) v2Warnings += 1;
    series.set(sk, {
      v1Label: acc.v1Label,
      v2Label: expectedRowKeyLabel(rowKey),
      v1Warnings: v1WarnByDoc.get(docId) ?? 0,
      v2Warnings,
      allYears: all.length,
      allFrom: all.length ? Math.min(...years(all)) : null,
      allTo: all.length ? Math.max(...years(all)) : null,
      allPageNo: maxPage(all),
      goodYears: good.length,
      goodFrom: good.length ? Math.min(...years(good)) : null,
      goodTo: good.length ? Math.max(...years(good)) : null,
      goodPageNo: maxPage(good),
    });
  }
  return { series, yearDistinct };
}

/** `cells.sqlite` を読み取り専用で開いて期待値を作る。 */
export function loadDocsExpectations(cellsDbPath: string, ids: Iterable<string>): DocsExpectations | undefined {
  if (!docsNeeded(ids)) return undefined;
  const db = new Database(cellsDbPath, { readonly: true, fileMustExist: true });
  try {
    return buildDocsExpectations(db);
  } finally {
    db.close();
  }
}
