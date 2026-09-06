"use client";

import * as React from "react";
import * as maplibregl from "maplibre-gl";
import type {
  Map as MlMap,
  LayerSpecification,
  SourceSpecification,
  MapGeoJSONFeature,
  MapMouseEvent,
  GeoJSONSource,
  LngLat,
  StyleImageSource,
  DistributiveOmit,
} from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { BASEMAPS, DEFAULT_BASEMAP_ID, DEFAULT_CENTER, DEFAULT_ZOOM, getBasemap, mapTransformRequest, type Basemap } from "@/lib/map/basemaps";

export interface MapLayerSpec {
  id: string;
  /** どのソースに属するか */
  source: string;
  // LayerSpecification は共用体なので素の Omit だと全レイヤ共通のキーしか残らず、
  // fill だけが持つ `filter` などが書けなくなる。maplibre が配る分配版の Omit を使う。
  spec: DistributiveOmit<LayerSpecification, "id" | "source"> & { source?: string };
  /** クリック時にポップアップを出すか */
  interactive?: boolean;
}

export interface MapCanvasProps {
  sources: Record<string, SourceSpecification>;
  layers: MapLayerSpec[];
  /**
   * `fill-pattern` などで使うランタイム生成の画像（id -> RGBA）。
   * レイヤより先に登録しないと「画像が無い」で面が描かれないので、ここで受けて
   * addLayer の前に addImage する。スタイル（ベースマップ）を切り替えると画像も消えるため
   * styledata のたびに入れ直す。作り方は lib/map/stripe.ts。
   */
  images?: Record<string, StyleImageSource>;
  onFeatureClick?: (f: MapGeoJSONFeature, lngLat: LngLat) => void;
  onHover?: (f: MapGeoJSONFeature | null) => void;
  fitBounds?: [[number, number], [number, number]] | null;
  center?: [number, number];
  zoom?: number;
  className?: string;
  /** 右上に重ねる凡例など */
  overlay?: React.ReactNode;
  /** ベースマップの明暗をユーザーに知らせたい場合 */
  onBasemapChange?: (b: Basemap) => void;
}

const LS_KEY = "ryuiki.basemap";

/** 未登録のものだけ addImage する（同じ id を二度足すと MapLibre が警告を出す）。 */
function applyImages(map: MlMap, images: Record<string, StyleImageSource> | undefined) {
  if (!images) return;
  for (const [id, image] of Object.entries(images)) {
    if (!map.hasImage(id)) map.addImage(id, image);
  }
}

// MapLibre のワーカーはバンドラ経由だと URL を解決できないため、public/ に置いた素のファイルを指す。
// （scripts/copy-maplibre-worker.mjs が npm run dev / build の前に配置する）
let workerConfigured = false;
function ensureWorkerUrl() {
  if (workerConfigured || typeof window === "undefined") return;
  maplibregl.setWorkerUrl("/maplibre/maplibre-gl-worker.mjs");
  workerConfigured = true;
}

/**
 * MapLibre GL の薄いラッパ。
 * ベースマップを切り替えてもデータレイヤは保持される（styledata で再投入する）。
 * Mapbox に移行する場合は lib/map/basemaps.ts にトークンを与えるだけでよい。
 */
export function MapCanvas({
  sources,
  layers,
  images,
  onFeatureClick,
  onHover,
  fitBounds,
  center = DEFAULT_CENTER,
  zoom = DEFAULT_ZOOM,
  className = "",
  overlay,
  onBasemapChange,
}: MapCanvasProps) {
  const containerRef = React.useRef<HTMLDivElement>(null);
  const mapRef = React.useRef<MlMap | null>(null);
  const [ready, setReady] = React.useState(false);
  // 保存済みのベースマップ設定は初期化時に読む（localStorage が無い環境でも動く）
  const [basemapId, setBasemapId] = React.useState<string>(() => {
    if (typeof window === "undefined") return DEFAULT_BASEMAP_ID;
    try {
      const saved = window.localStorage.getItem(LS_KEY);
      return saved && BASEMAPS.some((b) => b.id === saved) ? saved : DEFAULT_BASEMAP_ID;
    } catch {
      return DEFAULT_BASEMAP_ID;
    }
  });

  const sourcesRef = React.useRef(sources);
  const layersRef = React.useRef(layers);
  const imagesRef = React.useRef(images);
  React.useEffect(() => {
    sourcesRef.current = sources;
    layersRef.current = layers;
    imagesRef.current = images;
  });

  // データレイヤを（再）投入する
  const applyData = React.useCallback(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;
    applyImages(map, imagesRef.current);
    for (const [id, spec] of Object.entries(sourcesRef.current) as [string, SourceSpecification][]) {
      if (!map.getSource(id)) map.addSource(id, spec);
    }
    for (const l of layersRef.current) {
      if (!map.getLayer(l.id)) {
        map.addLayer({ ...l.spec, id: l.id, source: l.source } as unknown as LayerSpecification);
      }
    }
  }, []);

  // 初期化
  React.useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    ensureWorkerUrl();
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: getBasemap(basemapId).buildStyle(),
      center,
      zoom,
      attributionControl: { compact: true },
      transformRequest: (url: string) => mapTransformRequest(url),
      maxZoom: 18,
      // 会議用に地図を画像として書き出せるようにする（canvas.toDataURL に必要）
      canvasContextAttributes: { preserveDrawingBuffer: true },
    });
    mapRef.current = map;
    if (process.env.NODE_ENV !== "production") {
      (window as unknown as { __ryuikiMap?: MlMap }).__ryuikiMap = map;
    }
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    map.addControl(new maplibregl.ScaleControl({ maxWidth: 90, unit: "metric" }), "bottom-left");
    map.on("load", () => {
      applyData();
      setReady(true);
    });
    map.on("styledata", applyData);
    return () => {
      map.remove();
      mapRef.current = null;
    };
    // basemapId は別 effect で扱う
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ベースマップ切替
  React.useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const bm = getBasemap(basemapId);
    map.setStyle(bm.buildStyle() as never, { diff: false });
    onBasemapChange?.(bm);
    try {
      localStorage.setItem(LS_KEY, basemapId);
    } catch {
      /* noop */
    }
  }, [basemapId, ready, onBasemapChange]);

  // ソースのデータ更新
  React.useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    for (const [id, spec] of Object.entries(sources) as [string, SourceSpecification][]) {
      const src = map.getSource(id);
      if (!src) {
        if (map.isStyleLoaded()) map.addSource(id, spec);
        continue;
      }
      if (spec.type === "geojson" && "setData" in src) {
        (src as GeoJSONSource).setData(spec.data as never);
      }
    }
  }, [sources, ready]);

  // fill-pattern 用の画像。**レイヤの effect より先に宣言する**（先に走らせるため）。
  // 画像が無いまま fill-pattern のレイヤを足すと、その面は何も描かれない。
  React.useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    applyImages(map, images);
  }, [images, ready]);

  // レイヤの増減・スタイル更新
  React.useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    // スタイル読み込み中に来た更新は取りこぼさず、読み終わってから当てる
    if (!map.isStyleLoaded()) {
      const retry = () => sync();
      map.once("idle", retry);
      return () => {
        map.off("idle", retry);
      };
    }
    sync();

    function sync() {
      if (!map || !map.isStyleLoaded()) return;
      for (const [id, spec] of Object.entries(sourcesRef.current) as [string, SourceSpecification][]) {
        if (!map.getSource(id)) map.addSource(id, spec);
      }
      const wanted = new Set(layers.map((l) => l.id));
      // 消えたレイヤを削除
      for (const l of map.getStyle().layers ?? []) {
        if (l.id.startsWith("ry-") && !wanted.has(l.id)) map.removeLayer(l.id);
      }
      for (const l of layers) {
        const existing = map.getLayer(l.id);
        if (!existing) {
          if (map.getSource(l.source)) {
            map.addLayer({ ...l.spec, id: l.id, source: l.source } as unknown as LayerSpecification);
          }
          continue;
        }
        const spec = l.spec as { paint?: Record<string, unknown>; layout?: Record<string, unknown>; filter?: unknown };
        for (const [k, v] of Object.entries(spec.paint ?? {})) map.setPaintProperty(l.id, k as never, v as never);
        for (const [k, v] of Object.entries(spec.layout ?? {})) map.setLayoutProperty(l.id, k as never, v as never);
        map.setFilter(l.id, (spec.filter ?? null) as never);
      }
    }
  }, [layers, ready]);

  // クリック / ホバー
  React.useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const ids = layers.filter((l) => l.interactive).map((l) => l.id);
    if (ids.length === 0) return;

    const click = (e: MapMouseEvent) => {
      const feats = map.queryRenderedFeatures(e.point, { layers: ids.filter((i) => map.getLayer(i)) });
      if (feats[0]) onFeatureClick?.(feats[0], e.lngLat);
    };
    const move = (e: MapMouseEvent) => {
      const feats = map.queryRenderedFeatures(e.point, { layers: ids.filter((i) => map.getLayer(i)) });
      map.getCanvas().style.cursor = feats.length ? "pointer" : "";
      onHover?.(feats[0] ?? null);
    };
    map.on("click", click);
    if (onHover) map.on("mousemove", move);
    return () => {
      map.off("click", click);
      if (onHover) map.off("mousemove", move);
    };
  }, [layers, ready, onFeatureClick, onHover]);

  // fitBounds
  React.useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !fitBounds) return;
    map.fitBounds(fitBounds, { padding: 48, duration: 700, maxZoom: 14 });
  }, [fitBounds, ready]);

  // className は「位置指定済みの箱」であることが前提（absolute inset-0 か relative + 高さ）。
  // ここで relative を足すと呼び出し側の absolute と競合して高さ 0 になるため足さない。
  return (
    <div className={className || "relative h-full"}>
      {/* MapLibre はコンテナの position を relative に上書きするため、
          inset-0 での引き伸ばしは効かない。幅・高さを直接 100% にする。 */}
      <div ref={containerRef} className="w-full h-full" />
      <div className="absolute top-2 left-2 z-10 no-print">
        <select
          value={basemapId}
          onChange={(e) => setBasemapId(e.target.value)}
          className="text-[11px] px-2 py-1 rounded border border-line bg-surface/95 shadow-sm backdrop-blur focus:outline-none"
          aria-label="ベースマップ"
        >
          {BASEMAPS.map((b) => (
            <option key={b.id} value={b.id}>
              {b.label}
            </option>
          ))}
        </select>
      </div>
      {overlay}
    </div>
  );
}

export { maplibregl };
