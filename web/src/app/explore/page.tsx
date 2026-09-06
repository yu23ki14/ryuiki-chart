import Link from "next/link";
import { Suspense } from "react";
import { listTables } from "@/lib/db";
import { Explorer } from "@/components/explore/Explorer";
import { EXPLORE_ENABLED } from "@/lib/features";
import { PageContextSetter } from "@/components/assistant/PageContextProvider";

export const dynamic = "force-dynamic";
export const metadata = { title: "データ探索" };

export default async function ExplorePage() {
  if (!EXPLORE_ENABLED) return <Closed />;
  const tables = await listTables();
  // Explorer は useSearchParams（?sql= の受け口）を使うクライアントコンポーネントなので
  // Suspense 境界が要る。
  return (
    <Suspense>
      <Explorer tables={tables} />
    </Suspense>
  );
}

/** 閉じているときの画面。ナビからは消えているが、直リンクや古いブックマークで来る人がいる。 */
function Closed() {
  return (
    <div className="flex-1 overflow-y-auto thin-scroll">
      <PageContextSetter context={{ route: "/explore", title: "データ探索（停止中）" }} />
      <div className="max-w-[720px] mx-auto px-6 py-16">
        <p className="text-[11px] tracking-[0.16em] text-muted uppercase">Closed</p>
        <h1 className="text-[22px] font-bold leading-tight mt-1">データ探索は現在閉じています</h1>
        <p className="text-[13px] text-ink-2 mt-4 leading-relaxed">
          テーブルの中身をそのまま見る画面と、任意の SELECT を実行する画面を一時的に止めています。
          集計した結果は各画面から、データの出どころは「出典」から見られます。
        </p>
        <div className="flex flex-wrap gap-2 mt-6">
          <Link
            href="/"
            className="text-[12px] border border-line rounded px-3 py-1.5 text-ink-2 hover:bg-surface-2"
          >
            概況へ
          </Link>
          <Link
            href="/sources"
            className="text-[12px] border border-line rounded px-3 py-1.5 text-ink-2 hover:bg-surface-2"
          >
            出典へ
          </Link>
        </div>
      </div>
    </div>
  );
}
