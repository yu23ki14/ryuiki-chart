"use client";

import * as React from "react";
import { AssistantRuntimeProvider } from "@assistant-ui/react";
import { useChatRuntime } from "@assistant-ui/ai-sdk";
import { DefaultChatTransport } from "ai";
import { Thread } from "./Thread";
import { usePageContextSnapshot } from "./PageContextProvider";

/**
 * 右下のフローティングボタン → 右ペインのAIアシスタント。
 * app/layout.tsx に常駐させ、ルート遷移で会話が消えないようにする
 * （このコンポーネント自体がページ遷移でアンマウントされないので、useChatRuntime の状態も保たれる）。
 *
 * layout.tsx の body は `h-full overflow-hidden flex flex-col`。各画面が自前でスクロールを持つ作りなので、
 * flex の兄弟としてここに差し込むと MapLibre や useSize 系チャートの再計測が壊れる。
 * そのため fixed のオーバーレイパネルにする。
 */
export function AssistantPanel() {
  const [open, setOpen] = React.useState(false);
  // 表を含む回答は 420px だと窮屈なので全画面に広げられるようにする。open とは独立のフラグで、
  // aside の className を切り替えるだけ（下の JSX 参照）。<Thread/> や AssistantRuntimeProvider を
  // アンマウントする分岐は一切無いので、全画面の出し入れで会話が消えることはない。
  const [fullscreen, setFullscreen] = React.useState(false);
  // 今の画面の状態。DefaultChatTransport の body は関数を渡すと送信のたびに再評価されるので
  // （node_modules/ai の HttpChatTransport.sendMessages が resolve(this.body) を毎回呼ぶ）、
  // クロージャで拾った最新スナップショットがそのまま最新のリクエストに乗る。
  const pageContext = usePageContextSnapshot();
  const runtime = useChatRuntime({
    transport: new DefaultChatTransport({ api: "/api/chat", body: () => ({ pageContext }) }),
  });

  // Esc で全画面だけを解除する（パネルそのものを閉じない）。全画面のときだけ listener を張るので、
  // 通常パネル時の Esc の挙動（今は何もしていない）はそのまま。
  React.useEffect(() => {
    if (!fullscreen) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") setFullscreen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [fullscreen]);

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      {!open && (
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="no-print fixed right-4 bottom-4 z-40 flex items-center gap-2 rounded-full border border-water bg-water text-white px-4 py-2.5 text-[13px] font-medium shadow hover:brightness-110"
        >
          <ChatMark />
          AIに聞く
        </button>
      )}
      {open && (
        <aside
          className={`no-print fixed top-12 bottom-0 z-40 bg-surface shadow flex flex-col ${
            // 全画面: SiteNav（h-12）の下から左右いっぱい。幅は left-0/right-0 の inset だけで
            // 決まるので w-* は要らない。通常時: 右docked の固定幅パネル（従来通り）。
            fullscreen ? "left-0 right-0" : "right-0 w-[420px] max-w-[92vw] border-l border-line"
          }`}
        >
          <header className="shrink-0 flex items-center justify-between gap-2 px-3.5 py-2.5 border-b border-line">
            <div className="min-w-0">
              <h2 className="text-[13px] font-semibold leading-tight">AIデータ分析アシスタント</h2>
              <p className="text-[10.5px] text-muted mt-0.5">流域カルテのデータについて質問できます</p>
            </div>
            <div className="shrink-0 flex items-center gap-0.5">
              <button
                type="button"
                onClick={() => setFullscreen((v) => !v)}
                className="text-muted hover:text-ink rounded px-1.5 py-1 hover:bg-surface-2"
                aria-label={fullscreen ? "全画面を解除" : "全画面表示"}
                aria-pressed={fullscreen}
                title={fullscreen ? "全画面を解除" : "全画面表示"}
              >
                {fullscreen ? <CollapseIcon /> : <ExpandIcon />}
              </button>
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="text-muted hover:text-ink text-[18px] leading-none px-1.5 py-1"
                aria-label="閉じる"
                title="閉じる"
              >
                ×
              </button>
            </div>
          </header>
          <div className="flex-1 min-h-0">
            <Thread />
          </div>
        </aside>
      )}
    </AssistantRuntimeProvider>
  );
}

function ChatMark() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true" fill="none">
      <path d="M2 3.5h12v7H6.5L3 13.5v-3H2v-7Z" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
    </svg>
  );
}

/** 四隅が外向きに開いた括弧＝「広げる」。よくある全画面切り替えアイコンの最小構成。 */
function ExpandIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 16 16" aria-hidden="true" fill="none">
      <path
        d="M2 6V2h4M14 10v4h-4"
        stroke="currentColor"
        strokeWidth="1.3"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/** ExpandIcon の括弧を内側に寄せた形＝「元に戻す」。 */
function CollapseIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 16 16" aria-hidden="true" fill="none">
      <path
        d="M6 2v4H2M10 14v-4h4"
        stroke="currentColor"
        strokeWidth="1.3"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
