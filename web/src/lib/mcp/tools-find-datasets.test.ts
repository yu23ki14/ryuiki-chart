import Database from "better-sqlite3";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { applyMigrations, wrapSqlite } from "@/lib/cube/__fixtures__/cube-fixture";
import { McpInputError } from "./errors";
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
});
