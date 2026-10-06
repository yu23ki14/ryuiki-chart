/**
 * `/api/mcp` の入口の守り（Origin・レート制限・本文サイズ）。route.ts は Next の制約で export を増やせないので
 * ここに置いてテストする。
 */
import { getCloudflareContext } from "@opennextjs/cloudflare";
import { MCP_ALLOWED_ORIGIN_HOSTS } from "@/lib/features";

/**
 * Origin の許可リスト。Origin ヘッダが無いもの（Claude Desktop / Claude Code などブラウザ以外）は通す。
 * あるものは、ホスト名が許可リストにあるときだけ通す（`Origin: null` や別サイトのページからの呼び出しは弾く）。
 * 注意: これはブラウザ経由の呼び出しを絞るもので、認証ではない（ブラウザ以外は Origin を偽れる）。
 * Origin と Host の一致比較は DNS リバインディング対策にならない（攻撃者のドメインは Origin も Host も攻撃者のものになる）ので使わない。
 */
export function originAllowed(origin: string | null): boolean {
  if (!origin) return true;
  try {
    const host = new URL(origin).hostname.toLowerCase();
    return (MCP_ALLOWED_ORIGIN_HOSTS as readonly string[]).includes(host);
  } catch {
    return false;
  }
}

/** Cloudflare Rate Limiting バインディングの最小形。 */
export interface RateLimiter {
  limit(opts: { key: string }): Promise<{ success: boolean }>;
}

let warned = false;

/** バインディングを引く。無い環境（vitest・素の dev）は null。本番ビルドで無いときは1度だけ error ログ。 */
export async function getRateLimiter(): Promise<RateLimiter | null> {
  let limiter: RateLimiter | undefined;
  try {
    const { env } = await getCloudflareContext({ async: true });
    limiter = (env as { MCP_RATE_LIMITER?: RateLimiter }).MCP_RATE_LIMITER;
  } catch {
    limiter = undefined;
  }
  if (!limiter && process.env.NODE_ENV === "production" && !warned) {
    warned = true;
    console.error("MCP_RATE_LIMITER バインディングが無い。/api/mcp のレート制限が効いていない（wrangler.jsonc の ratelimits を確認）");
  }
  return limiter ?? null;
}

/** 超過なら false。limiter が無ければ素通し。キーが取れないとき（ローカル等）は共有キーで数える。 */
export async function withinRateLimit(limiter: RateLimiter | null, ip: string | null): Promise<boolean> {
  if (!limiter) return true;
  try {
    return (await limiter.limit({ key: ip || "unknown" })).success;
  } catch (e) {
    // 制限器の障害で MCP 全体を落とさない（開く側に倒す）。
    console.error("mcp rate limiter failed", e);
    return true;
  }
}

/** 本文をストリームで読み、`maxBytes` を超えた時点で打ち切る（Content-Length 無し・chunked でも効く）。超過は null。 */
export async function readBodyLimited(req: Request, maxBytes: number): Promise<string | null> {
  if (Number(req.headers.get("content-length") ?? 0) > maxBytes) return null;
  if (!req.body) return "";
  const reader = req.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    total += value.byteLength;
    if (total > maxBytes) {
      await reader.cancel();
      return null;
    }
    chunks.push(value);
  }
  const buf = new Uint8Array(total);
  let off = 0;
  for (const c of chunks) {
    buf.set(c, off);
    off += c.byteLength;
  }
  return new TextDecoder().decode(buf);
}
