import { NextRequest, NextResponse } from "next/server";
import { meshPolygon } from "@/lib/geo";
import { d1CubeDb, gridCatalog, meshByYear } from "@/lib/cube";

export const runtime = "nodejs";

/** 生物観察の 0.01度メッシュ集計を GeoJSON で返す */
export async function GET(req: NextRequest) {
  const yearRaw = req.nextUrl.searchParams.get("year");
  const year = yearRaw ? Number(yearRaw) : null;
  const db = await d1CubeDb();
  const rows = year
    ? (await meshByYear(db, year)).map((r) => ({
        mlat: r.mlat,
        mlon: r.mlon,
        n: r.n,
        species_n: r.speciesN,
        rl_n: r.rlN,
        rl_species_n: 0,
      }))
    : (await gridCatalog(db)).map((r) => ({
        mlat: r.mlat,
        mlon: r.mlon,
        n: r.n,
        species_n: r.speciesN,
        rl_n: r.rlN,
        rl_species_n: r.rlSpeciesN,
      }));
  return NextResponse.json(
    {
      type: "FeatureCollection",
      features: rows.map((r) => ({
        type: "Feature",
        geometry: { type: "Polygon", coordinates: meshPolygon(r.mlat, r.mlon) },
        properties: {
          n: r.n,
          species_n: r.species_n,
          rl_n: r.rl_n,
          rl_species_n: r.rl_species_n,
          lat: r.mlat / 100,
          lon: r.mlon / 100,
        },
      })),
    },
    { headers: { "Cache-Control": "public, max-age=300" } },
  );
}
