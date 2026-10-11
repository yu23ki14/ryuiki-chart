"use client";

import { useSearchParams } from "next/navigation";
import type { RegionFilter } from "@/lib/region";
import { regionFromSearch } from "@/components/region-url";

/** 今の画面の地域の絞り。URL の `?region=` が正（不正値は 'all'）。useSearchParams を使うので Suspense 境界の内側で呼ぶ。 */
export function useRegion(): RegionFilter {
  return regionFromSearch(useSearchParams());
}
