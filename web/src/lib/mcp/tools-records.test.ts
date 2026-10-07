import Database from "better-sqlite3";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { applyMigrations, wrapSqlite } from "@/lib/cube/__fixtures__/cube-fixture";
import { McpInputError } from "./tools";
import { getRecordsTool } from "./tools-records";

let raw: Database.Database;
const ctx = () => ({ db: async () => wrapSqlite(raw), now: new Date("2026-10-07T00:00:00Z") });
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const run = (args: unknown, tool = getRecordsTool()) => tool.execute(args as never, ctx()) as Promise<any>;

beforeEach(() => {
  raw = new Database(":memory:");
  applyMigrations(raw);
  const ins = raw.prepare("INSERT INTO sites (site_id, name, source_id) VALUES (?,?,?)");
  for (let i = 1; i <= 5; i++) ins.run(`d${i}`, `ダム${i}`, "dams_kanagawa");
  ins.run("j1", "気象", "jma_stations_kanagawa");
});
afterEach(() => raw.close());

describe("get_records（MCP）", () => {
  it("封筒: 出典 1 件の provenance・excluded は 0・table と rows と offset", async () => {
    const e = await run({ source_id: "dams_kanagawa", limit: 3 });
    expect(e.data.table).toBe("sites");
    expect(e.data.rows.map((r: { site_id: string }) => r.site_id)).toEqual(["d1", "d2", "d3"]);
    expect(e.data.offset).toBe(0);
    expect(e.truncated).toBe(true);
    expect(e.provenance).toHaveLength(1);
    expect(e.provenance[0].source_id).toBe("dams_kanagawa");
    expect(e.excluded).toMatchObject({ by_license: 0, by_embargo: 0 });
    expect(e.data).not.toHaveProperty("n_total");
  });

  it("offset で続きが取れ、最後は truncated=false", async () => {
    const e = await run({ source_id: "dams_kanagawa", limit: 3, offset: 3 });
    expect(e.data.rows.map((r: { site_id: string }) => r.site_id)).toEqual(["d4", "d5"]);
    expect(e.truncated).toBe(false);
  });

  it("n_total は q・id なしのときだけ、渡された事前計算の値を載せる", async () => {
    const tool = getRecordsTool({ nTotal: (s) => (s === "dams_kanagawa" ? 5 : null) });
    expect((await run({ source_id: "dams_kanagawa", limit: 1 }, tool)).data.n_total).toBe(5);
    expect((await run({ source_id: "dams_kanagawa", q: "ダム" }, tool)).data).not.toHaveProperty("n_total");
    expect((await run({ source_id: "dams_kanagawa", id: "d1" }, tool)).data).not.toHaveProperty("n_total");
  });

  it("入力エラーは McpInputError（ジオメトリの一覧・出典に無い表）", async () => {
    await expect(run({ source_id: "biodic_veg2024_kanagawa", include_geometry: true })).rejects.toThrow(McpInputError);
    await expect(run({ source_id: "dams_kanagawa", table: "mammal_mesh" })).rejects.toThrow(McpInputError);
  });

  it("入力スキーマは strict。source_id なし・未知のキー・許可リスト外の指定は拒否", () => {
    const t = getRecordsTool();
    expect(t.inputSchema.safeParse({}).success).toBe(false);
    expect(t.inputSchema.safeParse({ source_id: "dams_kanagawa", sql: "select 1" }).success).toBe(false);
    expect(t.inputSchema.safeParse({ source_id: "dams_kanagawa", columns: ["geohash"] }).success).toBe(false);
    expect(t.inputSchema.safeParse({ source_id: "dams_kanagawa" }).success).toBe(true);
    expect(JSON.stringify(t.inputSchema)).not.toContain("prefixItems");
  });
});
