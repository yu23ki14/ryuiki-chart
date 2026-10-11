import Database from "better-sqlite3";
import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { applyMigrations, wrapSqlite } from "@/lib/cube/__fixtures__/cube-fixture";
import { A45_BBOX_MARGIN, HAZARD_BBOX_MARGIN, HAZARD_MAX, parseBbox } from "@/lib/geo-overlay";

let raw: Database.Database;
const SQUARE = (lon: number, lat: number, d: number) =>
  JSON.stringify({ type: "Polygon", coordinates: [[[lon - d, lat - d], [lon + d, lat - d], [lon + d, lat + d], [lon - d, lat + d], [lon - d, lat - d]]] });

beforeEach(() => {
  raw = new Database(":memory:");
  applyMigrations(raw);
  vi.resetModules();
  vi.doMock("@/lib/cube", async (orig) => ({ ...(await orig<typeof import("@/lib/cube")>()), d1CubeDb: async () => wrapSqlite(raw) }));
});
afterEach(() => {
  raw.close();
  vi.doUnmock("@/lib/cube");
});

interface Body {
  type: string;
  truncated: boolean;
  features: { properties: Record<string, unknown> }[];
  sources: { source_id: string; note: string | null; license: string | null }[];
}
const json = async (r: Response) => (await r.json()) as Body;
const get = (path: string) => new NextRequest(`http://localhost:3000${path}`);
const HZ = "bodik_kagoshima_dosha_amami";
const hz = (id: string, lat: number, lon: number, kind = "warning", ph = "debris_flow", geom: string | null = SQUARE(lon, lat, 0.001)) =>
  raw
    .prepare("INSERT INTO hazard_zones (zone_id, zone_kind_code, zone_kind_ja, phenomenon_code, phenomenon_ja, centroid_lat, centroid_lon, geometry_geojson, source_id) VALUES (?,?,?,?,?,?,?,?,?)")
    .run(id, kind, kind, ph, ph, lat, lon, geom, HZ);

describe("parseBbox", () => {
  it("正しい 4 つ組だけ通す", () => {
    expect(parseBbox("129.4,28.2,129.6,28.4")).toEqual({ w: 129.4, s: 28.2, e: 129.6, n: 28.4 });
    for (const v of [null, "", "1,2,3", "a,b,c,d", "2,0,1,1", "0,2,1,1", "0,0,1,,", "0,0,200,1"]) expect(parseBbox(v), String(v)).toBeNull();
  });
});

describe("GET /api/geo/hazard-zones", () => {
  it("bbox 無し・不正は 400。kind・phenomenon が許可外でも 400", async () => {
    const { GET } = await import("./hazard-zones/route");
    expect((await GET(get("/api/geo/hazard-zones"))).status).toBe(400);
    expect((await GET(get("/api/geo/hazard-zones?bbox=1,2"))).status).toBe(400);
    expect((await GET(get("/api/geo/hazard-zones?bbox=129,28,130,29&kind=x"))).status).toBe(400);
    expect((await GET(get("/api/geo/hazard-zones?bbox=129,28,130,29&phenomenon=x"))).status).toBe(400);
  });

  it("bbox（代表点＋余白）で絞り、絞り込み・Cache-Control・sources.note が載る", async () => {
    hz("in", 28.3, 129.5);
    hz("edge", 28.3, 129.5 + 0.1 + HAZARD_BBOX_MARGIN - 0.001); // 余白の内側
    hz("out", 28.3, 129.5 + 0.1 + HAZARD_BBOX_MARGIN + 0.01);
    hz("sp", 28.31, 129.5, "special_warning", "steep_slope");
    hz("nogeo", 28.32, 129.5, "warning", "debris_flow", null);
    const { GET } = await import("./hazard-zones/route");
    const res = await GET(get("/api/geo/hazard-zones?bbox=129.4,28.2,129.6,28.4"));
    expect(res.status).toBe(200);
    expect(res.headers.get("Cache-Control")).toBe("public, max-age=300");
    const body = await json(res);
    expect(body.type).toBe("FeatureCollection");
    expect(body.truncated).toBe(false);
    expect(body.features.map((f) => f.properties.zone_id)).toEqual(["edge", "in", "sp"]); // zone_id 昇順。ジオメトリ無しは落ちる
    expect(body.sources[0].source_id).toBe(HZ);
    expect(body.sources[0].note).toContain("特別警戒区域は警戒区域の内側");
    expect(body.sources[0].license).toBeTruthy();
    const kind = await json(await GET(get("/api/geo/hazard-zones?bbox=129.4,28.2,129.6,28.4&kind=special_warning")));
    expect(kind.features.map((f) => f.properties.zone_id)).toEqual(["sp"]);
    const ph = await json(await GET(get("/api/geo/hazard-zones?bbox=129.4,28.2,129.6,28.4&phenomenon=steep_slope")));
    expect(ph.features).toHaveLength(1);
  });

  it(`上限 ${HAZARD_MAX} を超えたら truncated`, async () => {
    const ins = raw.prepare("INSERT INTO hazard_zones (zone_id, centroid_lat, centroid_lon, geometry_geojson, source_id) VALUES (?,?,?,?,?)");
    raw.transaction(() => {
      for (let i = 0; i < HAZARD_MAX + 1; i++) ins.run(`z${String(i).padStart(5, "0")}`, 28.3, 129.5, SQUARE(129.5, 28.3, 0.0001), HZ);
    })();
    const { GET } = await import("./hazard-zones/route");
    const body = await json(await GET(get("/api/geo/hazard-zones?bbox=129.4,28.2,129.6,28.4")));
    expect(body.truncated).toBe(true);
    expect(body.features).toHaveLength(HAZARD_MAX);
  });
});

describe("GET /api/geo/protected-areas/polygons", () => {
  const pa = (id: string, src: string, code: string, lat: number, lon: number) =>
    raw
      .prepare("INSERT INTO protected_areas (area_id, name_ja, category_code, category_ja, area_ha, lat, lon, geometry_geojson, source_id) VALUES (?,?,?,?,?,?,?,?,?)")
      .run(id, id, code, code, 1.5, lat, lon, SQUARE(lon, lat, 0.01), src);

  it("source_id が奄美 3 つ以外・無しは 400。A45 は bbox 必須", async () => {
    const { GET } = await import("./protected-areas/polygons/route");
    expect((await GET(get("/api/geo/protected-areas/polygons"))).status).toBe(400);
    expect((await GET(get("/api/geo/protected-areas/polygons?source_id=hiratsuka_parks"))).status).toBe(400);
    expect((await GET(get("/api/geo/protected-areas/polygons?source_id=nlni_a45_forest_amami"))).status).toBe(400);
    expect((await GET(get("/api/geo/protected-areas/polygons?source_id=nlni_a10_natparks_amami&bbox=bad"))).status).toBe(400);
  });

  it("A10 は bbox 無しで全件・他の出典の行は混ざらない。note と Cache-Control が載る", async () => {
    pa("p1", "nlni_a10_natparks_amami", "natpark_area", 28.3, 129.5);
    pa("p2", "nlni_a10_natparks_amami", "natpark_special", 28.4, 129.6);
    pa("w1", "nlni_a15_wildlife_amami", "wildlife_reserve", 28.3, 129.5);
    pa("k1", "hiratsuka_parks", "city_park", 35.3, 139.3);
    const { GET } = await import("./protected-areas/polygons/route");
    const res = await GET(get("/api/geo/protected-areas/polygons?source_id=nlni_a10_natparks_amami"));
    expect(res.headers.get("Cache-Control")).toBe("public, max-age=300");
    const body = await json(res);
    expect(body.features.map((f) => f.properties.area_id)).toEqual(["p1", "p2"]);
    expect(body.features[0].properties).toMatchObject({ category_code: "natpark_area", area_ha: 1.5 });
    expect(body.truncated).toBe(false);
    expect(body.sources[0].note).toContain("入れ子");
  });

  it(`A45 は bbox（代表点＋${A45_BBOX_MARGIN} 度）で絞る`, async () => {
    pa("f_in", "nlni_a45_forest_amami", "national_forest", 28.3, 129.5);
    pa("f_edge", "nlni_a45_forest_amami", "national_forest", 28.3, 129.6 + A45_BBOX_MARGIN - 0.001);
    pa("f_out", "nlni_a45_forest_amami", "national_forest", 28.3, 129.6 + A45_BBOX_MARGIN + 0.01);
    const { GET } = await import("./protected-areas/polygons/route");
    const body = await json(await GET(get("/api/geo/protected-areas/polygons?source_id=nlni_a45_forest_amami&bbox=129.4,28.2,129.6,28.4")));
    expect(body.features.map((f) => f.properties.area_id)).toEqual(["f_edge", "f_in"]);
  });
});
