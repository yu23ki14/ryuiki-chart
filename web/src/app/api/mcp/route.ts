import { NextRequest, NextResponse } from "next/server";
import { MCP_ENABLED } from "@/lib/features";
import { d1CubeDb } from "@/lib/cube";
import { handleBody, RPC_ERRORS } from "@/lib/mcp/server";

/**
 * MCP サーバ（Streamable HTTP、ステートレス・JSON 応答。ADR-0014 の第1段）。
 * `MCP_ENABLED`（`lib/features.ts`）が false の間は 404（存在しないものとして扱う）。
 */
export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const MAX_BODY_BYTES = 64 * 1024;

const notFound = () => NextResponse.json({ error: "Not Found" }, { status: 404 });

/** DNS リバインディング対策（MCP 仕様）: Origin があるなら Host と同じものだけ受ける。MCP クライアントは通常 Origin を付けない。 */
function originAllowed(req: NextRequest): boolean {
  const origin = req.headers.get("origin");
  if (!origin) return true;
  try {
    return new URL(origin).host === req.headers.get("host");
  } catch {
    return false;
  }
}

export async function POST(req: NextRequest) {
  if (!MCP_ENABLED) return notFound();
  if (!originAllowed(req)) return NextResponse.json({ error: "Forbidden origin" }, { status: 403 });

  const text = await req.text();
  if (new TextEncoder().encode(text).length > MAX_BODY_BYTES) {
    return NextResponse.json({ jsonrpc: "2.0", id: null, error: { code: RPC_ERRORS.invalidRequest, message: "本文が大きすぎる" } }, { status: 413 });
  }
  let body: unknown;
  try {
    body = JSON.parse(text);
  } catch {
    return NextResponse.json({ jsonrpc: "2.0", id: null, error: { code: RPC_ERRORS.parse, message: "JSON として読めない" } }, { status: 400 });
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
