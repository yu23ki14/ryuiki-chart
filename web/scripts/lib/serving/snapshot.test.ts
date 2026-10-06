/**
 * `snapshot.ts`（serving-snapshot の純関数部分）のテスト。実 DB は使わない（実 DB での実行は統合者が CI 手順で1回）。
 */
import { describe, expect, it } from "vitest";
import type { NormRow, QueryDef } from "./normalize";
import {
  compareScalar,
  degenerateProblems,
  diffTable,
  evenIndices,
  expandParams,
  finalizeRows,
  fingerprintRun,
  formatFingerprint,
  formatSnapshot,
  parseServingQueries,
  resolveDomain,
  roundNumber,
  type ResolvedDomain,
  type Snapshot,
} from "./snapshot";

const row = (key: (string | number)[], numeric: Record<string, number | null> = {}, label: Record<string, string | null> = {}): NormRow => ({ key, numeric, label });

describe("順序・丸め", () => {
  it("compareScalar: 数値は数値順（10 は 9 の後）・文字列は UTF-16 順・数値が文字列より前", () => {
    const xs: (string | number)[] = ["b", 10, "a", 9, "B", "あ", "Z"];
    expect([...xs].sort(compareScalar)).toEqual([9, 10, "B", "Z", "a", "b", "あ"]);
  });
  it("roundNumber: 12 桁に丸める・整数はそのまま・-0 は 0", () => {
    expect(roundNumber(0.1 + 0.2)).toBe(0.3);
    expect(roundNumber(123456789012345)).toBe(123456789012345);
    expect(Object.is(roundNumber(-0), 0)).toBe(true);
    expect(roundNumber(1 / 3)).toBe(0.333333333333);
  });
  it("roundNumber: NaN / Infinity は例外（隠さない）", () => {
    expect(() => roundNumber(Number.NaN)).toThrow();
    expect(() => roundNumber(Number.POSITIVE_INFINITY)).toThrow();
  });
  it("finalizeRows: key の辞書式で整列し、数値を丸める", () => {
    const rows = finalizeRows([row([2, "b"], { v: 0.1 + 0.2 }), row([2, "a"], { v: 1 }), row([10, "a"], { v: null })]);
    expect(rows.map((r) => r.key)).toEqual([
      [2, "a"],
      [2, "b"],
      [10, "a"],
    ]);
    expect(rows[1].numeric.v).toBe(0.3);
    expect(rows[2].numeric.v).toBeNull();
  });
  it("finalizeRows: 同じ key の行は行全体の JSON で決まるので入力の並びに依らない", () => {
    const a = finalizeRows([row([1], { v: 2 }), row([1], { v: 1 })]);
    const b = finalizeRows([row([1], { v: 1 }), row([1], { v: 2 })]);
    expect(a).toEqual(b);
  });
});

describe("evenIndices（等間隔選択）", () => {
  it("n<=max は全部。超えるときは先頭・末尾を含む max 個で、昇順・重複なし", () => {
    expect(evenIndices(3, 12)).toEqual([0, 1, 2]);
    expect(evenIndices(0, 12)).toEqual([]);
    const idx = evenIndices(100, 12);
    expect(idx).toHaveLength(12);
    expect(idx[0]).toBe(0);
    expect(idx[11]).toBe(99);
    expect(new Set(idx).size).toBe(12);
    expect([...idx].sort((a, b) => a - b)).toEqual(idx);
    expect(evenIndices(5, 1)).toEqual([0]);
  });
});

describe("expandParams（直積・複数列ドメイン）", () => {
  const dom = (columns: string[], tuples: (string | number)[][]): ResolvedDomain => ({ columns, tuples });
  const def = (params: QueryDef["params"]): QueryDef => ({ id: "q", params, compare: { key: [], numeric: [], label: [] } });

  it("params が無ければ1件（空の組）", () => {
    expect(expandParams(def({}), {}, 12)).toEqual({ nDomain: 1, params: [{}] });
  });
  it("2軸の直積は先頭の軸が最上位。n_domain は全件数。出力の params はキー昇順", () => {
    const r = expandParams(def({ y: { domain: "Y" }, x: { domain: "X" } }), { Y: dom(["y"], [[1], [2]]), X: dom(["x"], [["a"], ["b"], ["c"]]) }, 100);
    expect(r.nDomain).toBe(6);
    expect(r.params.map((p) => JSON.stringify(p))).toEqual([
      '{"x":"a","y":1}',
      '{"x":"b","y":1}',
      '{"x":"c","y":1}',
      '{"x":"a","y":2}',
      '{"x":"b","y":2}',
      '{"x":"c","y":2}',
    ]);
  });
  it("複数列ドメインは1つの軸（組）。実在する組だけが出る", () => {
    const r = expandParams(
      def({ v: { domain: "VS", column: "v" }, s: { domain: "VS", column: "s" } }),
      {
        VS: dom(
          ["v", "s"],
          [
            ["v1", "s1"],
            ["v1", "s2"],
            ["v2", "s9"],
          ],
        ),
      },
      100,
    );
    expect(r.nDomain).toBe(3);
    expect(r.params).toEqual([
      { s: "s1", v: "v1" },
      { s: "s2", v: "v1" },
      { s: "s9", v: "v2" },
    ]);
  });
  it("上限を超えるときは先頭と末尾を含む等間隔。n_domain は全件数のまま", () => {
    const tuples = Array.from({ length: 50 }, (_, i) => [i]);
    const r = expandParams(def({ i: { domain: "I" } }), { I: dom(["i"], tuples) }, 5);
    expect(r.nDomain).toBe(50);
    expect(r.params.map((p) => p.i)).toEqual([0, 12, 25, 37, 49]);
  });
  it("軸が空なら n_domain 0・run 0 件", () => {
    expect(expandParams(def({ i: { domain: "I" } }), { I: dom(["i"], []) }, 5)).toEqual({ nDomain: 0, params: [] });
  });
});

describe("resolveDomain", () => {
  it("SQL の結果を全順序に並べ、重複と NULL を含む組を除く", async () => {
    const all = async () => [{ k: "b" }, { k: "a" }, { k: null }, { k: "a" }, { k: 10 }, { k: 9 }];
    const r = await resolveDomain("d", { db: "v2", sql: "x" }, all);
    expect(r.tuples).toEqual([[9], [10], ["a"], ["b"]]);
  });
  it("columns を持つ domain は列の順に組にする", async () => {
    const all = async () => [
      { a: 2, b: "y" },
      { a: 1, b: "z" },
    ];
    const r = await resolveDomain("d", { db: "v2", sql: "x", columns: ["a", "b"] }, all);
    expect(r).toEqual({
      columns: ["a", "b"],
      tuples: [
        [1, "z"],
        [2, "y"],
      ],
    });
  });
  it("values はそのまま並べ替える", async () => {
    const r = await resolveDomain("d", { values: [3, 1, 2] }, async () => []);
    expect(r.tuples).toEqual([[1], [2], [3]]);
  });
});

describe("formatSnapshot", () => {
  const snap: Snapshot = {
    schema_version: 1,
    imputation: "lod",
    queries: [
      {
        id: "a",
        n_domain: 2,
        runs: [
          { params: { x: 1 }, rows: [row([1], { n: 2 }, { u: "mg/L" }), row([2], { n: 3 }, { u: null })] },
          { params: { x: 2 }, rows: [] },
        ],
      },
      { id: "b", n_domain: 1, runs: [{ params: {}, rows: [row([], { n: 1 })] }] },
    ],
  };
  it("JSON として読め、元の値に戻る", () => {
    expect(JSON.parse(formatSnapshot(snap))).toEqual(snap);
  });
  it("1 row = 1 行。同じ入力でバイト一致。日時などを含まない", () => {
    const a = formatSnapshot(snap);
    expect(formatSnapshot(structuredClone(snap))).toBe(a);
    expect(a.split("\n").filter((l) => l.startsWith('{"key"'))).toHaveLength(3);
    expect(a.endsWith("\n")).toBe(true);
    expect(a).not.toMatch(/\d{4}-\d{2}-\d{2}T|git|sqlite/i);
  });
});

describe("fingerprint", () => {
  const run = { params: { x: 1 }, rows: [row([1], { n: 2, avg: 0.1 }), row([2], { n: 3, avg: 0.2 }), row([3], { n: null, avg: null })] };
  it("行数・列ごとの和（NULL は足さない・丸める）・hash", () => {
    const f = fingerprintRun(run, ["n", "avg"]);
    expect(f.n_rows).toBe(3);
    expect(f.sums).toEqual({ n: 5, avg: 0.3 });
    expect(f.hash).toMatch(/^[0-9a-f]{64}$/);
    expect(fingerprintRun(run, ["n", "avg"]).hash).toBe(f.hash);
  });
  it("行が1つ変われば hash が変わる", () => {
    const changed = { ...run, rows: [row([1], { n: 2, avg: 0.1 }), row([2], { n: 4, avg: 0.2 }), run.rows[2]] };
    expect(fingerprintRun(changed, ["n", "avg"]).hash).not.toBe(fingerprintRun(run, ["n", "avg"]).hash);
  });
  it("format は JSON として読める", () => {
    const fp = { schema_version: 1, imputation: "lod" as const, queries: [{ id: "a", n_domain: 1, runs: [fingerprintRun(run, ["n"])] }] };
    expect(JSON.parse(formatFingerprint(fp))).toEqual(fp);
  });
});

describe("degenerateProblems（空振り検査）", () => {
  const def = (over: Partial<QueryDef> = {}, numeric: string[] = ["n"]): QueryDef => ({ id: "q", params: {}, compare: { key: ["k"], numeric, label: [] }, ...over });
  it("全 run が0行は不合格。allow_empty なら合格", () => {
    expect(degenerateProblems([{ def: def(), runs: [{ rows: [] }, { rows: [] }] }])).toHaveLength(1);
    expect(degenerateProblems([{ def: def({ allowEmpty: true }), runs: [{ rows: [] }] }])).toEqual([]);
    expect(degenerateProblems([{ def: def(), runs: [] }])).toHaveLength(1);
  });
  it("n を持つ問い合わせで n の最大が1以下は不合格。2以上なら合格", () => {
    expect(degenerateProblems([{ def: def(), runs: [{ rows: [row(["a"], { n: 1 })] }, { rows: [row(["b"], { n: 1 })] }] }])).toHaveLength(1);
    expect(degenerateProblems([{ def: def(), runs: [{ rows: [row(["a"], { n: 1 }), row(["b"], { n: 2 })] }] }])).toEqual([]);
  });
  it("n 列が無い問い合わせには (b) を当てない", () => {
    expect(degenerateProblems([{ def: def({}, ["avg"]), runs: [{ rows: [row(["a"], { avg: 1 })] }] }])).toEqual([]);
  });
});

describe("diffTable（--mode diff の表）", () => {
  const mk = (rows: NormRow[], x = 1): Snapshot => ({ schema_version: 1, imputation: "lod", queries: [{ id: "a", n_domain: 1, runs: [{ params: { x }, rows }] }] });
  it("変化なしなら「変化なし」・変化のあった問い合わせ 0", () => {
    const t = diffTable(mk([row([1], { n: 2 })]), mk([row([1], { n: 2 })]));
    expect(t).toContain("変化なし");
    expect(t).toContain("変化のあった問い合わせ: 0 / 1");
  });
  it("行数・変わった run 数・数値列の和の変化が出る", () => {
    const t = diffTable(mk([row([1], { n: 2 })]), mk([row([1], { n: 5 }), row([2], { n: 1 })]));
    expect(t).toContain("1 → 2");
    expect(t).toContain("n: 2 → 6");
    expect(t).toMatch(/\| 1 \|/);
    expect(t).toContain("変化のあった問い合わせ: 1 / 1");
  });
  it("問い合わせの追加・削除・比較元なし", () => {
    const base = mk([row([1], { n: 2 })]);
    const cur: Snapshot = { ...base, queries: [{ ...base.queries[0], id: "b" }] };
    const t = diffTable(base, cur);
    expect(t).toContain("(新規)");
    expect(t).toContain("(削除)");
    expect(diffTable(null, base)).toContain("比較元のスナップショットが無い");
  });
});

describe("parseServingQueries", () => {
  const ok = `
version: 2
domains:
  d: { db: v2, sql: "SELECT 1 AS a, 2 AS b", columns: [a, b] }
  v: { values: [1, 2] }
queries:
  - id: q1
    max_runs: { snapshot: 3 }
    params: { a: { domain: d }, b: { domain: d }, y: { domain: v } }
    compare: { key: [k], numeric: [n], label: [] }
  - id: q2
    allow_empty: true
    max_runs: { snapshot: 5, fingerprint: 5 }
    params: {}
    compare: { key: [], numeric: [], label: [] }
`;
  it("snake_case を camelCase にして読む", () => {
    const c = parseServingQueries(ok);
    expect(c.queries[0].maxRuns).toEqual({ snapshot: 3 });
    expect(c.queries[1]).toMatchObject({ allowEmpty: true, maxRuns: { snapshot: 5, fingerprint: 5 } });
  });
  it("存在しない domain・列・重複 id・不正な db は例外", () => {
    expect(() => parseServingQueries(ok.replace("y: { domain: v }", "y: { domain: nope }"))).toThrow(/domain/);
    expect(() => parseServingQueries(ok.replace("b: { domain: d }", "zz: { domain: d }"))).toThrow(/列/);
    expect(() => parseServingQueries(ok.replace("id: q2", "id: q1"))).toThrow(/重複/);
    expect(() => parseServingQueries(ok.replace("db: v2", "db: d1"))).toThrow(/db/);
  });
});
