import { NextRequest, NextResponse } from "next/server";
import {
  d1CubeDb,
  representativeSeries,
  withTheme,
  yearCellFilterForBasis,
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
  MEASUREMENTS_DATASET as DATASET,
} from "@/lib/cube";
import { freshnessForSeries } from "@/lib/cube/source-meta";
import { facetsForSeries, caveatKeysForFacets } from "@/lib/cube/caveats";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type Basis = "day" | "fiscal_year" | "year";

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
      // series は basis で絞り込まない（basis はセルの性質。Issue #48 PR-2 統合後修正A #1）。
      // basis の絞り込みは `yearSeries`/`monthSeries`/`daySeries`（`lib/cube`）がセル側で行う。
      const series = representativeSeries(variableId, DATASET, stat ?? "representative");
      const unit = unitLabel(series[0]?.unitId ?? null);
      const caveats = series.length ? caveatKeysForFacets(facetsForSeries(series.map((s) => withTheme(s)), scope)) : [];
      // 出典ごとの取得日・更新方式・経過日数（加算。registry の生成物から引くので D1 は引かない。ADR-0014/0020）。
      const freshness = freshnessForSeries(series);
      const sites = mode === "water" ? await sitesInWaterBody(db, sp.get("water") ?? "", { dataset: DATASET }) : undefined;

      if (series.length === 0) {
        return NextResponse.json({ sites, points: [], unit, grain: sp.get("grain") ?? basis, basis, stat: stat ?? "representative", caveats, freshness });
      }

      const grain = sp.get("grain") ?? (basis === "day" ? "year" : basis);
      if (grain === "month" || grain === "day") {
        if (basis !== "day") {
          return NextResponse.json({ sites, points: [], unit, grain, basis, stat: stat ?? "representative", caveats, freshness });
        }
        const period = { from: sp.get("from") ?? undefined, to: sp.get("to") ?? undefined };
        const { rows: points } = grain === "month"
          ? await monthSeries(db, { variableId, stat, scope, imputation: "lod" })
          : await daySeries(db, { variableId, stat, scope, period, imputation: "lod" });
        return NextResponse.json({ sites, points, unit, grain, basis, stat: stat ?? "representative", caveats, freshness });
      }

      const { rows: points } = await yearSeries(db, { variableId, stat, basis, scope, imputation: "lod" });
      return NextResponse.json({ sites, points, unit, grain: basis === "day" ? "year" : basis, basis, stat: stat ?? "representative", caveats, freshness });
    }

    if (mode === "zone") {
      const series = representativeSeries(variableId, DATASET, stat ?? "representative");
      const unit = unitLabel(series[0]?.unitId ?? null);
      const { grain: cellGrain, inputGrain } = yearCellFilterForBasis(basis);
      if (series.length === 0) {
        return NextResponse.json({ points: [], unit, grain: cellGrain, basis, stat: stat ?? "representative", caveats: [], freshness: [] });
      }
      const scope: Scope = { kind: "all_sites" };
      const spec: CellSpec = { series, scope, grain: cellGrain, inputGrain, imputation: "lod" };
      const { rows: points } = await summarize(db, spec, "zone");
      const caveats = caveatKeysForFacets(facetsForSeries(series.map((s) => withTheme(s)), scope));
      return NextResponse.json({ points, unit, grain: cellGrain, basis, stat: stat ?? "representative", caveats, freshness: freshnessForSeries(series) });
    }

    if (mode === "season") {
      // 季節性（月別）は検体値（basis='day'）だけが意味を持つ（v1 meas_clim/zone_clim と同じ前提）。
      // series は value_grain で絞り込まない（day-registered 以外の系列は grain='day'/'month'
      // のセル自体を持たないため、grain 指定だけで自然に day-input セルに絞り込まれる）。
      const series = representativeSeries(variableId, DATASET, stat ?? "representative");
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
      return NextResponse.json({ overall: overall.rows, byZone: byZone.rows, rain: rain.rows, unit, freshness: freshnessForSeries(series) });
    }

    return NextResponse.json({ error: "不明な mode" }, { status: 400 });
  } catch (e) {
    return NextResponse.json({ error: e instanceof Error ? e.message : String(e) }, { status: 500 });
  }
}
