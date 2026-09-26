/**
 * 実 DB 統合テスト（design §7 末尾）。原本のある手元だけで実行する
 * （`describe.skipIf`、`generated.test.ts` と同じ流儀）。
 *
 * v1 の `data/db/derived.sqlite` の代表数件（`meas_year`/`meas_clim`/`zone_year`/
 * `var_catalog`/`rain_daily`）と、`lib/cube` を alias の系列集合（`seriesForAlias`）で
 * 呼んだ結果が一致することを確かめる。serving-diff（1c）の前の自己点検であり、
 * ここで見ているのは「問い合わせ層が正しい行を返すか」で、`assertD1Compatible` や
 * v1 アダプタの列名変換などは見ない（それは 1c の役割）。
 *
 * 雨量（RAIN）は v1 側が `/10` した上でラベル日割りしているため、`/10` だけを
 * このテストで戻して比較する（日割りの差は既知の系統——design §5.2「day_split」
 * ——なのでここでは対象日をずらして日割りの影響が出ない日を選ぶ）。
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import Database from "better-sqlite3";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import type { CubeDb } from "./db";
import { sqliteCubeDb } from "./db-sqlite";
import { queryCells, summarize } from "./observation";
import { seriesForAlias, seriesKeyString } from "./series";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, "..", "..", "..", "..");
const DB_DIR = path.join(REPO_ROOT, "data", "db");
const V2 = path.join(DB_DIR, "v2.sqlite");
const REGISTRY = path.join(DB_DIR, "registry.sqlite");
const RYUIKI = path.join(DB_DIR, "ryuiki.sqlite");
const DERIVED = path.join(DB_DIR, "derived.sqlite");

const hasRealDb = [V2, REGISTRY, RYUIKI, DERIVED].every((p) => fs.existsSync(p));

describe.skipIf(!hasRealDb)("実DB統合テスト: lib/cube と v1 (derived.sqlite) の突合", () => {
  let cube: CubeDb & { close(): void };
  let v1: Database.Database;

  beforeAll(() => {
    cube = sqliteCubeDb({ v2: V2, registry: REGISTRY, ryuiki: RYUIKI });
    v1 = new Database(DERIVED, { readonly: true, fileMustExist: true });
  });
  afterAll(() => {
    cube.close();
    v1.close();
  });

  it("meas_year: pH（atsugi_river_water_quality__中津川、daily、2002年。SS の宣言済み差分とは無関係な variable）", async () => {
    const v1Row = v1
      .prepare(`SELECT n, avg, min, max, n_censored, unit FROM meas_year WHERE site_id=? AND variable=? AND kind='daily' AND year=2002`)
      .get("atsugi_river_water_quality__中津川", "pH") as
      | { n: number; avg: number; min: number; max: number; n_censored: number; unit: string | null }
      | undefined;
    expect(v1Row).toBeDefined();

    const series = seriesForAlias("measurements", "pH").filter((s) => s.obsStat === "mean" && s.valueGrain === "day");
    expect(series).toHaveLength(1);

    const { rows } = await queryCells(cube, {
      series,
      scope: { kind: "site", siteId: "atsugi_river_water_quality__中津川" },
      grain: "year",
      inputGrain: "day",
      stats: ["mean", "min", "max"],
      period: { from: "2002-01-01", to: "2002-12-31" },
      imputation: "zero",
    });
    const byStat = new Map(rows.map((r) => [r.stat, r]));
    expect(byStat.get("mean")?.value).toBeCloseTo(v1Row!.avg, 9);
    expect(byStat.get("min")?.value).toBeCloseTo(v1Row!.min, 9);
    expect(byStat.get("max")?.value).toBeCloseTo(v1Row!.max, 9);
    expect(byStat.get("mean")?.n).toBe(v1Row!.n);
    expect(byStat.get("mean")?.nCensored).toBe(v1Row!.n_censored);
  });

  it("meas_clim: pH の月別平年値（月1〜12件すべて。alias 'pH' の全系列を混ぜる——design §3.3）", async () => {
    const v1Rows = v1.prepare(`SELECT month, n, avg, min, max FROM meas_clim WHERE variable='pH' ORDER BY month`).all() as {
      month: number;
      n: number;
      avg: number;
      min: number;
      max: number;
    }[];
    expect(v1Rows.length).toBeGreaterThan(0);

    const series = seriesForAlias("measurements", "pH"); // 複数系列（mean/point）を混ぜる
    const { rows } = await summarize(
      cube,
      {
        series,
        scope: { kind: "all_sites" },
        grain: "day",
        stats: ["mean"],
        inputGrain: "day",
        imputation: "zero",
      },
      "month_of_year",
    );
    const byMonth = new Map(rows.map((r) => [r.month, r]));

    for (const v1Row of v1Rows) {
      const r = byMonth.get(v1Row.month);
      expect(r, `month ${v1Row.month}`).toBeDefined();
      expect(r!.n, `month ${v1Row.month} n`).toBe(v1Row.n);
      expect(r!.avg, `month ${v1Row.month} avg`).toBeCloseTo(v1Row.avg, 6);
      expect(r!.min, `month ${v1Row.month} min`).toBeCloseTo(v1Row.min, 9);
      expect(r!.max, `month ${v1Row.month} max`).toBeCloseTo(v1Row.max, 9);
    }
  });

  it("zone_year: BOD 75%値（zone=2, year=2011, annual）", async () => {
    const v1Row = v1
      .prepare(`SELECT zone, n_sites, n, avg, unit FROM zone_year WHERE variable='BOD 75%値' AND kind='annual' AND zone=2 AND year=2011`)
      .get() as { zone: number; n_sites: number; n: number; avg: number; unit: string | null } | undefined;
    expect(v1Row).toBeDefined();

    const series = seriesForAlias("measurements", "BOD 75%値");
    expect(series).toHaveLength(1); // p75/fiscal_year の1系列だけ

    const { rows } = await summarize(
      cube,
      {
        series,
        scope: { kind: "all_sites" },
        grain: "fiscal_year",
        stats: ["mean"],
        inputGrain: "same",
        period: { from: "2011-04-01", to: "2011-04-01" },
        imputation: "zero",
      },
      "zone",
    );
    const zone2 = rows.find((r) => r.zone === 2);
    expect(zone2).toBeDefined();
    expect(zone2!.nSites).toBe(v1Row!.n_sites);
    expect(zone2!.n).toBe(v1Row!.n);
    expect(zone2!.avg).toBeCloseTo(v1Row!.avg, 9);
  });

  it("var_catalog: BOD 75%値（alias 単位で1系列に絞れば var_catalog の1行と一致する——PR-1 は variable_id 単位で束ねると差分が出る、という design の指摘の裏返し）", async () => {
    const v1Row = v1
      .prepare(`SELECT unit, n, n_sites, y_from, y_to, n_daily, n_annual, n_censored FROM var_catalog WHERE variable='BOD 75%値'`)
      .get() as
      | { unit: string | null; n: number; n_sites: number; y_from: number; y_to: number; n_daily: number; n_annual: number; n_censored: number }
      | undefined;
    expect(v1Row).toBeDefined();

    const series = seriesForAlias("measurements", "BOD 75%値");
    expect(series).toHaveLength(1);

    const { rows } = await summarize(
      cube,
      { series, scope: { kind: "all_sites" }, grain: ["year", "fiscal_year"], stats: ["mean"], imputation: "zero" },
      "series",
    );
    expect(rows).toHaveLength(1); // 1系列・1 input_grain（fiscal_year）だけのはず
    const r = rows[0];
    expect(r.seriesKey).toBe(seriesKeyString(series[0]));
    expect(r.n).toBe(v1Row!.n);
    expect(r.nPlaces).toBe(v1Row!.n_sites);
    expect(r.yFrom).toBe(v1Row!.y_from);
    expect(r.yTo).toBe(v1Row!.y_to);
    expect(r.nAnnual).toBe(v1Row!.n_annual);
    expect(r.nDaily).toBe(v1Row!.n_daily);
    expect(r.nCensored).toBe(v1Row!.n_censored);
  });

  it("rain_daily: RAIN（sagamihara）は cube の day/sum セルを /10 すると v1 と一致する（既知差分: 日割りが絡む日はここでは選ばない）", async () => {
    const v1Row = v1.prepare(`SELECT d, mm FROM rain_daily WHERE d = ?`).get("2015-04-01") as { d: string; mm: number } | undefined;
    expect(v1Row).toBeDefined();

    const series = seriesForAlias("sensor_timeseries", "RAIN");
    expect(series).toHaveLength(1);

    const { rows } = await queryCells(cube, {
      series,
      scope: { kind: "site", siteId: "sagamihara_taiki_stations__sagamihara_101" },
      grain: "day",
      stats: ["sum"],
      period: { from: "2015-04-01", to: "2015-04-01" },
      imputation: "zero",
    });
    expect(rows).toHaveLength(1);
    expect(Math.round((rows[0].value! / 10) * 100) / 100).toBeCloseTo(v1Row!.mm, 6);
  });
});
