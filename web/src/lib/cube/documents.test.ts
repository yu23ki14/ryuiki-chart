import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { DOCFX, buildDocFixture, type DocFixture } from "./__fixtures__/documents-fixture";
import type { CubeDb, SqlParam } from "./db";
import { DOC_SERIES_WHERE, docSeriesList, docSeriesPoints, rowKeyLabel } from "./documents";

let fx: DocFixture;
beforeAll(() => {
  fx = buildDocFixture();
});
afterAll(() => fx.db.close());

describe("rowKeyLabel（最後の | の後ろ）", () => {
  it("複数の | は最後の後ろ。v1 は最初の | の次から末尾の | までだった", () => {
    expect(rowKeyLabel("部門|項目|合計")).toBe("合計");
    expect(rowKeyLabel("a|b")).toBe("b");
  });
  it("| が無ければ row_key 全体、末尾が | で後ろが空でも row_key 全体", () => {
    expect(rowKeyLabel("合 計（人数）")).toBe("合 計（人数）");
    expect(rowKeyLabel("a|")).toBe("a|");
    expect(rowKeyLabel("")).toBe("");
  });
  it("後ろの前後の空白は落とす。空白だけなら row_key 全体", () => {
    expect(rowKeyLabel("a|  b ")).toBe("b");
    expect(rowKeyLabel("湘南地域|  ")).toBe("湘南地域|  ");
  });
});

describe("docSeriesList", () => {
  it("n_years DESC, doc_id, table_id, row_key の順。既定は 3 年以上（短い系列は出ない）", async () => {
    const list = await docSeriesList(fx.db);
    expect(list.map((m) => [m.docId, m.tableId, m.rowKey, m.nYears])).toEqual([
      [DOCFX.t2.doc, DOCFX.t2.table, DOCFX.t2.row, 4],
      [DOCFX.split.doc, DOCFX.split.table, DOCFX.split.row, 3],
      [DOCFX.s1.doc, DOCFX.s1.table, DOCFX.s1.row, 3],
      [DOCFX.dup.doc, DOCFX.dup.table, DOCFX.dup.row, 3],
      [DOCFX.paged.doc, DOCFX.paged.table, DOCFX.paged.row, 3],
    ]);
  });

  it("minYears を下げると 2 年の系列も出る", async () => {
    const list = await docSeriesList(fx.db, { minYears: 2 });
    expect(list.some((m) => m.rowKey === DOCFX.short.row && m.nYears === 2)).toBe(true);
  });

  it("入力条件（superseded・is_total・非数値・value/年/row_key の欠け）のセルは点にならない", async () => {
    const m = (await docSeriesList(fx.db)).find((x) => x.rowKey === DOCFX.s1.row)!;
    expect(m).toMatchObject({ nYears: 3, yFrom: 2018, yTo: 2020, label: "合計", unit: "頭", docTitle: "文書A", publisher: "県", url: "https://example.test/a.pdf", license: "CC-BY" });
  });

  it("D1=A: 同じ年に別の値のセルがある年は系列から除く（値が同じ重複は1点）", async () => {
    const list = await docSeriesList(fx.db);
    const split = list.find((m) => m.rowKey === DOCFX.split.row)!;
    expect(split).toMatchObject({ nYears: 3, yFrom: 2020, yTo: 2023 });
    const pts = await docSeriesPoints(fx.db, split.docId, split.tableId, split.rowKey);
    expect(pts.map((p) => p.fiscalYear)).toEqual([2020, 2021, 2023]); // 2022（5 と 6）は無い
    expect(pts.map((p) => p.value)).toEqual([1, 2, 3]); // 平均 5.5 のような「どの観測値でもない数」は出ない

    const dup = list.find((m) => m.rowKey === DOCFX.dup.row)!;
    expect(dup.nYears).toBe(3);
    const dpts = await docSeriesPoints(fx.db, dup.docId, dup.tableId, dup.rowKey);
    expect(dpts.find((p) => p.fiscalYear === 2021)?.value).toBe(5);
  });

  it("n_warnings: 文書全体の注記（table_ids が []・NULL・空）＋その表を名指しする注記。blocks_timeseries=0 と別文書は数えない", async () => {
    const list = await docSeriesList(fx.db);
    const by = (t: string, d: string = DOCFX.docA) => list.find((m) => m.docId === d && m.tableId === t)!;
    expect(by("p1_t1").nWarnings).toBe(4); // n1,n2,n3（全体）＋n5（p1_t1 を含む）
    expect(by("p2_t1").nWarnings).toBe(5); // 上の3＋n4＋n5（n6 は止めない注記）
    expect(by("p9_t1", DOCFX.docB).nWarnings).toBe(1); // n7（別文書の全体注記は混ざらない）
  });

  it("page_no/unit が割れても決定的: 点は MIN(page_no)・MAX(unit)、meta は点の MAX(page_no)", async () => {
    const m = (await docSeriesList(fx.db)).find((x) => x.rowKey === DOCFX.paged.row)!;
    const pts = await docSeriesPoints(fx.db, m.docId, m.tableId, m.rowKey);
    expect(pts[0]).toMatchObject({ fiscalYear: 2018, value: 3, pageNo: 5, unit: "b" });
    expect(m.pageNo).toBe(6);
    expect(m.unit).toBe("b");
  });
});

describe("docSeriesPoints", () => {
  it("fiscal_year 昇順。未知の系列は空", async () => {
    const pts = await docSeriesPoints(fx.db, DOCFX.t2.doc, DOCFX.t2.table, DOCFX.t2.row);
    expect(pts.map((p) => p.fiscalYear)).toEqual([2018, 2019, 2020, 2021]);
    expect(await docSeriesPoints(fx.db, "nope", "t", "r")).toEqual([]);
  });
});

/**
 * EXPLAIN の固定（§3.1）。部分索引 `ix_cells_series` の述語は問い合わせの WHERE と一字一句同じでなければ
 * 使われず、全走査（rows_read が 119,533 に戻る）になる。関数が本当に投げた SQL を捕まえて確かめる。
 */
describe("EXPLAIN QUERY PLAN の固定（cells の部分索引）", () => {
  function capture(): { db: CubeDb; seen: { sql: string; params: readonly SqlParam[] }[] } {
    const seen: { sql: string; params: readonly SqlParam[] }[] = [];
    const db: CubeDb = {
      kind: "sqlite",
      async all(sql, params = []) {
        seen.push({ sql, params });
        return fx.db.all(sql, params);
      },
    };
    return { db, seen };
  }

  const cases: [string, (db: CubeDb) => Promise<unknown>][] = [
    ["docSeriesList", (db) => docSeriesList(db)],
    ["docSeriesPoints", (db) => docSeriesPoints(db, DOCFX.s1.doc, DOCFX.s1.table, DOCFX.s1.row)],
  ];
  for (const [name, fn] of cases) {
    it(`${name}: cells は ix_cells_series を使い、全走査しない`, async () => {
      const { db, seen } = capture();
      await fn(db);
      expect(seen).toHaveLength(1);
      const plan = (
        fx.raw.prepare(`EXPLAIN QUERY PLAN ${seen[0].sql}`).all(...(seen[0].params as unknown[])) as { detail: string }[]
      ).map((r) => r.detail);
      const cellsPlan = plan.filter((d) => /\bcells\b/.test(d));
      expect(cellsPlan.some((d) => /USING (COVERING )?INDEX ix_cells_series/.test(d))).toBe(true);
      expect(cellsPlan.some((d) => /^SCAN cells\b(?! USING)/.test(d))).toBe(false);
    });
  }

  it("問い合わせの WHERE は DOC_SERIES_WHERE をそのまま含む（部分索引の述語との一致）", async () => {
    const { db, seen } = capture();
    await docSeriesList(db);
    expect(seen[0].sql).toContain(DOC_SERIES_WHERE);
  });

  it("INDEXED BY を付けない（cells.sqlite の原本には部分索引が無い。付けると serving-diff が実行時エラー）", async () => {
    const { db, seen } = capture();
    await docSeriesList(db);
    expect(seen[0].sql).not.toMatch(/INDEXED BY/);
  });
});
