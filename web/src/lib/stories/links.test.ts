import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { AMAMI_STORY_HREF, showAmamiStory } from "./links";

describe("奄美の物語への導線", () => {
  it("region=jp-46 のときだけ出す（全体・神奈川・不正値では出さない）", () => {
    expect(showAmamiStory("jp-46")).toBe(true);
    for (const r of ["all", "jp-14", "", "x"]) expect(showAmamiStory(r)).toBe(false);
  });
  it("リンク先は固定の /stories/amami?region=jp-46", () => {
    expect(AMAMI_STORY_HREF).toBe("/stories/amami?region=jp-46");
  });
  it("SiteNav・HomeHighlights とも showAmamiStory で出し分けている", () => {
    for (const f of ["src/components/SiteNav.tsx", "src/components/HomeHighlights.tsx"]) {
      const src = fs.readFileSync(path.resolve(__dirname, "../../..", f), "utf8");
      expect(src, f).toMatch(/showAmamiStory\(region\)/);
    }
  });
});
