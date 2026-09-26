/**
 * `lib/cube` のテスト用フィクスチャ（design §7）。
 *
 * `better-sqlite3(":memory:")` に `web/drizzle/migrations/*.sql` を
 * `--> statement-breakpoint` で分割して順に適用する（＝ D1 と同じ DDL・索引）。
 * その上に手書きの行を入れる:
 *   - 地点3（ゾーン3・水域「境川（１）」の2地点 fx_site_a/fx_site_b、`sites` に無い
 *     厚木型1地点 fx_site_c）＋ゾーン2の地点1つ（fx_site_rain、雨量用）
 *   - `water.ss` に2系列（mean/day＝atsugi型＋合成、point/day＝env型。alias は同じ
 *     '浮遊物質量 SS'）＋ fiscal_year の3系列目
 *   - 日セル（検閲あり: value_zero ≠ value_lod、n_not_detected>0 で value_lod NULL）
 *   - 月・年（暦年 input=day）・年度（fiscal_year）セル
 *   - `weather.precipitation` の hour→day sum セル（2ヶ月分、月別平年値のテスト用）
 *   - `unit_id` NULL のセル（water.ss・weather.precipitation）と NULL でないセル（water.bod）
 *   - レジストリ8表の必要行（`place_source_ref` の `sites.site_id`/`sites.zone`、
 *     `place_relation` の within、`variable_alias` の source_id NULL 行＝合成）
 *   - `caveat`/`caveat_scope`（table 行と facet 行〔1b が使う `dataset` kind〕の両方）
 *
 * 実データの `variable_id`/`alias` 文字列（`common:variable:water.ss`・'浮遊物質量 SS' 等）を
 * そのまま再利用しているが、これは design §3.3 が言及する実測ケース（SS/DO の合成データと
 * env_kousui の2系列混在）を再現するための命名の一致であり、実 DB への依存は無い
 * （`better-sqlite3(":memory:")` に手書きで入れた行だけを見る）。
 */
import path from "node:path";
import fs from "node:fs";
import { fileURLToPath } from "node:url";
import Database from "better-sqlite3";
import { assertD1Compatible, type CubeDb, type Row, type SqlParam } from "../db";
import type { SeriesKey } from "../series";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const MIGRATIONS_DIR = path.resolve(__dirname, "..", "..", "..", "..", "drizzle", "migrations");

function applyMigrations(db: Database.Database): void {
  const files = fs
    .readdirSync(MIGRATIONS_DIR)
    .filter((f) => f.endsWith(".sql"))
    .sort();
  for (const file of files) {
    const sql = fs.readFileSync(path.join(MIGRATIONS_DIR, file), "utf-8");
    for (const stmt of sql.split("--> statement-breakpoint")) {
      const trimmed = stmt.trim();
      if (trimmed) db.exec(trimmed);
    }
  }
}

/** フィクスチャ内の既知の ID・系列（テストから参照する）。 */
export const FX = {
  places: {
    a: "fx_place_a",
    b: "fx_place_b",
    c: "fx_place_c",
    rain: "fx_place_rain",
    zone3: "fx_place_zone3",
    zone2: "fx_place_zone2",
  },
  sites: { a: "fx_site_a", b: "fx_site_b", c: "fx_site_c", rain: "fx_site_rain" },
  municipality: "境川（１）",
  variables: {
    ss: "common:variable:water.ss",
    rain: "common:variable:weather.precipitation",
    bod: "common:variable:water.bod",
  },
  units: { mgPerL: "common:unit:mg_per_l" },
  series: {
    // `unitId`: 実 registry（`web/src/lib/registry/generated.ts`。Issue #48 PR-1b の
    // D3 で `variable_alias` の unit_id を実測で埋めた後）は `common:variable:water.ss`
    // の mean/day 組が `common:unit:mg_per_l` を持つ（null ではない）。`seriesInfo()`
    // は実データの `generated.ts` を見るため、ここも合わせておかないと
    // `envelope.test.ts` の provenance/synthetic 系のテスト（実 registry の
    // sourceIds を引く）がヒットしない（この組にヒットさせるための一致）。
    ssMean: { variableId: "common:variable:water.ss", obsStat: "mean", unitId: "common:unit:mg_per_l", valueGrain: "day" } as SeriesKey,
    ssPoint: { variableId: "common:variable:water.ss", obsStat: "point", unitId: null, valueGrain: "day" } as SeriesKey,
    ssAnnual: { variableId: "common:variable:water.ss", obsStat: "mean", unitId: null, valueGrain: "fiscal_year" } as SeriesKey,
    rainSum: { variableId: "common:variable:weather.precipitation", obsStat: "sum", unitId: null, valueGrain: "hour" } as SeriesKey,
    bodMean: {
      variableId: "common:variable:water.bod",
      obsStat: "mean",
      unitId: "common:unit:mg_per_l",
      valueGrain: "day",
    } as SeriesKey,
  },
} as const;

interface ObsAggFixtureRow {
  regionId?: string | null;
  placeId: string | null;
  placeKind?: string | null;
  variableId: string | null;
  obsStat?: string | null;
  unitId?: string | null;
  valueGrain?: string | null;
  periodStart: string | null;
  periodEnd?: string | null;
  grain: string | null;
  inputGrain: string | null;
  stat: string | null;
  valueZero?: number | null;
  valueLod?: number | null;
  n: number;
  nCensored?: number;
  nNotDetected?: number;
  nPlaces?: number;
}

function insertObsAgg(db: Database.Database, rows: ObsAggFixtureRow[]): void {
  const stmt = db.prepare(`
    INSERT INTO observation_agg
      (region_id, place_id, place_kind, variable_id, obs_stat, unit_id, value_grain,
       period_start, period_end, grain, input_grain, stat, value_zero, value_lod,
       n, n_censored, n_not_detected, n_places, built_from, spec_version)
    VALUES (@regionId,@placeId,@placeKind,@variableId,@obsStat,@unitId,@valueGrain,
            @periodStart,@periodEnd,@grain,@inputGrain,@stat,@valueZero,@valueLod,
            @n,@nCensored,@nNotDetected,@nPlaces,'fixture:cube-fixture','fixture@1')
  `);
  for (const r of rows) {
    stmt.run({
      regionId: "kanagawa",
      placeKind: "site",
      obsStat: null,
      unitId: null,
      valueGrain: null,
      periodEnd: r.periodStart,
      valueZero: null,
      valueLod: null,
      nCensored: 0,
      nNotDetected: 0,
      nPlaces: 1,
      ...r,
    });
  }
}

function seed(db: Database.Database): void {
  db.prepare(
    `INSERT INTO sites (site_id, name, name_en, watershed, zone, lat, lon, elevation_m, municipality, muni_code, treatment, established_on, operator, source_id, source_ref, is_synthetic)
     VALUES (@siteId,@name,NULL,NULL,@zone,@lat,@lon,@elevationM,@municipality,NULL,NULL,NULL,NULL,NULL,NULL,0)`,
  ).run({ siteId: FX.sites.a, name: "地点A", zone: 3, lat: 35.4, lon: 139.4, elevationM: 50, municipality: FX.municipality });
  db.prepare(
    `INSERT INTO sites (site_id, name, name_en, watershed, zone, lat, lon, elevation_m, municipality, muni_code, treatment, established_on, operator, source_id, source_ref, is_synthetic)
     VALUES (@siteId,@name,NULL,NULL,@zone,@lat,@lon,@elevationM,@municipality,NULL,NULL,NULL,NULL,NULL,NULL,0)`,
  ).run({ siteId: FX.sites.b, name: "地点B", zone: 3, lat: 35.41, lon: 139.41, elevationM: 30, municipality: FX.municipality });
  db.prepare(
    `INSERT INTO sites (site_id, name, name_en, watershed, zone, lat, lon, elevation_m, municipality, muni_code, treatment, established_on, operator, source_id, source_ref, is_synthetic)
     VALUES (@siteId,@name,NULL,NULL,@zone,@lat,@lon,@elevationM,@municipality,NULL,NULL,NULL,NULL,NULL,NULL,0)`,
  ).run({ siteId: FX.sites.rain, name: "地点雨量", zone: 2, lat: 35.5, lon: 139.3, elevationM: 100, municipality: "相模原" });
  // fx_site_c は意図的に `sites` に行を作らない（厚木型。design §7「sites に無い厚木型1地点」）。

  const psr = db.prepare(`INSERT INTO place_source_ref (place_id, external_key, source_id) VALUES (?,?,?)`);
  psr.run(FX.places.a, FX.sites.a, "sites.site_id");
  psr.run(FX.places.b, FX.sites.b, "sites.site_id");
  psr.run(FX.places.c, FX.sites.c, "sites.site_id");
  psr.run(FX.places.rain, FX.sites.rain, "sites.site_id");
  psr.run(FX.places.zone3, "3", "sites.zone");
  psr.run(FX.places.zone2, "2", "sites.zone");

  const rel = db.prepare(`INSERT INTO place_relation (parent_id, child_id, relation, fraction, basis) VALUES (?,?,'within',1.0,NULL)`);
  rel.run(FX.places.zone3, FX.places.a);
  rel.run(FX.places.zone3, FX.places.b);
  rel.run(FX.places.zone3, FX.places.c);
  rel.run(FX.places.zone2, FX.places.rain);

  db.prepare(`INSERT INTO unit (unit_id, symbol, ucum, name_ja, quantity_kind) VALUES (?,?,?,?,?)`).run(
    FX.units.mgPerL,
    "mg/L",
    "mg/L",
    "ミリグラム毎リットル",
    "concentration",
  );

  const variable = db.prepare(
    `INSERT INTO variable (variable_id, code, name_ja, name_en, theme, unit_id, value_type, default_stat, higher_is_worse, description_ja, status)
     VALUES (@variableId,NULL,@nameJa,NULL,@theme,@unitId,'numeric','mean',1,NULL,'active')`,
  );
  variable.run({ variableId: FX.variables.ss, nameJa: "浮遊物質量", theme: "water", unitId: null });
  variable.run({ variableId: FX.variables.rain, nameJa: "降水量", theme: "weather", unitId: null });
  variable.run({ variableId: FX.variables.bod, nameJa: "BOD", theme: "water", unitId: FX.units.mgPerL });

  const alias = db.prepare(
    `INSERT INTO variable_alias (alias, dataset, source_id, variable_id, unit_id, stat, grain)
     VALUES (@alias,@dataset,@sourceId,@variableId,@unitId,@stat,@grain)`,
  );
  // unitId: `FX.series.ssMean`/`ssPoint` の observation_agg セル（`FX.units.mgPerL`。
  // 上のコメント参照）と揃える。`catalog.ts` の `variableCatalogByDataset` は
  // このテーブル（`variable_alias`）の (variable_id, grain, stat, unit_id) の組と
  // セル自身の組を突き合わせるため、ここがずれると該当セルが1件も拾えなくなる。
  alias.run({ alias: "浮遊物質量 SS", dataset: "measurements", sourceId: null, variableId: FX.variables.ss, unitId: FX.units.mgPerL, stat: "mean", grain: "day" });
  alias.run({ alias: "浮遊物質量 SS", dataset: "measurements", sourceId: "fx_atsugi", variableId: FX.variables.ss, unitId: FX.units.mgPerL, stat: "mean", grain: "day" });
  // point/day（`FX.series.ssPoint`）は unitId を変えていない（fx_place_b のセルは
  // 引き続き unit_id NULL のまま）ので、この alias 行も null のまま揃える。
  alias.run({ alias: "浮遊物質量 SS", dataset: "measurements", sourceId: "fx_env", variableId: FX.variables.ss, unitId: null, stat: "point", grain: "day" });
  alias.run({
    alias: "浮遊物質量 SS(年間)",
    dataset: "measurements",
    sourceId: "fx_annual",
    variableId: FX.variables.ss,
    unitId: null,
    stat: "mean",
    grain: "fiscal_year",
  });
  alias.run({ alias: "RAIN", dataset: "sensor_timeseries", sourceId: "fx_sagamihara", variableId: FX.variables.rain, unitId: null, stat: "sum", grain: "hour" });
  alias.run({ alias: "BOD", dataset: "measurements", sourceId: "fx_atsugi2", variableId: FX.variables.bod, unitId: FX.units.mgPerL, stat: "mean", grain: "day" });

  const source = db.prepare(`INSERT INTO source_registry (source_id, name, publisher, url, category, access_method, format, license, redistributable, fetched_at, record_count, notes) VALUES (@sourceId,@name,NULL,NULL,NULL,NULL,NULL,@license,1,NULL,NULL,NULL)`);
  source.run({ sourceId: "fx_atsugi", name: "厚木河川水質", license: "CC-BY" });
  source.run({ sourceId: "fx_env", name: "環境科学水質サンプル", license: "CC-BY" });
  source.run({ sourceId: "fx_annual", name: "年間集計", license: "CC-BY" });
  source.run({ sourceId: "fx_sagamihara", name: "相模原大気", license: "CC0" });
  source.run({ sourceId: "fx_atsugi2", name: "厚木BOD", license: "CC-BY" });
  // `envelope.ts` の provenance 解決は `series.ts`（実データの generated.ts、フィクスチャの
  // variable_alias とは独立）の `seriesInfo()` を経由するため、`common:variable:water.ss`
  // の mean/day 組の実際の source_id（'atsugi_river_water_quality'、実 registry.sqlite の
  // 値）でも引けるよう、テスト用にこの source_id の行も入れておく（envelope.test.ts 参照）。
  source.run({ sourceId: "atsugi_river_water_quality", name: "厚木河川水質（実データ源）", license: "CC-BY-FX" });

  db.prepare(`INSERT INTO caveat (caveat_id, severity, kind, title_ja, body_ja, quote) VALUES ('common:caveat:fx_test','info','data_quality','テスト注記','フィクスチャ用のテスト注記',NULL)`).run();
  db.prepare(`INSERT INTO caveat_scope (caveat_id, scope_kind, scope_ref, sort_order, priority) VALUES ('common:caveat:fx_test','table','meas_year',0,0)`).run();
  // facet 行（1b が使う v2 キー。design §6）。1a はこの行を消費しないが、
  // フィクスチャの内容としては design §7 の要求どおり両方入れておく。
  db.prepare(`INSERT INTO caveat_scope (caveat_id, scope_kind, scope_ref, sort_order, priority) VALUES ('common:caveat:fx_test','dataset','measurements',0,0)`).run();

  // --- water.ss: mean/day（合成 + atsugi。fx_place_a） ---
  // `unitId: FX.units.mgPerL`: `FX.series.ssMean` と一致させる（上のコメント参照。
  // 実 registry が mean/day 組に `common:unit:mg_per_l` を持つのに合わせてある）。
  insertObsAgg(db, [
    // 日セル（3日分。2日目は検閲〔value_zero≠value_lod〕、3日目は不検出〔value_lod NULL〕）
    { placeId: FX.places.a, variableId: FX.variables.ss, obsStat: "mean", unitId: FX.units.mgPerL, valueGrain: "day", grain: "day", inputGrain: "day", stat: "mean", periodStart: "2024-01-01", valueZero: 10.0, valueLod: 10.0, n: 1 },
    { placeId: FX.places.a, variableId: FX.variables.ss, obsStat: "mean", unitId: FX.units.mgPerL, valueGrain: "day", grain: "day", inputGrain: "day", stat: "mean", periodStart: "2024-01-02", valueZero: 8.0, valueLod: 6.0, n: 1, nCensored: 1 },
    { placeId: FX.places.a, variableId: FX.variables.ss, obsStat: "mean", unitId: FX.units.mgPerL, valueGrain: "day", grain: "day", inputGrain: "day", stat: "mean", periodStart: "2024-01-03", valueZero: 0.0, valueLod: null, n: 1, nCensored: 1, nNotDetected: 1 },
    // 月セル（1月、上の3日の集計。SQLite の AVG は NULL を無視する実際の挙動に合わせてある）
    { placeId: FX.places.a, variableId: FX.variables.ss, obsStat: "mean", unitId: FX.units.mgPerL, valueGrain: "day", grain: "month", inputGrain: "day", stat: "mean", periodStart: "2024-01-01", periodEnd: "2024-01-31", valueZero: 6.0, valueLod: 8.0, n: 3, nCensored: 2, nNotDetected: 1 },
    // 年セル（暦年、input_grain='day' = v1 の kind='daily'）
    { placeId: FX.places.a, variableId: FX.variables.ss, obsStat: "mean", unitId: FX.units.mgPerL, valueGrain: "day", grain: "year", inputGrain: "day", stat: "mean", periodStart: "2024-01-01", periodEnd: "2024-12-31", valueZero: 6.0, valueLod: 8.0, n: 3, nCensored: 2, nNotDetected: 1 },
  ]);

  // fx_place_c（`sites` に無い地点）にも同じ mean/day 系列のセルを持たせる
  // （all_sites/zone スコープには入るが、water スコープ（`sites` JOIN）には入らないことを
  // テストするため）。
  insertObsAgg(db, [
    { placeId: FX.places.c, variableId: FX.variables.ss, obsStat: "mean", unitId: FX.units.mgPerL, valueGrain: "day", grain: "day", inputGrain: "day", stat: "mean", periodStart: "2024-01-01", valueZero: 5.0, valueLod: 5.0, n: 1 },
    { placeId: FX.places.c, variableId: FX.variables.ss, obsStat: "mean", unitId: FX.units.mgPerL, valueGrain: "day", grain: "year", inputGrain: "day", stat: "mean", periodStart: "2024-01-01", periodEnd: "2024-12-31", valueZero: 5.0, valueLod: 5.0, n: 1 },
  ]);

  // --- water.ss: point/day（env。fx_place_b） ---
  // `obs_stat`（系列キーの一部。出典側の「点測定」というメタ情報）と `stat`（キューブが
  // 常に持つ集計方法の列。mean/min/max/sum のどれか）は別物: `obs_stat='point'` の系列でも
  // 実データでは `stat` は常に mean/min/max（1個の観測なら mean=min=max=値）で、
  // `stat='point'` という値はキューブに一度も現れない（実 v2.sqlite で確認済み）。
  insertObsAgg(db, [
    { placeId: FX.places.b, variableId: FX.variables.ss, obsStat: "point", valueGrain: "day", grain: "day", inputGrain: "day", stat: "mean", periodStart: "2024-01-01", valueZero: 15.0, valueLod: 15.0, n: 1 },
    { placeId: FX.places.b, variableId: FX.variables.ss, obsStat: "point", valueGrain: "day", grain: "day", inputGrain: "day", stat: "mean", periodStart: "2024-01-02", valueZero: 17.0, valueLod: 17.0, n: 1 },
    // 年セル（year, input_grain='day'）。b04 は grain='day' の観測があるかぎり
    // 年ロールアップも作るため、fx_place_b にも同じ形の年セルを持たせる
    // （無いと site_var/sites 系のカタログ問い合わせから fx_place_b が丸ごと落ちてしまう）。
    { placeId: FX.places.b, variableId: FX.variables.ss, obsStat: "point", valueGrain: "day", grain: "year", inputGrain: "day", stat: "mean", periodStart: "2024-01-01", periodEnd: "2024-12-31", valueZero: 16.0, valueLod: 16.0, n: 2 },
  ]);

  // --- water.ss: mean/fiscal_year（annual。fx_place_a） ---
  insertObsAgg(db, [
    { placeId: FX.places.a, variableId: FX.variables.ss, obsStat: "mean", valueGrain: "fiscal_year", grain: "fiscal_year", inputGrain: "fiscal_year", stat: "mean", periodStart: "2024-04-01", periodEnd: "2025-03-31", valueZero: 11.0, valueLod: 11.0, n: 1 },
  ]);

  // --- weather.precipitation: sum/hour（RAIN、hour→day。fx_place_rain。2ヶ月分） ---
  insertObsAgg(db, [
    { placeId: FX.places.rain, variableId: FX.variables.rain, obsStat: "sum", valueGrain: "hour", grain: "day", inputGrain: "hour", stat: "sum", periodStart: "2024-01-01", valueZero: 5.0, valueLod: 5.0, n: 24 },
    { placeId: FX.places.rain, variableId: FX.variables.rain, obsStat: "sum", valueGrain: "hour", grain: "day", inputGrain: "hour", stat: "sum", periodStart: "2024-01-02", valueZero: 0.0, valueLod: 0.0, n: 24 },
    { placeId: FX.places.rain, variableId: FX.variables.rain, obsStat: "sum", valueGrain: "hour", grain: "day", inputGrain: "hour", stat: "sum", periodStart: "2024-02-15", valueZero: 12.0, valueLod: 12.0, n: 24 },
  ]);

  // --- water.bod: mean/day（unit_id NOT NULL。fx_place_a） ---
  insertObsAgg(db, [
    { placeId: FX.places.a, variableId: FX.variables.bod, obsStat: "mean", unitId: FX.units.mgPerL, valueGrain: "day", grain: "day", inputGrain: "day", stat: "mean", periodStart: "2024-01-01", valueZero: 2.0, valueLod: 2.0, n: 1 },
    { placeId: FX.places.a, variableId: FX.variables.bod, obsStat: "mean", unitId: FX.units.mgPerL, valueGrain: "day", grain: "year", inputGrain: "day", stat: "mean", periodStart: "2024-01-01", periodEnd: "2024-12-31", valueZero: 2.0, valueLod: 2.0, n: 1 },
  ]);
}

export interface CubeFixture {
  db: CubeDb & { close(): void };
  raw: Database.Database;
}

/** in-memory の `CubeDb` を組み立てる（ATTACH は使わない。全テーブルが同じ DB に同居）。 */
export function buildCubeFixture(): CubeFixture {
  const raw = new Database(":memory:");
  applyMigrations(raw);
  seed(raw);

  const db: CubeDb & { close(): void } = {
    kind: "sqlite",
    async all<T = Row>(sql: string, params: readonly SqlParam[] = []): Promise<T[]> {
      assertD1Compatible(sql, params);
      const stmt = raw.prepare(sql);
      const rows = params.length ? stmt.all(...(params as unknown[])) : stmt.all();
      return rows as T[];
    },
    close() {
      raw.close();
    },
  };

  return { db, raw };
}
