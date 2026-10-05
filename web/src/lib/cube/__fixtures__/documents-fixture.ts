/**
 * 文書系列（`documents.ts`、Issue #48 PR-4 §3.1）のテスト用フィクスチャ。`better-sqlite3(":memory:")` に
 * migrations を当て、`documents`/`cells`/`notes` を手書きで入れる。部分索引 `ix_cells_series` は
 * `schema.ts` と同じ述語（`DOC_SERIES_WHERE`）で作る（migration 0009 は統合者が db:generate するので
 * ここでは migrations に無い。`IF NOT EXISTS` で、入った後は何もしない）。
 */
import Database from "better-sqlite3";
import { applyMigrations, wrapSqlite } from "./cube-fixture";
import { DOC_SERIES_WHERE } from "../doc-series-where";
import type { CubeDb } from "../db";

export interface DocFixture {
  db: CubeDb & { close(): void };
  raw: Database.Database;
}

interface CellFx {
  doc: string;
  table: string | null;
  row: string | null;
  year: number | null;
  value: string | null;
  page?: number | null;
  unit?: string | null;
  type?: string;
  total?: number;
  superseded?: number;
}

/** 系列 S1〜S6 の意図は `documents.test.ts` を参照。 */
export const DOCFX = {
  docA: "fx_doc_a",
  docB: "fx_doc_b",
  /** 3 年そろう通常の系列。 */
  s1: { doc: "fx_doc_a", table: "p1_t1", row: "部門|項目|合計" },
  /** 2022 年の値が割れる（5 と 6）系列。残る年は 3 点。 */
  split: { doc: "fx_doc_a", table: "p1_t1", row: "割れる系列" },
  /** 重複セルの値が同じ（5 と 5）で 1 点にまとまる系列。 */
  dup: { doc: "fx_doc_a", table: "p1_t1", row: "重複同値" },
  /** 年が 2 つしかない系列（minYears=3 で落ちる）。 */
  short: { doc: "fx_doc_a", table: "p1_t1", row: "短い系列" },
  /** 別の表（table_ids で名指しされる）。 */
  t2: { doc: "fx_doc_a", table: "p2_t1", row: "別表|値" },
  /** page_no/unit が割れる系列。 */
  paged: { doc: "fx_doc_b", table: "p9_t1", row: "ページ割れ" },
} as const;

function yearCells(k: { doc: string; table: string; row: string }, years: number[], base = 10, extra: Partial<CellFx> = {}): CellFx[] {
  return years.map((y, i) => ({ doc: k.doc, table: k.table, row: k.row, year: y, value: String(base + i), page: 1, unit: "頭", ...extra }));
}

function cells(): CellFx[] {
  return [
    ...yearCells(DOCFX.s1, [2018, 2019, 2020]),
    // 割れる年（2022 は 5 と 6）。列見出し違いの2セル。
    ...yearCells(DOCFX.split, [2020, 2021, 2023], 1),
    { doc: DOCFX.split.doc, table: DOCFX.split.table, row: DOCFX.split.row, year: 2022, value: "5", page: 1, unit: "頭" },
    { doc: DOCFX.split.doc, table: DOCFX.split.table, row: DOCFX.split.row, year: 2022, value: "6", page: 1, unit: "頭" },
    // 重複同値（2021 は 5 と 5）
    ...yearCells(DOCFX.dup, [2019, 2020], 1),
    { doc: DOCFX.dup.doc, table: DOCFX.dup.table, row: DOCFX.dup.row, year: 2021, value: "5", page: 1, unit: "頭" },
    { doc: DOCFX.dup.doc, table: DOCFX.dup.table, row: DOCFX.dup.row, year: 2021, value: "5", page: 1, unit: "頭" },
    // 2 年だけ
    ...yearCells(DOCFX.short, [2020, 2021]),
    // 別表
    ...yearCells(DOCFX.t2, [2018, 2019, 2020, 2021]),
    // page_no/unit が割れる（同じ値なので点は残る。page は MIN、unit は MAX）
    { doc: DOCFX.paged.doc, table: DOCFX.paged.table, row: DOCFX.paged.row, year: 2018, value: "3", page: 7, unit: "a" },
    { doc: DOCFX.paged.doc, table: DOCFX.paged.table, row: DOCFX.paged.row, year: 2018, value: "3", page: 5, unit: "b" },
    { doc: DOCFX.paged.doc, table: DOCFX.paged.table, row: DOCFX.paged.row, year: 2019, value: "4", page: 5, unit: "b" },
    { doc: DOCFX.paged.doc, table: DOCFX.paged.table, row: DOCFX.paged.row, year: 2020, value: "5", page: 6, unit: "b" },
    // 入力条件で落ちるセル（s1 に足しても点は増えない／別系列として 1 点以下）
    { doc: DOCFX.s1.doc, table: DOCFX.s1.table, row: DOCFX.s1.row, year: 2021, value: "99", page: 1, unit: "頭", superseded: 1 },
    { doc: DOCFX.s1.doc, table: DOCFX.s1.table, row: DOCFX.s1.row, year: 2022, value: "99", page: 1, unit: "頭", total: 1 },
    { doc: DOCFX.s1.doc, table: DOCFX.s1.table, row: DOCFX.s1.row, year: 2023, value: "abc", page: 1, unit: "頭", type: "text" },
    { doc: DOCFX.s1.doc, table: DOCFX.s1.table, row: DOCFX.s1.row, year: 2024, value: null, page: 1, unit: "頭" },
    { doc: DOCFX.s1.doc, table: DOCFX.s1.table, row: DOCFX.s1.row, year: null, value: "99", page: 1, unit: "頭" },
    { doc: DOCFX.s1.doc, table: DOCFX.s1.table, row: "", year: 2018, value: "1", page: 1, unit: "頭" },
    { doc: DOCFX.s1.doc, table: DOCFX.s1.table, row: null, year: 2018, value: "1", page: 1, unit: "頭" },
  ];
}

/** `blocks` は `blocks_timeseries`。 */
const NOTES: { id: string; doc: string; tableIds: string | null; blocks: number }[] = [
  { id: "n1", doc: "fx_doc_a", tableIds: "[]", blocks: 1 }, // 文書全体
  { id: "n2", doc: "fx_doc_a", tableIds: null, blocks: 1 }, // 文書全体（NULL）
  { id: "n3", doc: "fx_doc_a", tableIds: "", blocks: 1 }, // 文書全体（空文字）
  { id: "n4", doc: "fx_doc_a", tableIds: '["p2_t1"]', blocks: 1 }, // p2_t1 だけ
  { id: "n5", doc: "fx_doc_a", tableIds: '["p1_t1","p2_t1"]', blocks: 1 }, // 両方
  { id: "n6", doc: "fx_doc_a", tableIds: '["p2_t1"]', blocks: 0 }, // 止めない注記
  { id: "n7", doc: "fx_doc_b", tableIds: '["p9_t1"]', blocks: 1 }, // 別文書
];

export function buildDocFixture(): DocFixture {
  const raw = new Database(":memory:");
  applyMigrations(raw);
  raw.exec(`CREATE INDEX IF NOT EXISTS ix_cells_series ON cells (doc_id, table_id, row_key) WHERE ${DOC_SERIES_WHERE}`);

  const doc = raw.prepare(`INSERT INTO documents (doc_id, title, publisher, url, license) VALUES (?,?,?,?,?)`);
  doc.run(DOCFX.docA, "文書A", "県", "https://example.test/a.pdf", "CC-BY");
  doc.run(DOCFX.docB, "文書B", null, null, null);
  // cells の外部キーがあっても足りるよう、cells にしか出ない doc は作らない。

  const ins = raw.prepare(
    `INSERT INTO cells (doc_id, page_no, table_id, row_key, col_key, value, value_type, unit, fiscal_year, is_total, superseded)
     VALUES (@doc,@page,@table,@row,NULL,@value,@type,@unit,@year,@total,@superseded)`,
  );
  for (const c of cells()) {
    ins.run({
      doc: c.doc,
      page: c.page ?? null,
      table: c.table,
      row: c.row,
      value: c.value,
      type: c.type ?? "int",
      unit: c.unit ?? null,
      year: c.year,
      total: c.total ?? 0,
      superseded: c.superseded ?? 0,
    });
  }
  const note = raw.prepare(`INSERT INTO notes (note_id, doc_id, table_ids, kind, text, page, blocks_timeseries, reason) VALUES (?,?,?,?,?,?,?,?)`);
  for (const n of NOTES) note.run(n.id, n.doc, n.tableIds, "k", "t", 1, n.blocks, null);

  return { db: wrapSqlite(raw), raw };
}
