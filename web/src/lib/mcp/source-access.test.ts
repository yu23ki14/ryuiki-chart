import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { MCP_TOOLS } from "./tools";
import { OBSERVATION_SOURCE_IDS, OCCURRENCE_SOURCE_IDS, RECORD_SOURCE_IDS } from "@/lib/cube";
import { RECORD_SET_TABLES, SOURCE_ACCESS, SOURCE_META } from "@/lib/registry/generated-source";

/** 出典の状態（MCP_SOURCE_ACCESS.md §2）。生成物と describe_catalog / search_registry の応答の整合を固定する。 */
const NOW = new Date("2026-10-07T00:00:00Z");
const NO_DB = async () => {
  throw new Error("この検査は D1 を読まない");
};

async function run(name: string, args: Record<string, unknown>) {
  const tool = MCP_TOOLS.find((t) => t.name === name)!;
  const parsed = (tool.inputSchema as { parse: (a: unknown) => unknown }).parse(args);
  return (await tool.execute(parsed as never, { db: NO_DB as never, now: NOW })) as {
    data: Record<string, unknown>;
  };
}

type Row = {
  source_id: string;
  queryable_via: string[];
  records_tables: string[];
  n_source_rows: number | null;
  unavailable_reason: string | null;
  unavailable_reason_ja: string | null;
};

describe("出典の状態 SOURCE_ACCESS", () => {
  it("全出典（合成を除く）が状態を持つ。取れない出典は理由コードと日本語の理由を持つ", () => {
    const ids = SOURCE_META.map((m) => m.sourceId).sort();
    expect(Object.keys(SOURCE_ACCESS).sort()).toEqual(ids);
    for (const [id, a] of Object.entries(SOURCE_ACCESS)) {
      expect(a.state === "queryable", id).toBe(a.queryableVia.length > 0);
      if (a.state === "not_queryable") {
        expect(a.reason, id).toBeTruthy();
        expect(a.reasonJa, id).toBeTruthy();
        expect(a.nSourceRows, id).toBeNull();
        expect(a.nSourceRowsBasis, id).toBe("none");
      } else {
        expect(a.reason, id).toBeNull();
        expect(a.nSourceRows, id).toBeGreaterThan(0);
      }
    }
  });

  it("queryable_via は manifests 由来の ID 集合・records の表と一致する", () => {
    for (const [id, a] of Object.entries(SOURCE_ACCESS)) {
      // cube_only: キューブにはあるが get_observations では引けない（宣言。queryable-via.test.ts が実データで確かめる）
      expect(a.queryableVia.includes("get_observations"), id).toBe(OBSERVATION_SOURCE_IDS.includes(id) && a.reason !== "cube_only");
      if (a.reason === "cube_only") expect(OBSERVATION_SOURCE_IDS, id).toContain(id);
      expect(a.queryableVia.includes("get_occurrences"), id).toBe(OCCURRENCE_SOURCE_IDS.includes(id));
      expect(a.queryableVia.includes("get_records"), id).toBe(a.tables.length > 0);
    }
    expect([...RECORD_SOURCE_IDS].sort()).toEqual(
      Object.entries(SOURCE_ACCESS)
        .filter(([, a]) => a.tables.length > 0)
        .map(([id]) => id)
        .sort(),
    );
  });

  it("get_records の表は D1 のスキーマにある（原本にだけある表を宣言しない）", () => {
    const dir = path.join(__dirname, "../../db");
    const defined = new Set<string>();
    for (const f of ["schema.ts", "schema-registry.ts"]) {
      for (const m of fs.readFileSync(path.join(dir, f), "utf8").matchAll(/sqliteTable\(\s*"([a-z_0-9]+)"/g)) defined.add(m[1]);
    }
    const tables = new Set(Object.values(RECORD_SET_TABLES));
    for (const a of Object.values(SOURCE_ACCESS)) for (const t of a.tables) expect(RECORD_SET_TABLES, t).toHaveProperty(t);
    expect(tables.size).toBeGreaterThan(0);
    for (const t of tables) expect(defined.has(t), t).toBe(true);
  });
});

describe("describe_catalog(sources) の状態と summary", () => {
  it("全行が queryable_via（配列）を持ち、空なら理由がある。summary は行から数えた値と一致する", async () => {
    const { data } = await run("describe_catalog", { what: "sources" });
    const rows = data.sources as Row[];
    const summary = data.summary as {
      total: number;
      queryable: number;
      not_queryable: number;
      by_tool: Record<string, number>;
      by_reason: Record<string, number>;
      excluded: Record<string, number>;
    };
    expect(rows).toHaveLength(SOURCE_META.length);
    for (const r of rows) {
      expect(Array.isArray(r.queryable_via), r.source_id).toBe(true);
      if (r.queryable_via.length === 0) {
        expect(r.unavailable_reason, r.source_id).toBeTruthy();
        expect(r.unavailable_reason_ja, r.source_id).toBeTruthy();
      }
    }
    expect(summary.total).toBe(rows.length);
    expect(summary.queryable + summary.not_queryable).toBe(summary.total);
    expect(summary.queryable).toBe(rows.filter((r) => r.queryable_via.length > 0).length);
    expect(Object.values(summary.by_reason).reduce((a, b) => a + b, 0)).toBe(summary.not_queryable);
    const toolCount = (t: string) => rows.filter((r) => r.queryable_via.includes(t)).length;
    for (const [t, n] of Object.entries(summary.by_tool)) expect(n, t).toBe(toolCount(t));
    expect(summary.by_tool.get_records).toBe(RECORD_SOURCE_IDS.length);
    expect(summary.excluded).toEqual({ synthetic: 1 }); // 一覧から除いた出典（合成データ）。total には含めない
  });

  it("queryable で絞れる。summary は絞り込みに関わらず全出典の集計", async () => {
    const all = (await run("describe_catalog", { what: "sources" })).data;
    const yes = (await run("describe_catalog", { what: "sources", queryable: true })).data;
    const no = (await run("describe_catalog", { what: "sources", queryable: false })).data;
    const s = all.summary as { queryable: number; not_queryable: number };
    expect((yes.sources as Row[]).length).toBe(s.queryable);
    expect((no.sources as Row[]).length).toBe(s.not_queryable);
    expect(yes.summary).toEqual(all.summary);
  });

  it("search_registry(kind=source) の行も同じ形", async () => {
    const { data } = await run("search_registry", { kind: "source", query: "神奈川" });
    const rows = data.matches as Row[];
    expect(rows.length).toBeGreaterThan(0);
    for (const r of rows) {
      expect(Array.isArray(r.queryable_via), r.source_id).toBe(true);
      expect(Array.isArray(r.records_tables), r.source_id).toBe(true);
      expect("n_source_rows" in r && "unavailable_reason" in r).toBe(true);
    }
  });
});
