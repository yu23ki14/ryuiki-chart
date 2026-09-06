import type { StyleSpecification, RequestParameters } from "maplibre-gl";

/**
 * ベースマップの抽象化層。
 *
 * 既定は OpenStreetMap / 国土地理院のラスタタイル（トークン不要）。
 * `NEXT_PUBLIC_MAPBOX_TOKEN` を .env に入れるだけで Mapbox のスタイルが選択肢に増える。
 * 描画エンジンは MapLibre GL JS（Mapbox GL JS のオープンソース版）で、
 * Mapbox のスタイル仕様と互換なので、差し替えはこのファイルの編集だけで完結する。
 */

export type BasemapId = string;

export interface Basemap {
  id: BasemapId;
  label: string;
  /** 出典表示（法的に必須） */
  attribution: string;
  /** 暗い地図か（オーバーレイの配色を反転させるのに使う） */
  dark?: boolean;
  /** ラベル等を持たない素の地図か（データを主役にしたい時に選ぶ） */
  minimal?: boolean;
  buildStyle: () => StyleSpecification | string;
}

const OSM_ATTRIB = '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';
const GSI_ATTRIB = '<a href="https://maps.gsi.go.jp/development/ichiran.html">地理院タイル</a>';

function rasterStyle(opts: {
  tiles: string[];
  attribution: string;
  maxzoom?: number;
  background?: string;
}): StyleSpecification {
  return {
    version: 8,
    sources: {
      base: {
        type: "raster",
        tiles: opts.tiles,
        tileSize: 256,
        maxzoom: opts.maxzoom ?? 18,
        attribution: opts.attribution,
      },
    },
    layers: [
      { id: "bg", type: "background", paint: { "background-color": opts.background ?? "#eef2f5" } },
      { id: "base", type: "raster", source: "base", paint: { "raster-opacity": 1 } },
    ],
  };
}

export const MAPBOX_TOKEN = process.env.NEXT_PUBLIC_MAPBOX_TOKEN ?? "";

const OPEN_BASEMAPS: Basemap[] = [
  {
    id: "osm",
    label: "OpenStreetMap",
    attribution: OSM_ATTRIB,
    buildStyle: () =>
      rasterStyle({
        tiles: [
          "https://a.tile.openstreetmap.org/{z}/{x}/{y}.png",
          "https://b.tile.openstreetmap.org/{z}/{x}/{y}.png",
          "https://c.tile.openstreetmap.org/{z}/{x}/{y}.png",
        ],
        attribution: OSM_ATTRIB,
        maxzoom: 19,
      }),
  },
  {
    id: "gsi-pale",
    label: "地理院 淡色",
    attribution: GSI_ATTRIB,
    minimal: true,
    buildStyle: () =>
      rasterStyle({
        tiles: ["https://cyberjapandata.gsi.go.jp/xyz/pale/{z}/{x}/{y}.png"],
        attribution: GSI_ATTRIB,
        maxzoom: 18,
      }),
  },
  {
    id: "gsi-relief",
    label: "地理院 陰影起伏",
    attribution: GSI_ATTRIB,
    minimal: true,
    buildStyle: () =>
      rasterStyle({
        tiles: ["https://cyberjapandata.gsi.go.jp/xyz/hillshademap/{z}/{x}/{y}.png"],
        attribution: GSI_ATTRIB,
        maxzoom: 16,
        background: "#f6f4ef",
      }),
  },
  {
    id: "gsi-photo",
    label: "地理院 航空写真",
    attribution: GSI_ATTRIB,
    dark: true,
    buildStyle: () =>
      rasterStyle({
        tiles: ["https://cyberjapandata.gsi.go.jp/xyz/seamlessphoto/{z}/{x}/{y}.jpg"],
        attribution: GSI_ATTRIB,
        maxzoom: 18,
        background: "#0b1218",
      }),
  },
];

/** トークンが設定されている時だけ出す Mapbox スタイル */
const MAPBOX_BASEMAPS: Basemap[] = [
  { id: "mapbox/light-v11", label: "Mapbox Light" },
  { id: "mapbox/streets-v12", label: "Mapbox Streets" },
  { id: "mapbox/outdoors-v12", label: "Mapbox Outdoors" },
  { id: "mapbox/satellite-streets-v12", label: "Mapbox Satellite", dark: true },
  { id: "mapbox/dark-v11", label: "Mapbox Dark", dark: true },
].map((s) => ({
  id: s.id,
  label: s.label,
  dark: s.dark,
  attribution: '© <a href="https://www.mapbox.com/about/maps/">Mapbox</a> ' + OSM_ATTRIB,
  buildStyle: () => `https://api.mapbox.com/styles/v1/${s.id}?access_token=${MAPBOX_TOKEN}`,
}));

export const BASEMAPS: Basemap[] = [...OPEN_BASEMAPS, ...(MAPBOX_TOKEN ? MAPBOX_BASEMAPS : [])];

export const DEFAULT_BASEMAP_ID: BasemapId = "osm";

export function getBasemap(id: BasemapId | undefined): Basemap {
  return BASEMAPS.find((b) => b.id === id) ?? BASEMAPS[0];
}

/**
 * Mapbox のスタイル JSON は `mapbox://` スキームの URL を含むため、
 * MapLibre から読むには実 URL への書き換えとトークン付与が要る。
 * OSM / 地理院タイルの時は何もしない。
 */
export function mapTransformRequest(url: string): RequestParameters | undefined {
  if (!MAPBOX_TOKEN) return undefined;
  if (url.startsWith("mapbox://sprites/") || url.startsWith("mapbox://styles/")) {
    const rest = url.replace("mapbox://sprites/", "").replace("mapbox://styles/", "");
    const [pathPart, query] = rest.split("?");
    const kind = url.includes("/sprites/") ? "sprites" : "styles/v1";
    return { url: `https://api.mapbox.com/${kind}/${pathPart}?${query ? query + "&" : ""}access_token=${MAPBOX_TOKEN}` };
  }
  if (url.startsWith("mapbox://fonts/")) {
    const rest = url.replace("mapbox://fonts/", "");
    return { url: `https://api.mapbox.com/fonts/v1/${rest}?access_token=${MAPBOX_TOKEN}` };
  }
  if (url.startsWith("mapbox://")) {
    // タイルセット: mapbox://mapbox.satellite -> TileJSON
    const id = url.replace("mapbox://", "");
    return { url: `https://api.mapbox.com/v4/${id}.json?secure&access_token=${MAPBOX_TOKEN}` };
  }
  return undefined;
}

/** 神奈川県のだいたいの範囲（データの実測 bbox に合わせてある） */
export const KANAGAWA_BOUNDS: [[number, number], [number, number]] = [
  [138.9, 35.1],
  [139.83, 35.68],
];
export const DEFAULT_CENTER: [number, number] = [139.35, 35.42];
export const DEFAULT_ZOOM = 9.2;
