import { NextRequest, NextResponse } from "next/server";
import { d1CubeDb } from "@/lib/cube";
import { bboxRange, HAZARD_BBOX_MARGIN, HAZARD_MAX, HAZARD_SOURCE_ID, OVERLAY_CACHE, overlaySources, parseBbox, polygonFeature } from "@/lib/geo-overlay";
import { readRecordSet } from "@/lib/records";

export const runtime = "nodejs";

const KINDS = ["warning", "special_warning"] as const;
const PHENOMENA = ["debris_flow", "steep_slope", "landslide"] as const;

interface HazardRow {
  zone_id: string;
  site_name_ja: string | null;
  phenomenon_code: string | null;
  phenomenon_ja: string | null;
  zone_kind_code: string | null;
  zone_kind_ja: string | null;
  municipality_ja: string | null;
  locality_ja: string | null;
  river_name_ja: string | null;
  designated_on: string | null;
  area_m2: number | null;
  geometry_geojson: string | null;
}

/**
 * 土砂災害警戒区域・特別警戒区域（奄美 5 市町村。BODIK）のポリゴン。bbox 必須（全件は返さない）。
 *   /api/geo/hazard-zones?bbox=w,s,e,n[&kind=warning|special_warning][&phenomenon=debris_flow|steep_slope|landslide]
 * 面積を足し合わせる用途ではない（警戒と特別警戒は重なる。note を参照）。
 */
export async function GET(req: NextRequest) {
  const sp = req.nextUrl.searchParams;
  const bbox = parseBbox(sp.get("bbox"));
  if (!bbox) return NextResponse.json({ error: "bbox=w,s,e,n（経度・緯度の数 4 つ）が必要" }, { status: 400 });
  const kind = sp.get("kind");
  const phenomenon = sp.get("phenomenon");
  if (kind && !(KINDS as readonly string[]).includes(kind)) {
    return NextResponse.json({ error: `kind は ${KINDS.join(" / ")}` }, { status: 400 });
  }
  if (phenomenon && !(PHENOMENA as readonly string[]).includes(phenomenon)) {
    return NextResponse.json({ error: `phenomenon は ${PHENOMENA.join(" / ")}` }, { status: 400 });
  }
  const eq = [
    { col: "source_id", value: HAZARD_SOURCE_ID },
    ...(kind ? [{ col: "zone_kind_code", value: kind }] : []),
    ...(phenomenon ? [{ col: "phenomenon_code", value: phenomenon }] : []),
  ];
  const rows = await readRecordSet<HazardRow>(await d1CubeDb(), "hazard_zones", {
    eq,
    range: bboxRange(bbox, "centroid_lat", "centroid_lon", HAZARD_BBOX_MARGIN),
    order: [{ col: "zone_id" }],
    limit: HAZARD_MAX + 1,
    maxLimit: HAZARD_MAX + 1,
    withGeometry: true,
  });
  const truncated = rows.length > HAZARD_MAX;
  const features = rows.slice(0, HAZARD_MAX).flatMap((r) =>
    polygonFeature(r.geometry_geojson, {
      zone_id: r.zone_id,
      site_name_ja: r.site_name_ja,
      phenomenon_code: r.phenomenon_code,
      phenomenon_ja: r.phenomenon_ja,
      zone_kind_code: r.zone_kind_code,
      zone_kind_ja: r.zone_kind_ja,
      municipality_ja: r.municipality_ja,
      locality_ja: r.locality_ja,
      river_name_ja: r.river_name_ja,
      designated_on: r.designated_on,
      area_m2: r.area_m2,
    }),
  );
  return NextResponse.json(
    { type: "FeatureCollection", features, truncated, sources: overlaySources([HAZARD_SOURCE_ID]) },
    { headers: OVERLAY_CACHE },
  );
}
