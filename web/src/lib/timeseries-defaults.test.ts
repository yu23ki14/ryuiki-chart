import { describe, expect, it } from "vitest";
import { pickVariable, pickWater } from "./timeseries-defaults";

const vars = [
  { variableId: "common:variable:water.ph", n: 774 },
  { variableId: "common:variable:water.cod", n: 692 },
];

describe("pickVariable", () => {
  it("希望が一覧にあればそれ", () => {
    expect(pickVariable(vars, ["common:variable:water.cod", null])).toBe("common:variable:water.cod");
  });
  it("希望が地域に無ければ次の候補（地域の既定）", () => {
    expect(pickVariable(vars, ["common:variable:water.bod", "common:variable:water.cod"])).toBe("common:variable:water.cod");
  });
  it("候補がすべて地域に無ければ件数最多", () => {
    expect(pickVariable(vars, ["common:variable:water.bod", undefined])).toBe("common:variable:water.ph");
  });
  it("一覧が空なら最初の候補", () => {
    expect(pickVariable([], [null, "common:variable:water.bod"])).toBe("common:variable:water.bod");
  });
});

describe("pickWater", () => {
  const ws = [{ name: "奄美大島本島海域" }, { name: "名瀬港海域（２）" }];
  it("希望があればそれ", () => expect(pickWater(ws, "名瀬港海域（２）")).toBe("名瀬港海域（２）"));
  it("他地域の水域は選ばない", () => expect(pickWater(ws, "境川（１）")).toBe("奄美大島本島海域"));
  it("空なら null", () => expect(pickWater([], "境川（１）")).toBeNull());
});
