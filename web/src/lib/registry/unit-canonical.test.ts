import { describe, expect, it } from "vitest";
import { canonicalOf, unitBasis } from "./lookup";
import { GENERATED_UNITS, GENERATED_VARIABLES } from "./generated";

describe("正準単位・単位の根拠（Issue #31）", () => {
  it("canonicalOf: 換算する単位・しない単位・不明", () => {
    expect(canonicalOf("common:unit:ppb")).toEqual({ unitId: "common:unit:ppm", symbol: "ppm", scale: 0.001 });
    expect(canonicalOf("common:unit:mg_per_l")).toEqual({ unitId: "common:unit:mg_per_l", symbol: "mg/L", scale: 1 });
    expect(canonicalOf(null)).toBeUndefined();
    expect(canonicalOf("common:unit:nope")).toBeUndefined();
  });

  it("全 unit の正準は実在し、正準自身は自分を指して倍率1", () => {
    const ids = new Set(GENERATED_UNITS.map((u) => u.unitId));
    for (const u of GENERATED_UNITS) {
      expect(ids.has(u.canonicalUnitId)).toBe(true);
      const c = GENERATED_UNITS.find((x) => x.unitId === u.canonicalUnitId)!;
      expect(c.canonicalUnitId).toBe(c.unitId);
      expect(c.scaleToCanonical).toBe(1);
    }
  });

  it("unitBasis: pH は registry、BOD は source、流量は registry、単位の無い変数は null", () => {
    expect(unitBasis("common:variable:water.ph")).toBe("registry");
    expect(unitBasis("common:variable:water.bod")).toBe("source");
    expect(unitBasis("common:variable:hydro.flow")).toBe("registry");
    const noUnit = GENERATED_VARIABLES.find((v) => !v.unitId)!;
    expect(unitBasis(noUnit.variableId)).toBeNull();
  });
});
