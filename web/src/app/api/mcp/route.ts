import { NextRequest, NextResponse } from "next/server";
import { MCP_ENABLED, MCP_RATE_LIMIT } from "@/lib/features";
import { getRateLimiter, originAllowed, readBodyLimited, withinRateLimit } from "@/lib/mcp/guard";
import { d1CubeDb } from "@/lib/cube";
import { handleBody, RPC_ERRORS } from "@/lib/mcp/server";

/**
 * MCP サーバ（Streamable HTTP、ステートレス・JSON 応答。ADR-0014 の第1段）。
 * `MCP_ENABLED`（`lib/features.ts`）が false なら 404（存在しないものとして扱う）。
 */
export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const MAX_BODY_BYTES = 64 * 1024;

const notFound = () => NextResponse.json({ error: "Not Found" }, { status: 404 });
const rpcFail = (status: number, code: number, message: string, headers?: Record<string, string>) =>
  NextResponse.json({ jsonrpc: "2.0", id: null, error: { code, message } }, { status, headers });
const tooLarge = () => rpcFail(413, RPC_ERRORS.invalidRequest, "本文が大きすぎる");

export async function POST(req: NextRequest) {
  if (!MCP_ENABLED) return notFound();
  if (!originAllowed(req.headers.get("origin"))) return rpcFail(403, RPC_ERRORS.invalidRequest, "許可されていない Origin");
  if (!(await withinRateLimit(await getRateLimiter(), req.headers.get("cf-connecting-ip")))) {
    return rpcFail(429, RPC_ERRORS.invalidRequest, "リクエストが多すぎる。しばらく待ってから再試行して", { "Retry-After": String(MCP_RATE_LIMIT.periodSeconds) });
  }

  const text = await readBodyLimited(req, MAX_BODY_BYTES);
  if (text === null) return tooLarge();
  let body: unknown;
  try {
    body = JSON.parse(text);
  } catch {
    return rpcFail(400, RPC_ERRORS.parse, "JSON として読めない");
  }

  const out = await handleBody(body, { db: d1CubeDb });
  return out === null ? new NextResponse(null, { status: 202 }) : NextResponse.json(out);
}

/** サーバ発の SSE ストリームは持たない（仕様上 405 でよい）。 */
export async function GET() {
  if (!MCP_ENABLED) return notFound();
  return new NextResponse(null, { status: 405, headers: { Allow: "POST" } });
}

export async function DELETE() {
  if (!MCP_ENABLED) return notFound();
  return new NextResponse(null, { status: 405, headers: { Allow: "POST" } });
}
