import { Suspense } from "react";
import { BiotaExplorer } from "@/components/biota/BiotaExplorer";

export const dynamic = "force-dynamic";
export const metadata = { title: "生物相" };

export default function Page() {
  // BiotaExplorer（と中の TrendTab）は useSearchParams を使うクライアントコンポーネントなので
  // Suspense 境界が要る。
  return (
    <Suspense>
      <BiotaExplorer />
    </Suspense>
  );
}
