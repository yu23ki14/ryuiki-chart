import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

function req(body: unknown, headers: Record<string, string> = {}) {
  return new NextRequest("http://localhost:3000/api/mcp", { method: "POST", body: JSON.stringify(body), headers: { host: "localhost:3000", ...headers } });
}
const init = { jsonrpc: "2.0", id: 1, method: "initialize", params: { protocolVersion: "2025-06-18" } };

/** フラグとレート制限器の状態を明示して route を読み込む（本番既定には依存しない）。 */
async function load(enabled: boolean, limiter: { limit: (o: { key: string }) => Promise<{ success: boolean }> } | null = null) {
  vi.resetModules();
  vi.doMock("@/lib/features", async (orig) => ({ ...(await orig<typeof import("@/lib/features")>()), MCP_ENABLED: enabled }));
  vi.doMock("@/lib/mcp/guard", async (orig) => ({ ...(await orig<typeof import("@/lib/mcp/guard")>()), getRateLimiter: async () => limiter }));
  return import("./route");
}

afterEach(() => {
  vi.resetModules();
  vi.doUnmock("@/lib/features");
  vi.doUnmock("@/lib/mcp/guard");
});

describe("/api/mcp の出し分け（MCP_ENABLED）", () => {
  it("false なら POST/GET/DELETE とも 404（フラグで閉じられる）", async () => {
    const route = await load(false);
    expect((await route.POST(req(init))).status).toBe(404);
    expect((await route.GET()).status).toBe(404);
    expect((await route.DELETE()).status).toBe(404);
  });

  it("true なら initialize に応答し、通知は 202、GET は 405", async () => {
    const route = await load(true);
    const res = await route.POST(req(init));
    expect(res.status).toBe(200);
    expect(((await res.json()) as { result: { serverInfo: { name: string } } }).result.serverInfo.name).toBe("ryuiki-karte");
    expect((await route.POST(req({ jsonrpc: "2.0", method: "notifications/initialized" }))).status).toBe(202);
    expect((await route.GET()).status).toBe(405);
  });
});

describe("Origin の許可リスト", () => {
  it("Origin 無し（Claude Desktop/Code）と本番・localhost は通り、それ以外は JSON-RPC 形の 403", async () => {
    const route = await load(true);
    expect((await route.POST(req(init))).status).toBe(200);
    expect((await route.POST(req(init, { origin: "https://ryuiki-demo.tokyo-odh-009.workers.dev" }))).status).toBe(200);
    expect((await route.POST(req(init, { origin: "http://localhost:3000" }))).status).toBe(200);
    for (const origin of ["https://evil.example", "null", "https://ryuiki-demo.tokyo-odh-009.workers.dev.evil.example"]) {
      const res = await route.POST(req(init, { origin }));
      expect(res.status).toBe(403);
      expect(((await res.json()) as { jsonrpc: string }).jsonrpc).toBe("2.0");
    }
  });
});

describe("本文の上限", () => {
  it("壊れた JSON は 400", async () => {
    const route = await load(true);
    const broken = new NextRequest("http://localhost:3000/api/mcp", { method: "POST", body: "{" });
    expect((await route.POST(broken)).status).toBe(400);
  });

  it("Content-Length が上限超なら本文を読まずに 413", async () => {
    const route = await load(true);
    const r = new NextRequest("http://localhost:3000/api/mcp", { method: "POST", body: "{}", headers: { "content-length": String(70 * 1024) } });
    const res = await route.POST(r);
    expect(res.status).toBe(413);
    expect(((await res.json()) as { error: { code: number } }).error.code).toBe(-32600);
  });

  it("Content-Length 無しのストリーム（chunked）でも上限を超えた時点で 413（全部は読まない）", async () => {
    const route = await load(true);
    const chunk = new TextEncoder().encode("x".repeat(16 * 1024));
    let sent = 0;
    const stream = new ReadableStream<Uint8Array>({
      pull(c) {
        if (sent >= 10) return c.close();
        sent++;
        c.enqueue(chunk);
      },
    });
    const r = new NextRequest("http://localhost:3000/api/mcp", { method: "POST", body: stream, duplex: "half" } as ConstructorParameters<typeof NextRequest>[1]);
    expect((await route.POST(r)).status).toBe(413);
    expect(sent).toBeLessThan(10);
  });
});

describe("レート制限", () => {
  it("超過なら Retry-After 付きの JSON-RPC 形 429。キーは cf-connecting-ip", async () => {
    const keys: string[] = [];
    const route = await load(true, { limit: async ({ key }) => (keys.push(key), { success: false }) });
    const res = await route.POST(req(init, { "cf-connecting-ip": "203.0.113.7" }));
    expect(res.status).toBe(429);
    expect(res.headers.get("retry-after")).toBe("60");
    expect(((await res.json()) as { jsonrpc: string }).jsonrpc).toBe("2.0");
    expect(keys).toEqual(["203.0.113.7"]);
  });

  it("枠内なら通る。バインディングが無ければ素通し", async () => {
    expect((await (await load(true, { limit: async () => ({ success: true }) })).POST(req(init))).status).toBe(200);
    expect((await (await load(true, null)).POST(req(init))).status).toBe(200);
  });
});
