import "server-only";
import type { TextStreamPart, ToolSet } from "ai";

/**
 * 「Streaming は正常終了したのに答えが出ていない」で終わらせないための、streamText の出口の関門。
 *
 * 実測（Workers AI / Kimi K2.6）で見た終わり方は2つあり、どちらも finishReason は "stop" なので
 * エラーにはならず、画面には最後の証跡カードだけが残る:
 *
 * 1. 最終ステップ（route.ts が activeTools: [] でツールを外したステップ）で、モデルがまだツールを
 *    呼びたがり、呼び出しを特殊トークンのまま本文に流す。
 *      …別のツールが使えるか確認します。<|tool_calls_section_begin|><|tool_call_begin|>functions.…
 * 2. 最終ステップで reasoning だけ出し、本文パートを開いて中身ゼロで閉じる。
 *
 * ここでやること:
 * - 1 の生トークンを本文から落とす（利用者はデータ分析の専門家ではない前提。生トークンは見せない）
 * - 最後のステップが「漏れただけ」「空だった」のどちらかなら、打ち切りの注記を本文として足す。
 *   モデルの言い分ではなく機械的な注記なので、文面はここに固定で持つ（注記をサーバ側が付けるのは
 *   caveats と同じ方針）。
 * - 中身ゼロで閉じた本文パートはストリームから落とす。空の本文パートが残っていると、
 *   画面側は「最後は本文で終わっている」と判断してローディングも注記も出さず、無言で止まる。
 */

/** 打ち切りの注記。モデルが最後まで答えなかったときだけ、独立した本文パートとして足す。 */
const CUTOFF_NOTE =
  "（データを調べる回数の上限に達したため、ここで打ち切りました。答えにはたどり着けていません。" +
  "質問を分けて聞くか、もう一度試してください。）";

export function guardAssistantStream<TOOLS extends ToolSet>() {
  return () => {
    /** `<|` を見つけた本文パート以降を捨てているか。ステップの頭で解除する。 */
    let suppressed = false;
    /** チャンク境界で `<` と `|` に割れるので、末尾の `<` は次のチャンクまで持ち越す。 */
    let pending = "";
    let pendingId = "";
    /** 今のステップで生トークンを落としたか／本文が出たか。最後のステップの分だけを見て判定する。 */
    let leakedInStep = false;
    let textInStep = "";
    /**
     * text-start は最初の1文字が実際に出るまで持っておく。中身ゼロのまま text-end が来たら
     * 両方捨てる（空の本文パートを画面に渡さない）。
     */
    let heldTextStart: TextStreamPart<TOOLS> | null = null;

    type Ctl = TransformStreamDefaultController<TextStreamPart<TOOLS>>;

    /** 本文を出す唯一の口。保留してある text-start があればここで先に流す。 */
    const emitText = (controller: Ctl, part: TextStreamPart<TOOLS>, text: string) => {
      if (heldTextStart) {
        controller.enqueue(heldTextStart);
        heldTextStart = null;
      }
      controller.enqueue(part);
      textInStep += text;
    };
    const flushPending = (controller: Ctl) => {
      if (!pending) return;
      emitText(controller, { type: "text-delta", id: pendingId, text: pending } as TextStreamPart<TOOLS>, pending);
      pending = "";
    };
    /**
     * 注記は最後の finish-step の後ろ（finish の直前）に、独立した本文パートとして足す。
     *
     * finish-step を保留してはいけない。ai v7 の streamText は、変換の出口を通った finish-step で
     * ステップの結果を確定させてから次（stopWhen の判定・finish）に進むので、ここで止めると
     * 上流が先に進めず、本文が出きったところでストリームが閉じも終わりもしなくなる
     * （Workers では「code had hung」で打ち切られ、finish が届かない）。
     */
    const emitCutoffNote = (controller: Ctl) => {
      // 最後のステップが答えになっていない（ツールを呼ぼうとして終わった／本文が空）ときだけ。
      if (!leakedInStep && textInStep.trim()) return;
      const id = "cutoff-note";
      controller.enqueue({ type: "text-start", id } as TextStreamPart<TOOLS>);
      controller.enqueue({ type: "text-delta", id, text: CUTOFF_NOTE } as TextStreamPart<TOOLS>);
      controller.enqueue({ type: "text-end", id } as TextStreamPart<TOOLS>);
    };

    return new TransformStream<TextStreamPart<TOOLS>, TextStreamPart<TOOLS>>({
      transform(part, controller) {
        if (part.type === "text-delta") {
          if (suppressed) return;
          pendingId = part.id;
          let text = pending + part.text;
          pending = "";

          const cut = text.indexOf("<|");
          if (cut >= 0) {
            suppressed = true;
            leakedInStep = true;
            // 起きたこと自体は運用上知りたい（モデルやゲートウェイを差し替えた直後の切り分けに要る）。
            console.warn("[ai/stream-guard] ツール呼び出しの生トークンを本文から除去:", text.slice(cut, cut + 120));
            text = text.slice(0, cut);
          } else if (text.endsWith("<")) {
            pending = "<";
            text = text.slice(0, -1);
          }

          if (text) emitText(controller, { ...part, text }, text);
          return;
        }

        flushPending(controller);

        if (part.type === "text-start") {
          heldTextStart = part;
          return;
        }
        if (part.type === "text-end") {
          // 1文字も出ないまま閉じた本文パートは、text-start ごと捨てる。
          if (heldTextStart) {
            heldTextStart = null;
            return;
          }
          controller.enqueue(part);
          return;
        }
        if (part.type === "start-step") {
          suppressed = false;
          leakedInStep = false;
          textInStep = "";
          controller.enqueue(part);
          return;
        }
        if (part.type === "finish") {
          emitCutoffNote(controller);
          controller.enqueue(part);
          return;
        }
        controller.enqueue(part);
      },
      flush(controller) {
        flushPending(controller);
        heldTextStart = null;
      },
    });
  };
}
