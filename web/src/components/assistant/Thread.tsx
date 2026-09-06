"use client";

import * as React from "react";
import {
  ThreadPrimitive,
  ComposerPrimitive,
  MessagePrimitive,
  type EmptyMessagePartProps,
  type ReasoningMessagePartProps,
} from "@assistant-ui/react";
import { ToolResultCard } from "./tool-ui/ToolResultCard";
import { SeriesChartCard } from "./tool-ui/SeriesChartCard";
import { MarkdownText } from "./MarkdownText";
import { usePageContextSnapshot } from "./PageContextProvider";
import { suggestedQuestions } from "@/lib/ai/page-context";

/**
 * assistant-ui のプリミティブに globals.css のトークンで薄くスタイルを当てたもの。
 * `npx assistant-ui init` の shadcn 系コンポーネントは生成していない
 * （この repo は --ink / --line / --water / --surface という独自トークンで、shadcn の
 * bg-background 等は存在しないため）。
 */
export function Thread() {
  return (
    <ThreadPrimitive.Root className="flex h-full flex-col min-h-0">
      <ThreadPrimitive.Viewport className="flex-1 min-h-0 overflow-y-auto thin-scroll px-3 py-3">
        {/* 読みやすい行長の上限。パネルが 420px の通常時はこの max-w が常に無効（パネルの方が
            狭い）なので見た目は変わらない。AssistantPanel の全画面モード（1400px 級）で初めて
            効いてきて、中央に幅 900px の読み物カラムを作る。Thread 自身は自分が全画面かどうかを
            知らなくてよい（AssistantPanel 側は aside の className を切り替えるだけで、この
            コンポーネントごとアンマウントすることはない）。 */}
        <div className="flex flex-col gap-3 w-full max-w-[900px] mx-auto">
          <ThreadPrimitive.Empty>
            <EmptyState />
          </ThreadPrimitive.Empty>
          <ThreadPrimitive.Messages>
            {({ message }) => (message.role === "user" ? <UserMessage /> : <AssistantMessage />)}
          </ThreadPrimitive.Messages>
        </div>
      </ThreadPrimitive.Viewport>
      <Composer />
    </ThreadPrimitive.Root>
  );
}

/**
 * 「何を聞けばいいか分からない」への最小対応。ハードコードの固定文言ではなく、
 * 今の画面（PageContext）の実際の値（選択中の項目名・水域名・地点名）を埋め込んだ質問例を出す。
 * 値が無い画面（トップページなど）では一般的な例に落ちる（suggestedQuestions 側の責務）。
 */
function EmptyState() {
  const pageContext = usePageContextSnapshot();
  const questions = suggestedQuestions(pageContext);
  return (
    <div className="text-[12px] text-muted leading-relaxed py-6">
      <p className="mb-2">流域カルテのデータについて聞いてください。例えば:</p>
      <ul className="space-y-1 list-disc list-inside">
        {questions.map((q) => (
          <li key={q}>{q}</li>
        ))}
      </ul>
    </div>
  );
}

/**
 * min-w-0 の理由（表がパネルの右にはみ出すバグの本体）:
 * Viewport は縦フレックス（flex flex-col）で、このメッセージ Root は ml-auto/mr-auto を
 * 持つそのフレックスアイテム。交差軸（横）に auto マージンがあるアイテムは align-items:stretch
 * が効かず、fit-content で幅が決まる——ml-auto/mr-auto は「短い発言は内容の幅だけの吹き出しに
 * なる」ためにわざと使っている（UserMessage が短文で右端にぴったり張り付く小さな吹き出しに
 * なるのはこの仕組みのおかげ）。
 * fit-content は自分の min-content を下回れない。フレックスアイテムの min-width の既定値は
 * auto で、これは「自動最小サイズ」＝ここでは中身（＝子孫の min-content）に連動する
 * （overflow が visible でないフレックスアイテム自身なら自動的に 0 になるが、この Root 自身は
 * overflow を指定していないので該当しない）。表（MdTable の table 要素、th に
 * whitespace-nowrap）は改行できない列見出しを持つため min-content が大きく、それがそのまま
 * この Root の min-width になって max-w-[94%] を超えて右にはみ出していた。
 * min-w-0 を明示すると「自動最小サイズ」の代わりに 0 が使われ、fit-content の下限が消える。
 * 結果として Root の実寸は clamp(0, 利用可能幅, max-w) に収まり、その中の MdTable の
 * div.overflow-x-auto（普通のブロック要素で shrink-to-fit ではないので Root の実寸をそのまま
 * 継承する）が初めて意図通り横スクロールする。対症療法の overflow-x:hidden ではなく、
 * はみ出しの発生源（Root の暗黙の最小幅）を直接消しているだけなので、表自体は自分の箱の中で
 * 横スクロールできるまま。
 */
/**
 * overflow-wrap:anywhere は min-w-0 と対で要る。min-w-0 でバブルが中身より狭くなれるように
 * なったので、折り返せない長い文字列（貼り付けた URL など）を入れると文字がバブルから溢れる。
 * アシスタント側は MarkdownText のコンテナが同じ指定を持っている。
 */
function UserMessage() {
  return (
    <MessagePrimitive.Root className="max-w-[90%] ml-auto min-w-0 rounded-lg bg-water text-white px-3 py-2 text-[12.5px] leading-relaxed [overflow-wrap:anywhere]">
      <MessagePrimitive.Parts />
    </MessagePrimitive.Root>
  );
}

function AssistantMessage() {
  return (
    <MessagePrimitive.Root className="max-w-[94%] mr-auto min-w-0 text-[12.5px] leading-relaxed">
      {/* get_timeseries だけ専用のチャートカード。他の9ツールは今まで通り ToolResultCard（Fallback）。
          Text は素のまま出すとモデルの Markdown が地の文で出てしまうので MarkdownText を差す。
          Empty/Reasoning は送信後の空白（本文がまだ無い・reasoning しか届いていない）を
          スピーチバブル型のローディング表示で埋める。本文（Text）が届いた瞬間に自動で消える。
          詳しい根拠は ThinkingBubble のコメント参照。 */}
      <MessagePrimitive.Parts
        components={{
          Text: MarkdownText,
          Reasoning: ReasoningThinkingBubble,
          Empty: EmptyThinkingBubble,
          tools: { by_name: { get_timeseries: SeriesChartCard }, Fallback: ToolResultCard },
        }}
      />
      <MessagePrimitive.Error>
        <p className="text-[11.5px] text-bad mt-1">エラーが発生しました。もう一度試してください。</p>
      </MessagePrimitive.Error>
    </MessagePrimitive.Root>
  );
}

/**
 * レスポンス待ちのスピーチバブル。assistant-ui の2つのフックポイントに刺している。
 * node_modules/@assistant-ui/core/dist/react/primitives/message/MessageParts.js
 * （MessagePrimitivePartsCompat / ConditionalEmpty / EmptyParts）を実測して配線した。
 *
 * - Empty スロット: パートが1つも無い間（送信直後）と、最後のパートが text/reasoning 以外
 *   （＝ツール呼び出しで終わっている間。実行中もツール完了後の次の一手待ちも含む）に自動で
 *   出る（`unstable_showEmptyOnNonTextEnd` は既定 true のまま触っていない）。
 * - Reasoning スロット: Kimi は本文より先に reasoning チャンクを流してくる。reasoning パートは
 *   Empty 側の「text/reasoning は空扱いしない」判定に引っかかって Empty が発火しないため、
 *   Empty だけでは reasoning 中の空白はカバーできない。reasoning パート自身の status が
 *   running の間だけ出し、reasoning が終わって次のパート（本文かツール）が始まった瞬間に消す。
 *
 * ツール実行中は ToolResultCard/SeriesChartCard 自身の Spinner と一緒に出ることがある
 * （Empty 側にはそのツール呼び出しが実行中か完了直後かを区別する情報が来ない。メッセージ全体の
 * status しか分からない）。無理に出し分けようとすると MessagePrimitive.Parts の内部実装に
 * 踏み込むことになり、既存のツール振り分けを壊すリスクの方が大きいと判断し、そのままにした。
 */
function EmptyThinkingBubble({ status }: EmptyMessagePartProps) {
  if (status.type === "running") return <ThinkingBubble />;
  // 停止ボタンで切ったときは利用者が自分で止めたと分かっているので、何も足さない。
  if (status.type === "incomplete" && status.reason === "cancelled") return null;
  // ここに来るのは「ツール呼び出しで終わったまま応答が完了した」ケース。
  // route.ts の最終ステップ予約と stream-guard.ts の打ち切り注記で通常は起きないが、
  // 通信が途中で切れたときなどに残る最後の受け皿として、無言で終わらせない。
  return (
    <p className="text-[11.5px] text-muted mt-1">
      応答が途中で終わってしまいました。ここまでの証跡は上に残っています。もう一度聞いてみてください。
    </p>
  );
}

function ReasoningThinkingBubble({ status }: ReasoningMessagePartProps) {
  if (status?.type !== "running") return null;
  return <ThinkingBubble />;
}

/** UserMessage（bg-water・右寄せ）の対になる、左寄せ・bg-surface-2 のスピーチバブル。
 *  中身は3点ドットのアニメーション（globals.css の loading-dots）。会議用の書き出しには
 *  不要なので no-print を付ける。 */
function ThinkingBubble() {
  return (
    <div
      role="status"
      aria-live="polite"
      className="no-print inline-flex items-center gap-1.5 rounded-lg border border-line bg-surface-2 px-3 py-2"
    >
      <span className="sr-only">回答を生成中…</span>
      <span className="loading-dots" aria-hidden="true">
        <span />
        <span />
        <span />
      </span>
    </div>
  );
}

/** Btn（ui.tsx）は forwardRef していないので ComposerPrimitive.Send の asChild には使わず、
 *  同じ見た目をここで直接クラスにして当てる。 */
const sendBtnCls =
  "shrink-0 text-[12px] px-3 py-1.5 rounded border whitespace-nowrap transition-colors disabled:opacity-40 disabled:cursor-not-allowed bg-water text-white border-water hover:brightness-110";
const cancelBtnCls =
  "shrink-0 text-[12px] px-3 py-1.5 rounded border whitespace-nowrap transition-colors bg-surface border-line hover:bg-surface-2 text-ink-2";

function Composer() {
  return (
    <ComposerPrimitive.Root className="no-print shrink-0 border-t border-line p-2.5 flex items-end gap-2">
      <ComposerPrimitive.Input
        placeholder="データについて質問する…"
        rows={1}
        autoFocus
        className="flex-1 resize-none max-h-32 text-[12px] px-2 py-1.5 rounded border border-line bg-surface focus:outline-none focus:ring-2 focus:ring-water/30 focus:border-water"
      />
      <ThreadPrimitive.If running={false}>
        <ComposerPrimitive.Send className={sendBtnCls}>送信</ComposerPrimitive.Send>
      </ThreadPrimitive.If>
      <ThreadPrimitive.If running>
        <ComposerPrimitive.Cancel className={cancelBtnCls}>停止</ComposerPrimitive.Cancel>
      </ThreadPrimitive.If>
    </ComposerPrimitive.Root>
  );
}
