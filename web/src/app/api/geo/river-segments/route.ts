import { NextRequest, NextResponse } from "next/server";
import { d1CubeDb } from "@/lib/cube";
import { readRecordSet } from "@/lib/records";

export const runtime = "nodejs";

/**
 * 相模川水系の流路 GeoJSON（水系単位なので山梨県側の桂川上流部を含む）。
 *   /api/geo/river-segments?prefecture=山梨県
 */
export async function GET(req: NextRequest) {
  const prefecture = req.nextUrl.searchParams.get("prefecture") || undefined;
  const rows = await readRecordSet(await d1CubeDb(), "river_segments", {
    eq: prefecture ? [{ col: "prefecture_ja", value: prefecture }] : undefined,
    order: [{ col: "length_m", desc: true }],
    limit: null, // 水系全体（上限なし）
    withGeometry: true,
  });
  const features = rows.flatMap((r) => {
    if (!r.geometry_geojson) return [];
    let geometry: unknown;
    try {
      geometry = JSON.parse(String(r.geometry_geojson));
    } catch {
      return [];
    }
    return [
      {
        type: "Feature",
        geometry,
        properties: {
          feature_id: r.feature_id,
          name_ja: r.name_ja,
          section_type: r.section_type,
          prefecture_ja: r.prefecture_ja,
          length_m: r.length_m,
        },
      },
    ];
  });
  return NextResponse.json(
    { type: "FeatureCollection", features },
    { headers: { "Cache-Control": "public, max-age=300" } },
  );
}
