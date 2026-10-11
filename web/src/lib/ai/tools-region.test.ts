import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("server-only", () => ({}));
const spies = vi.hoisted(() => ({
  variableCatalog: vi.fn(async () => []),
  waterBodies: vi.fn(async () => []),
  sites: vi.fn(async () => []),
  taxonGroupYears: vi.fn(async () => []),
  effortYears: vi.fn(async () => []),
  redlistBundle: vi.fn(async () => ({ summary: [], flows: [], species: [] })),
  overviewCounts: vi.fn(async () => ({ sites: 0, sources: 0, watersheds: 0, variables: 0, yFrom: null, yTo: null })),
  watershedRollup: vi.fn(async () => ({ watersheds: [], landuseYears: null, outsideWatershed: null })),
  occurrenceTotals: vi.fn(async () => ({ records: 0, species: 0, grids: 0, gbif: 0, inat: 0 })),
  d1CubeDb: vi.fn(async () => ({})),
}));
vi.mock("@/lib/cube", async (orig) => ({
  ...(await orig<typeof import("@/lib/cube")>()),
  ...spies,
}));

import { z } from "zod";
import { aiTools } from "./tools";
import { describePageContext } from "./page-context";
import { timeseriesUrl } from "./links";
import { buildSystemPrompt } from "./prompt";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const run = (name: keyof typeof aiTools, input: unknown) => (aiTools[name].execute as any)(input, { toolCallId: "t", messages: [] }) as Promise<any>;
const schemaOf = (name: keyof typeof aiTools) => z.toJSONSchema(aiTools[name].inputSchema as z.ZodType) as { properties?: Record<string, { enum?: string[] }>; oneOf?: { properties: Record<string, { enum?: string[] }> }[] };

beforeEach(() => Object.values(spies).forEach((s) => s.mockClear()));

describe("AI ツールの region", () => {
  it("対象ツールのスキーマに region（enum: jp-14／jp-46、省略可）があり、z.tuple（prefixItems）は無い", () => {
    for (const name of ["list_catalog", "get_timeseries", "get_seasonality", "get_sites", "get_redlist", "get_overview"] as const) {
      const j = schemaOf(name);
      expect(j.properties?.region?.enum, name).toEqual(["jp-14", "jp-46"]);
      expect((j as { required?: string[] }).required ?? [], name).not.toContain("region");
    }
    const biota = schemaOf("get_biota_trend");
    for (const b of biota.oneOf ?? []) expect(b.properties.region?.enum).toEqual(["jp-14", "jp-46"]);
    for (const name of Object.keys(aiTools) as (keyof typeof aiTools)[]) expect(JSON.stringify(schemaOf(name)), name).not.toContain("prefixItems");
  });

  it("不正な region は入力エラー（all も入れられない）", () => {
    const s = aiTools.list_catalog.inputSchema as z.ZodType;
    expect(s.safeParse({ what: "variables", region: "jp-46" }).success).toBe(true);
    expect(s.safeParse({ what: "variables" }).success).toBe(true);
    for (const region of ["xx", "all", ""]) expect(s.safeParse({ what: "variables", region }).success, region).toBe(false);
  });

  it("list_catalog: region を cube に渡し、結果の region に入る。省略は null", async () => {
    const r = await run("list_catalog", { what: "variables", region: "jp-46" });
    expect(spies.variableCatalog).toHaveBeenCalledWith(expect.anything(), expect.objectContaining({ region: "jp-46" }));
    expect(r.region).toBe("jp-46");
    expect((await run("list_catalog", { what: "variables" })).region).toBeNull();
  });

  it("get_overview / get_redlist / get_biota_trend / get_sites も region を渡す", async () => {
    await run("get_overview", { region: "jp-46" });
    expect(spies.overviewCounts).toHaveBeenCalledWith(expect.anything(), "jp-46");
    expect(spies.watershedRollup).toHaveBeenCalledWith(expect.anything(), "jp-46");
    expect(spies.occurrenceTotals).toHaveBeenCalledWith(expect.anything(), "jp-46");
    await run("get_redlist", { year: 2014, region: "jp-46" });
    expect(spies.redlistBundle).toHaveBeenCalledWith(expect.anything(), 2014, expect.objectContaining({ region: "jp-46" }));
    await run("get_biota_trend", { mode: "groups", region: "jp-46" });
    expect(spies.taxonGroupYears).toHaveBeenCalledWith(expect.anything(), { region: "jp-46" });
    expect(spies.effortYears).toHaveBeenCalledWith(expect.anything(), { region: "jp-46" });
    const s = await run("get_sites", { region: "jp-14" });
    expect(spies.sites).toHaveBeenCalledWith(expect.anything(), expect.objectContaining({ region: "jp-14" }));
    expect(s.region).toBe("jp-14");
  });
});

describe("PageContext の region", () => {
  it("全体（省略・'all'）は何も足さず、jp-46 は『表示の地域=奄美大島』と region 値を足す", () => {
    const base = describePageContext({ route: "/", title: "概況" });
    expect(describePageContext({ route: "/", title: "概況", region: "all" })).toBe(base);
    const t = describePageContext({ route: "/", title: "概況", region: "jp-46" });
    expect(t).toBe(`${base}表示の地域=奄美大島（region="jp-46"）。`);
    expect(describePageContext({ route: "/biota", title: "生物相", tab: "trend", region: "jp-14" })).toContain("表示の地域=神奈川県");
  });

  it("システムプロンプト: 画面の地域が入り、ツールの region に渡す指示がある", () => {
    const p = buildSystemPrompt({ route: "/", title: "概況", region: "jp-46" });
    expect(p).toContain("表示の地域=奄美大島");
    expect(p).toContain("ツールの region にそれを渡す");
    expect(p).toContain("summary_* 表は全地域の合算");
  });
});

describe("ディープリンクの region", () => {
  const input = { variableId: "common:variable:water.bod", scope: { type: "zone" as const }, grain: "year" as const };
  it("全体（省略・'all'）は URL に付けない（現状と同じ）。地域つきは ?region= が付く", () => {
    const base = timeseriesUrl(input);
    expect(timeseriesUrl({ ...input, region: "all" })).toBe(base);
    expect(base).not.toContain("region");
    expect(timeseriesUrl({ ...input, region: "jp-46" })).toBe(`${base}&region=jp-46`);
  });
});
