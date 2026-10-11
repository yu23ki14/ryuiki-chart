import fs from "node:fs";
import path from "node:path";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import type { CubeDb } from "@/lib/cube/db";
import { sqliteCubeDb } from "@/lib/cube/db-sqlite";
import { placeIdOfWatershedId } from "@/lib/cube/grid";
import { handleRpc } from "./server";
import type { McpContext } from "./tools";
import { getWatershedsTool } from "./tools-watersheds";

const REPO = path.resolve(__dirname, "../../../..");
const P = {
  v2: path.join(REPO, "data/db/v2.sqlite"),
  registry: path.join(REPO, "data/db/registry.sqlite"),
  ryuiki: path.join(REPO, "data/db/ryuiki.sqlite"),
};
const GEO = path.join(REPO, "web/public/geo/watersheds.geojson");
const haveReal = [...Object.values(P), GEO].every((p) => fs.existsSync(p));
const AMAMI_039 = "common:place:watershed.dem.amami-039";

type Env = { data: { rows: Record<string, unknown>[]; n_total: number; not_found?: string[]; geojson_url: string; watershed_id_rule: string }; provenance: { source_id: string }[]; truncated: boolean };

describe.skipIf(!haveReal)("get_watersheds（実データ・読み取り専用）", () => {
  let db: CubeDb & { close(): void };
  beforeAll(() => {
    db = sqliteCubeDb(P);
  });
  afterAll(() => db.close());
  const geo = async () => JSON.parse(fs.readFileSync(GEO, "utf8"));
  const tool = getWatershedsTool(geo);
  const run = (args: unknown, origin?: string) => tool.execute(args as never, { db: async () => db, origin } as McpContext) as Promise<Env>;

  it("地域 jp-46: 全 71 流域。属性は D1、河口は GeoJSON から。geojson_url はリクエストのオリジンから組む", async () => {
    const r = await run({ region: "jp-46", limit: 500 }, "https://example.test");
    expect(r.data.rows).toHaveLength(71);
    expect(r.data.geojson_url).toBe("https://example.test/geo/watersheds.geojson");
    const w = r.data.rows.find((x) => x.place_id === AMAMI_039)!;
    expect(w).toMatchObject({ region: "jp-46", name: "役勝川", unit_kind: "basin", main_rivers: "役勝川|名称不明", source_id: "gsi_dem_watersheds_amami" });
    expect(w.area_km2 as number).toBeCloseTo(96.546567, 5);
    expect(w.outlet_lat as number).toBeCloseTo(28.250297, 5);
    expect(w.geometry).toBeUndefined();
    expect(r.provenance.map((p) => p.source_id)).toEqual(["gsi_dem_watersheds_amami"]);
  });

  it("origin が無ければ相対パス。神奈川の流域は outlet が null、unit_kind も null", async () => {
    const r = await run({ place_ids: ["common:place:watershed.nlni.83030-0001"] });
    expect(r.data.geojson_url).toBe("/geo/watersheds.geojson");
    expect(r.data.rows[0]).toMatchObject({ region: "jp-14", name: "多摩川", outlet_lat: null, unit_kind: null, source_id: "nlni_w12_watersheds" });
  });

  it("include_geometry は place_ids 指定時だけ。GeoJSON の geometry のまま。未知の place_id は not_found", async () => {
    await expect(run({ include_geometry: true })).rejects.toThrow(/geojson_url/);
    const r = await run({ place_ids: [AMAMI_039, "common:place:watershed.dem.nope"], include_geometry: true });
    expect(r.data.rows).toHaveLength(1);
    expect((r.data.rows[0].geometry as { type: string }).type).toMatch(/Polygon/);
    expect(r.data.not_found).toEqual(["common:place:watershed.dem.nope"]);
  });

  it("GeoJSON の watershed_id から place_id への規則が全 448 面で D1 の place に当たる", async () => {
    const r = await run({ limit: 500 });
    const ids = new Set(r.data.rows.map((x) => x.place_id));
    const fc = await geo();
    const missing = fc.features.map((f: { properties: { watershed_id: string } }) => placeIdOfWatershedId(f.properties.watershed_id)).filter((id: string) => !ids.has(id));
    expect(missing).toEqual([]);
    expect(r.data.n_total).toBeGreaterThanOrEqual(448);
  });

  it("MCP 経由: 入力エラーは isError、未知キーは strict で弾く", async () => {
    const ctx: McpContext = { db: async () => db };
    const call = async (args: unknown) =>
      (await handleRpc({ jsonrpc: "2.0", id: 1, method: "tools/call", params: { name: "get_watersheds", arguments: args } }, ctx))!.result as { isError: boolean };
    expect((await call({ include_geometry: true })).isError).toBe(true);
    expect((await call({ foo: 1 })).isError).toBe(true);
    expect((await call({ place_ids: Array.from({ length: 21 }, (_, i) => `x${i}`) })).isError).toBe(true);
  });
});
