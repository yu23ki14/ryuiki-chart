/**
 * Workers AI（`AI`）と Vectorize（`VECTORIZE`）のバインディングの取り出し口（1か所）。
 * 設計: docs/plans/TATSUGO_KOHO_VECTOR.md §2.3・§6.2。
 *
 * 無い・接続できないときは null（検索だけ無効にして他は動かす）。ローカル（`next dev`）は既定でリモートのバインディングを
 * 張らない（next.config.ts。未ログインでも起動できるように）ので、`RYUIKI_REMOTE_BINDINGS=1` でなければ無効扱いにする。
 */
import { getCloudflareContext } from "@opennextjs/cloudflare";
import { VECTOR_SEARCH_ENABLED } from "@/lib/features";
import config from "./config.json";

export interface VectorMatch {
  id: string;
  score: number;
  metadata?: Record<string, string | number | boolean | null | undefined>;
}

/** Vectorize の `query` のうち使う部分（テストで偽物に差し替える）。 */
export interface VectorIndexLike {
  query(
    vector: number[],
    options: { topK: number; returnMetadata: "all" | "indexed" | "none"; filter?: Record<string, unknown> },
  ): Promise<{ matches: VectorMatch[] }>;
}

/** Workers AI の `run` のうち使う部分。bge-m3 は `{ text: string[] }` → `{ data: number[][] }`。 */
export interface AiLike {
  run(model: string, input: { text: string[] }): Promise<unknown>;
}

export interface VectorBindings {
  ai: AiLike;
  index: VectorIndexLike;
}

export const VECTOR_CONFIG = config;

export function embeddingFromAiResult(res: unknown): number[] {
  const data = (res as { data?: unknown } | null)?.data;
  const first = Array.isArray(data) ? data[0] : null;
  if (!Array.isArray(first) || first.length !== config.dimensions) {
    throw new Error(`埋め込みの形が想定外（期待 ${config.dimensions} 次元）`);
  }
  return first as number[];
}

/** 質問を埋め込む（モデルの指示文 query_prefix を付ける）。 */
export async function embedQuery(ai: AiLike, text: string): Promise<number[]> {
  return embeddingFromAiResult(await ai.run(config.model, { text: [config.query_prefix + text] }));
}

export async function getVectorBindings(): Promise<VectorBindings | null> {
  if (!VECTOR_SEARCH_ENABLED) return null;
  if (process.env.NODE_ENV === "development" && process.env.RYUIKI_REMOTE_BINDINGS !== "1") return null;
  try {
    const { env } = await getCloudflareContext({ async: true });
    const e = env as unknown as { AI?: AiLike; VECTORIZE?: VectorIndexLike };
    if (!e.AI || !e.VECTORIZE) return null;
    return { ai: e.AI, index: e.VECTORIZE };
  } catch {
    return null;
  }
}
