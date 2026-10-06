import { describe, expect, it } from "vitest";
import { REGION_TIME } from "@/lib/registry/generated-client";
import { regionTimeZone } from "@/lib/registry/lookup-client";

describe("regionTimeZone（Issue #32-3、registry/region.yaml）", () => {
  it("jp-14 は Asia/Tokyo・+09:00", () => {
    expect(regionTimeZone("jp-14")).toEqual({ tzName: "Asia/Tokyo", utcOffset: "+09:00" });
  });

  it("未知の region は黙って JST に倒さず例外にする", () => {
    expect(() => regionTimeZone("jp-99")).toThrow(/registry\/region\.yaml/);
  });

  it("全 region で tz_name が実在する IANA 名で、宣言した utc_offset と実際のオフセットが一致する", () => {
    expect(REGION_TIME.length).toBeGreaterThan(0);
    // 夏時間の無い地域だけを登録する前提（registry/region.yaml のコメント）。年の2時点で同じ値になることも確かめる。
    for (const r of REGION_TIME) {
      for (const iso of ["2020-01-15T12:00:00Z", "2020-07-15T12:00:00Z"]) {
        const parts = new Intl.DateTimeFormat("en", { timeZone: r.tzName, timeZoneName: "longOffset" }).formatToParts(
          new Date(iso),
        );
        const name = parts.find((p) => p.type === "timeZoneName")?.value ?? "";
        const actual = name === "GMT" ? "+00:00" : name.replace("GMT", "");
        expect(actual, `${r.regionId} ${iso}`).toBe(r.utcOffset);
      }
    }
  });
});
