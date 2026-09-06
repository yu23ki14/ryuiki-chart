import { NextResponse } from "next/server";
import {
  qualityMonthly,
  qualityByActor,
  qualityTotals,
  observerStats,
  instrumentList,
  pairedMeasurements,
  interventions,
  decisions,
  protocolList,
} from "@/lib/queries";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const [monthly, byActor, totals, observers, instruments, pairs, iv, dec, protocols] =
      await Promise.all([
        qualityMonthly(),
        qualityByActor(),
        qualityTotals(),
        observerStats(),
        instrumentList(),
        pairedMeasurements(),
        interventions(),
        decisions(),
        protocolList(),
      ]);
    return NextResponse.json({
      monthly,
      byActor,
      totals,
      observers,
      instruments,
      pairs,
      interventions: iv,
      decisions: dec,
      protocols,
    });
  } catch (e) {
    return NextResponse.json({ error: e instanceof Error ? e.message : String(e) }, { status: 500 });
  }
}
