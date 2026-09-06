import { NextResponse } from "next/server";
import { listTables, isSeeded } from "@/lib/db";
import { EXPLORE_ENABLED, EXPLORE_DISABLED_MESSAGE } from "@/lib/features";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET() {
  // データ探索のカタログ。61 テーブルへ count(*) を投げるので 1 回で 419 万行読む。
  // 画面からは呼んでいない（AI の list_catalog は listTables() を直に呼ぶ）ので、
  // 探索を閉じている間はここも閉じる。
  if (!EXPLORE_ENABLED) {
    return NextResponse.json({ error: EXPLORE_DISABLED_MESSAGE }, { status: 503 });
  }
  try {
    const [tables, seeded] = await Promise.all([listTables(), isSeeded()]);
    return NextResponse.json({ tables, seeded });
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 });
  }
}
