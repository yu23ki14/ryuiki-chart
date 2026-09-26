import { notFound } from "next/navigation";
import { d1CubeDb, site, siteVariables, unitLabel, type CubeDb } from "@/lib/cube";
import { SiteDetail } from "@/components/sites/SiteDetail";

export const dynamic = "force-dynamic";

/** measurements データセット固定（PR-2 のスコープは測定値系。design §1.1 と同じ前提）。 */
const DATASET = "measurements";

/**
 * `catalog.siteVariables()` の第2引数は（`site()`/`sites()`/`Scope{kind:'site'}` と違い）
 * 外部キーの `site_id` ではなく内部の `place_id` を取る（`catalog.test.ts` が `FX.places.a`
 * を渡していることで確認済み）。`lib/cube` はこの2つを結ぶ関数を公開していない
 * （報告参照）ので、ここで `place_source_ref` を直接引く。
 */
async function resolvePlaceId(db: CubeDb, siteId: string): Promise<string | null> {
  const rows = await db.all<{ place_id: string }>(
    "SELECT place_id FROM place_source_ref WHERE source_id = 'sites.site_id' AND external_key = ?",
    [siteId],
  );
  return rows[0]?.place_id ?? null;
}

export async function generateMetadata({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const db = await d1CubeDb();
  const s = await site(db, decodeURIComponent(id), { dataset: DATASET });
  return { title: s?.name ?? "地点カルテ" };
}

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const siteId = decodeURIComponent(id);
  const db = await d1CubeDb();
  const [s, placeId] = await Promise.all([site(db, siteId, { dataset: DATASET }), resolvePlaceId(db, siteId)]);
  const variables = placeId ? await siteVariables(db, placeId, { imputation: "lod", dataset: DATASET }) : [];
  if (!s) notFound();
  // `SiteSeriesRow` の unitId を表示記号へ解決してからクライアントへ渡す（SiteDetail.tsx は
  // "use client" なので、サーバ専用の大きい registry/generated.ts を経由する unitLabel を
  // クライアント側で呼ばないため）。
  const variablesForClient = variables.map((v) => ({
    variableId: v.series.variableId,
    obsStat: v.series.obsStat,
    valueGrain: v.series.valueGrain,
    grain: v.grain,
    n: v.n,
    yFrom: v.yFrom,
    yTo: v.yTo,
    avg: v.avg,
    unit: unitLabel(v.series.unitId),
  }));
  return <SiteDetail site={s} variables={variablesForClient} />;
}
