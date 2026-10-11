import { Suspense } from "react";
import { MapPage } from "@/components/map/MapPage";

export const dynamic = "force-dynamic";
export const metadata = { title: "流域マップ" };

export default function Page() {
  // MapPage は useSearchParams（?region=）を使うクライアントコンポーネントなので Suspense 境界が要る。
  return (
    <Suspense>
      <MapPage />
    </Suspense>
  );
}
