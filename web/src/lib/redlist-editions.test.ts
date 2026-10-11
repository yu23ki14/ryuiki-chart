import { describe, expect, it } from "vitest";
import { ASSESSMENT_LIST } from "@/lib/registry/generated-client";
import { redlistSourceIds } from "@/lib/cube/source-meta";
import { REGIONS } from "@/lib/region";
import { defaultRedlistYear, redlistEditions } from "./redlist-editions";

describe("redlist-editions", () => {
  it("jp-14（と全体）は神奈川の3版で既定は 2022、jp-46 は鹿児島の1版", () => {
    expect(redlistEditions(undefined).map((e) => e.year)).toEqual([2020, 2022, 2026]);
    expect(redlistEditions("jp-14")).toEqual(redlistEditions(undefined));
    expect(defaultRedlistYear(undefined)).toBe(2022);
    expect(redlistEditions("jp-46").map((e) => e.year)).toEqual([2014]);
    expect(defaultRedlistYear("jp-46")).toBe(2014);
  });
  it("red_list の版を持つ全地域に出典が登録されている", () => {
    for (const r of REGIONS) {
      if (Object.values(ASSESSMENT_LIST).some((l) => l.kind === "red_list" && l.region === r.id)) {
        expect(redlistSourceIds(r.id).length, r.id).toBeGreaterThan(0);
      }
    }
    expect(redlistSourceIds("jp-46")).toEqual(["kagoshima_redlist"]);
  });
});
