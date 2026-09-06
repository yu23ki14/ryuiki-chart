import { NextRequest, NextResponse } from "next/server";
import { queryTable, rowsToCsv, type Filter } from "@/lib/table-query";
import { EXPLORE_ENABLED, EXPLORE_DISABLED_MESSAGE } from "@/lib/features";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

function parseParams(sp: URLSearchParams) {
  let filters: Filter[] = [];
  const raw = sp.get("filters");
  if (raw) {
    try {
      const p = JSON.parse(raw);
      if (Array.isArray(p)) filters = p as Filter[];
    } catch {
      /* 無視 */
    }
  }
  return {
    schema: sp.get("schema") ?? "main",
    table: sp.get("table") ?? "",
    limit: Number(sp.get("limit") ?? 100),
    offset: Number(sp.get("offset") ?? 0),
    orderBy: sp.get("orderBy") ?? undefined,
    dir: (sp.get("dir") as "asc" | "desc" | null) ?? undefined,
    q: sp.get("q") ?? undefined,
    filters,
  };
}

export async function GET(req: NextRequest) {
  // データ探索画面の裏側。画面を閉じている間はここも閉じる（任意のテーブルを引けるため）。
  if (!EXPLORE_ENABLED) {
    return NextResponse.json({ error: EXPLORE_DISABLED_MESSAGE }, { status: 503 });
  }
  const sp = req.nextUrl.searchParams;
  const opts = parseParams(sp);
  if (!opts.table) return NextResponse.json({ error: "table は必須です" }, { status: 400 });
  try {
    if (sp.get("format") === "csv") {
      const res = await queryTable({ ...opts, limit: Math.min(opts.limit || 5000, 5000), offset: 0 });
      const csv = rowsToCsv(res.columns.map((c) => c.name), res.rows);
      return new NextResponse("﻿" + csv, {
        headers: {
          "Content-Type": "text/csv; charset=utf-8",
          "Content-Disposition": `attachment; filename="${opts.table}.csv"`,
        },
      });
    }
    return NextResponse.json(await queryTable(opts));
  } catch (e) {
    return NextResponse.json({ error: e instanceof Error ? e.message : String(e) }, { status: 400 });
  }
}
