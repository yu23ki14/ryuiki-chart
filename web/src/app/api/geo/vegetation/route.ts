import { NextRequest, NextResponse } from "next/server";
import { vegetationShapes } from "@/lib/queries";

export const runtime = "nodejs";

/**
 * 現存植生図2024（神奈川県相当範囲）の GeoJSON。
 * 全件は重いので既定 1,500 件で打ち切る。凡例で絞るのが本来の使い方。
 *   /api/geo/vegetation?legend=<凡例コード>&limit=3000
 */
export async function GET(req: NextRequest) {
  const sp = req.nextUrl.searchParams;
  const rows = await vegetationShapes(
    sp.get("legend") || undefined,
    Math.min(Number(sp.get("limit") ?? 1500), 5000),
  );
  const features = rows.flatMap((r) => {
    if (!r.geometry_geojson) return [];
    let geometry: unknown;
    try {
      geometry = JSON.parse(r.geometry_geojson);
    } catch {
      return [];
    }
    return [
      {
        type: "Feature",
        geometry,
        properties: {
          feature_id: r.feature_id,
          legend_code: r.legend_code,
          legend_name_ja: r.legend_name_ja,
          naturalness: r.naturalness,
          area_m2: r.area_m2,
        },
      },
    ];
  });
  return NextResponse.json(
    { type: "FeatureCollection", features },
    { headers: { "Cache-Control": "public, max-age=300" } },
  );
}
