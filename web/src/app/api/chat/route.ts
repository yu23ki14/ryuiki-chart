import { NextRequest, NextResponse } from "next/server";
import { streamText, convertToModelMessages, stepCountIs, createUIMessageStreamResponse, toUIMessageStream, type UIMessage } from "ai";
import { getModel, isAiConfigured } from "@/lib/ai/provider";
import { buildSystemPrompt, FINAL_STEP_NOTE, FINAL_STEP_USER_NUDGE } from "@/lib/ai/prompt";
import { aiTools } from "@/lib/ai/tools";
import { guardAssistantStream } from "@/lib/ai/stream-guard";
import type { PageContext } from "@/lib/ai/page-context";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 120;

/**
 * ツール呼び出しの往復の上限。最後の1回は「ツール無しで答えを書く」ために予約するので、
 * 実際にツールを呼べるのは MAX_STEPS - 1 回（= 7回）。
 *
 * 以前は 5 だった。5回とも探索に使い切ると本文が1文字も出ないまま stream が正常終了し、
 * 画面には最後の証跡カードだけが残って「Done なのに答えが出ない」状態になっていた
 * （実測: 「生物種が多い流域は？」→ get_overview 1回 + describe_schema 4回で打ち切り）。
 * 予約の分だけ探索に使える回数が減るので、その埋め合わせも兼ねて上限自体を上げてある。
 */
const MAX_STEPS = 8;

interface ChatRequestBody {
  messages?: UIMessage[];
  /** 今どの画面で何を見ているか。AssistantPanel が送信のたびに乗せる（状態のみ・データは含まない）。 */
  pageContext?: PageContext;
}

export async function POST(req: NextRequest) {
  if (!isAiConfigured()) {
    return NextResponse.json(
      { error: "AI が未設定です。管理者に AI Gateway の環境変数（AI_GATEWAY_ACCOUNT_ID / AI_GATEWAY_TOKEN）の設定を依頼してください。" },
      { status: 503 },
    );
  }

  let body: ChatRequestBody;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "JSON ボディが必要です" }, { status: 400 });
  }
  const messages = body.messages ?? [];

  const instructions = buildSystemPrompt(body.pageContext);

  const result = streamText({
    model: getModel(),
    instructions,
    messages: await convertToModelMessages(messages),
    tools: aiTools,
    // 多段ツール呼び出しはレイテンシと課金の上限として MAX_STEPS ステップで打ち切る
    stopWhen: stepCountIs(MAX_STEPS),
    // 最後の1ステップはツールを外し、「ここまでの結果で答える」だけに使う。
    //
    // stopWhen だけだと、上限に達したステップがツール呼び出しで終わったときに
    // 本文が無いまま正常終了してしまう（利用者からは固まったように見える）。
    // ツールを外しておけばモデルは文章を書くしかなく、探索が実らなかったときでも
    // 「何を探して何が無かったか」が必ず残る。
    //
    // toolChoice: "none" ではなく activeTools: [] を使う。openai-compatible の prepareTools は
    // 前者だと tools を送ったまま tool_choice だけ付けるのに対し、後者は tools ごと落とすので、
    // リクエストにツールが1つも乗らない。実測ではどちらでもモデルが呼び出しを本文に漏らすことが
    // あったが（stream-guard.ts で拾う）、送らない方が一段確実。
    prepareStep: ({ stepNumber, messages: stepMessages }) =>
      stepNumber === MAX_STEPS - 1
        ? {
            activeTools: [],
            instructions: `${instructions}\n\n${FINAL_STEP_NOTE}`,
            // システムプロンプトへの追記だけだと Kimi は無視してツールを呼び続ける。
            // 直近の発言として同じ指示をもう一度積む（根拠は FINAL_STEP_USER_NUDGE のコメント）。
            messages: [...stepMessages, { role: "user" as const, content: FINAL_STEP_USER_NUDGE }],
          }
        : undefined,
    // 最終ステップを予約しても、モデルが答えずに終わることが実測である（呼び出しの生トークンを
    // 本文に流す／本文が空のまま閉じる）。その2つを潰して「無言で終わらない」を保証する。
    experimental_transform: guardAssistantStream<typeof aiTools>(),
  });

  return createUIMessageStreamResponse({
    stream: toUIMessageStream({
      stream: result.stream,
      tools: aiTools,
      // 既定では詳細を伏せて "An error occurred." だけが出る。資格情報の設定直後は
      // ゲートウェイの 401/404 とモデル側のエラーを切り分けられないと詰まるので、
      // 由来が分かる範囲だけ日本語で返す。
      onError: (error) => {
        const msg = error instanceof Error ? error.message : String(error);
        console.error("[api/chat]", msg);
        if (/401|403|unauthor|forbidden/i.test(msg)) {
          return "AI Gateway の認証に失敗しました。AI_GATEWAY_TOKEN を確認してください。";
        }
        if (/404|not found/i.test(msg)) {
          return `AI Gateway のエンドポイントかモデル名が見つかりません。AI_GATEWAY_ACCOUNT_ID / AI_GATEWAY_NAME / AI_MODEL（現在: ${process.env.AI_MODEL || "既定値"}）を確認してください。`;
        }
        return `AI の呼び出しでエラーが発生しました: ${msg}`;
      },
    }),
  });
}
