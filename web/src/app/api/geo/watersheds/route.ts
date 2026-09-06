import { NextResponse } from "next/server";
import { loadGeoJson } from "@/lib/geo";
import { watershedRollup } from "@/lib/queries";

export const runtime = "nodejs";

/** 国土数値情報 W12 の流域界ポリゴンに、集計値を載せて返す。 */
export async function GET() {
  try {
    const fc = await loadGeoJson("watersheds.geojson");
    const rollup = new Map((await watershedRollup()).map((r) => [r.watershed_id, r]));
    const features = fc.features.map((f) => {
      const id = String((f.properties as Record<string, unknown>).watershed_id ?? "");
      const r = rollup.get(id);
      const builtDelta =
        r?.built_km2_2016 != null && r?.built_km2_2006 != null ? r.built_km2_2016 - r.built_km2_2006 : null;
      const forestDelta =
        r?.forest_km2_2016 != null && r?.forest_km2_2006 != null ? r.forest_km2_2016 - r.forest_km2_2006 : null;
      const paddyDelta =
        r?.paddy_km2_2016 != null && r?.paddy_km2_2006 != null ? r.paddy_km2_2016 - r.paddy_km2_2006 : null;
      return {
        type: "Feature" as const,
        geometry: f.geometry,
        properties: {
          watershed_id: id,
          water_system_name: r?.water_system_name ?? null,
          main_rivers: (f.properties as Record<string, unknown>).main_river_names_ja ?? null,
          area_km2: r?.area_km2 ?? null,
          site_n: r?.site_n ?? 0,
          org_n: r?.org_n ?? 0,
          org_redlist_n: r?.org_redlist_n ?? 0,
          org_density: r?.area_km2 ? (r.org_n ?? 0) / r.area_km2 : 0,
          built_2016: r?.built_km2_2016 ?? null,
          built_delta: builtDelta,
          built_delta_pct:
            builtDelta != null && r?.built_km2_2006 ? (builtDelta / r.built_km2_2006) * 100 : null,
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
