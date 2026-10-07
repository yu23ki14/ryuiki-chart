import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { buildCubeFixture, FX, type CubeFixture } from "@/lib/cube/__fixtures__/cube-fixture";
import { buildOccurrenceFixture, FXO, type OccurrenceFixture } from "@/lib/cube/__fixtures__/occurrence-fixture";
import { OCCURRENCE_SOURCE_IDS } from "@/lib/cube";
import { handleBody, handleRpc, listTools, MAX_BATCH, MCP_PROTOCOL_VERSION } from "./server";
import realDatapackage from "./__fixtures__/datapackage.real.json";
import { datapackageResources, MCP_TOOLS, type McpContext } from "./tools";

/**
 * 公開範囲の不変条件（Issue #40 D6。ADR-0028 の下で「機械的に効く」の読み替え）のうち、MCP の応答に関するもの。
 *  1. 合成データが出ない（provenance に source_id NULL・synthetic_* が無い）
 *  5. 任意 SQL・全表走査が MCP に無い（`tools.test.ts` が一覧を固定）
 *  6. excluded が常に 0（全ツールの応答で）
 */
function expectPublicInvariants(env: Record<string, unknown>) {
  expect(env.spec_version).toBe("cube-envelope@2");
  expect(env.excluded).toEqual({ by_license: 0, by_embargo: 0, reasons: [] });
  const provenance = (env.provenance ?? []) as { source_id: string | null }[];
  for (const p of provenance) {
    expect(p.source_id).not.toBeNull();
    expect(String(p.source_id)).not.toMatch(/^synthetic/);
  }
  // provenance だけでなく応答全体（data を含む）に合成の出典が出ない
  expect(JSON.stringify(env.data ?? null)).not.toMatch(/synthetic_/);
  expect(JSON.stringify(env.provenance ?? null)).not.toMatch(/synthetic_/);
  expect(typeof env.cite_as).toBe("string");
  expect(typeof env.as_of).toBe("string");
}

let cube: CubeFixture;
let occ: OccurrenceFixture;
beforeEach(() => {
  cube = buildCubeFixture();
  occ = buildOccurrenceFixture();
});
afterEach(() => {
  cube.db.close();
  occ.db.close();
});

const NOW = new Date("2026-10-06T03:00:00Z");
const ctx = (over: Partial<McpContext> = {}): McpContext => ({ db: async () => cube.db, now: NOW, ...over });

async function call(name: string, args: unknown, c: McpContext = ctx()) {
  const res = await handleRpc({ jsonrpc: "2.0", id: 1, method: "tools/call", params: { name, arguments: args } }, c);
  return res!.result as { structuredContent: Record<string, unknown>; isError: boolean; content: { type: string; text: string }[] };
}

describe("JSON-RPC / MCP プロトコル", () => {
  it("initialize: 要求された版を受け、tools 能力を返す", async () => {
    const res = await handleRpc({ jsonrpc: "2.0", id: 1, method: "initialize", params: { protocolVersion: "2025-03-26" } }, ctx());
    const r = res!.result as { protocolVersion: string; capabilities: { tools: object }; serverInfo: { name: string } };
    expect(r.protocolVersion).toBe("2025-03-26");
    expect(r.capabilities.tools).toBeDefined();
    expect(r.serverInfo.name).toBe("ryuiki-karte");
    const unknown = await handleRpc({ jsonrpc: "2.0", id: 2, method: "initialize", params: { protocolVersion: "1999-01-01" } }, ctx());
    expect((unknown!.result as { protocolVersion: string }).protocolVersion).toBe(MCP_PROTOCOL_VERSION);
  });

  it("通知（id なし）には応答しない／未知メソッドは -32601", async () => {
    expect(await handleRpc({ jsonrpc: "2.0", method: "notifications/initialized" }, ctx())).toBeNull();
    const res = await handleRpc({ jsonrpc: "2.0", id: 3, method: "resources/list" }, ctx());
    expect(res!.error?.code).toBe(-32601);
  });

  it("JSON-RPC でない入力は -32600、バッチも処理する", async () => {
    expect((await handleRpc({ foo: 1 }, ctx()))!.error?.code).toBe(-32600);
    const out = await handleBody(
      [
        { jsonrpc: "2.0", id: 1, method: "ping" },
        { jsonrpc: "2.0", method: "notifications/initialized" },
      ],
      ctx(),
    );
    expect(out).toEqual([{ jsonrpc: "2.0", id: 1, result: {} }]);
  });

  it("未知のツールは -32602、入力不正は isError（例外にしない）", async () => {
    const res = await handleRpc({ jsonrpc: "2.0", id: 4, method: "tools/call", params: { name: "run_sql", arguments: { sql: "select 1" } } }, ctx());
    expect(res!.error?.code).toBe(-32602);
    const bad = await call("get_observations", { variableId: 1 });
    expect(bad.isError).toBe(true);
    expect(bad.structuredContent.error).toBe("入力が不正です");
  });

  it("内部の例外の中身（SQL 断片など）を利用者に返さない", async () => {
    const boom = await call("describe_catalog", { what: "variables" }, ctx({ db: async () => Promise.reject(new Error("SELECT secret FROM x")) }));
    expect(boom.isError).toBe(true);
    expect(boom.content[0].text).not.toContain("SELECT");
  });
});

describe("5 ツールの応答は封筒（excluded=0・合成なし・cite_as・鮮度）", () => {
  it("describe_catalog: zones / sources / waters / variables", async () => {
    for (const what of ["zones", "sources", "waters", "variables"] as const) {
      const r = await call("describe_catalog", { what });
      expect(r.isError, what).toBe(false);
      expectPublicInvariants(r.structuredContent);
    }
    const src = await call("describe_catalog", { what: "sources" });
    const sources = (src.structuredContent.data as { sources: { source_id: string; fetched_at: string | null; update_mode: string }[] }).sources;
    expect(sources.length).toBeGreaterThan(100);
    expect(sources.every((s) => s.update_mode !== undefined)).toBe(true);
    expect(sources.some((s) => s.fetched_at?.endsWith("+09:00"))).toBe(true);
  });

  it("search_registry: variable / source / species", async () => {
    const v = await call("search_registry", { kind: "variable", query: "水温" });
    expect((v.structuredContent.data as { matches: unknown[] }).matches.length).toBeGreaterThan(0);
    expectPublicInvariants(v.structuredContent);
    const s = await call("search_registry", { kind: "source", query: "厚木" });
    expect((s.structuredContent.data as { matches: { source_id: string }[] }).matches.map((m) => m.source_id)).toContain("atsugi_river_water_quality");
    expectPublicInvariants(s.structuredContent);
    const sp = await call("search_registry", { kind: "species", query: FXO.binoms.alpha }, ctx({ db: async () => occ.db }));
    expectPublicInvariants(sp.structuredContent);
  });

  it("get_observations: 封筒に fetched_at・update_mode・age_days・cite_as・注記が載り、excluded=0", async () => {
    const r = await call("get_observations", { variableId: FX.variables.ss, scope: { type: "site", siteId: FX.sites.a }, grain: "day", from: "2000-01-01" });
    expect(r.isError).toBe(false);
    const env = r.structuredContent as { provenance: Record<string, unknown>[]; rows: unknown[]; caveats: { key: string; severity: unknown }[]; cite_as: string };
    expectPublicInvariants(env);
    expect(env.rows.length).toBeGreaterThan(0);
    const p = env.provenance.find((x) => x.source_id === "atsugi_river_water_quality")!;
    expect(p.fetched_at).toBe("2026-08-30T16:20:58+09:00");
    expect(p.age_days).toBe(37);
    expect(p.update_mode).toBeDefined();
    expect(env.cite_as).toContain("取得 2026-08-30");
    // 注記は同梱される（facet から機械的に付与。モデル任意のツールにしない）
    expect(Array.isArray(env.caveats)).toBe(true);
  });

  it("get_observations: 系列が無い variableId は空の封筒（別の系列に倒さない）", async () => {
    const r = await call("get_observations", { variableId: "common:variable:no_such", scope: { type: "zone" }, grain: "year" });
    expect(r.isError).toBe(false);
    expectPublicInvariants(r.structuredContent);
    expect((r.structuredContent.data as { rows: unknown[] }).rows).toEqual([]);
  });

  it("get_observations: limit で行を切り、truncated を立てる", async () => {
    const r = await call("get_observations", { variableId: FX.variables.ss, scope: { type: "site", siteId: FX.sites.a }, grain: "day", from: "2000-01-01", limit: 1 });
    const env = r.structuredContent as { rows: unknown[]; truncated: boolean };
    expect(env.rows).toHaveLength(1);
    expect(env.truncated).toBe(true);
  });

  it("get_occurrences: species_years / catalog / watershed_years", async () => {
    const c = ctx({ db: async () => occ.db });
    const years = await call("get_occurrences", { kind: "species_years", binoms: [FXO.binoms.alpha] }, c);
    expectPublicInvariants(years.structuredContent);
    expect((years.structuredContent.data as { rows: unknown[] }).rows.length).toBeGreaterThan(0);
    const prov = years.structuredContent.provenance as { source_id: string }[];
    expect(prov.map((p) => p.source_id)).toContain("gbif_kanagawa_occurrences");
    for (const args of [{ kind: "species_catalog" }, { kind: "watershed_years" }]) {
      expectPublicInvariants((await call("get_occurrences", args, c)).structuredContent);
    }
    const missing = await call("get_occurrences", { kind: "species_years" }, c);
    expect(missing.isError).toBe(true);
  });

  it("get_occurrences: source_ids で絞ると provenance も絞った出典だけ。未指定は全出典。未知の出典は入力エラー", async () => {
    const c = ctx({ db: async () => occ.db });
    const args = { kind: "species_years", binoms: [FXO.binoms.alpha] };
    const all = await call("get_occurrences", args, c);
    const one = await call("get_occurrences", { ...args, source_ids: ["inaturalist_kanagawa"] }, c);
    expectPublicInvariants(one.structuredContent);
    const ids = (r: typeof all) => (r.structuredContent.provenance as { source_id: string }[]).map((p) => p.source_id).sort();
    expect(ids(one)).toEqual(["inaturalist_kanagawa"]);
    expect(ids(all)).toEqual([...OCCURRENCE_SOURCE_IDS].sort());
    const total = (r: typeof all) => (r.structuredContent.data as { rows: { n: number }[] }).rows.reduce((a, x) => a + x.n, 0);
    const gbif = await call("get_occurrences", { ...args, source_ids: ["gbif_kanagawa_occurrences"] }, c);
    expect(total(one) + total(gbif)).toBe(total(all));
    const bad = await call("get_occurrences", { ...args, source_ids: ["no_such_source"] }, c);
    expect(bad.isError).toBe(true);
  });

  it("get_edna: provenance に kanagawa_edna。未知の mode は入力エラー", async () => {
    const c = ctx({ db: async () => occ.db });
    const ok = await call("get_edna", { detected_only: true, limit: 5 }, c);
    expectPublicInvariants(ok.structuredContent);
    expect((ok.structuredContent.provenance as { source_id: string }[]).map((p) => p.source_id)).toEqual(["kanagawa_edna"]);
    expect((await call("get_edna", { mode: "nope" }, c)).isError).toBe(true);
    const keys = (r: typeof ok) => (r.structuredContent.caveats as { key: string }[]).map((x) => x.key);
    expect(keys(ok)).toContain("ednaNonDetect");
    // get_occurrences: 全出典（eDNA を含む）では付き、eDNA を外すと付かない
    const occArgs = { kind: "species_years", binoms: [FXO.binoms.alpha] };
    expect(keys(await call("get_occurrences", occArgs, c))).toContain("ednaReads");
    expect(keys(await call("get_occurrences", { ...occArgs, source_ids: ["inaturalist_kanagawa"] }, c))).not.toContain("ednaReads");
  });

  it("export_dataset: datapackage が無ければ available=false、あれば path と sha256 だけ返す", async () => {
    const none = await call("export_dataset", {}, ctx({ datapackage: async () => null }));
    expectPublicInvariants(none.structuredContent);
    expect((none.structuredContent.data as { available: boolean }).available).toBe(false);
    const pkg = { resources: [{ name: "occurrence", path: "occurrence/a.parquet", hash: "sha256:abc", bytes: 10, schema: { huge: true } }] };
    const some = await call("export_dataset", {}, ctx({ datapackage: async () => pkg }));
    expectPublicInvariants(some.structuredContent);
    expect((some.structuredContent.data as { resources: unknown[] }).resources).toEqual([{ name: "occurrence", path: "occurrence/a.parquet", sha256: "abc", bytes: 10 }]);
    expect(datapackageResources({})).toEqual([]);
  });

  it("export_dataset: 担当 P の実際の datapackage.json（scripts/d01_build_dist.py の出力から切り出した fixture）の形を読める", async () => {
    // fixture は実出力の resources 先頭 3 件（schema だけ 2 項目に切り詰め）。キー名（name/path/sha256/bytes）が変わったら
    // ここが落ちる。scripts/tests/test_dist.py も同じキーを固定している。
    const res = datapackageResources(realDatapackage);
    expect(res).toHaveLength(3);
    for (const r of res) {
      expect(typeof r.name).toBe("string");
      expect(r.path).toMatch(/\.parquet$/);
      expect(r.sha256).toMatch(/^[0-9a-f]{64}$/);
      expect(typeof r.bytes).toBe("number");
    }
    const out = await call("export_dataset", {}, ctx({ datapackage: async () => realDatapackage }));
    expect((out.structuredContent.data as { resources: unknown[] }).resources).toEqual(res);
  });

  it("JSON-RPC バッチは上限 MAX_BATCH 件で、順に実行する。超過は invalid request", async () => {
    const ping = (id: number) => ({ jsonrpc: "2.0", id, method: "ping" });
    const ok = (await handleBody(Array.from({ length: MAX_BATCH }, (_, i) => ping(i + 1)), ctx())) as { id: number }[];
    expect(ok.map((r) => r.id)).toEqual(Array.from({ length: MAX_BATCH }, (_, i) => i + 1));
    const over = (await handleBody(Array.from({ length: MAX_BATCH + 1 }, (_, i) => ping(i + 1)), ctx())) as { error?: { code: number } };
    expect(over.error?.code).toBe(-32600);
  });

  it("全ツールを網羅している（新ツールを足したらこのテストに応答検査を足す）", () => {
    expect(MCP_TOOLS.map((t) => t.name)).toEqual(["describe_catalog", "search_registry", "get_observations", "get_occurrences", "get_edna", "export_dataset"]);
  });
});

describe("不変条件の検査そのものが効く（わざと壊すと止まる）", () => {
  const good = () => ({
    spec_version: "cube-envelope@2",
    excluded: { by_license: 0, by_embargo: 0, reasons: [] },
    provenance: [{ source_id: "atsugi_river_water_quality" }],
    cite_as: "x",
    as_of: "y",
  });
  it("正常な封筒は通る", () => expectPublicInvariants(good()));
  it("excluded が 0 でない（ライセンスで絞る実装が入った）と落ちる", () => {
    expect(() => expectPublicInvariants({ ...good(), excluded: { by_license: 1, by_embargo: 0, reasons: ["x"] } })).toThrow();
  });
  it("合成の出典が provenance に出ると落ちる", () => {
    expect(() => expectPublicInvariants({ ...good(), provenance: [{ source_id: "synthetic_sensor" }] })).toThrow();
    expect(() => expectPublicInvariants({ ...good(), data: { sources: [{ source_id: "synthetic_sensor" }] } })).toThrow();
    expect(() => expectPublicInvariants({ ...good(), provenance: [{ source_id: null }] })).toThrow();
  });
  it("tools/list に listTools と同じものが出る", async () => {
    const res = await handleRpc({ jsonrpc: "2.0", id: 9, method: "tools/list" }, ctx());
    expect((res!.result as { tools: unknown }).tools).toEqual(listTools());
  });
});
