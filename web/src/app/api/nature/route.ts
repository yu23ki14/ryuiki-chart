import { NextRequest, NextResponse } from "next/server";
import {
  protectedAreas,
  protectedAreaSummary,
  wildlifeSightings,
  wildlifeSightingSummary,
  mammalMesh,
  mammalMeshIndex,
  vegetationSummary,
  vegetationNaturalness,
  riverSegmentSummary,
} from "@/lib/queries";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * Tier 1 で足したデータ（保護区台帳・獣の出没記録・哺乳類メッシュ・植生・流路）の集約エンドポイント。
 * 形状（GeoJSON）が要るものは /api/geo/* 側にある。
 *
 *   /api/nature?kind=protected&category=city_park
 *   /api/nature?kind=wildlife&fiscal_year=2025
 *   /api/nature?kind=mammal&species=tanuki&survey=dai6kai
 *   /api/nature?kind=vegetation
 */
export async function GET(req: NextRequest) {
  const sp = req.nextUrl.searchParams;
  const kind = sp.get("kind") ?? "protected";
  try {
    switch (kind) {
      case "protected": {
        const category = sp.get("category") || undefined;
        const [rows, summary] = await Promise.all([
          protectedAreas(category, Number(sp.get("limit") ?? 1000)),
          protectedAreaSummary(),
        ]);
        return NextResponse.json({ rows, summary });
      }
      case "wildlife": {
        const fy = sp.get("fiscal_year");
        const [rows, summary] = await Promise.all([
          wildlifeSightings(fy ? Number(fy) : undefined, Number(sp.get("limit") ?? 800)),
          wildlifeSightingSummary(),
        ]);
        return NextResponse.json({ rows, summary });
      }
      case "mammal": {
        const [rows, index] = await Promise.all([
          mammalMesh(sp.get("species") || undefined, sp.get("survey") || undefined),
          mammalMeshIndex(),
        ]);
        return NextResponse.json({ rows, index });
      }
      case "vegetation": {
        const [legends, naturalness] = await Promise.all([
          vegetationSummary(Number(sp.get("limit") ?? 60)),
          vegetationNaturalness(),
        ]);
        return NextResponse.json({ legends, naturalness });
      }
      case "rivers":
        return NextResponse.json({ summary: await riverSegmentSummary() });
      default:
        return NextResponse.json({ error: "不明な kind" }, { status: 400 });
    }
  } catch (e) {
    return NextResponse.json({ error: e instanceof Error ? e.message : String(e) }, { status: 500 });
  }
}
