import { NextRequest, NextResponse } from "next/server";
import { columnStats } from "@/lib/table-query";
import { EXPLORE_ENABLED, EXPLORE_DISABLED_MESSAGE } from "@/lib/features";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  // 任意の表の列の頻度集計（全表スキャン）。探索を閉じている間はここも閉じる（api/table と同じ）。
  if (!EXPLORE_ENABLED) {
    return NextResponse.json({ error: EXPLORE_DISABLED_MESSAGE }, { status: 404 });
  }
  const sp = req.nextUrl.searchParams;
  const table = sp.get("table") ?? "";
  const column = sp.get("column") ?? "";
  if (!table || !column) return NextResponse.json({ error: "table と column は必須です" }, { status: 400 });
  try {
    return NextResponse.json(await columnStats(table, column, Number(sp.get("topN") ?? 30)));
  } catch (e) {
    return NextResponse.json({ error: e instanceof Error ? e.message : String(e) }, { status: 400 });
  }
}
