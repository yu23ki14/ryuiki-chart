import Database from "better-sqlite3";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { applyMigrations, wrapSqlite } from "@/lib/cube/__fixtures__/cube-fixture";

vi.mock("server-only", () => ({}));

let raw: Database.Database;
vi.mock("@/lib/cube", async (orig) => ({
  ...(await orig<typeof import("@/lib/cube")>()),
  d1CubeDb: async () => wrapSqlite(raw),
}));

import { aiTools } from "./tools";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const run = (input: unknown) => (aiTools.get_records.execute as any)(input, { toolCallId: "t", messages: [] }) as Promise<any>;

beforeEach(() => {
  raw = new Database(":memory:");
  applyMigrations(raw);
});
afterEach(() => raw.close());

describe("get_records（AI）", () => {
  it("行は予算に合わせて間引かず、行数を減らして next_after で続きが取れる（欠落なし）", async () => {
    const ins = raw.prepare("INSERT INTO protected_areas (area_id, name_ja, note_ja, source_id) VALUES (?,?,?,?)");
    const big = "あ".repeat(2000);
    for (let i = 0; i < 60; i++) ins.run(`a${String(i).padStart(3, "0")}`, `区${i}`, big, "hiratsuka_parks");
    const seen: string[] = [];
    let after: string | undefined;
    for (let guard = 0; guard < 100; guard++) {
      const r = await run({ source_id: "hiratsuka_parks", limit: 50, after });
      expect(JSON.stringify(r.data).length).toBeLessThan(24 * 1024);
      seen.push(...r.data.rows.map((x: { area_id: string }) => x.area_id));
      if (!r.truncated) break;
      expect(r.data.next_after).toBe(seen[seen.length - 1]);
      after = r.data.next_after;
    }
    expect(seen).toHaveLength(60);
    expect(new Set(seen).size).toBe(60);
  });

  it("ジオメトリは間引かない。予算を超えるなら省いてその旨を返す", async () => {
    raw.prepare("INSERT INTO vegetation_polygons (feature_id, legend_name_ja, source_id, geometry_geojson) VALUES (?,?,?,?)").run(
      "v1",
      "ブナ",
      "biodic_veg2024_kanagawa",
      JSON.stringify({ type: "Polygon", coordinates: [Array.from({ length: 3000 }, (_, i) => [139 + i / 1e5, 35 + i / 1e5])] }),
    );
    const r = await run({ source_id: "biodic_veg2024_kanagawa", id: "v1", include_geometry: true });
    expect(r.data.geometry_omitted).toBeTruthy();
    expect(r.data.rows[0]).not.toHaveProperty("geometry_geojson");
    raw.prepare("UPDATE vegetation_polygons SET geometry_geojson=?").run(JSON.stringify({ type: "Point", coordinates: [139, 35] }));
    const ok = await run({ source_id: "biodic_veg2024_kanagawa", id: "v1", include_geometry: true });
    expect(ok.data.rows[0].geometry_geojson).toEqual({ type: "Point", coordinates: [139, 35] });
    expect(ok.data.geometry_omitted).toBeUndefined();
  });

  it("入力エラーは例外にせず data.error で返す", async () => {
    const r = await run({ source_id: "dams_kanagawa", record_set: "mammal_mesh" });
    expect(r.data.error).toBeTruthy();
  });
});
