import { REGION_ALL, parseRegion, type RegionFilter } from "@/lib/region";

/**
 * 地域の絞り（?region=）を URL に載せ降ろしする純粋な関数（クライアント・サーバ共通）。
 * URL が正（クッキー・localStorage は使わない）。'all'（既定）のときは `region` を付けない＝現状と同じ URL。
 */

/** 内部リンク・API の URL に `region` を足す。'all' のときは何もしない。既存の `region` は置き換える。 */
export function withRegion(url: string, region: RegionFilter): string {
  // 空文字は useJson の「取得しない」の合図なので、そのまま返す。
  if (!url) return url;
  const hashAt = url.indexOf("#");
  const hash = hashAt >= 0 ? url.slice(hashAt) : "";
  const base = hashAt >= 0 ? url.slice(0, hashAt) : url;
  const qAt = base.indexOf("?");
  const path = qAt >= 0 ? base.slice(0, qAt) : base;
  const qs = searchWithRegion(qAt >= 0 ? base.slice(qAt + 1) : "", region);
  return `${path}${qs ? `?${qs}` : ""}${hash}`;
}

/**
 * クエリ文字列（先頭の ? は有っても無くてもよい）の `region` だけを差し替えて返す（先頭の ? は付けない）。
 * 'all' は `region` を消す。他のクエリは順序ごと保つ。
 */
export function searchWithRegion(search: string, region: RegionFilter): string {
  const params = new URLSearchParams(search.startsWith("?") ? search.slice(1) : search);
  if (region === REGION_ALL) params.delete("region");
  else params.set("region", region);
  return params.toString();
}

/** 現在のクエリから地域を読む（不正値・未指定は 'all'）。 */
export function regionFromSearch(search: { get(name: string): string | null } | null | undefined): RegionFilter {
  return parseRegion(search?.get("region") ?? undefined);
}
