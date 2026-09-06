import { NextRequest, NextResponse } from "next/server";
import { docSeriesList, docSeriesPoints, docNotes, documentsList, blockingNotes } from "@/lib/queries";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  const sp = req.nextUrl.searchParams;
  const kind = sp.get("kind") ?? "list";
  try {
    if (kind === "list") {
      const [series, docs, warnings] = await Promise.all([
        docSeriesList(3),
        documentsList(),
        blockingNotes(),
      ]);
      return NextResponse.json({ series, docs, warnings });
    }
    if (kind === "series") {
      const doc = sp.get("doc") ?? "";
      const table = sp.get("table") ?? "";
      const row = sp.get("row") ?? "";
      const [points, notes] = await Promise.all([docSeriesPoints(doc, table, row), docNotes(doc)]);
      return NextResponse.json({ points, notes });
    }
    return NextResponse.json({ error: "不明な kind" }, { status: 400 });
  } catch (e) {
    return NextResponse.json({ error: e instanceof Error ? e.message : String(e) }, { status: 500 });
  }
}
