/**
 * 地点の座標から Google マップを開く URL。
 * 環境省の水質測定点には「監視点イ」のように名前だけでは場所の分からない地点があり、
 * 同名の別地点もあるので、画面は地点名の横にこの URL へのリンクを添える。
 * URL の組み立てはここ1箇所に置く（画面ごとに書かない）。
 * 座標が無い（needs_review の）地点は null を返し、画面はリンクを出さない。
 */
export function googleMapsUrl(lat: number | null | undefined, lon: number | null | undefined): string | null {
  if (typeof lat !== "number" || typeof lon !== "number") return null;
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;
  return `https://www.google.com/maps/search/?api=1&query=${lat.toFixed(6)},${lon.toFixed(6)}`;
}
