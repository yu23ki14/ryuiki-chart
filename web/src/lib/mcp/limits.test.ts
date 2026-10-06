import { describe, expect, it, vi } from "vitest";

const { timeseries, speciesCatalog } = vi.hoisted(() => ({
  timeseries: vi.fn(async (...args: unknown[]) => ({ envelope: null, sites: [], n: args.length })),
  speciesCatalog: vi.fn(async (...args: unknown[]) => (args.length ? [] : [])),
}));
vi.mock("@/lib/cube", async (orig) => ({ ...(await orig<typeof import("@/lib/cube")>()), timeseries, speciesCatalog }));

import { handleRpc } from "./server";

const ctx = { db: async () => ({}) as never, now: new Date("2026-10-07T00:00:00Z") };
const call = (name: string, args: unknown) => handleRpc({ jsonrpc: "2.0", id: 1, method: "tools/call", params: { name, arguments: args } }, ctx);

describe("読み取り量の上限", () => {
  it("get_observations の day 粒度で from/to が無ければ直近 2 年に絞る。指定があればそのまま", async () => {
    const base = { variableId: "common:variable:water.ph", scope: { type: "zone" }, grain: "day" };
    await call("get_observations", base);
    expect((timeseries.mock.calls.at(-1) as unknown[])[1]).toMatchObject({ from: "2024-10-07" });
    await call("get_observations", { ...base, from: "2020-01-01", to: "2020-12-31" });
    expect((timeseries.mock.calls.at(-1) as unknown[])[1]).toMatchObject({ from: "2020-01-01", to: "2020-12-31" });
    await call("get_observations", { ...base, grain: "year" });
    expect((timeseries.mock.calls.at(-1) as unknown[])[1]).not.toHaveProperty("from");
  });

  it("species_catalog は limit を問い合わせに渡す（limit+1 で truncated を判定）", async () => {
    await call("get_occurrences", { kind: "species_catalog", limit: 5 });
    expect(speciesCatalog.mock.calls.at(-1)).toMatchObject([expect.anything(), { limit: 6 }]);
  });
});

describe("通知（id 無し）", () => {
  it("tools/call を通知として送られても実行しない", async () => {
    timeseries.mockClear();
    speciesCatalog.mockClear();
    expect(await handleRpc({ jsonrpc: "2.0", method: "tools/call", params: { name: "get_occurrences", arguments: { kind: "species_catalog" } } }, ctx)).toBeNull();
    expect(speciesCatalog).not.toHaveBeenCalled();
  });
});
