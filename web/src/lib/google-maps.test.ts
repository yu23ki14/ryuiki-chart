import { describe, expect, it } from "vitest";
import { googleMapsUrl } from "./google-maps";

describe("googleMapsUrl", () => {
  it("緯度,経度の順で小数6桁に整えた検索 URL を作る", () => {
    expect(googleMapsUrl(28.4635, 129.66458333)).toBe(
      "https://www.google.com/maps/search/?api=1&query=28.463500,129.664583",
    );
  });
  it("0 は有効な座標", () => {
    expect(googleMapsUrl(0, 0)).toBe("https://www.google.com/maps/search/?api=1&query=0.000000,0.000000");
  });
  it("極小値でも指数表記にならない", () => {
    expect(googleMapsUrl(1e-7, 129)).toBe("https://www.google.com/maps/search/?api=1&query=0.000000,129.000000");
  });
  it("null / undefined / 非有限は null", () => {
    expect(googleMapsUrl(null, 129)).toBeNull();
    expect(googleMapsUrl(28, null)).toBeNull();
    expect(googleMapsUrl(undefined, undefined)).toBeNull();
    expect(googleMapsUrl(NaN, 129)).toBeNull();
    expect(googleMapsUrl(28, Infinity)).toBeNull();
  });
});
