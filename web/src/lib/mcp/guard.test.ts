import { describe, expect, it, vi } from "vitest";
import { originAllowed, withinRateLimit } from "./guard";

describe("originAllowed", () => {
  it("ヘッダ無しは通す。許可ホスト（ポート違い・大文字小文字は正規化）は通す", () => {
    expect(originAllowed(null)).toBe(true);
    expect(originAllowed("https://RYUIKI-DEMO.tokyo-odh-009.workers.dev")).toBe(true);
    expect(originAllowed("http://localhost:8787")).toBe(true);
    expect(originAllowed("http://127.0.0.1:3000")).toBe(true);
    expect(originAllowed("http://[::1]:3000")).toBe(true);
  });
  it("それ以外・壊れた値・null は弾く", () => {
    for (const o of ["https://evil.example", "null", "not a url", "https://ryuiki-demo.tokyo-odh-009.workers.dev.evil.example", "https://localhost.evil.example"]) {
      expect(originAllowed(o)).toBe(false);
    }
  });
});

describe("withinRateLimit", () => {
  it("limiter が無ければ true、success=false なら false、例外は開く側（true）", async () => {
    expect(await withinRateLimit(null, "1.2.3.4")).toBe(true);
    expect(await withinRateLimit({ limit: async () => ({ success: false }) }, "1.2.3.4")).toBe(false);
    vi.spyOn(console, "error").mockImplementation(() => {});
    expect(
      await withinRateLimit(
        {
          limit: async () => {
            throw new Error("x");
          },
        },
        null,
      ),
    ).toBe(true);
  });
});
