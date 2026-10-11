"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { REGION_OPTIONS as OPTIONS, type RegionFilter } from "@/lib/region";
import { regionFromSearch, searchWithRegion } from "@/components/region-url";


/** 全体／神奈川県／奄美大島の切り替え。現在の URL の `region` だけを差し替える（他のクエリは保つ。'all' は消す）。 */
export function RegionSwitcher() {
  const router = useRouter();
  const pathname = usePathname();
  const sp = useSearchParams();
  const current = regionFromSearch(sp);

  const choose = (id: RegionFilter) => {
    if (id === current) return;
    const qs = searchWithRegion(sp.toString(), id);
    router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
  };

  return (
    <div role="group" aria-label="地域" className="flex items-center rounded border border-line overflow-hidden text-[11.5px]">
      {OPTIONS.map((o) => (
        <button
          key={o.id}
          type="button"
          aria-pressed={o.id === current}
          onClick={() => choose(o.id)}
          className={`px-2 py-1 whitespace-nowrap ${
            o.id === current ? "bg-water text-white font-medium" : "text-ink-2 hover:bg-surface-2"
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
