import { NextRequest, NextResponse } from "next/server";
import { protectedAreas } from "@/lib/queries";

export const runtime = "nodejs";

/**
 * 保護区・緑地・保存樹木のうち座標を持つものを点で返す。
 * 面積しか持たない区域（自然公園やPDF由来の指定状況）は原本に座標が無いので出てこない。
 *   /api/geo/protected-areas?category=city_park
 */
export async function GET(req: NextRequest) {
  const sp = req.nextUrl.searchParams;
  const rows = await protectedAreas(sp.get("category") || undefined, Number(sp.get("limit") ?? 2000));
  const features = rows
    .filter((r) => r.lat != null && r.lon != null)
    .map((r) => ({
      type: "Feature",
      geometry: { type: "Point", coordinates: [r.lon, r.lat] },
      properties: {
        area_id: r.area_id,
        name_ja: r.name_ja,
        category_ja: r.category_ja,
        category_code: r.category_code,
        municipality_ja: r.municipality_ja,
        area_ha: r.area_ha,
        designated_on: r.designated_on,
        watershed: r.watershed,
        zone: r.zone,
        source_id: r.source_id,
      },
    }));
  return NextResponse.json(
    { type: "FeatureCollection", features },
    { headers: { "Cache-Control": "public, max-age=300" } },
  );
}
