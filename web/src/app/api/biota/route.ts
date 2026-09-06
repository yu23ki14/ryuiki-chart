import { NextRequest, NextResponse } from "next/server";
import {
  taxonGroupYears,
  effortYears,
  speciesShareTrend,
  speciesYears,
  speciesMonths,
  speciesMeshYears,
  iasSpecies,
  redlistFlows,
  redlistSpecies,
  redlistSummary,
  speciesList,
  biotaTotals,
} from "@/lib/queries";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  const sp = req.nextUrl.searchParams;
  const kind = sp.get("kind") ?? "effort";
  try {
    switch (kind) {
      case "effort": {
        const [groups, effort, totals] = await Promise.all([
          taxonGroupYears(),
          effortYears(),
          biotaTotals(),
        ]);
        return NextResponse.json({ groups, effort, totals });
      }
      case "trend": {
        const group = sp.get("group") ?? "鳥類";
        const a0 = Number(sp.get("a0") ?? 2018);
        const a1 = Number(sp.get("a1") ?? 2020);
        const b0 = Number(sp.get("b0") ?? 2022);
        const b1 = Number(sp.get("b1") ?? 2024);
        return NextResponse.json({
          rows: await speciesShareTrend(group, a0, a1, b0, b1),
          a: [a0, a1],
          b: [b0, b1],
        });
      }
      case "species": {
        const binoms = (sp.get("binoms") ?? "").split(",").filter(Boolean);
        const [years, months] = await Promise.all([speciesYears(binoms), speciesMonths(binoms)]);
        return NextResponse.json({ years, months });
      }
      case "mesh":
        return NextResponse.json({ rows: await speciesMeshYears(sp.get("binom") ?? "") });
      case "ias":
        return NextResponse.json({ rows: await iasSpecies() });
      case "redlist": {
        const y = Number(sp.get("year") ?? 2022);
        const group = sp.get("group") || undefined;
        const [flows, species, summary] = await Promise.all([
          redlistFlows(y, group),
          redlistSpecies(y, sp.get("direction") || undefined, group, 400),
          redlistSummary(),
        ]);
        return NextResponse.json({ flows, species, summary });
      }
      case "list":
        return NextResponse.json({ rows: await speciesList(sp.get("group") || null, 300) });
      default:
        return NextResponse.json({ error: "不明な kind" }, { status: 400 });
    }
  } catch (e) {
    return NextResponse.json({ error: e instanceof Error ? e.message : String(e) }, { status: 500 });
  }
}
