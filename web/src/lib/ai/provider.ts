import "server-only";
import { createOpenAICompatible } from "@ai-sdk/openai-compatible";
import type { LanguageModel } from "ai";

/**
 * Cloudflare AI Gateway の OpenAI 互換エンドポイント（.../compat）に向けるだけの薄いラッパー。
 * モデルの差し替えが env 1個（AI_MODEL）で済むこと以外の抽象は作らない。
 *
 * 認証は cf-aig-authorization ヘッダで行う（AI Gateway 自体の認証）。
 * apiKey オプションだけだと Authorization ヘッダにしかならずゲートウェイ認証を通らないため、
 * 同じトークンを headers 経由でも渡す。
 */

const DEFAULT_MODEL = "workers-ai/@cf/moonshotai/kimi-k2.6";

export function isAiConfigured(): boolean {
  return Boolean(process.env.AI_GATEWAY_ACCOUNT_ID && process.env.AI_GATEWAY_TOKEN);
}

export function getModel(): LanguageModel {
  const accountId = process.env.AI_GATEWAY_ACCOUNT_ID;
  const gateway = process.env.AI_GATEWAY_NAME || "default";
  const token = process.env.AI_GATEWAY_TOKEN;
  const modelId = process.env.AI_MODEL || DEFAULT_MODEL;

  if (!accountId || !token) {
    throw new Error(
      "AI Gateway が未設定（AI_GATEWAY_ACCOUNT_ID / AI_GATEWAY_TOKEN）。呼び出し側で isAiConfigured() を先に見ること。",
    );
  }

  const provider = createOpenAICompatible({
    name: "cloudflare-ai-gateway",
    baseURL: `https://gateway.ai.cloudflare.com/v1/${accountId}/${gateway}/compat`,
    apiKey: token,
    headers: { "cf-aig-authorization": `Bearer ${token}` },
  });

  return provider(modelId);
}
