import { NextRequest, NextResponse } from "next/server";
import { runUserSql, SqlError } from "@/lib/db";
import { rowsToCsv } from "@/lib/table-query";
import { EXPLORE_ENABLED, EXPLORE_DISABLED_MESSAGE } from "@/lib/features";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 120;

export async function POST(req: NextRequest) {
  if (!EXPLORE_ENABLED) {
    return NextResponse.json({ error: EXPLORE_DISABLED_MESSAGE }, { status: 503 });
  }
  let body: { sql?: string; limit?: number; format?: string };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "JSON ボディが必要です" }, { status: 400 });
  }
  try {
    const res = await runUserSql(body.sql ?? "", body.limit ?? 1000);
    if (body.format === "csv") {
      return new NextResponse("﻿" + rowsToCsv(res.columns, res.rows), {
        headers: {
          "Content-Type": "text/csv; charset=utf-8",
          "Content-Disposition": 'attachment; filename="query.csv"',
        },
      });
    }
    return NextResponse.json(res);
  } catch (e) {
    const msg = e instanceof SqlError ? e.message : e instanceof Error ? e.message : String(e);
    return NextResponse.json({ error: msg }, { status: 400 });
  }
}
