import { NextRequest, NextResponse } from "next/server";
import { d1CubeDb } from "@/lib/cube";
import { readRecordSet } from "@/lib/records";

interface ProtectedAreaRow {
  area_id: string;
  name_ja: string | null;
  category_ja: string | null;
  category_code: string | null;
  municipality_ja: string | null;
  area_ha: number | null;
  designated_on: string | null;
  lat: number | null;
  lon: number | null;
  watershed: string | null;
  zone: number | null;
  source_id: string | null;
}

export const runtime = "nodejs";

/**
 * 保護区・緑地・保存樹木のうち座標（点または代表点）を持つものを点で返す。神奈川と奄美の両方が混ざる
 * （区別は source_id。奄美の国土数値情報 A10/A15/A45 は区域の代表点）。区域のポリゴンはここでは返さない
 * （get_records の include_geometry）。座標を持たない行は出てこない。
 *   /api/geo/protected-areas?category=city_park
 */
export async function GET(req: NextRequest) {
  const sp = req.nextUrl.searchParams;
  const category = sp.get("category") || undefined;
  const rows = await readRecordSet<ProtectedAreaRow>(await d1CubeDb(), "protected_areas", {
    eq: category ? [{ col: "category_code", value: category }] : undefined,
    order: [{ col: "category_code" }, { col: "area_ha", desc: true }, { col: "name_ja" }],
    limit: Number(sp.get("limit")),
    defaultLimit: 5000,
    maxLimit: 5000,
  });
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
