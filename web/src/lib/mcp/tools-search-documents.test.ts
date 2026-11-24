/**
 * search_documents のツール一覧への出し分け（設計 §8 の 7・8）。バインディングが無い／null のときは一覧に出ず、他のツールは動く。
 */
import { describe, expect, it, vi } from "vitest";

vi.mock("server-only", () => ({}));

import { MCP_TOOLS, type McpContext } from "./tools";
import { handleRpc, listTools, toolsFor } from "./server";
import { defaultSearchDeps, type SearchDeps } from "@/lib/document-search";
import { aiToolsFor, aiTools, searchDocumentsAiTool } from "@/lib/ai/tools";

const emptyDeps: SearchDeps = {
  embed: async () => [1, 0],
  index: { query: async () => ({ matches: [] }) },
  all: async () => [],
  chunked: async () => [],
};
const ctx = (vector?: McpContext["vector"]): McpContext => ({
  db: async () => {
    throw new Error("db unused");
  },
  vector,
});

describe("search_documents の出し分け", () => {
  it("バインディングが無い（null）と MCP の一覧に出ない。静的な一覧は変わらない", async () => {
    const names = (await toolsFor(ctx(async () => null))).map((t) => t.name);
    expect(names).not.toContain("search_documents");
    expect(names).toEqual(MCP_TOOLS.map((t) => t.name));
    const res = await handleRpc({ jsonrpc: "2.0", id: 1, method: "tools/list" }, ctx(async () => null));
    expect((res!.result as { tools: unknown }).tools).toEqual(listTools());
  });

  it("既定の依存はバインディングが無い環境（テスト）で null を返し、例外にしない", async () => {
    expect(await defaultSearchDeps()).toBeNull();
    expect((await toolsFor(ctx(undefined))).map((t) => t.name)).toEqual(MCP_TOOLS.map((t) => t.name));
  });

  it("バインディングがあれば MCP の一覧に出て、呼べる（結果が空なら rows は空・notes 付き）", async () => {
    const c = ctx(async () => emptyDeps);
    expect((await toolsFor(c)).map((t) => t.name)).toContain("search_documents");
    const res = await handleRpc({ jsonrpc: "2.0", id: 2, method: "tools/call", params: { name: "search_documents", arguments: { query: "避難" } } }, c);
    const r = res!.result as { isError: boolean; structuredContent: { data: { rows: unknown[]; notes: string[] } } };
    expect(r.isError).toBe(false);
    expect(r.structuredContent.data.rows).toEqual([]);
    expect(r.structuredContent.data.notes.length).toBe(1);
  });

  it("バインディングが無いときに呼ぶと未知のツール（呼び出せない）", async () => {
    const res = await handleRpc({ jsonrpc: "2.0", id: 3, method: "tools/call", params: { name: "search_documents", arguments: { query: "x" } } }, ctx(async () => null));
    expect(res!.error?.message).toContain("未知のツール");
  });

  it("入力は strict（未知のキーは弾く）で、z.tuple を使わない", async () => {
    const c = ctx(async () => emptyDeps);
    const tool = (await toolsFor(c)).find((t) => t.name === "search_documents")!;
    expect(tool.inputSchema.safeParse({ query: "x", extra: 1 }).success).toBe(false);
    expect(JSON.stringify(listTools([tool]))).not.toContain("prefixItems");
  });

  it("AI: バインディングが無い環境では search_documents が一覧に出ない", async () => {
    // テスト環境には Cloudflare のコンテキストが無い → defaultSearchDeps は null
    expect(Object.keys(await aiToolsFor())).toEqual(Object.keys(aiTools));
  });

  it("AI: 依存があれば結果を返し、接続できなければ error を返す（例外にしない）", async () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const run = (t: ReturnType<typeof searchDocumentsAiTool>) => (t.execute as any)({ query: "避難" }, { toolCallId: "t", messages: [] }) as Promise<any>;
    const ok = await run(searchDocumentsAiTool(emptyDeps));
    expect(ok.data.rows).toEqual([]);
    const down = await run(searchDocumentsAiTool({ ...emptyDeps, embed: async () => { throw new Error("down"); } }));
    expect(down.data.error).toContain("接続できない");
  });
});
