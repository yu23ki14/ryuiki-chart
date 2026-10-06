import { describe, expect, it, vi } from "vitest";
import { getUnit, getVariable, resolveAliasForSource, resolveVariableInfo, unitSymbol } from "@/lib/registry/lookup";
import { caveatBody, resolveCaveatRefs } from "@/lib/registry/lookup-client";
import { VARIABLE_LABEL } from "@/lib/registry/generated-client";

describe("resolveVariableInfo", () => {
  it("出典表記から正準 variable を引く（measurements, 既定スコープ）", () => {
    const info = resolveVariableInfo("生物化学的酸素要求量 BOD");
    expect(info).toBeDefined();
    expect(info?.variableId).toBe("common:variable:water.bod");
    expect(info?.nameJa).toBe("BOD");
    expect(info?.unit).toBe("mg/L");
    expect(info?.higherIsWorse).toBe(true);
  });

  it("dataset が違えば別物として扱う（sensor_timeseries）", () => {
    const info = resolveVariableInfo("OX", "sensor_timeseries");
    expect(info?.variableId).toBe("common:variable:air.photochemical_oxidant");
  });

  it("同じ (dataset, alias) が複数 source_id に分かれていても一意に解決できる（BOD: atsugi/annual/sample の3行）", () => {
    const info = resolveVariableInfo("生物化学的酸素要求量 BOD", "measurements");
    expect(info?.variableId).toBe("common:variable:water.bod");
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

describe("resolveAliasForSource", () => {
  it("(dataset, alias, sourceId) の完全一致で stat/grain を含む1行を返す（BOD の3出典）", () => {
    const atsugi = resolveAliasForSource("生物化学的酸素要求量 BOD", "measurements", "atsugi_river_water_quality");
    expect(atsugi?.stat).toBe("mean");
    expect(atsugi?.grain).toBe("day");

    const sample = resolveAliasForSource("生物化学的酸素要求量 BOD", "measurements", "env_kousui_sample_kanagawa");
    expect(sample?.stat).toBe("point");
    expect(sample?.grain).toBe("day");

    const annual = resolveAliasForSource("生物化学的酸素要求量 BOD", "measurements", "env_kousui_annual_kanagawa");
    expect(annual?.stat).toBe("mean");
    expect(annual?.grain).toBe("fiscal_year");
  });

  it("sourceId が undefined/null は「出典未記録」として同じ意味に扱う（pH の合成データ行）", () => {
    const viaUndefined = resolveAliasForSource("pH", "measurements", undefined);
    const viaNull = resolveAliasForSource("pH", "measurements", null);
    const viaEmpty = resolveAliasForSource("pH", "measurements", "");
    expect(viaUndefined).toBeDefined();
    expect(viaUndefined).toEqual(viaNull);
    expect(viaUndefined).toEqual(viaEmpty);
  });

  it("一致が無ければ undefined（推測で埋めない）", () => {
    expect(resolveAliasForSource("生物化学的酸素要求量 BOD", "measurements", "そんな出典は無い")).toBeUndefined();
  });
});

describe("variable_alias の (dataset, alias, sourceId) 重複は索引構築時に例外にする", () => {
  // scripts/registry/build_unit_variable.py の _load_variable_alias_csv が
  // Python 側で一意性を assert しているが、SQLite の索引は非 UNIQUE で
  // D1 側では何も強制しない（code-review 指摘）。generated.ts をモックして
  // 重複行を注入し、モジュール読み込み時点で例外になることを確認する。
  it("(dataset, alias, sourceId) が重複する行があると import 時に throw する", async () => {
    vi.resetModules();
    vi.doMock("@/lib/registry/generated", () => ({
      GENERATED_UNITS: [],
      GENERATED_VARIABLES: [],
      GENERATED_VARIABLE_ALIASES: [
        { alias: "pH", dataset: "measurements", sourceId: "dup", variableId: "v.ph", unitId: null, stat: "point", grain: "day" },
        { alias: "pH", dataset: "measurements", sourceId: "dup", variableId: "v.ph", unitId: null, stat: "mean", grain: "day" },
      ],
    }));
    try {
      await expect(import("@/lib/registry/lookup")).rejects.toThrow(/重複している/);
    } finally {
      vi.doUnmock("@/lib/registry/generated");
      vi.resetModules();
    }
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

describe("caveatBody / variableNote — generated-client.ts 経由の引き", () => {
  it("caveatBody は registry/caveat.yaml の本文をそのまま返す", () => {
    expect(caveatBody("zone")).toContain("公式の区分ではない");
  });

  it("流量の変数説明（VARIABLE_LABEL の note）に逆流は埋め込まない（注記 flowTidalBackflow が持つ）", () => {
    expect(VARIABLE_LABEL["common:variable:hydro.flow"]?.note).toBe("河川の流量");
    expect(caveatBody("flowTidalBackflow")).toContain("逆流");
  });
});

describe("resolveCaveatRefs — priority が同点の複数の scope が別々の注記を持つ場合", () => {
  // 旧 table_synthetic の特殊分岐は「最初に一致した1件だけ足して break する」バグを生んだ。
  // priority 列だけで優先度を表す一般規則なので、同じ priority の2件目以降も失われない。
  const scope = (scopeRef: string, caveatKey: string, priority: number) => ({
    scopeKind: "observation_set" as const,
    scopeRef,
    caveatKey,
    sortOrder: 0,
    priority,
  });

  it("2つ目以降の priority=1 の注記も失われず、priority=0 より先に並ぶ", () => {
    const refs = resolveCaveatRefs([
      { scope: scope("x", "plain", 0), order: 0 },
      { scope: scope("a", "synthetic_a", 1), order: 1 },
      { scope: scope("b", "synthetic_b", 1), order: 2 },
    ]);
    expect(refs.map((r) => r.key)).toEqual(["synthetic_a", "synthetic_b", "plain"]);
  });
});
