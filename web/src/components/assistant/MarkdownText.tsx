"use client";

import * as React from "react";
import Link from "next/link";
import remarkGfm from "remark-gfm";
import { MarkdownTextPrimitive, useIsMarkdownCodeBlock } from "@assistant-ui/react-markdown";

/**
 * モデル回答（Markdown）のレンダラ。Thread.tsx の AssistantMessage で
 * `<MessagePrimitive.Parts components={{ Text: MarkdownText, tools: {...} }} />` として
 * Text スロットに差す。UserMessage 側（利用者の入力）はこれを使わず素のテキストのまま。
 *
 * react-markdown を直接使わず `@assistant-ui/react-markdown` の MarkdownTextPrimitive を
 * 経由する理由: ストリーミング中の未確定な Markdown（閉じていない ** や表の途中行）を
 * トークンが届くたびに再パースしても崩れて見えないよう、内部で平滑化・差分描画をしている
 * ため（`smooth` は既定 true のまま使う）。
 *
 * ここでも `npx assistant-ui init` の shadcn 系コンポーネントは生成していない。
 * globals.css の独自トークン（--ink / --line / --surface-2 / --water-ink 等）に
 * Tailwind ユーティリティで直接当てる、他のコンポーネントと同じ書き方に揃えている。
 */
export function MarkdownText() {
  return (
    <MarkdownTextPrimitive
      remarkPlugins={remarkPlugins}
      components={components}
      className="block [&>*:first-child]:mt-0 [&>*:last-child]:mb-0 [overflow-wrap:anywhere]"
    />
  );
}

// remarkGfm は表（| --- |）・取り消し線・タスクリストに要る。モデルは表をよく出すので必須。
// 配列を毎レンダー生成しないよう固定参照にする（react-markdown 側は plugins の同一性で
// 再パースの要否を見ている）。
const remarkPlugins = [remarkGfm];

type Props<Tag extends keyof React.JSX.IntrinsicElements> = React.ComponentPropsWithoutRef<Tag> & {
  // react-markdown は各要素に対応する hast ノードを node として渡してくる。
  node?: unknown;
};

/** DOM 要素にそのまま spread すると "Unknown prop `node`" 警告になるので落とす
 *  （@assistant-ui/react-markdown の DefaultPre/DefaultCode と同じ作法）。分割代入で
 *  `node` を名前付きの未使用変数にすると eslint の no-unused-vars に毎回引っかかるので
 *  一箇所にまとめている。 */
function omitNode<P extends { node?: unknown }>(props: P): Omit<P, "node"> {
  const rest: Partial<P> = { ...props };
  delete rest.node;
  return rest as Omit<P, "node">;
}

/**
 * 固定クラスだけを当てる要素用のファクトリ。
 *
 * 罠: pre/code は @assistant-ui/react-markdown 側が「コードブロックかどうか」の判定用に
 * 元の pre 要素の props（className を含む。値が無ければ空文字）をいったん捕まえておき、
 * 実際に <Pre> を呼ぶときにそれを渡してくる。`<pre className="固定" {...props} />` の並びで
 * 書くと props 側の className（空文字）が後勝ちで固定クラスを消してしまう
 * （このバグは実際に踏んだ: コードブロックの枠線が全部消えていた）。
 * ここでは props を先に展開し、className を必ず後ろに置くことで自分のクラスを勝たせる。
 */
function styled<Tag extends keyof React.JSX.IntrinsicElements>(tag: Tag, className: string) {
  return function StyledMd(props: Props<Tag>) {
    return React.createElement(tag, { ...omitNode(props), className });
  };
}

const MdH1 = styled("h1", "mt-3 mb-1.5 text-[14px] font-bold text-ink");
const MdH2 = styled("h2", "mt-3 mb-1.5 text-[13.5px] font-bold text-ink");
const MdH3 = styled("h3", "mt-2.5 mb-1 text-[13px] font-semibold text-ink");
const MdH4 = styled("h4", "mt-2 mb-1 text-[12.5px] font-semibold text-ink-2");
const MdP = styled("p", "my-1.5 leading-relaxed");
const MdUl = styled("ul", "my-1.5 pl-4 list-disc space-y-0.5");
const MdOl = styled("ol", "my-1.5 pl-4 list-decimal space-y-0.5");
const MdLi = styled("li", "leading-relaxed");
const MdStrong = styled("strong", "font-semibold text-ink");
const MdEm = styled("em", "italic");
const MdBlockquote = styled("blockquote", "my-1.5 border-l-2 border-line-strong pl-2.5 text-ink-2 italic");
const MdHr = styled("hr", "my-2.5 border-line");
const MdTableInner = styled("table", "w-max min-w-full border-collapse text-[11.5px]");
const MdThead = styled("thead", "bg-surface-2");
const MdTr = styled("tr", "border-b border-line last:border-b-0");
const MdTh = styled("th", "whitespace-nowrap border-b border-line-strong px-2 py-1 text-left font-semibold text-ink-2");
const MdTd = styled("td", "px-2 py-1 align-top");
const MdPre = styled(
  "pre",
  "my-1.5 overflow-x-auto rounded border border-line bg-surface-2 p-2 text-[11px] leading-snug thin-scroll",
);

/** 表は 420px 幅のパネルに対して確実にはみ出す。box 自体を overflow-x: auto にして、
 *  パネル全体（ThreadPrimitive.Viewport）が横に押し広げられないようにする。 */
function MdTable(props: Props<"table">) {
  return (
    <div className="my-2 overflow-x-auto rounded border border-line thin-scroll">
      <MdTableInner {...props} />
    </div>
  );
}

/** 外部 URL は新規タブ + noopener noreferrer。`/` から始まる内部ディープリンクは
 *  next/link で SPA 内遷移にする（ToolResultCard の「この SQL をデータ探索で開く →」と同じ作法。
 *  アシスタントパネルは layout.tsx 常駐のオーバーレイなので、フルリロードにすると
 *  useChatRuntime の会話状態が消える）。
 *  モデル自身が set_view の類を持たない設計（memory 参照）なので、内部リンクを本文中の
 *  Markdown リンクとして出すのは主にツール結果のプロヴェナンスの引用文くらいの想定だが、
 *  どちらが来ても壊れないようにしておく。 */
function MdA(props: Props<"a">) {
  const { href, children, ...rest } = omitNode(props);
  const linkCls = "text-water-ink underline decoration-dotted underline-offset-2";
  if (href && href.startsWith("/")) {
    return (
      <Link href={href} {...rest} className={linkCls}>
        {children}
      </Link>
    );
  }
  return (
    <a href={href} {...rest} target="_blank" rel="noopener noreferrer" className={linkCls}>
      {children}
    </a>
  );
}

/** インライン code と、コードブロック内の code は同じ `code` タグ経由で来る
 *  （react-markdown v9 以降は `inline` プロパティが無い）。@assistant-ui/react-markdown が
 *  Pre の中かどうかをコンテキストで教えてくれるので、それで出し分ける。 */
function MdCode(props: Props<"code">) {
  const { className, ...rest } = omitNode(props);
  const isBlock = useIsMarkdownCodeBlock();
  if (isBlock) return <code {...rest} className={`font-mono ${className ?? ""}`} />;
  return <code {...rest} className="rounded bg-surface-2 px-1 py-0.5 font-mono text-[11px]" />;
}

const components = {
  h1: MdH1,
  h2: MdH2,
  h3: MdH3,
  h4: MdH4,
  p: MdP,
  ul: MdUl,
  ol: MdOl,
  li: MdLi,
  strong: MdStrong,
  em: MdEm,
  blockquote: MdBlockquote,
  hr: MdHr,
  table: MdTable,
  thead: MdThead,
  tr: MdTr,
  th: MdTh,
  td: MdTd,
  a: MdA,
  code: MdCode,
  pre: MdPre,
};
