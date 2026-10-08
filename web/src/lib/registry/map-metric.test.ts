import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import path from "node:path";
import { MAP_METRICS } from "./generated-client";

// 地図指標の id は API の properties のキー名そのもの。yaml の id を変えたらここで落とす。
const ROUTE = (name: string) => readFileSync(path.join(__dirname, "../../app/api/geo", name, "route.ts"), "utf-8");

describe("MAP_METRICS", () => {
  for (const [scope, route] of [["watershed", "watersheds"], ["mesh", "mesh"]] as const) {
    it(`${scope} の id は /api/geo/${route} の properties に載る`, () => {
      const src = ROUTE(route);
      for (const m of MAP_METRICS.filter((x) => x.scope === scope)) {
        // meshの "n" は短いので `n:` の行頭一致で見る
        expect(src, m.id).toMatch(new RegExp(`^\\s*${m.id}:`, "m"));
      }
    });
  }
  it("既定の指標が存在する", () => {
    expect(MAP_METRICS.some((m) => m.scope === "watershed" && m.id === "org_density")).toBe(true);
    expect(MAP_METRICS.some((m) => m.scope === "mesh" && m.id === "species_n")).toBe(true);
  });
});
