import Database from "better-sqlite3";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { applyMigrations, wrapSqlite } from "@/lib/cube/__fixtures__/cube-fixture";
import { McpInputError } from "./errors";
import { FIND_DATASETS_MCP_BYTE_BUDGET } from "@/lib/catalog-search";
import { findDatasetsTool } from "./tools-find-datasets";

let raw: Database.Database;
const ctx = () => ({ db: async () => wrapSqlite(raw), now: new Date("2026-10-07T00:00:00Z") });
const run = (args: unknown, tool = findDatasetsTool()) => {
  const parsed = (tool.inputSchema as { parse: (a: unknown) => unknown }).parse(args);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return tool.execute(parsed as never, ctx()) as Promise<any>;
};

function add(source: string, id: string, license: string | null, modified: string) {
  raw
    .prepare(
      `INSERT INTO external_dataset (dataset_key, source_id, portal, dataset_id, name, title, description_truncated, license, n_resources, metadata_modified, page_url, api_url, fetched_at)
       VALUES (?,?,?,?,?,?,0,?,1,?,?,?,?)`,
    )
    .run(`${source}:${id}`, source, "ckan", id, `n_${id}`, `河川 ${id}`, license, modified, `https://x.test/dataset/n_${id}`, `https://x.test/api/3/action/package_show?id=${id}`, "2026-08-29T14:40:39");
  raw
    .prepare("INSERT INTO external_resource (resource_key, dataset_key, name, format, direct_url) VALUES (?,?,?,?,?)")
    .run(`${source}:${id}_r`, `${source}:${id}`, "資源", "CSV", `https://x.test/${id}.csv`);
}

beforeEach(() => {
  raw = new Database(":memory:");
  applyMigrations(raw);
  for (let i = 1; i <= 5; i++) add("ckan_kanagawa_pref", `a${i}`, i === 1 ? null : "CC-BY", `2026-0${i}-01T00:00:00`);
  add("ckan_yokohama", "y1", "CC-BY", "2026-09-01T00:00:00");
});
afterEach(() => raw.close());

describe("find_datasets（MCP）", () => {
  it("封筒: provenance は結果に出てくる出典だけ・excluded は 0・n_total（q なし）・offset", async () => {
    const e = await run({ source_id: "ckan_kanagawa_pref", limit: 3 });
    expect(e.data.rows).toHaveLength(3);
    expect(e.data.n_total).toBe(5);
    expect(e.data.offset).toBe(0);
    expect(e.truncated).toBe(true);
    expect(e.provenance.map((p: { source_id: string }) => p.source_id)).toEqual(["ckan_kanagawa_pref"]);
    expect(e.excluded).toMatchObject({ by_license: 0, by_embargo: 0 });
    expect(e.data.rows[0].dataset_key).toBe("ckan_kanagawa_pref:a5"); // 新しい順
  });

  it("q ありは n_total を返さず、truncated を limit+1 件で決める。provenance は複数出典", async () => {
    const e = await run({ q: "河川", limit: 6 });
    expect(e.data).not.toHaveProperty("n_total");
    expect(e.truncated).toBe(false);
    expect(e.provenance.map((p: { source_id: string }) => p.source_id).sort()).toEqual(["ckan_kanagawa_pref", "ckan_yokohama"]);
  });

  it("license が空の行は null で返り、除外されない（ADR-0028）", async () => {
    const e = await run({ id: "ckan_kanagawa_pref:a1" });
    expect(e.data.rows).toHaveLength(1);
    expect(e.data.rows[0].license).toBeNull();
    expect(e.excluded.by_license).toBe(0);
  });

  it("入力エラーは McpInputError（条件なし・資源つきで limit>10）。未知のキーは strict で拒否", async () => {
    await expect(run({})).rejects.toThrow(McpInputError);
    await expect(run({ source_id: "ckan_yokohama", include_resources: true, limit: 50 })).rejects.toThrow(McpInputError);
    expect(() => run({ q: "河川", select: "*" })).toThrow();
  });

  it("結果が空のときは provenance も空（出典を勝手に載せない）", async () => {
    const e = await run({ q: "存在しない語" });
    expect(e.data.rows).toEqual([]);
    expect(e.provenance).toEqual([]);
  });

  it("応答が大きいときは行を先頭から減らし、truncated と next_offset で続きを取る（欠落・重複なし）", async () => {
    const big = "あ".repeat(800);
    for (let i = 0; i < 120; i++) {
      add("ckan_sagamihara", `big${String(i).padStart(3, "0")}`, "CC-BY", `2026-01-01T00:00:${String(i % 60).padStart(2, "0")}`);
      raw.prepare("UPDATE external_dataset SET description = ? WHERE dataset_key = ?").run(big, `ckan_sagamihara:big${String(i).padStart(3, "0")}`);
    }
    const seen: string[] = [];
    let offset = 0;
    for (let guard = 0; guard < 50; guard++) {
      const e = await run({ source_id: "ckan_sagamihara", limit: 100, offset });
      expect(JSON.stringify(e.data).length).toBeLessThan(FIND_DATASETS_MCP_BYTE_BUDGET);
      seen.push(...e.data.rows.map((x: { dataset_key: string }) => x.dataset_key));
      if (!e.truncated) {
        expect(e.data).not.toHaveProperty("next_offset");
        break;
      }
      expect(e.data.next_offset).toBe(seen.length);
      offset = seen.length;
    }
    expect(seen).toHaveLength(120);
    expect(new Set(seen).size).toBe(120);
  });

  it("modified_since は metadata_modified が無い行を除き、件数と理由を data に出す", async () => {
    raw.prepare("UPDATE external_dataset SET metadata_modified = NULL WHERE dataset_key = 'ckan_kanagawa_pref:a2'").run();
    const e = await run({ source_id: "ckan_kanagawa_pref", modified_since: "2026-01-01" });
    expect(e.data.rows.map((r: { dataset_key: string }) => r.dataset_key)).not.toContain("ckan_kanagawa_pref:a2");
    expect(e.data.excluded_no_modified).toBe(1);
    expect(e.data.excluded_reason).toContain("metadata_modified");
    expect((await run({ source_id: "ckan_kanagawa_pref" })).data).not.toHaveProperty("excluded_no_modified");
  });
});
