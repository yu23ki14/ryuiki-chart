import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

function req(body: unknown, headers: Record<string, string> = {}) {
  return new NextRequest("http://localhost:3000/api/mcp", { method: "POST", body: JSON.stringify(body), headers: { host: "localhost:3000", ...headers } });
}
const init = { jsonrpc: "2.0", id: 1, method: "initialize", params: { protocolVersion: "2025-06-18" } };

afterEach(() => {
  vi.resetModules();
  vi.doUnmock("@/lib/features");
});

describe("/api/mcp の出し分け（MCP_ENABLED）", () => {
  it("既定は false。false の間は POST/GET/DELETE とも 404", async () => {
    const features = await import("@/lib/features");
    expect(features.MCP_ENABLED).toBe(false);
    const route = await import("./route");
    expect((await route.POST(req(init))).status).toBe(404);
    expect((await route.GET()).status).toBe(404);
    expect((await route.DELETE()).status).toBe(404);
  });

  it("true にすると initialize に応答し、通知は 202、GET は 405", async () => {
    vi.doMock("@/lib/features", () => ({ MCP_ENABLED: true }));
    const route = await import("./route");
    const res = await route.POST(req(init));
    expect(res.status).toBe(200);
    expect(((await res.json()) as { result: { serverInfo: { name: string } } }).result.serverInfo.name).toBe("ryuiki-karte");
    expect((await route.POST(req({ jsonrpc: "2.0", method: "notifications/initialized" }))).status).toBe(202);
    expect((await route.GET()).status).toBe(405);
  });

  it("Origin が Host と違えば 403、壊れた JSON は 400、大きすぎる本文は 413", async () => {
    vi.doMock("@/lib/features", () => ({ MCP_ENABLED: true }));
    const route = await import("./route");
    expect((await route.POST(req(init, { origin: "http://evil.example" }))).status).toBe(403);
    expect((await route.POST(req(init, { origin: "http://localhost:3000" }))).status).toBe(200);
    const broken = new NextRequest("http://localhost:3000/api/mcp", { method: "POST", body: "{", headers: { host: "localhost:3000" } });
    expect((await route.POST(broken)).status).toBe(400);
    const big = new NextRequest("http://localhost:3000/api/mcp", { method: "POST", body: "x".repeat(70 * 1024), headers: { host: "localhost:3000" } });
    expect((await route.POST(big)).status).toBe(413);
  });
});
