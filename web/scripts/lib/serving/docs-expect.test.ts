/**
 * 文書系列の3規則（`doc_label_rule`/`doc_warning_scope`/`doc_year_collapse`）と、その期待値
 * （`docs-expect.ts`）、PR-4 の変異のテスト（設計書 `V2_SERVING_PR4.md` §5.2）。
 *
 * メモリ上の最小 `cells.sqlite` を作り、「v1 の式で作った行」と「v2 の仕様で作った行」を手で用意して
 * 突き合わせる。実データは使わない（本番の確認は serving-diff の `--only doc_series_*`）。
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import Database from "better-sqlite3";
import { describe, expect, it } from "vitest";
import { rowsByKey, toNormRows, type NormRow } from "./normalize";
import { classifyDiff, compareRuns, docPointKey, docSeriesKey, type ClassifyContext, type KnownRule } from "./classify";
import { applyClassifyMutation, applyRowMutation, expandAllMutations, rowMutationAppliesTo } from "./mutations";
import { buildDocsExpectations, docsNeeded, expectedRowKeyLabel, loadDocsExpectations, parseNoteTableIds } from "./docs-expect";
import { buildReportMarkdown, emptyQueryStats } from "./report";

const HERE = path.dirname(fileURLToPath(import.meta.url));

describe("独立性（設計書 §8.4-3）", () => {
  it("docs-expect.ts のソースは lib/cube を import しない（正解を v2 の経路で作らない）", () => {
    const src = fs.readFileSync(path.join(HERE, "docs-expect.ts"), "utf8");
    expect(src).not.toMatch(/^\s*(import|export)\b[^;]*\bfrom\s+["'][^"']*lib\/cube/m);
    expect(src).not.toMatch(/\b(require|import)\(\s*["'][^"']*lib\/cube/);
  });

  it("v1 の label の式は build-derived.mjs の式そのまま（書き直していない）", () => {
    const derived = fs.readFileSync(path.join(HERE, "..", "..", "build-derived.mjs"), "utf8");
    const mine = fs.readFileSync(path.join(HERE, "docs-expect.ts"), "utf8");
    const norm = (t: string) => t.replace(/\b[a-z]\.row_key\b/g, "row_key").replace(/\s+/g, " ");
    const expr = "substr(row_key, length(row_key) - length(replace(substr(row_key, instr(row_key,'|')+1), '|', '')) + 1)";
    expect(norm(derived)).toContain(expr);
    expect(norm(mine)).toContain(expr);
  });
});

describe("expectedRowKeyLabel / parseNoteTableIds", () => {
  it("最後の | の後ろ。| が無い・末尾が空なら row_key 全体", () => {
    expect(expectedRowKeyLabel("a|b|c")).toBe("c");
    expect(expectedRowKeyLabel("abc")).toBe("abc");
    expect(expectedRowKeyLabel("a|b|")).toBe("a|b|");
  });
  it("table_ids: NULL・空・[] は文書全体（null）、配列は集合", () => {
    expect(parseNoteTableIds(null)).toBeNull();
    expect(parseNoteTableIds("")).toBeNull();
    expect(parseNoteTableIds("[]")).toBeNull();
    expect([...parseNoteTableIds('["t1","t2"]')!]).toEqual(["t1", "t2"]);
  });
});

/** 最小の cells.sqlite。 */
function buildCells() {
  const db = new Database(":memory:");
  db.exec(`
    CREATE TABLE cells (id INTEGER PRIMARY KEY, doc_id TEXT, page_no INTEGER, table_id TEXT, row_key TEXT, col_key TEXT,
      value TEXT, value_type TEXT, unit TEXT, fiscal_year INTEGER, is_total INTEGER DEFAULT 0, superseded INTEGER DEFAULT 0);
    CREATE TABLE notes (note_id TEXT PRIMARY KEY, doc_id TEXT, table_ids TEXT, kind TEXT, text TEXT, page INTEGER,
      blocks_timeseries INTEGER, reason TEXT);
  `);
  const ins = db.prepare(
    `INSERT INTO cells (doc_id, page_no, table_id, row_key, col_key, value, value_type, unit, fiscal_year) VALUES (?,?,?,?,?,?,?,?,?)`,
  );
  // 系列 S1（d1/t1/'r|x|y'）: 2010〜2014。2012 は値が割れる（10 と 11）。他の年は 1 種。
  for (const [y, v] of [[2010, "1"], [2011, "2"], [2012, "10"], [2012, "11"], [2013, "4"], [2014, "5"]] as const) {
    ins.run("d1", 3, "t1", "r|x|y", "c", v, "int", "u", y);
  }
  // 系列 S2（d1/t2/'plain'）: 2010〜2012、割れる年なし（同じ値の重複は 1 種）。
  for (const [y, v] of [[2010, "1"], [2011, "1"], [2011, "1"], [2012, "3"]] as const) {
    ins.run("d1", 4, "t2", "plain", "c", v, "int", "u", y);
  }
  // 系列 S3（d1/t3/'s'）: 4 年のうち 2 年が割れる → 値が1種の年は 2 年（<3）。
  for (const [y, v] of [[2010, "1"], [2010, "2"], [2011, "1"], [2011, "2"], [2012, "5"], [2013, "6"]] as const) {
    ins.run("d1", 5, "t3", "s", "c", v, "int", "u", y);
  }
  // 入力条件で除外される行。
  ins.run("d1", 6, "t9", "x", "c", "1", "text", "u", 2010);
  const note = db.prepare(`INSERT INTO notes (note_id, doc_id, table_ids, blocks_timeseries) VALUES (?,?,?,?)`);
  note.run("n1", "d1", null, 1); // 文書全体
  note.run("n2", "d1", '["t1"]', 1); // t1 だけ
  note.run("n3", "d1", '["t2"]', 0); // 数えない
  return db;
}

describe("buildDocsExpectations", () => {
  const exp = buildDocsExpectations(buildCells());
  const s1 = exp.series.get(docSeriesKey("d1", "t1", "r|x|y"))!;
  const s2 = exp.series.get(docSeriesKey("d1", "t2", "plain"))!;
  const s3 = exp.series.get(docSeriesKey("d1", "t3", "s"))!;

  it("label: v1 の式と lastIndexOf の再計算", () => {
    expect(s1.v2Label).toBe("y");
    expect(s1.v1Label).toBe("|y"); // v1 の式は | を2つ以上含むと壊れる（バグ①）
    expect(s2.v1Label).toBe("plain");
    expect(s2.v2Label).toBe("plain");
  });
  it("警告: v1 は doc 単位、v2 は文書全体＋当該表", () => {
    expect(s1.v1Warnings).toBe(2);
    expect(s1.v2Warnings).toBe(2);
    expect(s2.v1Warnings).toBe(2);
    expect(s2.v2Warnings).toBe(1); // 表指定の n2 は t1 のみ
  });
  it("年: v1 は割れる年も数え、v2 は値が1種の年だけ", () => {
    expect([s1.allYears, s1.allFrom, s1.allTo]).toEqual([5, 2010, 2014]);
    expect([s1.goodYears, s1.goodFrom, s1.goodTo]).toEqual([4, 2010, 2014]);
    expect(s2.goodYears).toBe(3);
    expect(s3.goodYears).toBe(2);
    expect(s3.allYears).toBe(4);
  });
  it("年ごとの値の種類数・page_no", () => {
    expect(exp.yearDistinct.get(docPointKey("d1", "t1", "r|x|y", 2012))).toBe(2);
    expect(exp.yearDistinct.get(docPointKey("d1", "t2", "plain", 2011))).toBe(1);
    expect(s1.allPageNo).toBe(3);
  });
  it("入力条件で除外された系列は無い", () => {
    expect(exp.series.has(docSeriesKey("d1", "t9", "x"))).toBe(false);
  });
  it("loadDocsExpectations は doc 系が無ければ何も読まない", () => {
    expect(docsNeeded(["variable_catalog"])).toBe(false);
    expect(loadDocsExpectations("/nonexistent.sqlite", ["variable_catalog"])).toBeUndefined();
  });
});

/* ------------------------------------------------------------------ */
/* 規則と変異                                                           */
/* ------------------------------------------------------------------ */

const META_COMPARE = {
  key: ["doc_id", "table_id", "row_key"],
  numeric: ["n_years", "y_from", "y_to", "page_no", "n_warnings"],
  label: ["label", "unit", "doc_title"],
};
const POINT_COMPARE = { key: ["fiscal_year"], numeric: ["value", "page_no"], label: ["unit"] };

const exp = buildDocsExpectations(buildCells());

function meta(rows: Record<string, unknown>[]): NormRow[] {
  return toNormRows(rows, META_COMPARE.key, META_COMPARE.numeric, META_COMPARE.label);
}

// v1（バグ①②③を持つ）と v2（直した）の meta。S3 は値が1種の年が 2 年なので v2 から消える。
const V1_META = meta([
  { doc_id: "d1", table_id: "t1", row_key: "r|x|y", label: "|y", page_no: 3, n_years: 5, y_from: 2010, y_to: 2014, n_warnings: 2, unit: "u", doc_title: "T" },
  { doc_id: "d1", table_id: "t2", row_key: "plain", label: "plain", page_no: 4, n_years: 3, y_from: 2010, y_to: 2012, n_warnings: 2, unit: "u", doc_title: "T" },
  { doc_id: "d1", table_id: "t3", row_key: "s", label: "s", page_no: 5, n_years: 4, y_from: 2010, y_to: 2013, n_warnings: 2, unit: "u", doc_title: "T" },
]);
const V2_META = meta([
  { doc_id: "d1", table_id: "t1", row_key: "r|x|y", label: "y", page_no: 3, n_years: 4, y_from: 2010, y_to: 2014, n_warnings: 2, unit: "u", doc_title: "T" },
  { doc_id: "d1", table_id: "t2", row_key: "plain", label: "plain", page_no: 4, n_years: 3, y_from: 2010, y_to: 2012, n_warnings: 1, unit: "u", doc_title: "T" },
]);

function metaCtx(extra: Partial<ClassifyContext> = {}): ClassifyContext {
  return {
    queryId: "doc_series_meta",
    docs: exp,
    expected: {},
    declared: { v1Table: null, builder: null },
    params: {},
    known: new Set<KnownRule>(["doc_label_rule", "doc_warning_scope", "doc_year_collapse"]),
    ...extra,
  };
}

function unexplainedMeta(v1: NormRow[], v2: NormRow[], ctx: ClassifyContext = metaCtx()): number {
  return compareRuns(rowsByKey(v1), rowsByKey(v2))
    .map((d) => classifyDiff(d, ctx))
    .filter((c) => c.rules.size === 0).length;
}

describe("doc_series_meta の3規則", () => {
  it("変異なしなら 3 規則で全部説明できる（label・n_warnings・n_years/y_to・消えた系列）", () => {
    expect(unexplainedMeta(V1_META, V2_META)).toBe(0);
    const rules = new Set<KnownRule>();
    for (const d of compareRuns(rowsByKey(V1_META), rowsByKey(V2_META))) for (const r of classifyDiff(d, metaCtx()).rules) rules.add(r);
    expect([...rules].sort()).toEqual(["doc_label_rule", "doc_warning_scope", "doc_year_collapse"]);
  });

  it("doc_label_rule_off / doc_warning_rule_off / doc_collapse_rule_off: それぞれ unexplained になる", () => {
    for (const name of ["doc_label_rule_off", "doc_warning_rule_off", "doc_collapse_rule_off"] as const) {
      const m = applyClassifyMutation(name);
      expect(unexplainedMeta(V1_META, V2_META, metaCtx({ disabledRules: m.disabledRules })), name).toBeGreaterThan(0);
    }
  });

  it("doc_label_wrong: 規則が有効でも、再計算と食い違う label は unexplained（規則が何でも説明する穴になっていない）", () => {
    const mutated = applyRowMutation("doc_label_wrong", "doc_series_meta", V2_META);
    expect(mutated[0].label.label).not.toBe(V2_META[0].label.label);
    expect(unexplainedMeta(V1_META, mutated)).toBeGreaterThan(0);
  });

  it("v2 の n_warnings が再計算と食い違えば unexplained", () => {
    // 再計算では t2 の v2 件数は 1。0 にすると v1(2) との差は説明できなくなる。
    const bad = V2_META.map((r, i) => (i === 1 ? { ...r, numeric: { ...r.numeric, n_warnings: 0 } } : r));
    expect(unexplainedMeta(V1_META, bad)).toBeGreaterThan(0);
  });

  it("値が1種の年が 3 以上ある系列が v2 から消えていれば unexplained（drop_series の穴を塞ぐ）", () => {
    const dropped = V2_META.filter((r) => r.key[1] !== "t2");
    expect(unexplainedMeta(V1_META, dropped)).toBeGreaterThan(0);
  });

  it("v2 にだけ在る系列は説明しない", () => {
    const extra = [...V2_META, ...meta([{ doc_id: "d1", table_id: "tz", row_key: "z", label: "z", n_years: 3 }])];
    expect(unexplainedMeta(V1_META, extra)).toBeGreaterThan(0);
  });

  it("docs が無い（--only で doc 系を回さない）ときは何も説明しない", () => {
    expect(unexplainedMeta(V1_META, V2_META, metaCtx({ docs: undefined }))).toBeGreaterThan(0);
  });
});

describe("doc_series_points の doc_year_collapse", () => {
  const v1 = toNormRows(
    [2010, 2011, 2012, 2013, 2014].map((y) => ({ fiscal_year: y, value: y, page_no: 3, unit: "u" })),
    POINT_COMPARE.key,
    POINT_COMPARE.numeric,
    POINT_COMPARE.label,
  );
  const v2 = v1.filter((r) => r.key[0] !== 2012); // 2012 は値が割れる年
  const ctx = (): ClassifyContext => ({
    queryId: "doc_series_points",
    docs: exp,
    expected: {},
    declared: { v1Table: null, builder: null },
    params: { doc_id: "d1", table_id: "t1", row_key: "r|x|y" },
    known: new Set<KnownRule>(["doc_year_collapse"]),
  });
  const unexplained = (a: NormRow[], b: NormRow[], c = ctx()) =>
    compareRuns(rowsByKey(a), rowsByKey(b)).map((d) => classifyDiff(d, c)).filter((x) => x.rules.size === 0).length;

  it("値が割れる年の点が v2 に無いのは説明できる", () => {
    expect(unexplained(v1, v2)).toBe(0);
  });
  it("doc_drop_point: 値が割れていない年の点を落とすと unexplained（doc_year_collapse は割れた年だけを説明する）", () => {
    const mutated = applyRowMutation("doc_drop_point", "doc_series_points", v2);
    expect(mutated.length).toBe(v2.length - 1);
    expect(unexplained(v1, mutated)).toBeGreaterThan(0);
  });
  it("doc_collapse_rule_off: 割れた年の点も unexplained", () => {
    expect(unexplained(v1, v2, { ...ctx(), disabledRules: applyClassifyMutation("doc_collapse_rule_off").disabledRules })).toBeGreaterThan(0);
  });
  it("値の差（value_diff）は規則では説明しない", () => {
    const changed = v2.map((r, i) => (i === 0 ? { ...r, numeric: { ...r.numeric, value: 99 } } : r));
    expect(unexplained(v1, changed)).toBeGreaterThan(0);
  });
});

describe("inflate_site_n / inflate_n(overview_counts) / 対象宣言表", () => {
  const COMPARE = { key: ["watershed_id"], numeric: ["org_n", "site_n", "built_km2_2016"], label: ["water_system_name"] };
  const rows = toNormRows([{ watershed_id: "w1", org_n: 3, site_n: 2, built_km2_2016: 1.5, water_system_name: "A" }], COMPARE.key, COMPARE.numeric, COMPARE.label);

  it("inflate_site_n: site_n と土地利用1列が +1 され、説明する規則が無いので unexplained", () => {
    const mutated = applyRowMutation("inflate_site_n", "watershed_rollup", rows);
    expect(mutated[0].numeric).toMatchObject({ site_n: 3, built_km2_2016: 2.5, org_n: 3 });
    const diffs = compareRuns(rowsByKey(rows), rowsByKey(mutated));
    const ctx: ClassifyContext = { queryId: "watershed_rollup", expected: {}, declared: { v1Table: null, builder: null }, params: {}, known: new Set<KnownRule>(["watershed_memo"]) };
    expect(diffs.map((d) => classifyDiff(d, ctx)).filter((c) => c.rules.size === 0).length).toBe(1);
  });

  it("inflate_n は overview_counts の n_sites を +1 する", () => {
    const ov = toNormRows([{ n_sites: 352, n_sources: 5 }], [], ["n_sites", "n_sources"], []);
    const mutated = applyRowMutation("inflate_n", "overview_counts", ov);
    expect(mutated[0].numeric.n_sites).toBe(353);
    expect(mutated[0].numeric.n_sources).toBe(5);
  });

  it("宣言表: doc_* は doc の2 ID、inflate_site_n は watershed_rollup に限る", () => {
    expect(rowMutationAppliesTo("doc_label_wrong", "doc_series_meta")).toBe(true);
    expect(rowMutationAppliesTo("doc_label_wrong", "doc_series_points")).toBe(false);
    expect(rowMutationAppliesTo("doc_drop_point", "doc_series_points")).toBe(true);
    expect(rowMutationAppliesTo("doc_drop_point", "doc_series_meta")).toBe(false);
    expect(rowMutationAppliesTo("inflate_site_n", "watershed_rollup")).toBe(true);
    expect(rowMutationAppliesTo("inflate_site_n", "watershed_year")).toBe(false);
    expect(rowMutationAppliesTo("inflate_n", "overview_counts")).toBe(true);
  });
});

describe("--mutate all の展開（§7-1）", () => {
  it("zero 実行では lod_rule_off を外し（skipped に理由つき）、lod 実行では入れる", () => {
    const zero = expandAllMutations("zero");
    expect(zero.names).not.toContain("lod_rule_off");
    expect(zero.skipped.map((k) => k.name)).toEqual(["lod_rule_off"]);
    expect(zero.skipped[0].reason).toContain("lod");
    const lod = expandAllMutations("lod");
    expect(lod.names).toContain("lod_rule_off");
    expect(lod.skipped).toEqual([]);
  });
  it("PR-4 の 6 変異が展開に入る（zero でも lod でも）", () => {
    for (const imp of ["zero", "lod"] as const) {
      const { names } = expandAllMutations(imp);
      for (const n of ["doc_label_rule_off", "doc_warning_rule_off", "doc_collapse_rule_off", "doc_label_wrong", "doc_drop_point", "inflate_site_n"]) {
        expect(names).toContain(n);
      }
    }
  });
});

describe("レポート", () => {
  it("文書系列の moved・廃止列・skipped を出す", () => {
    const s = emptyQueryStats("doc_series_meta");
    s.doc_label_rule = 20;
    s.doc_warning_scope = 245;
    const md = buildReportMarkdown({
      header: { gitHead: "x", v2PipelineFingerprint: null, registryInputFingerprint: null, sqliteVersion: "3", imputation: "zero", expand: "all", v1Source: "derived", generatedAt: "t", elapsedMs: 1 },
      stats: [s],
      unexplainedSamples: [],
      rottenDeclarations: [],
      mutationResults: [{ name: "doc_label_wrong", unexplained: 1, caughtAsExpected: true }],
      skippedMutations: [{ name: "lod_rule_off", reason: "lod 実行のみ（現在は zero）" }],
      retiredColumns: { overview_counts: ["n_meas", "n_sensor", "n_events"] },
    });
    expect(md).toContain("| doc_label_rule | doc_series_meta | 20 |");
    expect(md).toContain("| doc_warning_scope | doc_series_meta | 245 |");
    expect(md).toContain("skipped: `lod_rule_off`");
    expect(md).toContain("`n_meas`・`n_sensor`・`n_events`");
  });
});
