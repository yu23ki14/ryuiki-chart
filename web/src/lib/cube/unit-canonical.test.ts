import { describe, expect, it } from "vitest";
import { canonicalizeCells, toCanonical } from "./unit";

describe("正準単位での読み出し（ADR-0023, Issue #31）", () => {
  it("0.1℃ → ℃（×0.1）、出典の unit は sourceUnitId に残る", () => {
    const r = toCanonical(200, "common:unit:0_1degc");
    expect(r.value).toBeCloseTo(20, 10);
    expect(r.unitId).toBe("common:unit:degc");
    expect(r.sourceUnitId).toBe("common:unit:0_1degc");
  });

  it("ppb → ppm、ug/m3 → mg/m3、0.1mm → m、cm → m", () => {
    expect(toCanonical(1500, "common:unit:ppb").unitId).toBe("common:unit:ppm");
    expect(toCanonical(1500, "common:unit:ppb").value).toBeCloseTo(1.5, 10);
    expect(toCanonical(30, "common:unit:ug_per_m3").value).toBeCloseTo(0.03, 10);
    expect(toCanonical(30, "common:unit:ug_per_m3").unitId).toBe("common:unit:mg_per_m3");
    expect(toCanonical(5, "common:unit:0_1mm").value).toBeCloseTo(0.0005, 12);
    expect(toCanonical(250, "common:unit:cm").value).toBeCloseTo(2.5, 10);
  });

  it("換算しない単位は不変（mg/L・ppmC・m）。水の mg/L は大気の mg/m3 に寄せない", () => {
    expect(toCanonical(3, "common:unit:mg_per_l")).toEqual({
      value: 3,
      unitId: "common:unit:mg_per_l",
      sourceUnitId: "common:unit:mg_per_l",
    });
    expect(toCanonical(3, "common:unit:0_01ppmc").unitId).toBe("common:unit:0_01ppmc");
    expect(toCanonical(3, "common:unit:m").value).toBe(3);
  });

  it("単位不明（null）・未知の単位・null の値は換算せず素通し", () => {
    expect(toCanonical(7, null)).toEqual({ value: 7, unitId: null, sourceUnitId: null });
    expect(toCanonical(7, "common:unit:nope")).toEqual({
      value: 7,
      unitId: "common:unit:nope",
      sourceUnitId: "common:unit:nope",
    });
    expect(toCanonical(null, "common:unit:ppb").value).toBeNull();
  });

  it("canonicalizeCells は値3列と series.unitId を寄せ、入力を変更しない", () => {
    const row = {
      series: { unitId: "common:unit:0_1degc", variableId: "v" },
      value: 100,
      valueZero: 100,
      valueLod: null,
    };
    const [out] = canonicalizeCells([row]);
    expect(out.series.unitId).toBe("common:unit:degc");
    expect(out.value).toBeCloseTo(10, 10);
    expect(out.valueLod).toBeNull();
    expect(out.sourceUnitId).toBe("common:unit:0_1degc");
    expect(row.series.unitId).toBe("common:unit:0_1degc");
    expect(row.value).toBe(100);
  });
});
