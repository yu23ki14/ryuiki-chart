/**
 * v2 アダプタのテスト（DB 不要。`lib/cube` のフィクスチャかスタブを使う）。
 * 値の正しさは見ない（それはスナップショット・指紋の仕事）。見るのは、アダプタが生 SQL を持たないこと・
 * `serving_queries.yaml` の `compare` の列名とアダプタが返す列名が食い違っていないこと・呼び出しの既定値。
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it, vi } from "vitest";
import { runV2Query } from "./adapters-v2";
import { parseServingQueries } from "./snapshot";
import * as generatedClient from "@/lib/registry/generated-client";
import { buildOccurrenceFixture, FXO } from "@/lib/cube/__fixtures__/occurrence-fixture";
import type { ScalarParam } from "./normalize";

/**
 * design §8.4「検証が本番の経路を通っているか」の自動チェック1件:
 * `adapters-v2.ts` は生 SQL を持たない（`@/lib/cube` の公開関数だけを呼ぶ）
 * ——`observation_agg`/`summary_` という文字列そのものがソースに出てこないことで
 * 確認する（キューブ・summary 2表のテーブル名は `lib/cube` 側にしか書かない）。
 */
describe("adapters-v2.ts は生 SQL を持たない（design §8.4）", () => {
  it("ソースに observation_agg / summary_ という文字列が無い", () => {
    const HERE = path.dirname(fileURLToPath(import.meta.url));
    const src = fs.readFileSync(path.join(HERE, "adapters-v2.ts"), "utf8");
    expect(src).not.toMatch(/observation_agg/);
    expect(src).not.toMatch(/summary_/);
  });

  // PR-3b §5.4: 生物系（セル・summary 4表・レッドリスト）の表名も書かない。
  it("ソースに occurrence_agg / summary_ / taxon_assessment という文字列が無い（生物系。PR-3b §5.4）", () => {
    const HERE = path.dirname(fileURLToPath(import.meta.url));
    const src = fs.readFileSync(path.join(HERE, "adapters-v2.ts"), "utf8");
    expect(src).not.toMatch(/occurrence_agg/);
    expect(src).not.toMatch(/summary_/);
    expect(src).not.toMatch(/taxon_assessment/);
  });

  // PR-4 §8.4: 文書・概況・流域の表名（cells/notes/documents/place/observation_agg）が SQL 文脈で出ない。
  it("ソースに cells / notes / documents / place / observation_agg が SQL 文脈（FROM/JOIN/INTO/UPDATE の直後）で出ない（PR-4 §8.4）", () => {
    const HERE = path.dirname(fileURLToPath(import.meta.url));
    const src = fs.readFileSync(path.join(HERE, "adapters-v2.ts"), "utf8");
    const noComments = src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*$/gm, "");
    expect(noComments).not.toMatch(/\b(from|join|into|update)\s+["`]?(\w+\.)?(cells|notes|documents|place|place_relation|observation_agg)\b/i);
    // 引用符で囲んだ表名（`"cells"` 等）も書かない（`"place"` は summarize の分解軸の値でもあるので対象外）。
    expect(noComments).not.toMatch(/["'`](cells|notes|documents|place_relation|observation_agg)["'`]/);
    // 文書・概況・流域は lib/cube の公開関数（index.ts）だけを呼ぶ（内部ファイルを直接 import しない）。
    expect(src).not.toMatch(/@\/lib\/cube\/(documents|catalog-docs)/);
  });

  it("生物系の case は lib/cube の公開関数しか import しない（`@/lib/cube/<内部ファイル>` を足していない）", () => {
    const HERE = path.dirname(fileURLToPath(import.meta.url));
    const src = fs.readFileSync(path.join(HERE, "adapters-v2.ts"), "utf8");
    // 既存の測定値系が使う `@/lib/cube/catalog`・`/db-sqlite`・`/series` 等以外の新規 import を足していないこと
    // （occurrence/assessment の内部ファイルを直接読まない。index.ts の公開面だけ）。
    expect(src).not.toMatch(/@\/lib\/cube\/(occurrence|assessment|grid)/);
  });
});

/**
 * 生物系の v2 アダプタを `lib/cube` のフィクスチャ（`buildOccurrenceFixture`）に通す。
 * 目的: `serving_queries.yaml` の `compare`（key/numeric/label の列名）と、アダプタが返す列名が
 * 食い違っていないこと（`toNormRows` は無い列を黙って null にするので、全行 null の列を検出する）。
 * 値の正しさは見ない（それは serving-snapshot の仕事）。
 */
describe("生物系の v2 アダプタ: serving_queries.yaml の compare の列名とアダプタの列名が一致する", () => {
  const generated = generatedClient as unknown as { REDLIST_CATEGORY?: unknown; ASSESSMENT_LIST?: unknown };
  const hasVocab = generated.REDLIST_CATEGORY !== undefined && generated.ASSESSMENT_LIST !== undefined;

  const HERE_ = path.dirname(fileURLToPath(import.meta.url));
  const yamlPath = path.join(HERE_, "..", "..", "..", "serving_queries.yaml");
  const config = parseServingQueries(fs.readFileSync(yamlPath, "utf8"));

  // フィクスチャの架空の値（`Fx*`）で埋めた最小の params。
  const PARAMS: Record<string, Record<string, ScalarParam>> = {
    species_years: { binom: FXO.binoms.alpha },
    species_months: { binom: FXO.binoms.alpha },
    species_mesh_years: { binom: FXO.binoms.alpha },
    species_share_trend: { group: FXO.groups.bird, periods: "2000-2004:2010-2014" },
    mesh_by_year: { year: 2010 },
  };
  const BIOTA_IDS = [
    "effort_years",
    "taxon_group_years",
    "species_catalog",
    "species_years",
    "species_months",
    "species_mesh_years",
    "species_share_trend",
    "mesh_all",
    "mesh_by_year",
    "ias_species",
    "redlist_summary",
    "biota_totals",
    "watershed_rollup",
  ];
  // `watershed_rollup` は PR-4 で非生物列（site_n・area・土地利用）が増え、生物系フィクスチャには
  // `place_relation`/土地利用セルが無いので、下の「PR-4 の v2 アダプタ」（`lib/cube` の関数をモック）で見る。
  const FIXTURE_IDS = BIOTA_IDS.filter((id) => id !== "watershed_rollup");

  it("serving_queries.yaml に生物系の問い合わせが全部ある（アダプタの case と1対1）", () => {
    const ids = new Set(config.queries.map((q) => q.id));
    for (const id of BIOTA_IDS) expect(ids.has(id), id).toBe(true);
  });

  for (const id of FIXTURE_IDS) {
    const needsVocab = id.startsWith("redlist_");
    it.skipIf(needsVocab && !hasVocab)(`${id}: 行が返り、compare の numeric/label の各列が少なくとも1行で非 null`, async () => {
      const def = config.queries.find((q) => q.id === id)!;
      const fx = buildOccurrenceFixture();
      try {
        const rows = await runV2Query(fx.db, id, PARAMS[id] ?? {}, def.compare, "zero");
        expect(rows.length, `${id} の行`).toBeGreaterThan(0);
        for (const r of rows) expect(r.key.length).toBe(def.compare.key.length);
        for (const c of def.compare.numeric) expect(rows.some((r) => r.numeric[c] !== null), `${id}.${c}`).toBe(true);
        // `ord` のようにキー列としてだけ使う列は numeric/label ではないので対象外。
        for (const c of def.compare.label) expect(rows.some((r) => r.label[c] !== null), `${id}.${c}`).toBe(true);
      } finally {
        fx.db.close();
      }
    });
  }

});

/**
 * PR-4: 文書・概況・流域の v2 アダプタが、`serving_queries.yaml` の `compare` の列名どおりの行を返す
 * （`lib/cube` の新関数は U1 の実装なのでここでは §4.1 の形のスタブに差し替える。値の正しさは
 * serving-snapshot が見る）。呼び出しの既定値（画面・API と同じ `minYears: 3`・`limit: 8`・
 * `watershedRollup(db)` 1本）もここで固定する。
 */
describe("PR-4 の v2 アダプタ: compare の列名と呼び出しの既定値", () => {
  afterEach(() => {
    vi.doUnmock("@/lib/cube");
    vi.resetModules();
  });

  const HERE_ = path.dirname(fileURLToPath(import.meta.url));
  const config = parseServingQueries(fs.readFileSync(path.join(HERE_, "..", "..", "..", "serving_queries.yaml"), "utf8"));
  const IDS = ["doc_series_meta", "doc_series_points", "overview_counts", "landuse_highlight", "watershed_rollup"];

  it("serving_queries.yaml に PR-4 の 5 問い合わせ（新規4＋拡張1）が全部ある", () => {
    const ids = new Set(config.queries.map((q) => q.id));
    for (const id of IDS) expect(ids.has(id), id).toBe(true);
  });

  it("各 id が compare の全列（key/numeric/label）で非 null を返し、既定値で呼ぶ", async () => {
    const spies = {
      docSeriesList: vi.fn(async () => [
        { docId: "d", tableId: "t", rowKey: "a|b", label: "b", pageNo: 3, nYears: 4, yFrom: 2010, yTo: 2014, unit: "u", docTitle: "T", publisher: "P", url: "http://x", license: "L", nWarnings: 2 },
      ]),
      docSeriesPoints: vi.fn(async () => [{ fiscalYear: 2010, value: 1.5, unit: "u", pageNo: 3 }]),
      overviewCounts: vi.fn(async () => ({ sites: 352, sources: 5, watersheds: 377, variables: 75, yFrom: 1973, yTo: 2026 })),
      landuseHighlight: vi.fn(async () => [{ watershedId: "w1", waterSystemName: "A", delta: 5.9, areaKm2: 12 }]),
      watershedRollup: vi.fn(async () => {
        const cell = { from: 1, to: 2 };
        return {
          watersheds: [
            { watershedId: "w1", waterSystemName: "A", areaKm2: 12, centroidLat: 35.4, centroidLon: 139.4, siteN: 3, orgN: 4, orgAlienN: 1, orgRedlistN: 2, built: cell, forest: cell, paddy: cell },
          ],
          landuseYears: { from: 2006, to: 2016 },
          outsideWatershed: null,
        };
      }),
    };
    vi.resetModules();
    vi.doMock("@/lib/cube", async (importOriginal) => ({ ...(await importOriginal<typeof import("@/lib/cube")>()), ...spies }));
    const { runV2Query: run } = await import("./adapters-v2");
    const db = {} as never;
    const params: Record<string, Record<string, ScalarParam>> = { doc_series_points: { doc_id: "d", table_id: "t", row_key: "a|b" } };
    for (const id of IDS) {
      const def = config.queries.find((q) => q.id === id)!;
      const rows = await run(db, id, params[id] ?? {}, def.compare, "zero");
      expect(rows.length, id).toBe(1);
      expect(rows[0].key.length).toBe(def.compare.key.length);
      for (const c of def.compare.key) expect(rows[0].key.every((k) => k !== ""), `${id}.${c}`).toBe(true);
      for (const c of def.compare.numeric) expect(rows[0].numeric[c], `${id}.${c}`).not.toBeNull();
      for (const c of def.compare.label) expect(rows[0].label[c], `${id}.${c}`).not.toBeNull();
    }
    // 画面・API・AI と同じ既定値（設計書 §8.4-1）。
    expect(spies.docSeriesList).toHaveBeenCalledWith(db, { minYears: 3 });
    expect(spies.docSeriesPoints).toHaveBeenCalledWith(db, "d", "t", "a|b");
    expect(spies.landuseHighlight).toHaveBeenCalledWith(db, 8);
    expect(spies.watershedRollup).toHaveBeenCalledTimes(1);
    expect(spies.watershedRollup).toHaveBeenCalledWith(db);
    expect(spies.overviewCounts).toHaveBeenCalledWith(db);
  });

  it("土地利用の版が 2006/2016 でなければ止まる（v1 の列名との対応がずれたまま比べない）", async () => {
    vi.resetModules();
    vi.doMock("@/lib/cube", async (importOriginal) => ({
      ...(await importOriginal<typeof import("@/lib/cube")>()),
      watershedRollup: async () => ({ watersheds: [], landuseYears: { from: 2011, to: 2021 }, outsideWatershed: null }),
    }));
    const { runV2Query: run } = await import("./adapters-v2");
    const def = config.queries.find((q) => q.id === "watershed_rollup")!;
    await expect(run({} as never, "watershed_rollup", {}, def.compare, "zero")).rejects.toThrow(/2006\/2016/);
  });
});

describe("serving_queries.yaml と adapters-v2.ts の id が1対1", () => {
  const HERE_ = path.dirname(fileURLToPath(import.meta.url));
  const config = parseServingQueries(fs.readFileSync(path.join(HERE_, "..", "..", "..", "serving_queries.yaml"), "utf8"));
  const src = fs.readFileSync(path.join(HERE_, "adapters-v2.ts"), "utf8");
  const caseIds = new Set([...src.matchAll(/^ {4}case "(\w+)":/gm)].map((m) => m[1]));

  it("YAML の全 id にアダプタの case がある", () => {
    for (const q of config.queries) expect(caseIds.has(q.id), q.id).toBe(true);
  });
  it("アダプタの case はすべて YAML にある（呼ばれない分岐を残さない）", () => {
    const ids = new Set(config.queries.map((q) => q.id));
    for (const id of caseIds) expect(ids.has(id), id).toBe(true);
  });
});
