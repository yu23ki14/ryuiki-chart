import { beforeEach, describe, expect, it, vi } from "vitest";

/**
 * MCP の `region` 引数（Issue #93。docs/plans/REGION_FILTER.md §5）。
 * cube 層と地域の部品は差し替える（A の実装・生成物に依存せず、ツールの配線だけを見る）。
 */
vi.mock("@/lib/region", () => ({
  REGIONS: [
    { id: "jp-14", label: "神奈川県" },
    { id: "jp-46", label: "奄美大島" },
  ],
}));
vi.mock("@/lib/cube/region", () => ({
  // 出典の地域は ID の綴りで代用する（実物は SOURCE_REGION。ここでは「地域に属さない出典は並ばない」ことだけを見る）。
  sourcesOfRegion: (ids: readonly string[], region?: string) =>
    region === "jp-14" ? ids.filter((i) => !i.includes("amami")) : region === "jp-46" ? ids.filter((i) => !i.includes("kanagawa")) : [...ids],
}));

const spies = vi.hoisted(() => ({
  speciesCatalog: vi.fn(async () => []),
  watershedYears: vi.fn(async () => []),
  speciesMonths: vi.fn(async () => []),
  variableCatalog: vi.fn(async () => []),
  waterBodies: vi.fn(async () => []),
  timeseries: vi.fn(async () => ({ envelope: null })),
}));
vi.mock("@/lib/cube", async (orig) => ({ ...(await orig<typeof import("@/lib/cube")>()), ...spies }));

import { OCCURRENCE_SOURCE_IDS } from "@/lib/cube";
import { handleRpc, listTools } from "./server";
import type { McpContext } from "./tools";

const ctx: McpContext = { db: async () => ({}) as never, now: new Date("2026-10-11T03:00:00Z") };
async function call(name: string, args: unknown) {
  const res = await handleRpc({ jsonrpc: "2.0", id: 1, method: "tools/call", params: { name, arguments: args } }, ctx);
  return res!.result as { structuredContent: Record<string, unknown>; isError: boolean };
}
const REGION_TOOLS = ["describe_catalog", "search_registry", "get_observations", "get_occurrences"];

beforeEach(() => Object.values(spies).forEach((s) => s.mockClear()));

describe("region の入力スキーマ", () => {
  it("対象の4ツールに region（enum: jp-14／jp-46、省略可）があり、z.tuple は使っていない", () => {
    for (const name of REGION_TOOLS) {
      const schema = listTools().find((t) => t.name === name)!.inputSchema as {
        properties: Record<string, { enum?: string[] }>;
        required?: string[];
      };
      expect(schema.properties.region.enum, name).toEqual(["jp-14", "jp-46"]);
      expect(schema.required ?? [], name).not.toContain("region");
    }
    expect(JSON.stringify(listTools())).not.toContain("prefixItems");
  });

  it("地域で絞らないツール（get_edna・export_dataset・get_records・find_datasets）は region を取らない（strict で弾かれる）", async () => {
    for (const name of ["get_edna", "export_dataset"]) {
      expect((await call(name, { region: "jp-46" })).isError, name).toBe(true);
    }
  });

  it("不正な region（all も含む）は入力エラー。未知のキーも strict で弾かれる", async () => {
    for (const region of ["xx", "all", "jp-13", ""]) {
      expect((await call("get_occurrences", { kind: "species_catalog", region })).isError, region).toBe(true);
    }
    expect((await call("get_occurrences", { kind: "species_catalog", region: "jp-46", extra: 1 })).isError).toBe(true);
    expect(spies.speciesCatalog).not.toHaveBeenCalled();
  });
});

describe("region の配線", () => {
  const ids = (r: { structuredContent: Record<string, unknown> }) => (r.structuredContent.provenance as { source_id: string }[]).map((p) => p.source_id).sort();

  it("get_occurrences: region を cube に渡し、query.region に入れ、provenance は地域の出典だけ", async () => {
    const r = await call("get_occurrences", { kind: "species_catalog", region: "jp-46" });
    expect(r.isError).toBe(false);
    expect(spies.speciesCatalog).toHaveBeenCalledWith(expect.anything(), expect.objectContaining({ region: "jp-46" }));
    expect((r.structuredContent.query as { region: string }).region).toBe("jp-46");
    expect(ids(r).length).toBeGreaterThan(0);
    expect(ids(r).some((s) => s.includes("kanagawa"))).toBe(false);
    const k = await call("get_occurrences", { kind: "species_catalog", region: "jp-14" });
    expect(ids(k).some((s) => s.includes("amami"))).toBe(false);
  });

  it("get_occurrences: region 省略は全出典・query.region は null・cube に region を渡さない", async () => {
    const r = await call("get_occurrences", { kind: "species_catalog" });
    expect(ids(r)).toEqual([...OCCURRENCE_SOURCE_IDS].sort());
    expect((r.structuredContent.query as { region: unknown }).region).toBeNull();
    expect(spies.speciesCatalog.mock.calls[0]).toEqual([expect.anything(), { group: null, limit: 101, withNames: true }]);
  });

  it("get_occurrences: source_ids と region の併用は両方を渡す", async () => {
    await call("get_occurrences", { kind: "watershed_years", region: "jp-14", source_ids: ["inaturalist_kanagawa"] });
    expect(spies.watershedYears).toHaveBeenCalledWith(expect.anything(), { placeId: undefined, sourceIds: ["inaturalist_kanagawa"], region: "jp-14" });
  });

  it("search_registry(species) / describe_catalog(variables・waters) / get_observations も region を渡す", async () => {
    await call("search_registry", { kind: "species", query: "x", region: "jp-46" });
    expect(spies.speciesCatalog).toHaveBeenCalledWith(expect.anything(), expect.objectContaining({ region: "jp-46" }));
    await call("describe_catalog", { what: "variables", region: "jp-46" });
    expect(spies.variableCatalog).toHaveBeenCalledWith(expect.anything(), expect.objectContaining({ region: "jp-46" }));
    await call("describe_catalog", { what: "waters", region: "jp-46" });
    expect(spies.waterBodies).toHaveBeenCalledWith(expect.anything(), expect.objectContaining({ region: "jp-46" }));
    await call("get_observations", { variableId: "common:variable:water.bod", scope: { type: "zone" }, grain: "year", region: "jp-46" });
    expect(spies.timeseries).toHaveBeenCalledWith(expect.anything(), expect.objectContaining({ region: "jp-46" }), expect.anything());
  });

  it("get_observations: region 省略なら timeseries の入力に region が入らない", async () => {
    await call("get_observations", { variableId: "common:variable:water.bod", scope: { type: "zone" }, grain: "year" });
    expect(spies.timeseries.mock.calls[0][1]).not.toHaveProperty("region");
  });
});
