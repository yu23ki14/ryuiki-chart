/**
 * `expectedUnitSymbols()`（Issue #48 PR-1 code-review #3）のテスト。
 *
 * この関数は `registry.sqlite` の `variable_alias`/`unit` を SQL で直接読み、
 * v2 アダプタ自身が「v2 側の unit 列」を計算するのに使う経路（`seriesForAlias(...)[0].unitId`
 * 経由の `unitLabel()`。`adapters-v2.ts` の `fetchRawRows` 参照）とは独立に「正しい
 * unit symbol」を求める。以前の実装は両方が同じ式（`seriesForAlias(...)[0].unitId`）を
 * 使っていたため、`classify.ts` の `unit_label_registry` 規則の `expected === v2Unit` が
 * 構造的に常に真になり、実際にレジストリと一致しているかを何も確かめていなかった
 * （`seriesForAlias`/`generated.ts` 側にバグがあっても検出できない）。
 */
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import Database from "better-sqlite3";
import { afterEach, describe, expect, it, vi } from "vitest";
import { rowsByKey, toNormRows } from "./normalize";
import { classifyDiff, compareRuns, type ClassifyContext } from "./classify";
import { expectedUnitSymbols } from "./adapters-v2";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(HERE, "..", "..", "..", "..");
const DB_DIR = process.env.RYUIKI_DB_DIR ?? path.join(REPO_ROOT, "data", "db");
const REGISTRY_DB_PATH = process.env.RYUIKI_REGISTRY_DB ?? path.join(DB_DIR, "registry.sqlite");

function ctxBase(overrides: Partial<ClassifyContext> = {}): ClassifyContext {
  return {
    expected: {},
    declared: { v1Table: null, builder: null },
    params: {},
    known: new Set(),
    ...overrides,
  };
}

describe("expectedUnitSymbols（registry.sqlite を直接 SQL で読む）", () => {
  it("実データ: BOD（3 alias とも unit_id が common:unit:mg_per_l で一致）は symbol 'mg/L' を返す", () => {
    const map = expectedUnitSymbols(REGISTRY_DB_PATH);
    expect(map.get("生物化学的酸素要求量 BOD")).toBe("mg/L");
  });

  it("unit_id が1つに定まらない alias（NULLを除いて2種類以上）は期待値を持たない（unexplained に倒す）", () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "expected-unit-symbols-ambiguous-"));
    const dbPath = path.join(dir, "registry.sqlite");
    try {
      const db = new Database(dbPath);
      db.exec(`
        CREATE TABLE variable_alias (
          id INTEGER PRIMARY KEY AUTOINCREMENT, alias TEXT NOT NULL, dataset TEXT,
          source_id TEXT, variable_id TEXT, unit_id TEXT, stat TEXT, grain TEXT, note TEXT
        );
        CREATE TABLE unit (unit_id TEXT PRIMARY KEY, symbol TEXT, ucum TEXT, name_ja TEXT, quantity_kind TEXT);
      `);
      db.prepare(`INSERT INTO unit (unit_id, symbol) VALUES (?, ?)`).run("common:unit:mg_per_l", "mg/L");
      db.prepare(`INSERT INTO unit (unit_id, symbol) VALUES (?, ?)`).run("common:unit:degc", "℃");
      const insertAlias = db.prepare(
        `INSERT INTO variable_alias (alias, dataset, unit_id) VALUES ('生物化学的酸素要求量 BOD', 'measurements', ?)`,
      );
      insertAlias.run("common:unit:mg_per_l");
      insertAlias.run("common:unit:degc"); // 同じ alias に2つ目の異なる非NULL unit_id を混入させる
      db.close();

      const map = expectedUnitSymbols(dbPath);
      expect(map.has("生物化学的酸素要求量 BOD")).toBe(false);
    } finally {
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });

  afterEach(() => {
    vi.doUnmock("@/lib/registry/generated");
    vi.resetModules();
  });

  it("変異: seriesForAlias（generated.ts 由来）が BOD に別の unit_id を返しても、真の期待値（registry.sqlite 直読み）との食い違いを検出する（unexplained）", async () => {
    // `@/lib/registry/generated` の `GENERATED_VARIABLE_ALIASES` を、BOD の
    // unit_id が気温（degC）になるよう書き換えてモックする（`seriesForAlias`
    // 自体・`generated.ts` の生成にバグがあった場合の再現）。
    vi.resetModules();
    vi.doMock("@/lib/registry/generated", async (importOriginal) => {
      const actual = await importOriginal<typeof import("@/lib/registry/generated")>();
      const mutatedAliases = actual.GENERATED_VARIABLE_ALIASES.map((a) =>
        a.alias === "生物化学的酸素要求量 BOD" ? { ...a, unitId: "common:unit:degc" } : a,
      );
      return { ...actual, GENERATED_VARIABLE_ALIASES: mutatedAliases };
    });

    // v2 アダプタが実際に unit 列を計算するのと同じ式
    // （`adapters-v2.ts` の `unitLabel(series[0]?.unitId ?? null)`）で、
    // モック後の（壊れた）v2Unit を求める。
    const { seriesForAlias } = await import("@/lib/cube/series");
    const { unitSymbol } = await import("@/lib/registry/lookup");
    const mutatedSeries = seriesForAlias("measurements", "生物化学的酸素要求量 BOD");
    const brokenV2Unit = unitSymbol(mutatedSeries[0]?.unitId ?? null);
    expect(brokenV2Unit).toBe("degC"); // モックが効いていることの確認

    // `expectedUnitSymbols`（この describe の最上部で静的 import した、モックの
    // 影響を受けない元の実装）は registry.sqlite を直接読むので、上のモックとは
    // 無関係に真の期待値（mg/L）を返し続ける。
    const map = expectedUnitSymbols(REGISTRY_DB_PATH);
    expect(map.get("生物化学的酸素要求量 BOD")).toBe("mg/L");

    const v1 = rowsByKey(toNormRows([{ alias: "生物化学的酸素要求量 BOD", n: 5, unit: null }], ["alias"], ["n"], ["unit"]));
    const v2 = rowsByKey(toNormRows([{ alias: "生物化学的酸素要求量 BOD", n: 5, unit: brokenV2Unit }], ["alias"], ["n"], ["unit"]));
    const diffs = compareRuns(v1, v2);
    const ctx = ctxBase({ known: new Set(["unit_label_registry"]), expectedUnitSymbol: map });
    expect(classifyDiff(diffs[0], ctx).rule).toBe("unexplained");
  });
});
