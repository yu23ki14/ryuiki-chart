/**
 * 地域で絞る切り替え（Issue #93、`docs/plans/REGION_FILTER.md` §3-1）。
 * server-only を付けない（クライアントも使う）。
 *
 * - cube 層は `region?: RegionId`（undefined = 全体）を受ける。`'all'` は cube に入れない。
 *   入口（API・ページ・ツール）で `regionOf(parseRegion(...))` に直す。
 * - UI の語（神奈川県／奄美大島）はここだけに持つ。registry の `name_ja`（jp-46 は鹿児島県）は使わない。
 */
import { REGION_TIME } from "@/lib/registry/generated-client";

/** 具体的な地域（registry/region.yaml の region_id）。 */
export type RegionId = (typeof REGION_TIME)[number]["regionId"];
/** 画面・URL・ツール引数の「絞り」。'all' = 合算（既定）。 */
export type RegionFilter = "all" | RegionId;

export interface RegionUi {
  id: RegionId;
  /** 切り替えの表示名 */
  label: string;
  /** 地図の移動ボタン */
  jumpLabel: string;
  /** [[lon_min, lat_min], [lon_max, lat_max]] */
  bounds: [[number, number], [number, number]];
}

export const REGION_ALL = "all" as const;

/** scripts/regions.py の bbox と同じ値（`map/basemaps.ts` の KANAGAWA_BOUNDS/AMAMI_BOUNDS）。 */
export const REGIONS: readonly RegionUi[] = [
  {
    id: "jp-14",
    label: "神奈川県",
    jumpLabel: "神奈川県へ",
    bounds: [
      [138.9, 35.1],
      [139.83, 35.68],
    ],
  },
  {
    id: "jp-46",
    label: "奄美大島",
    jumpLabel: "奄美大島へ",
    bounds: [
      [129.1, 27.95],
      [129.85, 28.8],
    ],
  },
];

/** 'all'・既知の RegionId 以外（空・不正・配列）は 'all'。 */
export function parseRegion(raw: unknown): RegionFilter {
  if (typeof raw !== "string") return REGION_ALL;
  return REGIONS.some((r) => r.id === raw) ? (raw as RegionId) : REGION_ALL;
}

/** 'all' → undefined（cube 層へはこの形で渡す）。 */
export function regionOf(f: RegionFilter): RegionId | undefined {
  return f === REGION_ALL ? undefined : f;
}

export function regionLabel(f: RegionFilter): string {
  if (f === REGION_ALL) return "全体";
  return REGIONS.find((r) => r.id === f)?.label ?? "全体";
}
