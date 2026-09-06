"use client";

import * as React from "react";
import { usePathname } from "next/navigation";
import type { PageContext } from "@/lib/ai/page-context";

/**
 * 画面の「状態」をアシスタントに渡すための配線。app/layout.tsx に常駐させ、
 * 個々の画面（TimeseriesExplorer など）は useSetPageContext で今の状態を登録するだけでよい。
 *
 * 「今の画面の詳細」は指定した画面（/, /timeseries, /biota, /sites/[id]）だけが持ち、
 * それ以外のページでは route と画面名だけのフォールバックに自動的に落ちる。
 * フォールバックの切り替えを「画面遷移のたびに前の状態を消す」というリセット処理でやると、
 * 新しい画面の useSetPageContext エフェクトとリセットのエフェクトの実行順に依存してしまう
 * （React はコミット内で子→親の順にエフェクトを走らせるため、親側のリセットが後から
 * 子の登録を上書きしうる）。それを避けるため、登録した値には「そのときの pathname」を
 * 一緒に持たせておき、読み出すときに「今の pathname と一致するか」だけで判定する。
 * 一致しなければ黙ってフォールバックを返す（リセットという操作自体が要らない）。
 */

/** パス→画面名。SiteNav のラベルに合わせてある。ここに無いパスは説明無しでパスだけ返す。 */
const ROUTE_TITLES: Record<string, string> = {
  "/": "概況",
  "/map": "流域マップ",
  "/timeseries": "時系列比較",
  "/biota": "生物相",
  "/sites": "地点カルテ",
  "/documents": "文書と統計",
  "/quality": "品質と進捗",
  "/explore": "データ探索",
  "/sources": "出典",
};

function fallbackFor(pathname: string): PageContext {
  if (pathname === "/") return { route: "/", title: ROUTE_TITLES["/"] };
  const base = Object.keys(ROUTE_TITLES).find((p) => p !== "/" && pathname.startsWith(p));
  return { route: pathname, title: (base && ROUTE_TITLES[base]) || pathname };
}

interface Registered {
  pathname: string;
  ctx: PageContext;
}

interface Ctx {
  /** 登録が今の pathname のものでなければ getFallback() を返す（毎回新しい物を作らないため呼び側が持つ）。 */
  get: (pathname: string, getFallback: () => PageContext) => PageContext;
  subscribe: (cb: () => void) => () => void;
  set: (pathname: string, ctx: PageContext) => void;
}

const PageContextCtx = React.createContext<Ctx | null>(null);

export function PageContextProvider({ children }: { children: React.ReactNode }) {
  const registeredRef = React.useRef<Registered | null>(null);
  const listenersRef = React.useRef(new Set<() => void>());

  const notify = React.useCallback(() => {
    for (const l of listenersRef.current) l();
  }, []);

  const set = React.useCallback(
    (pathname: string, ctx: PageContext) => {
      registeredRef.current = { pathname, ctx };
      notify();
    },
    [notify],
  );

  const get = React.useCallback((pathname: string, getFallback: () => PageContext): PageContext => {
    const r = registeredRef.current;
    return r && r.pathname === pathname ? r.ctx : getFallback();
  }, []);

  const subscribe = React.useCallback((cb: () => void) => {
    listenersRef.current.add(cb);
    return () => listenersRef.current.delete(cb);
  }, []);

  const value = React.useMemo(() => ({ get, subscribe, set }), [get, subscribe, set]);

  return <PageContextCtx.Provider value={value}>{children}</PageContextCtx.Provider>;
}

/**
 * 画面側が今の状態を登録する。値が変わるたびに呼んでよい
 * （JSON化した中身が実質的に変わったときだけ登録し直すので、呼び出し頻度は気にしなくてよい）。
 */
export function useSetPageContext(snapshot: PageContext) {
  const ctx = React.useContext(PageContextCtx);
  const pathname = usePathname();
  const key = JSON.stringify(snapshot);
  React.useEffect(() => {
    ctx?.set(pathname, snapshot);
    // key は snapshot の内容そのもの。snapshot オブジェクトの identity ではなく中身が変わったときだけ効かせる
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ctx, pathname, key]);
}

/** サーバ側の searchParams などから初期値を作れない画面（/ など）向けの薄いラッパ。 */
export function PageContextSetter({ context }: { context: PageContext }) {
  useSetPageContext(context);
  return null;
}

/**
 * AssistantPanel が送信時に読む「今のスナップショット」。
 *
 * 外部ストア（ref + 購読）からの読み出しなので useSyncExternalStore を使う。
 * レンダー中に ref を直接読むと、並行レンダリングでレンダーごとに違う値を見る余地が残る。
 * getSnapshot は同じ状態なら同じ参照を返す必要があるので、フォールバックは毎回作らず
 * pathname ごとにキャッシュする（新しいオブジェクトを返し続けると無限ループになる）。
 */
export function usePageContextSnapshot(): PageContext {
  const ctx = React.useContext(PageContextCtx);
  const pathname = usePathname();
  const fallbackRef = React.useRef<{ pathname: string; ctx: PageContext } | null>(null);
  const getFallback = React.useCallback(() => {
    if (fallbackRef.current?.pathname !== pathname) {
      fallbackRef.current = { pathname, ctx: fallbackFor(pathname) };
    }
    return fallbackRef.current.ctx;
  }, [pathname]);

  const subscribe = React.useCallback(
    (cb: () => void) => (ctx ? ctx.subscribe(cb) : () => {}),
    [ctx],
  );
  const getSnapshot = React.useCallback(
    () => (ctx ? ctx.get(pathname, getFallback) : getFallback()),
    [ctx, pathname, getFallback],
  );

  return React.useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}
