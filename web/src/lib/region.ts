/**
 * 地域で絞る切り替え（Issue #93、`docs/plans/REGION_FILTER.md` §3-1）。
 * server-only を付けない（クライアントも使う）。
 *
 * - cube 層は `region?: RegionId`（undefined = 全体）を受ける。`'all'` は cube に入れない。
 *   入口（API・ページ・ツール）で `regionOf(parseRegion(...))` に直す。
 * - UI の語（神奈川県／奄美大島）はここだけに持つ。registry の `name_ja`（jp-46 は鹿児島県）は使わない。
 */
import { REGION_TIME, type CaveatKey } from "@/lib/registry/generated-client";

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
  /**
   * 概況①「場所で比べる」と時系列画面の既定（水域・指標・並び）。無ければ出さない（見出しだけ）。
   * 指標名は registry の VARIABLE_LABEL から引く。海は標高で並べられないので `order: "name"`。
   */
  highlight?: {
    water: string;
    variableId: string;
    order: "elevation" | "name";
  };
  /** 概況②を「サンゴ礁の被度（年で比べる）」にする。読む出典（モニタリングサイト1000 SAN01、奄美のみ）。 */
  homeCoral?: { sourceId: string };
  /** 概況の固定文言（境川・鶴見川・レッドリスト3版など）がこの地域の数字として当てはまるか。 */
  hasFixedNarrative: boolean;
  /** レッドリスト画面の既定の版の年。無ければ最新の版。 */
  defaultRedlistYear?: number;
  /** 流域マップの説明（地図の左の見出し下）。流域の作り方は地域で違う（Issue #94）。 */
  watershedBasis: string;
  /** 流域マップの出典の流域界の部分。 */
  watershedSource: string;
  /** 流域マップに添える注意書き（registry の caveat）。流域が公式の界でない地域だけ持つ。 */
  watershedCaveat?: CaveatKey;
}

export const REGION_ALL = "all" as const;

/** scripts/regions.py の bbox と同じ値（`map/basemaps.ts` の KANAGAWA_BOUNDS/AMAMI_BOUNDS）。 */
export const REGIONS: readonly RegionUi[] = [
  {
    id: "jp-14",
    label: "神奈川県",
    jumpLabel: "神奈川県へ",
    highlight: { water: "境川（１）", variableId: "common:variable:water.bod", order: "elevation" },
    hasFixedNarrative: true,
    defaultRedlistYear: 2022,
    watershedBasis: "国土数値情報 W12 の単位流域（1977年版）",
    watershedSource: "国土数値情報 流域界・非集水域 W12（国土数値情報利用約款）",
    bounds: [
      [138.9, 35.1],
      [139.83, 35.68],
    ],
  },
  {
    id: "jp-46",
    label: "奄美大島",
    jumpLabel: "奄美大島へ",
    hasFixedNarrative: false,
    // 奄美の BOD は水域に紐づく代表系列が無い。海域の COD は 2 水域・10 地点で揃っている。
    highlight: { water: "奄美大島本島海域", variableId: "common:variable:water.cod", order: "name" },
    homeCoral: { sourceId: "moni1000_coral_amami" },
    watershedBasis: "国土地理院の10m標高から計算した流域",
    watershedSource: "国土地理院 基盤地図情報 数値標高モデル（DEM10B）から計算した流域界",
    watershedCaveat: "amamiWatershedDem",
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

/** 具体的な地域の ID の一覧（zod の enum 用のタプル型）。 */
export const REGION_IDS = REGIONS.map((r) => r.id) as [RegionId, ...RegionId[]];

/** 切り替え UI の選択肢（'all' を先頭に含む）。 */
export const REGION_OPTIONS: readonly { id: RegionFilter; label: string }[] = [
  { id: REGION_ALL, label: regionLabel(REGION_ALL) },
  ...REGIONS.map((r) => ({ id: r.id as RegionFilter, label: r.label })),
];

/** 地図の移動先。'all' は先頭の地域（既定の見え方）。 */
export function regionBounds(f: RegionFilter): RegionUi["bounds"] {
  return (REGIONS.find((r) => r.id === f) ?? REGIONS[0]).bounds;
}

/** 地域の UI 宣言。'all' は undefined。 */
export function regionUi(f: RegionFilter): RegionUi | undefined {
  return REGIONS.find((r) => r.id === f);
}

/** URL・リンクのクエリに地域を載せる（'all' は `region` を消す＝現状と同じ URL）。 */
export function applyRegionParam(params: URLSearchParams, f: RegionFilter): void {
  if (f === REGION_ALL) params.delete("region");
  else params.set("region", f);
}

/**
 * 概況①・時系列画面の既定の水域・指標・並び。'all' は先頭の地域（神奈川の境川・BOD）。
 * 地域に宣言が無ければ undefined（出さない）。
 */
export function highlightOf(f: RegionFilter): RegionUi["highlight"] {
  return (f === REGION_ALL ? REGIONS[0] : regionUi(f))?.highlight;
}
