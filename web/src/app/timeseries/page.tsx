import { Suspense } from "react";
import { listWaterBodies, variableCatalog } from "@/lib/queries";
import { TimeseriesExplorer } from "@/components/timeseries/TimeseriesExplorer";

export const dynamic = "force-dynamic";
export const metadata = { title: "時系列比較" };

export default async function Page() {
  const [waters, vars] = await Promise.all([listWaterBodies(), variableCatalog()]);
  // TimeseriesExplorer は useSearchParams（ディープリンクの初期値読み込み）を使うクライアント
  // コンポーネントなので、Suspense 境界が要る（無いとビルド時に警告/失敗する）。
  return (
    <Suspense>
      <TimeseriesExplorer waters={waters} vars={vars} />
    </Suspense>
  );
}
