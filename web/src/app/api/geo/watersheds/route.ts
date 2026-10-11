import { NextRequest, NextResponse } from "next/server";
import { parseRegion, regionOf } from "@/lib/region";
import { loadGeoJson } from "@/lib/geo";
import { d1CubeDb, landuseDelta, watershedRollup } from "@/lib/cube";

export const runtime = "nodejs";

/** 国土数値情報 W12 の流域界ポリゴンに、集計値を載せて返す。 */
export async function GET(req: NextRequest) {
  const region = regionOf(parseRegion(req.nextUrl.searchParams.get("region")));
  try {
    const fc = await loadGeoJson("watersheds.geojson");
    const { watersheds, landuseYears } = await watershedRollup(await d1CubeDb(), region);
    const rollup = new Map(watersheds.map((r) => [r.watershedId, r]));
    // 地域指定時は、その地域の流域（watershedRollup が返す集合）だけ返す。他地域を 0 で塗らない。
    const features = (region ? fc.features.filter((f) => rollup.has(String((f.properties as Record<string, unknown>).watershed_id ?? ""))) : fc.features).map((f) => {
      const id = String((f.properties as Record<string, unknown>).watershed_id ?? "");
      const r = rollup.get(id);
      const orgN = r?.orgN ?? 0;
      const orgRedlistN = r?.orgRedlistN ?? 0;
      const builtDelta = landuseDelta(r?.built);
      const forestDelta = landuseDelta(r?.forest);
      const paddyDelta = landuseDelta(r?.paddy);
      return {
        type: "Feature" as const,
        geometry: f.geometry,
        properties: {
          watershed_id: id,
          water_system_name: r?.waterSystemName ?? null,
          main_rivers: (f.properties as Record<string, unknown>).main_river_names_ja ?? null,
          // 計算した流域（奄美）だけが持つ。W12 は undefined → null
          unit_kind: (f.properties as Record<string, unknown>).unit_kind ?? null,
          merged_share: (f.properties as Record<string, unknown>).merged_share ?? null,
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
      { type: "FeatureCollection", features, landuse_years: landuseYears },
      { headers: { "Cache-Control": "public, max-age=300" } },
    );
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 });
  }
}
