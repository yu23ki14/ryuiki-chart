import { NextResponse } from "next/server";
import { loadGeoJson } from "@/lib/geo";
import { d1CubeDb, watershedRollup } from "@/lib/cube";

export const runtime = "nodejs";

/** 国土数値情報 W12 の流域界ポリゴンに、集計値を載せて返す。 */
export async function GET() {
  try {
    const fc = await loadGeoJson("watersheds.geojson");
    const { watersheds } = await watershedRollup(await d1CubeDb());
    const rollup = new Map(watersheds.map((r) => [r.watershedId, r]));
    const features = fc.features.map((f) => {
      const id = String((f.properties as Record<string, unknown>).watershed_id ?? "");
      const r = rollup.get(id);
      const orgN = r?.orgN ?? 0;
      const orgRedlistN = r?.orgRedlistN ?? 0;
      const delta = (c?: { from: number | null; to: number | null }) =>
        c && c.from != null && c.to != null ? c.to - c.from : null;
      const builtDelta = delta(r?.built);
      const forestDelta = delta(r?.forest);
      const paddyDelta = delta(r?.paddy);
      return {
        type: "Feature" as const,
        geometry: f.geometry,
        properties: {
          watershed_id: id,
          water_system_name: r?.waterSystemName ?? null,
          main_rivers: (f.properties as Record<string, unknown>).main_river_names_ja ?? null,
          area_km2: r?.areaKm2 ?? null,
          site_n: r?.siteN ?? 0,
          org_n: orgN,
          org_redlist_n: orgRedlistN,
          org_density: r?.areaKm2 ? orgN / r.areaKm2 : 0,
          built_2016: r?.built?.to ?? null,
          built_delta: builtDelta,
          built_delta_pct:
            builtDelta != null && r?.built?.from ? (builtDelta / r.built.from) * 100 : null,
          forest_delta: forestDelta,
          paddy_delta: paddyDelta,
        },
      };
    });
    return NextResponse.json(
      { type: "FeatureCollection", features },
      { headers: { "Cache-Control": "public, max-age=300" } },
    );
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 });
  }
}
