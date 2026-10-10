import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { unitSymbol } from "@/lib/registry/lookup";
import { buildCubeFixture, FX, type CubeFixture } from "./__fixtures__/cube-fixture";
import { queryCells, summarize } from "./observation";
import type { CellRow, CellSpec } from "./observation";
import { buildEnvelope, buildZoneEnvelope } from "./envelope";

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
    const { rows } = await queryCells(fx.db, spec);
    const env = await buildEnvelope(spec, rows);

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
    const { rows } = await queryCells(fx.db, spec);
    const env = await buildEnvelope(spec, rows);
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
    const { rows } = await queryCells(fx.db, spec);
    const env = await buildEnvelope(spec, rows);
    const valueCol = env.columns.find((c) => c.name === "value")!;
    expect(valueCol.unit).toBe(unitSymbol(FX.units.mgPerL));
  });

  it("provenance: registry の生成物から name/license を解決する（複数出典の系列は両方に計上される）", async () => {
    const spec: CellSpec = {
      series: [FX.series.ssMean],
      scope: { kind: "site", siteId: FX.sites.a },
      grain: "day",
      imputation: "zero",
    };
    const { rows } = await queryCells(fx.db, spec);
    const env = await buildEnvelope(spec, rows);

    // provenance は `series.ts`（実データの generated.ts）の `seriesInfo()` を経由するため、
    // `common:variable:water.ss` の mean/day 組の実際の sourceIds
    // （[null, 'atsugi_river_water_quality']。null＝合成は provenance の行にしない）が使われる
    // （フィクスチャ自身の variable_alias.source_id='fx_atsugi' は catalog.ts 用で、
    // ここでは参照されない）。
    const bySource = new Map(env.provenance.map((p) => [p.source_id, p]));
    expect(bySource.has(null as unknown as string)).toBe(false);
    expect(bySource.get("atsugi_river_water_quality")?.n_rows).toBe(3);
    const atsugi = bySource.get("atsugi_river_water_quality");
    expect(atsugi?.name).toBe("厚木市 河川水質調査結果(相模川・中津川・小鮎川・玉川)");
    expect(atsugi?.license).toBe("クリエイティブ・コモンズ 表示（CC BY）");
    expect(atsugi?.license_class).toBe("cc_by");
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
    const env = await buildEnvelope(spec, rows);

    expect(env.coverage.n_rows).toBe(1);
    // 奄美の追加（Issue #89 PR-B）で同じ系列に jma_monthly_amami の alias が載った。
    // 系列キーは地域を持たないので、出典は地域ごとに1件ずつ（計2件）。肝心なのは
    // 「同じ出典の alias が2つあっても、その出典の n_rows は2重にならない」こと。
    expect(env.provenance.map((p) => p.source_id).sort()).toEqual(["jma_monthly_amami", "jma_monthly_kanagawa"]);
    for (const p of env.provenance) expect(p.n_rows).toBe(env.coverage.n_rows);
  });

  it("excluded.reasons: PR-2 で撤去した synthetic_included はもう報告しない（D2。b03 が合成データを除くため）", async () => {
    const spec: CellSpec = {
      series: [FX.series.ssMean],
      scope: { kind: "site", siteId: FX.sites.a },
      grain: "day",
      imputation: "zero",
    };
    const { rows } = await queryCells(fx.db, spec);
    const env = await buildEnvelope(spec, rows);
    expect(env.excluded.reasons).toEqual([]);
  });

  it("imputation='both': columns に value_zero/value_lod を単位付きで両方持つ（value 列は無い）", async () => {
    const spec: CellSpec = {
      series: [FX.series.bodMean],
      scope: { kind: "site", siteId: FX.sites.a },
      grain: "day",
      imputation: "both",
    };
    const { rows } = await queryCells(fx.db, spec);
    const env = await buildEnvelope(spec, rows);
    expect(env.columns.map((c) => c.name)).toEqual(["place_id", "period_start", "value_zero", "value_lod"]);
    const zeroCol = env.columns.find((c) => c.name === "value_zero")!;
    const lodCol = env.columns.find((c) => c.name === "value_lod")!;
    expect(zeroCol.unit).toBe(unitSymbol(FX.units.mgPerL));
    expect(lodCol.unit).toBe(unitSymbol(FX.units.mgPerL));
    expect(env.coverage.imputation).toBe("both");
  });

  it("opt.caveats をそのまま caveats に渡す（envelope.ts 自身は caveat の解決ロジックに依存しない）", async () => {
    const spec: CellSpec = {
      series: [FX.series.bodMean],
      scope: { kind: "site", siteId: FX.sites.a },
      grain: "day",
      imputation: "zero",
    };
    const { rows } = await queryCells(fx.db, spec);
    const caveats = [{ key: "common:caveat:fx_test", text: "テスト注記" }];
    const env = await buildEnvelope(spec, rows, { caveats });
    // key/text はそのまま。severity/kind は registry に無いキー（このテストの架空キー）なので null。
    expect(env.caveats).toEqual([{ ...caveats[0], severity: null, kind: null }]);
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
    const { rows } = await queryCells(fx.db, spec);
    expect(rows).toHaveLength(0);
    const env = await buildEnvelope(spec, rows);
    expect(env.coverage.n_rows).toBe(0);
    expect(env.coverage.period).toEqual({ start: null, end: null, grain: "day" });
    expect(env.provenance).toEqual([]);
  });
});

describe("buildZoneEnvelope（ゾーン単位の封筒。Issue #48 PR-2 統合後修正A #4）", () => {
  it("imputation='both' の summarize(...,'zone') 1回の結果を包む（envelope が null にならない）", async () => {
    const spec: CellSpec = {
      series: [FX.series.ssMean],
      scope: { kind: "all_sites" },
      grain: "day",
      imputation: "both",
    };
    const { rows, truncated } = await summarize(fx.db, spec, "zone");
    const env = await buildZoneEnvelope(spec, rows, { truncated });

    expect(env.columns.map((c) => c.name)).toEqual(["zone", "year", "value_zero", "value_lod"]);
    const zeroCol = env.columns.find((c) => c.name === "value_zero")!;
    expect(zeroCol.unit).toBe(unitSymbol(FX.units.mgPerL));
    expect(env.coverage.n_rows).toBe(rows.length);
    expect(env.coverage.n_places).toBe(new Set(rows.map((r) => r.zone)).size);
    expect(env.coverage.imputation).toBe("both");
    // fx_place_a の2日目（検閲）・3日目（不検出）がゾーン3の集計に含まれる。
    const zone3 = rows.find((r) => r.zone === 3)!;
    expect(zone3.nCensored).toBeGreaterThan(0);
    // provenance は spec.series（atsugi の実出典）から解決する（行ごとではなく系列集合から）。
    expect(env.provenance.length).toBeGreaterThan(0);
    expect(env.provenance.every((p) => p.n_rows === rows.length)).toBe(true);
  });

  it("空の rows でも例外にならない", async () => {
    const spec: CellSpec = {
      series: [FX.series.ssMean],
      scope: { kind: "site", siteId: "no-such-site" },
      grain: "year",
      imputation: "both",
    };
    const { rows } = await summarize(fx.db, spec, "zone");
    expect(rows).toHaveLength(0);
    const env = await buildZoneEnvelope(spec, rows);
    expect(env.coverage.n_rows).toBe(0);
    expect(env.coverage.period).toEqual({ start: null, end: null, grain: "year" });
    expect(env.provenance.length).toBeGreaterThan(0); // 系列自体は存在するので出典は列挙される
    expect(env.provenance.every((p) => p.n_rows === 0)).toBe(true);
  });
});


describe("cube-envelope@2（Issue #40 Phase D 担当 E）", () => {
  const NOW = new Date("2026-10-06T03:00:00Z"); // JST 2026-10-06 12:00

  async function atsugiEnvelope(opt?: Parameters<typeof buildEnvelope>[2]) {
    const spec: CellSpec = {
      series: [FX.series.ssMean],
      scope: { kind: "site", siteId: FX.sites.a },
      grain: "day",
      imputation: "zero",
    };
    const { rows } = await queryCells(fx.db, spec);
    return buildEnvelope(spec, rows, { now: NOW, ...opt });
  }

  it("spec_version は cube-envelope@2", async () => {
    expect((await atsugiEnvelope()).spec_version).toBe("cube-envelope@2");
  });

  it("provenance に fetched_at（時刻帯つき）・update_mode・age_days・source_edition_id・attribution が載る", async () => {
    const env = await atsugiEnvelope();
    const p = env.provenance.find((x) => x.source_id === "atsugi_river_water_quality");
    expect(p?.source_edition_id).toBe("common:edition:atsugi_river_water_quality.20260830");
    expect(p?.fetched_at).toBe("2026-08-30T16:20:58+09:00");
    // 2026-08-30 -> 2026-10-06（JST）= 37 日
    expect(p?.age_days).toBe(37);
    // update_mode は宣言があればその値、無ければ "undeclared"（NULL を黙って別の値にしない）。
    expect(["snapshot", "append", "revision", "static", "undeclared"]).toContain(p?.update_mode);
    expect(p?.attribution).toBeTruthy();
    // 合成（source_id NULL / synthetic_*）は provenance の行にならない（ADR-0028 の不変条件 1）。
    expect(env.provenance.some((x) => x.source_id === null || String(x.source_id).startsWith("synthetic"))).toBe(false);
  });

  it("coverage の oldest/newest_fetched_at・cite_as・as_of・time_zone", async () => {
    const env = await atsugiEnvelope();
    expect(env.coverage.oldest_fetched_at).toBe("2026-08-30T16:20:58+09:00");
    expect(env.coverage.newest_fetched_at).toBe("2026-08-30T16:20:58+09:00");
    expect(env.cite_as).toContain("取得 2026-08-30");
    expect(env.cite_as).toContain("厚木市 河川水質調査結果");
    expect(env.as_of).toBe("2026-10-06T03:00:00.000Z");
    expect(env.time_zone).toEqual({ region_id: "jp-14", tz_name: "Asia/Tokyo", utc_offset: "+09:00" });
  });

  it("JST の日付境界: UTC 14:59 はまだ 2026-10-06（JST 23:59）、15:00 で翌日", async () => {
    const before = await atsugiEnvelope({ now: new Date("2026-10-06T14:59:00Z") });
    const after = await atsugiEnvelope({ now: new Date("2026-10-06T15:00:00Z") });
    const f = (e: typeof before) => e.provenance.find((x) => x.source_id === "atsugi_river_water_quality")?.age_days;
    expect(f(after)).toBe(f(before)! + 1);
  });

  it("stale のような閾値判定のキーを持たない（ADR-0020・J5）", async () => {
    const env = await atsugiEnvelope();
    expect(JSON.stringify(env)).not.toMatch(/stale|expected_refresh/);
  });

  it("buildEnvelope/buildZoneEnvelope は DB を引かない（第1引数が CubeDb でない＝来歴の取得にクエリが走らない）", async () => {
    const spec: CellSpec = { series: [FX.series.ssMean], scope: { kind: "site", siteId: FX.sites.a }, grain: "day", imputation: "zero" };
    const { rows } = await queryCells(fx.db, spec);
    let calls = 0;
    const spy = fx.db.all.bind(fx.db);
    fx.db.all = ((...a: Parameters<typeof spy>) => {
      calls++;
      return spy(...a);
    }) as typeof fx.db.all;
    buildEnvelope(spec, rows, { now: NOW });
    expect(calls).toBe(0);
  });

  it("excluded は常に 0（ADR-0028。ライセンス・公開範囲で黙って減らさない）。redistributable=0 の出典が混ざっても 0", async () => {
    const spec: CellSpec = { series: [FX.series.ssMean], scope: { kind: "site", siteId: FX.sites.a }, grain: "day", imputation: "zero" };
    const { rows } = await queryCells(fx.db, spec);
    const env = buildEnvelope(spec, rows, { now: NOW });
    expect(env.excluded).toEqual({ by_license: 0, by_embargo: 0, reasons: [] });
    // 旗が 0 の出典（atsugi は redistributable=true だが、旗の値が出力を絞らないことを別系列でも固定する）
    const snow = buildEnvelope({ ...spec, series: [fakeSnowCellRow().series] }, [fakeSnowCellRow()], { now: NOW });
    expect(snow.excluded).toEqual({ by_license: 0, by_embargo: 0, reasons: [] });
    expect(snow.coverage.n_rows).toBe(1);
  });
});
