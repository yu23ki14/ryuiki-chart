import { NextRequest, NextResponse } from "next/server";
import { d1CubeDb } from "@/lib/cube";
import { A45_BBOX_MARGIN, bboxRange, POLYGON_MAX, POLYGON_SOURCE_IDS, OVERLAY_CACHE, overlaySources, parseBbox, polygonFeature } from "@/lib/geo-overlay";
import { readRecordSet } from "@/lib/records";

export const runtime = "nodejs";

/** bbox が必須の出典（小班が 940 件・約 1.8MB）。A10（61 件）・A15（20 件）は全件が小さいので bbox 不要。 */
const BBOX_REQUIRED = new Set<string>(["nlni_a45_forest_amami"]);

interface Row {
  area_id: string;
  name_ja: string | null;
  category_ja: string | null;
  category_code: string | null;
  municipality_ja: string | null;
  area_ha: number | null;
  geometry_geojson: string | null;
}

/**
 * 保護区のポリゴン。source_id は奄美の 3 つに固定（必須）。A45 だけ bbox 必須。
 *   /api/geo/protected-areas/polygons?source_id=nlni_a10_natparks_amami
 *   /api/geo/protected-areas/polygons?source_id=nlni_a45_forest_amami&bbox=w,s,e,n
 * 点を返す既存の /api/geo/protected-areas とは別（そちらの契約は変えない）。
 */
export async function GET(req: NextRequest) {
  const sp = req.nextUrl.searchParams;
  const sourceId = sp.get("source_id") ?? "";
  if (!(POLYGON_SOURCE_IDS as readonly string[]).includes(sourceId)) {
    return NextResponse.json({ error: `source_id は ${POLYGON_SOURCE_IDS.join(" / ")}` }, { status: 400 });
  }
  const rawBbox = sp.get("bbox");
  const bbox = parseBbox(rawBbox);
  if ((rawBbox || BBOX_REQUIRED.has(sourceId)) && !bbox) {
    return NextResponse.json({ error: "bbox=w,s,e,n（経度・緯度の数 4 つ）が必要" }, { status: 400 });
  }
  const rows = await readRecordSet<Row>(await d1CubeDb(), "protected_areas", {
    eq: [{ col: "source_id", value: sourceId }],
    range: bbox && BBOX_REQUIRED.has(sourceId) ? bboxRange(bbox, "lat", "lon", A45_BBOX_MARGIN) : undefined,
    order: [{ col: "area_id" }],
    limit: POLYGON_MAX + 1,
    maxLimit: POLYGON_MAX + 1,
    withGeometry: true,
  });
  const truncated = rows.length > POLYGON_MAX;
  const features = rows.slice(0, POLYGON_MAX).flatMap((r) =>
    polygonFeature(r.geometry_geojson, {
      area_id: r.area_id,
      name_ja: r.name_ja,
      category_code: r.category_code,
      category_ja: r.category_ja,
      municipality_ja: r.municipality_ja,
      area_ha: r.area_ha,
      source_id: sourceId,
    }),
  );
  return NextResponse.json(
    { type: "FeatureCollection", features, truncated, sources: overlaySources([sourceId]) },
    { headers: OVERLAY_CACHE },
  );
}
