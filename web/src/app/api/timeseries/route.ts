import { NextRequest, NextResponse } from "next/server";
import {
  sitesInWaterBody,
  yearSeries,
  monthSeries,
  daySeries,
  zoneSeries,
  zoneClimatology,
  climatology,
  rainDaily,
  rainMonthlyClim,
  rainTopDays,
  variableCatalog,
  waterBodiesForVariable,
} from "@/lib/queries";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  const sp = req.nextUrl.searchParams;
  const mode = sp.get("mode") ?? "water";
  const variable = sp.get("variable") ?? "";
  const grain = (sp.get("grain") ?? "year") as "year" | "month" | "day";

  try {
    if (!variable) return NextResponse.json({ error: "variable は必須です" }, { status: 400 });

    if (mode === "waters") {
      return NextResponse.json({ waters: await waterBodiesForVariable(variable) });
    }

    const cat = (await variableCatalog()).find((v) => v.variable === variable);
    const unit = cat?.unit ?? null;

    if (mode === "water") {
      const water = sp.get("water") ?? "";
      const sites = await sitesInWaterBody(water);
      const ids = sites.map((s) => s.site_id);
      const kind = (sp.get("kind") ?? "daily") as "daily" | "annual";
      const points =
        grain === "year"
          ? await yearSeries(variable, ids, kind)
          : grain === "month"
            ? await monthSeries(variable, ids)
            : await daySeries(variable, ids, sp.get("from") ?? undefined, sp.get("to") ?? undefined);
      return NextResponse.json({ sites, points, unit, grain, kind });
    }

    if (mode === "site") {
      const siteId = sp.get("site") ?? "";
      const kind = (sp.get("kind") ?? "daily") as "daily" | "annual";
      const [year, month, day] = await Promise.all([
        yearSeries(variable, [siteId], kind),
        monthSeries(variable, [siteId]),
        daySeries(variable, [siteId]),
      ]);
      return NextResponse.json({ year, month, day, unit });
    }

    if (mode === "zone") {
      const kind = (sp.get("kind") ?? "daily") as "daily" | "annual";
      return NextResponse.json({ points: await zoneSeries(variable, kind), unit, kind });
    }

    if (mode === "season") {
      const [overall, byZone, rain] = await Promise.all([
        climatology(variable),
        zoneClimatology(variable),
        rainMonthlyClim(),
      ]);
      return NextResponse.json({ overall, byZone, rain, unit });
    }

    if (mode === "rain") {
      const [rain, top] = await Promise.all([
        rainDaily(sp.get("from") ?? "2015-04-01", sp.get("to") ?? "2025-04-01"),
        rainTopDays(8),
      ]);
      return NextResponse.json({ rain, top });
    }

    return NextResponse.json({ error: "不明な mode" }, { status: 400 });
  } catch (e) {
    return NextResponse.json({ error: e instanceof Error ? e.message : String(e) }, { status: 500 });
  }
}
