import { describe, expect, it } from "vitest";
import { googleMapsUrl } from "./google-maps";

describe("googleMapsUrl", () => {
  it("緯度,経度の順で検索 URL を作る", () => {
    expect(googleMapsUrl(28.37, 129.49)).toBe("https://www.google.com/maps/search/?api=1&query=28.37,129.49");
  });
  it("0 は有効な座標", () => {
    expect(googleMapsUrl(0, 0)).toBe("https://www.google.com/maps/search/?api=1&query=0,0");
  });
  it("null / undefined / 非有限は null", () => {
    expect(googleMapsUrl(null, 129)).toBeNull();
    expect(googleMapsUrl(28, null)).toBeNull();
    expect(googleMapsUrl(undefined, undefined)).toBeNull();
    expect(googleMapsUrl(NaN, 129)).toBeNull();
    expect(googleMapsUrl(28, Infinity)).toBeNull();
  });
});
