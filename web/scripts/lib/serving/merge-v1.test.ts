/**
 * `merge-v1.ts`（v1 側の alias→variable_id 束ね、design §3 #2）のテスト。
 * `@/lib/cube` を一切 import しない（`series.ts`/`generated.ts` の実データに
 * 依存しない）ので、`registry.sqlite` と同じ `variable_alias` スキーマを持つ
 * 使い捨ての sqlite ファイルだけで完結する（`adapters-v2.test.ts` の
 * `expectedUnitSymbols` ambiguous テストと同じ流儀）。
 */
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import Database from "better-sqlite3";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  aliasKindRoutes,
  aliasesForBasis,
  allAliasesFor,
  allGroups,
  clearMergeV1Cache,
  loadAliasInfos,
  representativeGroups,
  variableIdsOf,
} from "./merge-v1";

const DATASET = "measurements";

interface AliasRow {
  alias: string;
  variable_id: string | null;
  stat: string | null;
  grain: string | null;
}

function makeRegistry(dir: string, rows: AliasRow[]): string {
  const dbPath = path.join(dir, "registry.sqlite");
  const db = new Database(dbPath);
  db.exec(`
    CREATE TABLE variable_alias (
      id INTEGER PRIMARY KEY AUTOINCREMENT, alias TEXT NOT NULL, dataset TEXT,
      source_id TEXT, variable_id TEXT, unit_id TEXT, stat TEXT, grain TEXT, note TEXT
    );
  `);
  const insert = db.prepare(
    `INSERT INTO variable_alias (alias, dataset, variable_id, stat, grain) VALUES (@alias, @dataset, @variable_id, @stat, @grain)`,
  );
  for (const r of rows) insert.run({ ...r, dataset: DATASET });
  db.close();
  return dbPath;
}

describe("merge-v1", () => {
  let dir: string;

  beforeEach(() => {
    dir = fs.mkdtempSync(path.join(fs.realpathSync(os.tmpdir()), "merge-v1-test-"));
    clearMergeV1Cache();
  });

  afterEach(() => {
    fs.rmSync(dir, { recursive: true, force: true });
    clearMergeV1Cache();
  });

  it("代表 stat（null/mean/point）の alias があれば、非代表 alias（p75 等）は代表グループから除かれる", () => {
    const dbPath = makeRegistry(dir, [
      { alias: "BOD", variable_id: "v:bod", stat: "mean", grain: "day" },
      { alias: "BOD 75%値", variable_id: "v:bod", stat: "p75", grain: "day" },
    ]);
    const groups = representativeGroups(dbPath, DATASET);
    expect(groups.get("v:bod")!.map((a) => a.alias)).toEqual(["BOD"]);
  });

  it("代表 alias が1つも無い variable は全 alias にフォールバックする（D4）", () => {
    const dbPath = makeRegistry(dir, [{ alias: "地盤沈下量", variable_id: "v:subsidence", stat: "max", grain: "year" }]);
    const groups = representativeGroups(dbPath, DATASET);
    expect(groups.get("v:subsidence")!.map((a) => a.alias)).toEqual(["地盤沈下量"]);
  });

  it("allGroups は代表フィルタをかけない（variable_catalog_by_variable/site_variables_by_variable 用）", () => {
    const dbPath = makeRegistry(dir, [
      { alias: "BOD", variable_id: "v:bod", stat: "mean", grain: "day" },
      { alias: "BOD 75%値", variable_id: "v:bod", stat: "p75", grain: "day" },
    ]);
    const groups = allGroups(dbPath, DATASET);
    expect(groups.get("v:bod")!.map((a) => a.alias).sort()).toEqual(["BOD", "BOD 75%値"]);
  });

  it("annualBasis: grain='year' の alias は annual を 'year' に、それ以外は 'fiscal_year' に振り分ける", () => {
    const dbPath = makeRegistry(dir, [
      { alias: "地盤沈下量", variable_id: "v:subsidence", stat: null, grain: "year" },
      { alias: "COD", variable_id: "v:cod", stat: "mean", grain: "fiscal_year" },
    ]);
    const infos = loadAliasInfos(dbPath, DATASET);
    expect(infos.get("地盤沈下量")!.annualBasis).toBe("year");
    expect(infos.get("COD")!.annualBasis).toBe("fiscal_year");
  });

  it("aliasesForBasis: day は hasDayGrain、それ以外は annualBasis が一致する alias だけ", () => {
    const dbPath = makeRegistry(dir, [
      { alias: "BOD", variable_id: "v:bod", stat: "mean", grain: "day" },
      { alias: "BOD", variable_id: "v:bod", stat: "mean", grain: "fiscal_year" },
    ]);
    expect(aliasesForBasis(dbPath, DATASET, "v:bod", "day")).toEqual(["BOD"]);
    expect(aliasesForBasis(dbPath, DATASET, "v:bod", "fiscal_year")).toEqual(["BOD"]);
    expect(aliasesForBasis(dbPath, DATASET, "v:bod", "year")).toEqual([]);
  });

  it("aliasesForBasis: 真の annual tuple が無い alias（hasAnnualGrain=false）は day 以外の basis に出てこない（実測: 'pH'）", () => {
    const dbPath = makeRegistry(dir, [{ alias: "pH", variable_id: "v:ph", stat: "point", grain: "day" }]);
    expect(aliasesForBasis(dbPath, DATASET, "v:ph", "day")).toEqual(["pH"]);
    expect(aliasesForBasis(dbPath, DATASET, "v:ph", "fiscal_year")).toEqual([]);
  });

  it("allAliasesFor: kind を問わず variable_id に属する alias 全部（代表フィルタ無し）", () => {
    const dbPath = makeRegistry(dir, [
      { alias: "BOD", variable_id: "v:bod", stat: "mean", grain: "day" },
      { alias: "BOD 75%値", variable_id: "v:bod", stat: "p75", grain: "day" },
    ]);
    expect(allAliasesFor(dbPath, DATASET, "v:bod").sort()).toEqual(["BOD", "BOD 75%値"]);
  });

  it("aliasKindRoutes: 1 alias が day/fiscal_year 両方の tuple を持てば (daily,day)/(annual,fiscal_year) の2行になる", () => {
    const dbPath = makeRegistry(dir, [
      { alias: "BOD", variable_id: "v:bod", stat: "mean", grain: "day" },
      { alias: "BOD", variable_id: "v:bod", stat: "mean", grain: "fiscal_year" },
    ]);
    const routes = aliasKindRoutes(dbPath, DATASET);
    expect(routes).toHaveLength(2);
    expect(routes).toContainEqual({ alias: "BOD", kind: "daily", variableId: "v:bod", basis: "day" });
    expect(routes).toContainEqual({ alias: "BOD", kind: "annual", variableId: "v:bod", basis: "fiscal_year" });
  });

  it("aliasKindRoutes: 同じ alias・同じ grain に複数の obs_stat が混在しても例外にならない（実測: 'pH'）", () => {
    const dbPath = makeRegistry(dir, [
      { alias: "pH", variable_id: "v:ph", stat: "point", grain: "day" },
      { alias: "pH", variable_id: "v:ph", stat: "mean", grain: "day" },
    ]);
    expect(() => aliasKindRoutes(dbPath, DATASET)).not.toThrow();
    const routes = aliasKindRoutes(dbPath, DATASET);
    // grain='day' しか登録が無くても、annual-kind 行は既定の annualBasis
    // （'fiscal_year'）に出す——`hasAnnualGrain`（真の annual tuple の登録）は
    // 問わない。v2 側（`adapters-v2.ts` が呼ぶ `@/lib/cube` の `basisOfCell`）も
    // セル単位の input_grain で basis を決めており、alias の登録を見ないため
    // （`aliasKindRoutes` の docstring 参照）。
    expect(routes).toEqual([
      { alias: "pH", kind: "daily", variableId: "v:ph", basis: "day" },
      { alias: "pH", kind: "annual", variableId: "v:ph", basis: "fiscal_year" },
    ]);
  });

  it("aliasKindRoutes: day tuple だけの alias（真の annual tuple 無し）でも annual 行は既定の annualBasis に出す", () => {
    const dbPath = makeRegistry(dir, [{ alias: "BOD", variable_id: "v:bod", stat: "mean", grain: "day" }]);
    const routes = aliasKindRoutes(dbPath, DATASET);
    expect(routes).toEqual([
      { alias: "BOD", kind: "daily", variableId: "v:bod", basis: "day" },
      { alias: "BOD", kind: "annual", variableId: "v:bod", basis: "fiscal_year" },
    ]);
  });

  it("aliasKindRoutes: 代表フィルタ無し（非代表 alias も含む）", () => {
    const dbPath = makeRegistry(dir, [
      { alias: "BOD", variable_id: "v:bod", stat: "mean", grain: "day" },
      { alias: "BOD 75%値", variable_id: "v:bod", stat: "p75", grain: "day" },
    ]);
    const routes = aliasKindRoutes(dbPath, DATASET);
    const aliases = new Set(routes.map((r) => r.alias));
    expect(aliases).toEqual(new Set(["BOD", "BOD 75%値"]));
  });

  it("variableIdsOf: 代表グループを持つ variable_id の一覧（ソート済み）", () => {
    const dbPath = makeRegistry(dir, [
      { alias: "BOD", variable_id: "v:bod", stat: "mean", grain: "day" },
      { alias: "COD", variable_id: "v:cod", stat: "mean", grain: "day" },
    ]);
    expect(variableIdsOf(dbPath, DATASET)).toEqual(["v:bod", "v:cod"]);
  });

  it("同じ alias が複数の variable_id にまたがっていれば例外（T4 不変条件）", () => {
    const dbPath = makeRegistry(dir, [
      { alias: "X", variable_id: "v:a", stat: "mean", grain: "day" },
      { alias: "X", variable_id: "v:b", stat: "mean", grain: "day" },
    ]);
    expect(() => loadAliasInfos(dbPath, DATASET)).toThrow(/複数の variable_id/);
  });

  it("同じ alias が fiscal_year と year の両方の grain を持てば例外（annual バケットが一意に決まらない）", () => {
    const dbPath = makeRegistry(dir, [
      { alias: "X", variable_id: "v:a", stat: "mean", grain: "fiscal_year" },
      { alias: "X", variable_id: "v:a", stat: "mean", grain: "year" },
    ]);
    expect(() => loadAliasInfos(dbPath, DATASET)).toThrow(/fiscal_year と year の両方/);
  });

  it("variable_id が NULL の行は無視する（未解決の alias）", () => {
    const dbPath = makeRegistry(dir, [{ alias: "未解決", variable_id: null, stat: null, grain: "day" }]);
    expect(loadAliasInfos(dbPath, DATASET).has("未解決")).toBe(false);
  });
});
