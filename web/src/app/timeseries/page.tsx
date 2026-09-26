import { Suspense } from "react";
import { redirect } from "next/navigation";
import { d1CubeDb, waterBodies, variableCatalog, unitLabel } from "@/lib/cube";
import { resolveVariableInfo } from "@/lib/registry/lookup";
import { TimeseriesExplorer } from "@/components/timeseries/TimeseriesExplorer";

export const dynamic = "force-dynamic";
export const metadata = { title: "時系列比較" };

/** measurements データセット固定（PR-2 のスコープは測定値系。design §1.1 と同じ前提）。 */
const DATASET = "measurements";

type SearchParams = Record<string, string | string[] | undefined>;

/**
 * `variable` が variable_id（"common:variable:..."）でなければ出典表記（alias）として
 * 解決し、`redirect()` で正準の URL に書き換える（design §5）。`kind`（旧 daily/annual）が
 * 来ていたら `basis`/`grain` に書き換える。
 */
function redirectIfAlias(sp: SearchParams): void {
  const rawVariable = typeof sp.variable === "string" ? sp.variable : undefined;
  if (!rawVariable || rawVariable.startsWith("common:variable:")) return;

  const info = resolveVariableInfo(rawVariable, DATASET);
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(sp)) {
    if (typeof v !== "string" || k === "variable" || k === "kind") continue;
    params.set(k, v);
  }
  params.set("variable", info?.variableId ?? "common:variable:water.bod");

  const kind = typeof sp.kind === "string" ? sp.kind : undefined;
  if (kind === "annual") {
    params.set("basis", "fiscal_year");
    params.set("grain", "fiscal_year");
  } else if (kind === "daily" && !params.get("grain")) {
    params.set("basis", "day");
    params.set("grain", "year");
  }
  redirect(`/timeseries?${params.toString()}`);
}

export default async function Page({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const sp = await searchParams;
  redirectIfAlias(sp);

  const db = await d1CubeDb();
  const [watersRaw, varsRaw] = await Promise.all([
    waterBodies(db, { dataset: DATASET }),
    variableCatalog(db, { dataset: DATASET }),
  ]);
  const waters = watersRaw.map((w) => ({
    name: w.name,
    nSites: w.nSites,
    elevMin: w.elevMin,
    elevMax: w.elevMax,
    nMeas: w.nMeas,
    yFrom: w.yFrom,
    yTo: w.yTo,
  }));
  const vars = varsRaw.map((r) => ({
    variableId: r.variableId,
    unit: unitLabel(r.unitId),
    n: r.n,
    nPlaces: r.nPlaces,
    yFrom: r.yFrom,
    yTo: r.yTo,
    nByBasis: r.nByBasis,
    nCensored: r.nCensored,
    stats: r.stats,
  }));

  // TimeseriesExplorer は useSearchParams（ディープリンクの初期値読み込み）を使うクライアント
  // コンポーネントなので、Suspense 境界が要る（無いとビルド時に警告/失敗する）。
  return (
    <Suspense>
      <TimeseriesExplorer waters={waters} vars={vars} />
    </Suspense>
  );
}
