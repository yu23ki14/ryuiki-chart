import { NextResponse } from "next/server";
import { interventions, decisions } from "@/lib/queries";

export const runtime = "nodejs";

/** 介入記録と意思決定記録（いずれも合成データ）を地図・年表用に返す */
export async function GET() {
  const [iv, dec] = await Promise.all([interventions(), decisions()]);
  return NextResponse.json({ interventions: iv, decisions: dec });
}
