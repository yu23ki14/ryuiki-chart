import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { MCP_TOOLS } from "./tools";
import { OBSERVATION_SOURCE_IDS, OCCURRENCE_SOURCE_IDS, RECORD_SOURCE_IDS } from "@/lib/cube";
import { FIND_DATASET_SOURCE_IDS } from "@/lib/catalog-search";
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
  record_sets: string[];
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
      expect(a.queryableVia.includes("get_observations"), id).toBe(OBSERVATION_SOURCE_IDS.includes(id));
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
    for (const t of ["external_dataset", "external_resource"]) expect(defined.has(t), t).toBe(true); // find_datasets の表
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
    expect(rows).toHaveLength(SOURCE_META.length - 1); // 置き換え済み（gbif_kanagawa）は一覧から除く
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
    expect(summary.by_tool.find_datasets).toBe(FIND_DATASET_SOURCE_IDS.length);
    expect(summary.excluded).toEqual({ synthetic: 1, superseded: 1 }); // 一覧から除いた出典（合成データ・置き換え済みの gbif_kanagawa）。total には含めない
    expect(rows.map((r) => r.source_id)).not.toContain("gbif_kanagawa"); // 一覧と total からだけ除く
    expect(SOURCE_META.map((m) => m.sourceId)).toContain("gbif_kanagawa"); // SOURCE_META には残る（search_registry・来歴・superseded_by の案内）
  });

  it("行政文書の表として値が引ける出典は queryable_via が get_records(document_cells) で、doc_id と有効なセル数を持つ。summary の queryable に数える", async () => {
    const { data } = await run("describe_catalog", { what: "sources" });
    const rows = data.sources as (Row & { n_source_rows_basis: string; document_ids: string[] })[];
    const docRows = rows.filter((r) => r.queryable_via.includes("get_records(document_cells)"));
    expect(docRows.length).toBeGreaterThan(0);
    const seen = new Set<string>();
    for (const r of docRows) {
      expect(r.queryable_via, r.source_id).toEqual(["get_records(document_cells)"]);
      expect(r.record_sets, r.source_id).toEqual([]);
      expect(r.n_source_rows_basis, r.source_id).toBe("document_cells");
      expect(r.n_source_rows, r.source_id).toBeGreaterThan(0);
      expect(r.unavailable_reason, r.source_id).toBeNull();
      expect(r.document_ids.length, r.source_id).toBeGreaterThan(0);
      for (const d of r.document_ids) {
        expect(seen.has(d), `${d} が複数の出典にある`).toBe(false);
        seen.add(d);
      }
    }
    // 行政文書の抽出済みの出典（PDF のままではない）
    for (const id of ["biodic_6th_kanagawa_report", "ckan_pdf_choju_higai", "kasen_kokusei_sagami", "kanagawa_rdb2006_animals", "kagoshima_umigame_amami"]) {
      expect(docRows.map((r) => r.source_id), id).toContain(id);
    }
    // 値の引けない文書の出典は残る（PDF のまま）
    expect(rows.find((r) => r.source_id === "amami_tourism_plans_amami")?.unavailable_reason).toBe("pdf_document");
    expect(rows.find((r) => r.source_id === "moe_redlist")?.unavailable_reason).toBe("not_in_d1");
    expect(docRows.filter((r) => r.unavailable_reason)).toEqual([]);
    const summary = data.summary as { by_tool: Record<string, number> };
    expect(summary.by_tool["get_records(document_cells)"]).toBe(docRows.length);
  });

  it("外部ポータルの目録 7 出典は queryable_via に find_datasets が付き、n_source_rows は目録の件数（basis=catalog_datasets）", async () => {
    const { data } = await run("describe_catalog", { what: "sources" });
    const rows = (data.sources as (Row & { n_source_rows_basis: string })[]).filter((r) => r.queryable_via.includes("find_datasets"));
    expect(rows.map((r) => r.source_id).sort()).toEqual([
      "ckan_bodik_kanagawa", "ckan_kanagawa_pref", "ckan_sagamihara", "ckan_yokohama",
      "estat_agri_census_kanagawa", "estat_census_population_kanagawa", "estat_shozaiki_kanagawa",
    ]);
    for (const r of rows) {
      expect(r.queryable_via, r.source_id).toEqual(["find_datasets"]);
      expect(r.n_source_rows_basis, r.source_id).toBe("catalog_datasets");
      expect(r.n_source_rows, r.source_id).toBeGreaterThan(0);
      expect(r.unavailable_reason, r.source_id).toBeNull();
    }
    expect(Object.fromEntries(rows.map((r) => [r.source_id, r.n_source_rows]))).toMatchObject({
      estat_agri_census_kanagawa: 5, estat_census_population_kanagawa: 1, estat_shozaiki_kanagawa: 1,
    });
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

  it("置き換え済みの出典は search_registry で引け、superseded_by で後継を案内する（一覧・total からは除く）", async () => {
    const { data } = await run("search_registry", { kind: "source", query: "gbif_kanagawa" });
    const hit = (data.matches as (Row & { superseded_by: string | null })[]).find((r) => r.source_id === "gbif_kanagawa");
    expect(hit?.superseded_by).toBe("gbif_kanagawa_occurrences");
    expect(hit?.unavailable_reason).toBe("superseded");
  });

  it("search_registry(kind=source) の行も同じ形", async () => {
    const { data } = await run("search_registry", { kind: "source", query: "神奈川" });
    const rows = data.matches as Row[];
    expect(rows.length).toBeGreaterThan(0);
    for (const r of rows) {
      expect(Array.isArray(r.queryable_via), r.source_id).toBe(true);
      expect(Array.isArray(r.record_sets), r.source_id).toBe(true);
      expect("n_source_rows" in r && "unavailable_reason" in r).toBe(true);
    }
  });
});
