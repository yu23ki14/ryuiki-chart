import { describe, expect, it, vi } from "vitest";
import { getUnit, getVariable, primaryAlias, resolveVariableInfo, unitSymbol } from "@/lib/registry/lookup";
import { caveatBody, caveatsForTables } from "@/lib/registry/lookup-client";

describe("resolveVariableInfo", () => {
  it("出典表記から正準 variable を引く（measurements, 既定スコープ）", () => {
    const info = resolveVariableInfo("生物化学的酸素要求量 BOD");
    expect(info).toBeDefined();
    expect(info?.variableId).toBe("common:variable:water.bod");
    expect(info?.nameJa).toBe("BOD");
    expect(info?.unit).toBe("mg/L");
    expect(info?.higherIsWorse).toBe(true);
  });

  it("sourceScope が違えば別物として扱う（sensor_timeseries）", () => {
    const info = resolveVariableInfo("OX", "sensor_timeseries");
    expect(info?.variableId).toBe("common:variable:air.photochemical_oxidant");
  });

  it("ADR-0010 の例: OX / Ox(ppm) / 光化学オキシダント（Ox）_日平均 は同じ variableId", () => {
    const a = resolveVariableInfo("OX", "sensor_timeseries");
    const b = resolveVariableInfo("Ox(ppm)", "sensor_timeseries");
    const c = resolveVariableInfo("光化学オキシダント（Ox）_日平均", "sensor_timeseries");
    expect(a?.variableId).toBe(b?.variableId);
    expect(b?.variableId).toBe(c?.variableId);
  });

  it("alias 側が unit_id を上書きしているとき（pH は無次元）はそちらを優先する", () => {
    const info = resolveVariableInfo("pH");
    expect(info?.variableId).toBe("common:variable:water.ph");
    expect(info?.unit).toBe("");
  });

  it("未登録の出典表記は undefined（推測で埋めない）", () => {
    expect(resolveVariableInfo("そんな項目は無い")).toBeUndefined();
  });
});

describe("primaryAlias", () => {
  it("grain='mixed'/'day' の表記があればそれを選ぶ（fiscal_yearの別名より優先）", () => {
    const a = primaryAlias("common:variable:water.bod");
    expect(a?.alias).toBe("生物化学的酸素要求量 BOD");
    expect(a?.grain).toBe("mixed");
  });

  it("fiscal_year の表記しか無い variable は default_stat と一致する行を選ぶ", () => {
    const a = primaryAlias("common:variable:water.tn");
    expect(a?.alias).toBe("全窒素 T-N");
    expect(a?.grain).toBe("fiscal_year");
  });
});

describe("getVariable / getUnit / unitSymbol", () => {
  it("variableId から variable 行を引ける", () => {
    expect(getVariable("common:variable:water.bod")?.code).toBe("water.bod");
  });

  it("unitSymbol は無次元（symbol=null）を空文字にする", () => {
    expect(getUnit("common:unit:dimensionless")?.symbol).toBeNull();
    expect(unitSymbol("common:unit:dimensionless")).toBe("");
  });

  it("unitSymbol は未知の unitId を null で返す", () => {
    expect(unitSymbol("common:unit:no-such-unit")).toBeNull();
    expect(unitSymbol(null)).toBeNull();
  });
});

describe("caveatBody / caveatsForTables — generated-client.ts 経由でも caveats.ts と同じ結果になる", () => {
  it("caveatBody は registry/caveat.yaml の本文をそのまま返す", () => {
    expect(caveatBody("zone")).toContain("公式の区分ではない");
  });

  it("caveatsForTables は複数テーブルで synthetic を最優先にする", () => {
    const refs = caveatsForTables(["measurements", "observers"]);
    expect(refs[0].key).toBe("synthetic");
    expect(refs.map((r) => r.key)).toContain("measuredOn");
  });
});

describe("caveatsForTables — table_synthetic が 1:N（複数の synthetic テーブルが別々の注記を持つ場合）", () => {
  // 現行の registry/caveat.yaml では 6 つの synthetic テーブルが全て同じキー
  // "synthetic" に写るため、実データだけでは「最初の1件で break していないか」を
  // 見分けられない（レビュー指摘: caveatsForTables の table_synthetic 分岐が
  // 最初に一致したテーブルの注記だけを足して break していた）。ここでは
  // generated-client.ts をモックし、2つの synthetic テーブルにそれぞれ別のキーを
  // 割り当てて、両方とも失われず返ることを確認する。
  it("2つ目以降の synthetic テーブルの注記も失われない", async () => {
    vi.resetModules();
    vi.doMock("@/lib/registry/generated-client", () => ({
      GENERATED_CAVEATS: [
        { key: "synthetic_a", severity: null, kind: null, bodyJa: "A注記" },
        { key: "synthetic_b", severity: null, kind: null, bodyJa: "B注記" },
      ],
      GENERATED_CAVEAT_SCOPE: [
        { scopeKind: "table_synthetic", scopeRef: "observers", caveatKey: "synthetic_a", sortOrder: 0 },
        { scopeKind: "table_synthetic", scopeRef: "quality_monthly", caveatKey: "synthetic_b", sortOrder: 0 },
      ],
    }));
    try {
      const mod = await import("@/lib/registry/lookup-client");
      const refs = mod.caveatsForTables(["observers", "quality_monthly"]);
      const keys = refs.map((r) => r.key);
      expect(keys).toContain("synthetic_a");
      expect(keys).toContain("synthetic_b");
    } finally {
      vi.doUnmock("@/lib/registry/generated-client");
      vi.resetModules();
    }
  });
});
