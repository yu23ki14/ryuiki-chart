import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { unitSymbol } from "@/lib/registry/lookup";
import { buildCubeFixture, FX, type CubeFixture } from "./__fixtures__/cube-fixture";
import { queryCells } from "./observation";
import type { CellRow, CellSpec } from "./observation";
import { buildEnvelope } from "./envelope";

/** `resolveProvenance` のテスト用に手で組み立てた `CellRow`（`queryCells` を経由しない。
 *  実データの `雪_最深 積雪`/`雪_最深積雪`〔同じ出典 jma_monthly_kanagawa の2 alias〕が
 *  まとまる組を使う——フィクスチャの DB にはこの変数のセルは無いが、
 *  `envelope.ts` の provenance 解決は `series.ts`（実データの generated.ts）の
 *  `seriesInfo()` だけを見るので DB 行が無くても検証できる）。 */
function fakeSnowCellRow(): CellRow {
  return {
    placeId: FX.places.rain,
    siteId: FX.sites.rain,
    series: {
      variableId: "common:variable:weather.snow_depth_max",
      obsStat: "max",
      unitId: "common:unit:cm",
      valueGrain: "month",
    },
    inputGrain: "month",
    grain: "month",
    periodStart: "2024-01-01",
    periodEnd: "2024-01-31",
    stat: "max",
    value: 10,
    valueZero: 10,
    valueLod: 10,
    n: 1,
    nCensored: 0,
    nNotDetected: 0,
    nPlaces: 1,
  };
}

let fx: CubeFixture;
beforeEach(() => {
  fx = buildCubeFixture();
});
afterEach(() => {
  fx.db.close();
});

describe("buildEnvelope", () => {
  it("coverage: n_rows/n_places/n_censored/n_not_detected/period を rows から計算する", async () => {
    const spec: CellSpec = {
      series: [FX.series.ssMean],
      scope: { kind: "site", siteId: FX.sites.a },
      grain: "day",
      imputation: "zero",
    };
    const rows = await queryCells(fx.db, spec);
    const env = await buildEnvelope(fx.db, spec, rows);

    expect(env.coverage.n_rows).toBe(3);
    expect(env.coverage.n_places).toBe(1);
    expect(env.coverage.n_censored).toBe(2);
    expect(env.coverage.n_not_detected).toBe(1);
    expect(env.coverage.period).toEqual({ start: "2024-01-01", end: "2024-01-03", grain: "day" });
    expect(env.coverage.imputation).toBe("zero");
    expect(env.spec_version).toBeTruthy();
    expect(env.truncated).toBe(false);
    expect(env.caveats).toEqual([]);
  });

  it("columns: unit_id が NULL の系列は unit が null", async () => {
    // `FX.series.ssMean` は実 registry に合わせて unit_id を持つ（下の provenance
    // テストのコメント参照）ため、ここでは `weather.precipitation`（RAIN。実 registry
    // でも unit 未解決のまま——design §0 要点6「雨量は単位NULL＋注記」）を使う。
    const spec: CellSpec = {
      series: [FX.series.rainSum],
      scope: { kind: "site", siteId: FX.sites.rain },
      grain: "day",
      stats: ["sum"],
      imputation: "zero",
    };
    const rows = await queryCells(fx.db, spec);
    const env = await buildEnvelope(fx.db, spec, rows);
    const valueCol = env.columns.find((c) => c.name === "value")!;
    expect(valueCol.unit).toBeNull();
  });

  it("columns: unit_id が NOT NULL の系列（BOD）は registry の symbol を解決する", async () => {
    const spec: CellSpec = {
      series: [FX.series.bodMean],
      scope: { kind: "site", siteId: FX.sites.a },
      grain: "day",
      imputation: "zero",
    };
    const rows = await queryCells(fx.db, spec);
    const env = await buildEnvelope(fx.db, spec, rows);
    const valueCol = env.columns.find((c) => c.name === "value")!;
    expect(valueCol.unit).toBe(unitSymbol(FX.units.mgPerL));
  });

  it("provenance: source_registry から name/license を解決する（複数出典の系列は両方に計上される）", async () => {
    const spec: CellSpec = {
      series: [FX.series.ssMean],
      scope: { kind: "site", siteId: FX.sites.a },
      grain: "day",
      imputation: "zero",
    };
    const rows = await queryCells(fx.db, spec);
    const env = await buildEnvelope(fx.db, spec, rows);

    // provenance は `series.ts`（実データの generated.ts）の `seriesInfo()` を経由するため、
    // `common:variable:water.ss` の mean/day 組の実際の sourceIds
    // （[null, 'atsugi_river_water_quality']。合成 + atsugi の実データ）が使われる
    // （フィクスチャ自身の variable_alias.source_id='fx_atsugi' は catalog.ts 用で、
    // ここでは参照されない）。
    const bySource = new Map(env.provenance.map((p) => [p.source_id, p]));
    expect(bySource.get(null)?.n_rows).toBe(3);
    expect(bySource.get("atsugi_river_water_quality")?.n_rows).toBe(3);
    expect(bySource.get("atsugi_river_water_quality")?.name).toBe("厚木河川水質（実データ源）");
    expect(bySource.get("atsugi_river_water_quality")?.license).toBe("CC-BY-FX");
    expect(bySource.get(null)?.name).toBeUndefined();
  });

  it("provenance: 同じ出典の alias が2つある系列は n_rows を2重計上しない（Issue #48 PR-1 code-review #2）", async () => {
    const spec: CellSpec = {
      series: [
        {
          variableId: "common:variable:weather.snow_depth_max",
          obsStat: "max",
          unitId: "common:unit:cm",
          valueGrain: "month",
        },
      ],
      scope: { kind: "all_sites" },
      grain: "month",
      imputation: "zero",
    };
    const rows = [fakeSnowCellRow()];
    const env = await buildEnvelope(fx.db, spec, rows);

    expect(env.coverage.n_rows).toBe(1);
    expect(env.provenance).toHaveLength(1);
    expect(env.provenance[0].source_id).toBe("jma_monthly_kanagawa");
    expect(env.provenance[0].n_rows).toBe(env.coverage.n_rows);
  });

  it("excluded.reasons: 合成データを含む系列は synthetic_included を報告する", async () => {
    const spec: CellSpec = {
      series: [FX.series.ssMean],
      scope: { kind: "site", siteId: FX.sites.a },
      grain: "day",
      imputation: "zero",
    };
    const rows = await queryCells(fx.db, spec);
    const env = await buildEnvelope(fx.db, spec, rows);
    expect(env.excluded.reasons).toContain("synthetic_included");
  });

  it("opt.caveats をそのまま caveats に渡す（envelope.ts 自身は caveat の解決ロジックに依存しない）", async () => {
    const spec: CellSpec = {
      series: [FX.series.bodMean],
      scope: { kind: "site", siteId: FX.sites.a },
      grain: "day",
      imputation: "zero",
    };
    const rows = await queryCells(fx.db, spec);
    const caveats = [{ key: "common:caveat:fx_test", text: "テスト注記" }];
    const env = await buildEnvelope(fx.db, spec, rows, { caveats });
    expect(env.caveats).toEqual(caveats);
    // BOD は合成を含まないので reasons は空。
    expect(env.excluded.reasons).toEqual([]);
  });

  it("空の rows でも例外にならない", async () => {
    const spec: CellSpec = {
      series: [FX.series.ssMean],
      scope: { kind: "site", siteId: "no-such-site" },
      grain: "day",
      imputation: "zero",
    };
    const rows = await queryCells(fx.db, spec);
    expect(rows).toHaveLength(0);
    const env = await buildEnvelope(fx.db, spec, rows);
    expect(env.coverage.n_rows).toBe(0);
    expect(env.coverage.period).toEqual({ start: null, end: null, grain: "day" });
    expect(env.provenance).toEqual([]);
  });
});
