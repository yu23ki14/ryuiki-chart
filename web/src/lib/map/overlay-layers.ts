/**
 * 奄美の重ね描きレイヤー（土砂災害警戒区域・保護区。Issue #105、docs/plans/ISSUE105_AMAMI_STORIES_MAP.md §2）。
 * 宣言・URL 同期・bbox の格子丸め・取得 URL・描画の式を、副作用のない関数で1か所に置く。
 * 表示する地域は出典の地域（sourceInRegion）から機械的に決め、手書きの地域リストは持たない。
 */
import type { RegionFilter, RegionId } from "@/lib/region";
import { REGION_ALL } from "@/lib/region";
import { sourceRegion } from "@/lib/cube/region";
import { INK, SERIES, STATUS } from "@/components/viz/palette";

export type OverlayId = "hazard" | "pa_a10" | "pa_a15" | "pa_a45";

export interface OverlayDecl {
  id: OverlayId;
  label: string;
  /** 出典。地域の出し分けはこの出典の地域（SOURCE_REGION）から決める */
  sourceIds: readonly string[];
  /**
   * SOURCE_REGION に載らない出典（manifests/ の地域宣言が無い台帳型）用の既定。宣言があればそちらが勝つ
   * （overlay-layers.test.ts が食い違いを検出する）。出典側に地域が宣言されたらこの行は消せる。
   */
  fallbackRegion: RegionId;
  /** これ未満のズームでは取りに行かない（bbox を使うレイヤー） */
  minZoom: number;
  /** bbox を付けて取るか（A10・A15 は全件が小さいので不要） */
  bbox: boolean;
}

/** 警戒区域の表示下限ズーム（設計書 §2-1）。 */
export const HAZARD_MIN_ZOOM = 11;
/** bbox の格子（度）。キャッシュを効かせるために外向きに丸める。 */
export const BBOX_GRID = 0.05;
/** 取得に失敗しても書けるよう、凡例の既定文言はここに置く。 */
export const NOTE_MIN_ZOOM = "拡大すると表示される";
export const NOTE_TRUNCATED = "表示範囲に収まらない分は省略した。拡大すると出る";

export const OVERLAYS: readonly OverlayDecl[] = [
  { id: "hazard", label: "土砂災害警戒区域", sourceIds: ["bodik_kagoshima_dosha_amami"], fallbackRegion: "jp-46", minZoom: HAZARD_MIN_ZOOM, bbox: true },
  { id: "pa_a10", label: "自然公園地域", sourceIds: ["nlni_a10_natparks_amami"], fallbackRegion: "jp-46", minZoom: 0, bbox: false },
  { id: "pa_a15", label: "鳥獣保護区", sourceIds: ["nlni_a15_wildlife_amami"], fallbackRegion: "jp-46", minZoom: 0, bbox: false },
  { id: "pa_a45", label: "国有林", sourceIds: ["nlni_a45_forest_amami"], fallbackRegion: "jp-46", minZoom: 10, bbox: true },
];

export const OVERLAY_IDS: readonly OverlayId[] = OVERLAYS.map((o) => o.id);

/** レイヤーの地域。出典の宣言（SOURCE_REGION）が先、無ければ fallbackRegion。 */
export function overlayRegion(o: OverlayDecl): RegionId {
  return (sourceRegion(o.sourceIds[0]) as RegionId | undefined) ?? o.fallbackRegion;
}

/** 地域で見せるレイヤー。全体（all）は全部。 */
export function overlaysForRegion(region: RegionFilter): OverlayDecl[] {
  return OVERLAYS.filter((o) => region === REGION_ALL || overlayRegion(o) === region);
}

/** `layers=hazard,pa_a10` を読む。知らない名前・重複は捨てる（宣言の順に並べ直す）。 */
export function parseLayersParam(v: string | null | undefined): OverlayId[] {
  if (!v) return [];
  const want = new Set(v.split(",").map((s) => s.trim()));
  return OVERLAY_IDS.filter((id) => want.has(id));
}

/** URL の `layers` を差し替えた検索文字列（先頭の ? なし）。空なら `layers` を消す。他のクエリは保つ。 */
export function searchWithLayers(search: string, ids: readonly OverlayId[]): string {
  const params = new URLSearchParams(search.startsWith("?") ? search.slice(1) : search);
  const ordered = OVERLAY_IDS.filter((id) => ids.includes(id));
  if (ordered.length) params.set("layers", ordered.join(","));
  else params.delete("layers");
  return params.toString();
}

export type Bbox = [number, number, number, number];

/** 0.05 度の格子へ外向きに丸める（西・南は切り下げ、東・北は切り上げ）。浮動小数の誤差は 1e-9 で吸収。 */
export function snapBbox(b: Bbox, grid = BBOX_GRID): Bbox {
  const lo = (x: number) => round6(Math.floor(x / grid + 1e-9) * grid);
  const hi = (x: number) => round6(Math.ceil(x / grid - 1e-9) * grid);
  return [lo(b[0]), lo(b[1]), hi(b[2]), hi(b[3])];
}

function round6(x: number): number {
  return Math.round(x * 1e6) / 1e6;
}

const bboxParam = (b: Bbox) => b.join(",");

/**
 * レイヤーの取得 URL。取りに行かないときは ""（useJson の「取得しない」）。
 * 同じ格子・同じレイヤーなら同じ文字列になるので、再取得は起きない。
 */
export function overlayUrl(decl: OverlayDecl, view: { bbox: Bbox; zoom: number } | null): string {
  if (decl.id === "hazard") {
    if (!view || view.zoom < decl.minZoom) return "";
    return `/api/geo/hazard-zones?bbox=${bboxParam(snapBbox(view.bbox))}`;
  }
  const sid = decl.sourceIds[0];
  const base = `/api/geo/protected-areas/polygons?source_id=${sid}`;
  if (!decl.bbox) return base;
  if (!view || view.zoom < decl.minZoom) return "";
  return `${base}&bbox=${bboxParam(snapBbox(view.bbox))}`;
}

/** ズームが足りず取得を止めているか（凡例に「拡大すると表示される」を出す）。 */
export function belowMinZoom(decl: OverlayDecl, zoom: number | null): boolean {
  return decl.bbox && (zoom == null || zoom < decl.minZoom);
}

/* ------------------------------ 描画 ------------------------------ */

export const PHENOMENA = [
  { code: "debris_flow", label: "土石流" },
  { code: "steep_slope", label: "急傾斜地の崩壊" },
  { code: "landslide", label: "地滑り" },
] as const;
export type PhenomenonCode = (typeof PHENOMENA)[number]["code"];

/** 区分の色（STATUS。色だけにせず凡例に文字ラベルを添える）。 */
export const HAZARD_STYLE = {
  warning: { color: STATUS.warning, opacity: 0.45, label: "警戒区域" },
  special_warning: { color: STATUS.critical, opacity: 0.6, label: "特別警戒区域" },
} as const;

/** A10 は入れ子（外側から内側）。濃淡は同じ青で重ねるほど濃くなる。 */
export const A10_STYLE = [
  { code: "natpark_area", label: "公園区域", opacity: 0.15 },
  { code: "natpark_special", label: "特別地域", opacity: 0.3 },
  { code: "natpark_special_protection", label: "特別保護地区", opacity: 0.5 },
] as const;
export const A15_STYLE = [
  { code: "wildlife_reserve", label: "鳥獣保護区", opacity: 0.3 },
  { code: "wildlife_special_protection", label: "特別保護地区", opacity: 0.5 },
] as const;

export const PA_COLORS = { pa_a10: SERIES[0], pa_a15: SERIES[2], pa_a45: SERIES[6] } as const;

/**
 * 保護区3色と警戒区域（黄・赤）の同時表示の検証は未了（validate_palette.js がリポジトリに無い）。
 * 検証できるまで A45 は面を塗らず線だけにする（設計書 §2-3 の安全側）。
 */
export const A45_FILL_VERIFIED = false;

export function phenomenonFilter(selected: readonly PhenomenonCode[]): unknown[] | null {
  // 全部（または空）は絞らない。空を「何も出さない」にするとチップを全部切ったときに迷子になる
  if (selected.length === 0 || selected.length === PHENOMENA.length) return null;
  return ["in", ["get", "phenomenon_code"], ["literal", [...selected]]];
}

/** 警戒区域の2レイヤー（警戒→特別警戒の順。特別警戒が上）＋白線。MapLayerSpec と同じ形（id/source/spec）。 */
export function hazardLayerSpecs(source: string, selected: readonly PhenomenonCode[]) {
  const ph = phenomenonFilter(selected);
  const kind = (k: string) => ["==", ["get", "zone_kind_code"], k];
  const f = (k: string) => (ph ? ["all", kind(k), ph] : kind(k));
  const fill = (k: keyof typeof HAZARD_STYLE) => ({
    id: `ry-hazard-fill-${k}`,
    source,
    interactive: true,
    spec: {
      type: "fill" as const,
      filter: f(k) as never,
      paint: { "fill-color": HAZARD_STYLE[k].color, "fill-opacity": HAZARD_STYLE[k].opacity },
    },
  });
  return [
    fill("warning"),
    fill("special_warning"),
    {
      id: "ry-hazard-line",
      source,
      spec: {
        type: "line" as const,
        ...(ph ? { filter: ph as never } : {}),
        paint: { "line-color": INK.surface, "line-width": 0.6, "line-opacity": 0.9 },
      },
    },
  ];
}

/** 保護区の面（線なし）。A45 は未検証の間は線のみ。 */
export function protectedLayerSpecs(id: Exclude<OverlayId, "hazard">, source: string) {
  const color = PA_COLORS[id];
  if (id === "pa_a45" && !A45_FILL_VERIFIED) {
    return [
      {
        id: "ry-pa-a45-line",
        source,
        interactive: true,
        spec: { type: "line" as const, paint: { "line-color": color, "line-width": 0.8, "line-opacity": 0.8 } },
      },
    ];
  }
  const styles = id === "pa_a10" ? A10_STYLE : id === "pa_a15" ? A15_STYLE : [{ code: "national_forest", opacity: 0.3 }];
  // opacity は category_code ごとに match で引く（外側→内側の描画順は features の並びでなくレイヤーを分けて保証する）
  return styles.map((s) => ({
    id: `ry-pa-${id.slice(3)}-${s.code}`,
    source,
    interactive: true,
    spec: {
      type: "fill" as const,
      filter: ["==", ["get", "category_code"], s.code] as never,
      paint: { "fill-color": color, "fill-opacity": s.opacity },
    },
  }));
}

/** 保護区は警戒区域の下に積む。呼び出し側はこの順（保護区 → 警戒区域）で layers に並べる。 */
export const PROTECTED_IDS = ["pa_a10", "pa_a15", "pa_a45"] as const;
