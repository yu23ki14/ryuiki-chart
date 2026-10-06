/**
 * MCP（Model Context Protocol）の最小実装: Streamable HTTP の「ステートレス・JSON 応答」モード。
 *
 * 公式 SDK（`@modelcontextprotocol/sdk` 1.32、展開 4.5MB、依存 17 件に express・hono・ajv・jose を含む）は
 * Workers のバンドルに載せる重さではないので、必要な JSON-RPC だけを自前で持つ
 * （initialize / ping / tools/list / tools/call と通知の受領）。ツール定義は SDK 非依存
 * （`tools.ts`）なので、後で SDK に差し替えても定義はそのまま使える。
 *
 * 対応しないもの: セッション（Mcp-Session-Id を発行しない）、SSE ストリーム（GET は 405）、
 * resources/prompts/sampling。サーバから始まるメッセージが無いので不要。
 */
import { z } from "zod";
import { MCP_TOOLS, McpInputError, type McpContext } from "./tools";

export const MCP_PROTOCOL_VERSION = "2025-06-18";
const SUPPORTED_VERSIONS = new Set(["2025-06-18", "2025-03-26", "2024-11-05"]);

export const SERVER_INFO = { name: "ryuiki-karte", version: "0.1.0" };

type Id = string | number | null;
export interface JsonRpcRequest {
  jsonrpc: "2.0";
  id?: Id;
  method: string;
  params?: Record<string, unknown>;
}
export interface JsonRpcResponse {
  jsonrpc: "2.0";
  id: Id;
  result?: unknown;
  error?: { code: number; message: string; data?: unknown };
}

const ERR = { parse: -32700, invalidRequest: -32600, methodNotFound: -32601, invalidParams: -32602, internal: -32603 } as const;

const rpcError = (id: Id, code: number, message: string): JsonRpcResponse => ({ jsonrpc: "2.0", id, error: { code, message } });

/** `tools/list` の中身。入力スキーマは zod から JSON Schema に直す（スナップショットで固定）。 */
export function listTools() {
  return MCP_TOOLS.map((t) => ({
    name: t.name,
    description: t.description,
    inputSchema: z.toJSONSchema(t.inputSchema, { io: "input" }),
  }));
}

async function callTool(params: Record<string, unknown> | undefined, ctx: McpContext): Promise<unknown> {
  const tool = MCP_TOOLS.find((t) => t.name === params?.name);
  if (!tool) throw new RpcError(ERR.invalidParams, `未知のツール: ${String(params?.name)}`);
  const parsed = tool.inputSchema.safeParse(params?.arguments ?? {});
  if (!parsed.success) {
    // 入力の誤りはツール実行のエラー（isError）として返し、モデルが直せるようにする。
    return toolResult({ error: "入力が不正です", issues: parsed.error.issues.map((i) => ({ path: i.path.join("."), message: i.message })) }, true);
  }
  try {
    return toolResult(await tool.execute(parsed.data as never, ctx), false);
  } catch (e) {
    if (e instanceof McpInputError) return toolResult({ error: e.message }, true);
    // 内部の例外メッセージ（SQL 断片など）は利用者に返さない。
    console.error("mcp tool failed", tool.name, e);
    return toolResult({ error: "ツールの実行に失敗しました" }, true);
  }
}

function toolResult(payload: unknown, isError: boolean) {
  return { content: [{ type: "text", text: JSON.stringify(payload) }], structuredContent: payload, isError };
}

class RpcError extends Error {
  constructor(
    readonly code: number,
    message: string,
  ) {
    super(message);
  }
}

/** 1 件の JSON-RPC リクエストを処理する。通知（id なし）は null（応答しない）。 */
export async function handleRpc(msg: unknown, ctx: McpContext): Promise<JsonRpcResponse | null> {
  const m = msg as Partial<JsonRpcRequest> | null;
  if (!m || typeof m !== "object" || m.jsonrpc !== "2.0" || typeof m.method !== "string") {
    return rpcError(null, ERR.invalidRequest, "JSON-RPC 2.0 のリクエストではない");
  }
  const isNotification = m.id === undefined;
  const id: Id = m.id ?? null;
  try {
    let result: unknown;
    switch (m.method) {
      case "initialize": {
        const asked = typeof m.params?.protocolVersion === "string" ? m.params.protocolVersion : "";
        result = {
          protocolVersion: SUPPORTED_VERSIONS.has(asked) ? asked : MCP_PROTOCOL_VERSION,
          capabilities: { tools: { listChanged: false } },
          serverInfo: SERVER_INFO,
          instructions:
            "流域カルテ（相模川流域の水質・生物出現データ）。まず describe_catalog で項目を確認し、get_observations / get_occurrences で取る。" +
            "応答の caveats と provenance（取得日・更新方式）を必ず伝える。任意の SQL は受け付けない。",
        };
        break;
      }
      case "ping":
        result = {};
        break;
      case "tools/list":
        result = { tools: listTools() };
        break;
      case "tools/call":
        result = await callTool(m.params, ctx);
        break;
      default:
        if (isNotification) return null; // notifications/initialized など
        return rpcError(id, ERR.methodNotFound, `未対応のメソッド: ${m.method}`);
    }
    return isNotification ? null : { jsonrpc: "2.0", id, result };
  } catch (e) {
    if (e instanceof RpcError) return isNotification ? null : rpcError(id, e.code, e.message);
    console.error("mcp rpc failed", m.method, e);
    return isNotification ? null : rpcError(id, ERR.internal, "内部エラー");
  }
}

/** POST 本文（単一またはバッチ）を処理して、返す JSON（無ければ null＝202）を返す。 */
export async function handleBody(body: unknown, ctx: McpContext): Promise<JsonRpcResponse | JsonRpcResponse[] | null> {
  if (Array.isArray(body)) {
    if (body.length === 0) return rpcError(null, ERR.invalidRequest, "空のバッチ");
    const out = (await Promise.all(body.map((m) => handleRpc(m, ctx)))).filter((r): r is JsonRpcResponse => r !== null);
    return out.length ? out : null;
  }
  return handleRpc(body, ctx);
}

export { ERR as RPC_ERRORS };
