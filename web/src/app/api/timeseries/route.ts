import { NextRequest, NextResponse } from "next/server";
import {
  d1CubeDb,
  representativeSeries,
  withTheme,
  yearSeries,
  monthSeries,
  daySeries,
  summarize,
  rainMonthlyClim,
  sitesInWaterBody,
  waterBodies,
  unitLabel,
  type Scope,
  type CellSpec,
} from "@/lib/cube";
import { facetsForSeries, caveatKeysForFacets } from "@/lib/cube/caveats";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** measurements データセット固定（PR-2 のスコープは測定値系。design §1.1 と同じ前提）。 */
const DATASET = "measurements";

type Basis = "day" | "fiscal_year" | "year";

/**
 * `representativeSeries()` を `basis`（元データの粒度）で絞り込む。`lib/cube/observation.ts`
 * の非公開ヘルパ `seriesForBasis` と同じロジック（`yearSeries` 等が内部で使っているのと
 * 同じ組み立て）。`web/src/lib/ai/tools.ts` にも同じ複製がある——`lib/cube` にこの
 * 分解だけを返す公開関数が無かった（報告参照）。
 */
function seriesForBasis(variableId: string, stat: string | undefined, basis: Basis) {
  return representativeSeries(variableId, DATASET, stat ?? "representative").filter((s) => s.valueGrain === basis);
}

/** `basis` から `queryCells`/`summarize` に渡す `inputGrain`（day 基準だけ検体値からの積み上げに絞る）。 */
function inputGrainForBasis(basis: Basis): "day" | "same" {
  return basis === "day" ? "day" : "same";
}

/** ゾーン・季節図の grain（`basis='day'` は year セルへ積み上げたもの、それ以外は basis そのもの）。 */
function cellGrainForBasis(basis: Basis): "year" | "fiscal_year" {
  return basis === "fiscal_year" ? "fiscal_year" : "year";
}

export async function GET(req: NextRequest) {
  const sp = req.nextUrl.searchParams;
  const mode = sp.get("mode") ?? "water";
  const variableId = sp.get("variable") ?? "";
  const stat = sp.get("stat") ?? undefined;
  const basis = ((sp.get("basis") as Basis | null) ?? "day") as Basis;

  try {
    if (!variableId) return NextResponse.json({ error: "variable（variable_id）は必須です" }, { status: 400 });
    const db = await d1CubeDb();

    if (mode === "waters") {
      const series = representativeSeries(variableId, DATASET, stat ?? "representative");
      const waters = await waterBodies(db, { series });
      return NextResponse.json({ waters });
    }

    if (mode === "water" || mode === "site") {
      const scope: Scope = mode === "water" ? { kind: "water", municipality: sp.get("water") ?? "" } : { kind: "site", siteId: sp.get("site") ?? "" };
      const series = seriesForBasis(variableId, stat, basis);
      const unit = unitLabel(series[0]?.unitId ?? null);
      const caveats = series.length ? caveatKeysForFacets(facetsForSeries(series.map((s) => withTheme(s)), scope)) : [];
      const sites = mode === "water" ? await sitesInWaterBody(db, sp.get("water") ?? "", { dataset: DATASET }) : undefined;

      if (series.length === 0) {
        return NextResponse.json({ sites, points: [], unit, grain: sp.get("grain") ?? basis, basis, stat: stat ?? "representative", caveats });
      }

      const grain = sp.get("grain") ?? (basis === "day" ? "year" : basis);
      if (grain === "month" || grain === "day") {
        if (basis !== "day") {
          return NextResponse.json({ sites, points: [], unit, grain, basis, stat: stat ?? "representative", caveats });
        }
        const period = { from: sp.get("from") ?? undefined, to: sp.get("to") ?? undefined };
        const { rows: points } = grain === "month"
          ? await monthSeries(db, { variableId, stat, scope, imputation: "lod" })
          : await daySeries(db, { variableId, stat, scope, period, imputation: "lod" });
        return NextResponse.json({ sites, points, unit, grain, basis, stat: stat ?? "representative", caveats });
      }

      const { rows: points } = await yearSeries(db, { variableId, stat, basis, scope, imputation: "lod" });
      return NextResponse.json({ sites, points, unit, grain: basis === "day" ? "year" : basis, basis, stat: stat ?? "representative", caveats });
    }

    if (mode === "zone") {
      const series = seriesForBasis(variableId, stat, basis);
      const unit = unitLabel(series[0]?.unitId ?? null);
      const cellGrain = cellGrainForBasis(basis);
      if (series.length === 0) {
        return NextResponse.json({ points: [], unit, grain: cellGrain, basis, stat: stat ?? "representative", caveats: [] });
      }
      const scope: Scope = { kind: "all_sites" };
      const spec: CellSpec = { series, scope, grain: cellGrain, inputGrain: inputGrainForBasis(basis), imputation: "lod" };
      const { rows: points } = await summarize(db, spec, "zone");
      const caveats = caveatKeysForFacets(facetsForSeries(series.map((s) => withTheme(s)), scope));
      return NextResponse.json({ points, unit, grain: cellGrain, basis, stat: stat ?? "representative", caveats });
    }

    if (mode === "season") {
      // 季節性（月別）は検体値（basis='day'）だけが意味を持つ（v1 meas_clim/zone_clim と同じ前提）。
      const series = representativeSeries(variableId, DATASET, stat ?? "representative").filter((s) => s.valueGrain === "day");
      const unit = unitLabel(series[0]?.unitId ?? null);
      const scope: Scope = { kind: "all_sites" };
      const [overall, byZone, rain] = await Promise.all([
        series.length
          ? summarize(db, { series, scope, grain: "day", imputation: "lod" }, "month_of_year")
          : Promise.resolve({ rows: [], truncated: false }),
        series.length
          ? summarize(db, { series, scope, grain: "month", imputation: "lod" }, "zone_month_of_year")
          : Promise.resolve({ rows: [], truncated: false }),
        rainMonthlyClim(db),
      ]);
      return NextResponse.json({ overall: overall.rows, byZone: byZone.rows, rain: rain.rows, unit });
    }

    return NextResponse.json({ error: "不明な mode" }, { status: 400 });
  } catch (e) {
    return NextResponse.json({ error: e instanceof Error ? e.message : String(e) }, { status: 500 });
  }
}
