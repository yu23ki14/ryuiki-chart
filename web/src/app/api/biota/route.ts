import { NextRequest, NextResponse } from "next/server";
import { IAS_SINCE_YEAR } from "@/lib/cube/sql";
import { freshnessFor, OCCURRENCE_SOURCE_IDS, REDLIST_SOURCE_IDS } from "@/lib/cube/source-meta";
import {
  d1CubeDb,
  taxonGroupYears,
  effortRowV1,
  effortYears,
  occurrenceTotals,
  speciesCatalog,
  speciesShareTrend,
  speciesYears,
  speciesMonths,
  speciesMeshYears,
  iasSpecies,
  redlistBundle,
} from "@/lib/cube";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  const sp = req.nextUrl.searchParams;
  const kind = sp.get("kind") ?? "effort";
  try {
    const db = await d1CubeDb();
    // 出典ごとの取得日・更新方式・経過日数（加算。registry の生成物から引き、D1 は引かない。ADR-0014/0020）。
    // レッドリスト（kind=redlist）は評価リストの出典（REDLIST_SOURCE_IDS）を載せる。
    const freshness = freshnessFor(OCCURRENCE_SOURCE_IDS);
    switch (kind) {
      case "effort": {
        const [groups, effort, totals] = await Promise.all([
          taxonGroupYears(db),
          effortYears(db),
          occurrenceTotals(db),
        ]);
        // 画面の形（snake_case）は v1 のまま。totals.mesh は日付のある記録が入るグリッド数（D3）。
        return NextResponse.json({
          freshness,
          groups: groups.map((g) => ({ year: g.year, taxon_group: g.taxonGroup, n: g.n, mesh_n: g.meshN })),
          effort: effort.map(effortRowV1),
          totals: {
            records: totals.records,
            species: totals.species,
            mesh: totals.grids,
            gbif: totals.gbif,
            inat: totals.inat,
          },
        });
      }
      case "trend": {
        const group = sp.get("group") ?? "鳥類";
        const a0 = Number(sp.get("a0") ?? 2018);
        const a1 = Number(sp.get("a1") ?? 2020);
        const b0 = Number(sp.get("b0") ?? 2022);
        const b1 = Number(sp.get("b1") ?? 2024);
        const rows = await speciesShareTrend(db, group, { from: a0, to: a1 }, { from: b0, to: b1 });
        return NextResponse.json({
          freshness,
          rows: rows.map((r) => ({
            binom: r.binom,
            label: r.label,
            n_a: r.nA,
            n_b: r.nB,
            total_a: r.totalA,
            total_b: r.totalB,
          })),
          a: [a0, a1],
          b: [b0, b1],
        });
      }
      case "species": {
        const binoms = (sp.get("binoms") ?? "").split(",").filter(Boolean);
        const [years, months] = await Promise.all([speciesYears(db, binoms), speciesMonths(db, binoms)]);
        return NextResponse.json({
          freshness,
          years: years.map((r) => ({ binom: r.binom, year: r.year, n: r.n, mesh_n: r.meshN })),
          months,
        });
      }
      case "mesh":
        return NextResponse.json({ rows: await speciesMeshYears(db, sp.get("binom") ?? ""), freshness });
      case "ias": {
        const rows = await iasSpecies(db);
        return NextResponse.json({
          freshness: freshnessFor([...OCCURRENCE_SOURCE_IDS, "moe_ias_list"]),
          since_year: IAS_SINCE_YEAR,
          rows: rows.map((r) => ({
            ias_category: r.iasCategory,
            binom: r.binom,
            name_ja: r.nameJa,
            taxon_group: r.taxonGroup,
            en_name: r.label,
            n: r.n,
            mesh_n: r.meshN,
            y_from: r.yFrom,
            y_to: r.yTo,
            n_since: r.nSince,
          })),
        });
      }
      case "redlist": {
        const y = Number(sp.get("year") ?? 2022);
        const group = sp.get("group") || undefined;
        const { flows, species, summary } = await redlistBundle(db, y, {
          group,
          direction: sp.get("direction") || undefined,
          limit: 400,
        });
        return NextResponse.json({
          freshness: freshnessFor(REDLIST_SOURCE_IDS),
          flows: flows.map((f) => ({ prev_label: f.prevLabel, cur_label: f.curLabel, direction: f.direction, n: f.n })),
          species: species.map((r) => ({
            vernacular_name_ja: r.vernacularNameJa,
            scientific_name: r.scientificName,
            family_ja: r.familyJa,
            taxon_group_ja: r.taxonGroupJa,
            prev_label: r.prevLabel,
            cur_label: r.curLabel,
            prev_rank: r.prevRank,
            cur_rank: r.curRank,
            direction: r.direction,
            national_category_ja: r.nationalCategoryJa,
          })),
          summary: summary.map((r) => ({
            list_year: r.listYear,
            list_name: r.listName,
            taxon_group_ja: r.taxonGroupJa,
            direction: r.direction,
            n: r.n,
          })),
        });
      }
      case "list": {
        const rows = await speciesCatalog(db, { group: sp.get("group") || null, limit: 300, withNames: true });
        return NextResponse.json({
          freshness,
          rows: rows.map((r) => ({
            binom: r.binom,
            taxon_group: r.taxonGroup,
            cls: r.class,
            family: r.family,
            en_name: r.label ?? r.binom,
            n: r.n,
            y_from: r.yFrom,
            y_to: r.yTo,
            n_years: r.nYears,
            mesh_n: r.nPlaces,
          })),
        });
      }
      default:
        return NextResponse.json({ error: "不明な kind" }, { status: 400 });
    }
  } catch (e) {
    return NextResponse.json({ error: e instanceof Error ? e.message : String(e) }, { status: 500 });
  }
}
