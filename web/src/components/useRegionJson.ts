"use client";

import { useJson } from "@/components/useJson";
import { useRegion } from "@/components/useRegion";
import { withRegion } from "@/components/region-url";

/**
 * `useJson` に画面の地域（URL の ?region=）を載せる。全体のときは URL を変えない（キャッシュキーも現状のまま）。
 * 自前の API（/api/biota・/api/timeseries・/api/geo/*）用。静的アセット（/geo/rivers.geojson 等）には使わない。
 */
export function useRegionJson<T>(url: string) {
  const region = useRegion();
  return useJson<T>(withRegion(url, region));
}
