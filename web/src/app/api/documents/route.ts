import { NextRequest, NextResponse } from "next/server";
import { d1CubeDb, docSeriesList, docSeriesPoints } from "@/lib/cube";
import { docNotes, documentsList, blockingNotes } from "@/lib/records";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  const sp = req.nextUrl.searchParams;
  const kind = sp.get("kind") ?? "list";
  try {
    if (kind === "list") {
      const cdb = await d1CubeDb();
      const [seriesRows, docs, warnings] = await Promise.all([
        docSeriesList(cdb, { minYears: 3 }),
        documentsList(cdb),
        blockingNotes(cdb),
      ]);
      // 応答の形は従来のまま（snake_case）。label は lib/cube が付ける（UI は再計算しない）。
      const series = seriesRows.map((r) => ({
        doc_id: r.docId,
        table_id: r.tableId,
        row_key: r.rowKey,
        label: r.label,
        page_no: r.pageNo,
        n_years: r.nYears,
        y_from: r.yFrom,
        y_to: r.yTo,
        unit: r.unit,
        doc_title: r.docTitle,
        publisher: r.publisher,
        url: r.url,
        license: r.license,
        n_warnings: r.nWarnings,
      }));
      return NextResponse.json({ series, docs, warnings });
    }
    if (kind === "series") {
      const doc = sp.get("doc") ?? "";
      const table = sp.get("table") ?? "";
      const row = sp.get("row") ?? "";
      const cdb = await d1CubeDb();
      const [pointRows, notes] = await Promise.all([docSeriesPoints(cdb, doc, table, row), docNotes(cdb, doc)]);
      const points = pointRows.map((p) => ({ fiscal_year: p.fiscalYear, value: p.value, unit: p.unit, page_no: p.pageNo }));
      return NextResponse.json({ points, notes });
    }
    return NextResponse.json({ error: "不明な kind" }, { status: 400 });
  } catch (e) {
    return NextResponse.json({ error: e instanceof Error ? e.message : String(e) }, { status: 500 });
  }
}
