import { notFound } from "next/navigation";
import { d1CubeDb, site, siteVariables, unitLabel } from "@/lib/cube";
import { SiteDetail } from "@/components/sites/SiteDetail";

export const dynamic = "force-dynamic";

/** measurements データセット固定（PR-2 のスコープは測定値系。design §1.1 と同じ前提）。 */
const DATASET = "measurements";

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
  // `catalog.siteVariables()` は `site()`/`sites()`/`Scope{kind:'site'}` と同じ外部キーの
  // `site_id` を受ける（Issue #48 PR-2 統合後修正A #2。内部の `place_id` への解決は
  // `lib/cube` 側に集約した——旧 `resolvePlaceId()` の複製をここでは持たない）。
  const [s, variables] = await Promise.all([
    site(db, siteId, { dataset: DATASET }),
    siteVariables(db, siteId, { imputation: "lod", dataset: DATASET }),
  ]);
  if (!s) notFound();
  // `SiteSeriesRow` の unitId を表示記号へ解決してからクライアントへ渡す（SiteDetail.tsx は
  // "use client" なので、サーバ専用の大きい registry/generated.ts を経由する unitLabel を
  // クライアント側で呼ばないため）。
  const variablesForClient = variables.map((v) => ({
    variableId: v.series.variableId,
    obsStat: v.series.obsStat,
    grain: v.grain,
    inputGrain: v.inputGrain,
    n: v.n,
    yFrom: v.yFrom,
    yTo: v.yTo,
    avg: v.avg,
    unit: unitLabel(v.series.unitId),
  }));
  return <SiteDetail site={s} variables={variablesForClient} />;
}
