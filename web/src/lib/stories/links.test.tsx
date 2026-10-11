import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

let search = "";
vi.mock("next/navigation", () => ({
  usePathname: () => "/",
  useSearchParams: () => new URLSearchParams(search),
  useRouter: () => ({ push: () => {}, replace: () => {} }),
}));

import { HomeHighlights } from "@/components/HomeHighlights";
import { SiteNav } from "@/components/SiteNav";
import { AMAMI_STORY_HREF, AMAMI_STORY_LABEL, showAmamiStory } from "./links";

const nav = (region: string) => {
  search = region === "all" ? "" : `region=${region}`;
  return renderToStaticMarkup(<SiteNav />);
};
const home = (region: "all" | "jp-14" | "jp-46") =>
  renderToStaticMarkup(<HomeHighlights longitudinal={[]} landuse={[]} redlist={[]} effort={[]} region={region} />);

describe("奄美の物語への導線（奄美を選んだときだけ）", () => {
  it("showAmamiStory は region=jp-46 だけ", () => {
    expect(showAmamiStory("jp-46")).toBe(true);
    for (const r of ["all", "jp-14", "", "x"]) expect(showAmamiStory(r)).toBe(false);
  });
  it("SiteNav: jp-46 で出て、jp-14・全体では出ない", () => {
    expect(nav("jp-46")).toContain(AMAMI_STORY_HREF.replace(/&/g, "&amp;"));
    expect(nav("jp-14")).not.toContain("/stories/amami");
    expect(nav("all")).not.toContain("/stories/amami");
  });
  it("HomeHighlights: jp-46 で出て、jp-14・全体では出ない", () => {
    expect(home("jp-46")).toContain(AMAMI_STORY_LABEL);
    expect(home("jp-14")).not.toContain("/stories/amami");
    expect(home("all")).not.toContain("/stories/amami");
  });
});
