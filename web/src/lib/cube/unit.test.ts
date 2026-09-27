import { describe, expect, it } from "vitest";
import { unitSymbol } from "@/lib/registry/lookup";
import { unitLabel } from "./unit";

describe("unitLabel", () => {
  it("既知の unit_id は unitSymbol と同じ値", () => {
    expect(unitLabel("common:unit:mg_per_l")).toBe(unitSymbol("common:unit:mg_per_l"));
    expect(unitLabel("common:unit:mg_per_l")).toBe("mg/L");
  });

  it("null は null（単位不明。呼び出し側の注記に任せる）", () => {
    expect(unitLabel(null)).toBeNull();
  });

  it("無次元の unit（symbol=null）は空文字（unitSymbol の既定挙動を継承する）", () => {
    expect(unitLabel("common:unit:dimensionless")).toBe("");
  });

  it("存在しない unit_id は null", () => {
    expect(unitLabel("common:unit:no-such-unit")).toBeNull();
  });
});
