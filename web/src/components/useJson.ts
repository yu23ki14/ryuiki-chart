"use client";
import * as React from "react";

interface State<T> {
  url: string;
  data: T | null;
  error: string | null;
}

/**
 * GET して JSON を返すだけの共通フック。url が空文字なら何もしない。
 * 取得中も直前のデータを保持する（読み込みのたびに図が消えて layout が跳ねるのを避ける）。
 */
export function useJson<T>(url: string) {
  const [state, setState] = React.useState<State<T>>({ url: "", data: null, error: null });

  React.useEffect(() => {
    if (!url) return;
    const ctrl = new AbortController();
    fetch(url, { signal: ctrl.signal })
      .then(async (r) => {
        const j = (await r.json()) as T & { error?: string };
        if (!r.ok) throw new Error(j.error ?? "取得に失敗しました");
        return j as T;
      })
      .then((data) => setState({ url, data, error: null }))
      .catch((e: Error) => {
        if (e.name !== "AbortError") setState({ url, data: null, error: String(e.message ?? e) });
      });
    return () => ctrl.abort();
  }, [url]);

  const settled = state.url === url;
  if (!url) return { data: null, loading: false, error: null };
  // 取得中は直前のデータを見せ続ける（図が消えて layout が跳ねるのを避ける）
  return { data: state.data, loading: !settled, error: settled ? state.error : null };
}
