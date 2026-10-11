import { describe, expect, it } from "vitest";
import {
  OVERLAYS,
  hazardLayerSpecs,
  overlayUrl,
  overlaysForRegion,
  parseLayersParam,
  parseViewParam,
  protectedLayerSpecs,
  searchWithLayers,
  snapBbox,
  type Bbox,
} from "./overlay-layers";
import { STATUS } from "@/components/viz/palette";

const hazard = OVERLAYS.find((o) => o.id === "hazard")!;
const a10 = OVERLAYS.find((o) => o.id === "pa_a10")!;
const a45 = OVERLAYS.find((o) => o.id === "pa_a45")!;

describe("layers の URL 往復", () => {
  it("知らない名前と重複は捨て、宣言の順に直す", () => {
    expect(parseLayersParam("pa_a15,foo,hazard,hazard")).toEqual(["hazard", "pa_a15"]);
    expect(parseLayersParam(null)).toEqual([]);
    expect(parseLayersParam("")).toEqual([]);
  });
  it("書いて読むと元に戻り、他のクエリを保つ。空なら layers を消す", () => {
    const qs = searchWithLayers("region=jp-46&x=1", ["pa_a10", "hazard"]);
    expect(new URLSearchParams(qs).get("layers")).toBe("hazard,pa_a10");
    expect(new URLSearchParams(qs).get("region")).toBe("jp-46");
    expect(parseLayersParam(new URLSearchParams(qs).get("layers"))).toEqual(["hazard", "pa_a10"]);
    expect(searchWithLayers(qs, [])).toBe("region=jp-46&x=1");
  });
});

describe("地域の出し分け", () => {
  it("奄美と全体では出て、神奈川では出ない（出典の地域から決まる）", () => {
    expect(overlaysForRegion("jp-46").map((o) => o.id)).toEqual(OVERLAYS.map((o) => o.id));
    expect(overlaysForRegion("all").length).toBe(OVERLAYS.length);
    expect(overlaysForRegion("jp-14")).toEqual([]);
  });
});

describe("bbox の格子丸め", () => {
  it("外向きに丸める", () => {
    expect(snapBbox([129.31, 28.21, 129.62, 28.52])).toEqual([129.3, 28.2, 129.65, 28.55]);
  });
  it("格子上の値はそのまま（浮動小数の誤差で広がらない）", () => {
    expect(snapBbox([129.3, 28.2, 129.65, 28.55])).toEqual([129.3, 28.2, 129.65, 28.55]);
  });
  it("格子内の小さな移動は同じ URL になる（再取得しない）", () => {
    const u = (b: Bbox) => overlayUrl(hazard, { bbox: b, zoom: 12 });
    expect(u([129.31, 28.31, 129.34, 28.34])).toBe(u([129.32, 28.32, 129.345, 28.35]));
    expect(u([129.31, 28.31, 129.34, 28.34])).not.toBe(u([129.41, 28.31, 129.44, 28.34]));
  });
});

describe("取得 URL", () => {
  const view = { bbox: [129.3, 28.3, 129.4, 28.4] as Bbox, zoom: 12 };
  it("zoom 11 未満では hazard を取りに行かない", () => {
    expect(overlayUrl(hazard, { ...view, zoom: 10.9 })).toBe("");
    expect(overlayUrl(hazard, null)).toBe("");
    expect(overlayUrl(hazard, { ...view, zoom: 11 })).toContain("/api/geo/hazard-zones?bbox=");
  });
  it("A10 は bbox なしで常に取る。A45 は bbox 必須", () => {
    expect(overlayUrl(a10, null)).toBe("/api/geo/protected-areas/polygons?source_id=nlni_a10_natparks_amami");
    expect(overlayUrl(a45, null)).toBe("");
    expect(overlayUrl(a45, view)).toBe(
      "/api/geo/protected-areas/polygons?source_id=nlni_a45_forest_amami&bbox=129.3,28.3,129.4,28.4",
    );
  });
});

describe("描画の式", () => {
  it("特別警戒が警戒の後（上）に積まれ、色は STATUS", () => {
    const ls = hazardLayerSpecs("s", ["debris_flow", "steep_slope", "landslide"]);
    const ids = ls.map((l) => l.id);
    expect(ids.indexOf("ry-hazard-fill-special_warning")).toBeGreaterThan(ids.indexOf("ry-hazard-fill-warning"));
    expect(ids.indexOf("ry-hazard-line")).toBeGreaterThan(ids.indexOf("ry-hazard-fill-special_warning"));
    expect((ls[0].spec.paint as Record<string, unknown>)["fill-color"]).toBe(STATUS.warning);
    expect((ls[1].spec.paint as Record<string, unknown>)["fill-color"]).toBe(STATUS.critical);
  });
  it("現象チップ: 全部なら絞らず、一部なら filter に入る", () => {
    expect(JSON.stringify(hazardLayerSpecs("s", ["debris_flow", "steep_slope", "landslide"])[0].spec.filter)).not.toContain("phenomenon_code");
    expect(JSON.stringify(hazardLayerSpecs("s", ["debris_flow"])[0].spec.filter)).toContain("phenomenon_code");
  });
  it("A10 は外側から内側の順に3枚、A45 は面", () => {
    expect(protectedLayerSpecs("pa_a10", "s").map((l) => l.id)).toEqual([
      "ry-pa-a10-natpark_area",
      "ry-pa-a10-natpark_special",
      "ry-pa-a10-natpark_special_protection",
    ]);
    const a = protectedLayerSpecs("pa_a45", "s");
    expect(a).toHaveLength(1);
    expect(a[0].spec.type).toBe("fill");
  });
});

describe("view パラメータ", () => {
  it("lon,lat,zoom を読む", () => {
    expect(parseViewParam("129.49,28.38,12")).toEqual({ center: [129.49, 28.38], zoom: 12 });
  });
  it("不正は null", () => {
    for (const v of [null, "", "1,2", "a,b,c", "129,28,", "129,95,12", "129,28,30", "1,2,3,4"]) expect(parseViewParam(v)).toBeNull();
  });
});
