import { NextResponse } from "next/server";
import { listSites } from "@/lib/queries";

export const runtime = "nodejs";

export async function GET() {
  const sites = await listSites();
  return NextResponse.json(
    {
      type: "FeatureCollection",
      features: sites.map((s) => ({
        type: "Feature",
        geometry: { type: "Point", coordinates: [s.lon, s.lat] },
        properties: {
          site_id: s.site_id,
          name: s.name,
          zone: s.zone,
          elevation_m: s.elevation_m,
          municipality: s.municipality,
          operator: s.operator,
          source_id: s.source_id,
          source_ref: s.source_ref,
          watershed: s.watershed,
          water_system_name: s.water_system_name,
          n_meas: s.n_meas,
          n_var: s.n_var,
          treatment: s.treatment,
        },
      })),
    },
    { headers: { "Cache-Control": "public, max-age=300" } },
  );
}
