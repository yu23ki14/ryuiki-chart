import { NextRequest, NextResponse } from "next/server";
import { meshPolygon } from "@/lib/geo";
import { meshAll, meshByYear } from "@/lib/queries";

export const runtime = "nodejs";

/** 生物観察の 0.01度メッシュ集計を GeoJSON で返す */
export async function GET(req: NextRequest) {
  const yearRaw = req.nextUrl.searchParams.get("year");
  const year = yearRaw ? Number(yearRaw) : null;
  const rows = year
    ? (await meshByYear(year)).map((r) => ({ ...r, rl_species_n: 0 }))
    : await meshAll();
  return NextResponse.json(
    {
      type: "FeatureCollection",
      features: rows.map((r) => ({
        type: "Feature",
        geometry: { type: "Polygon", coordinates: meshPolygon(r.mlat, r.mlon) },
        properties: {
          n: r.n,
          species_n: (r as { species_n?: number }).species_n ?? 0,
          rl_n: r.rl_n,
          rl_species_n: (r as { rl_species_n?: number }).rl_species_n ?? 0,
          lat: r.mlat / 100,
          lon: r.mlon / 100,
        },
      })),
    },
    { headers: { "Cache-Control": "public, max-age=300" } },
  );
}
