import { NextResponse } from "next/server";
import { d1CubeDb, sites, MEASUREMENTS_DATASET as DATASET } from "@/lib/cube";

export const runtime = "nodejs";

export async function GET() {
  const db = await d1CubeDb();
  const rows = await sites(db, { dataset: DATASET });
  return NextResponse.json(
    {
      type: "FeatureCollection",
      features: rows
        .filter((s) => s.lat != null && s.lon != null)
        .map((s) => ({
          type: "Feature",
          geometry: { type: "Point", coordinates: [s.lon, s.lat] },
          properties: {
            site_id: s.siteId,
            name: s.name,
            zone: s.zone,
            elevation_m: s.elevationM,
            municipality: s.municipality,
            operator: s.operator,
            source_id: s.sourceId,
            source_ref: s.sourceRef,
            watershed: s.watershed,
            water_system_name: s.waterSystemName,
            n_meas: s.nMeas,
            n_var: s.nVariables,
            treatment: s.treatment,
          },
        })),
    },
    { headers: { "Cache-Control": "public, max-age=300" } },
  );
}
