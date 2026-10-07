import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { TABLE_ORIGIN, TABLE_META, SAMPLE_QUERIES } from "@/lib/table-meta";

/**
 * Issue #48 PR-4 の完了条件: web/src のソース（テスト・fixture 以外）が v1 の表を参照しない。
 *
 * 参照とみなすのは、コメントを除いたうえで
 *   (A) SQL の FROM/JOIN/INTO/UPDATE/TABLE の直後に禁止表の名前が出る
 *   (B) 引用符（' " `）で囲まれた完全一致
 * の2つだけ。素の単語一致は CSS クラス（pointer-events-none）や変数名（events.data）に当たって偽陽性が出る。
 * 実行時の「カタログ」（TABLE_ORIGIN/TABLE_META）に禁止表が混ざっていないことも見る。
 *
 * PR-5 で表を DROP した（マイグレーション 0010）。ここは退行防止として残す
 * （schema*.ts に禁止表が再び現れないことも見る）。
 * 設計: docs/plans/V2_SERVING_PR4.md §2.2。
 */

/* ------------------------------------------------------------------ */
/* 禁止表（出典: docs/plans/V2_SERVING.md §3.1。テストに直書きする）        */
/* ------------------------------------------------------------------ */

/** derived.sqlite の33表（v1 の派生集計）。 */
const DERIVED_TABLES = [
  "doc_series", "doc_series_meta", "effort_year", "ias_species", "landuse_change", "landuse_watershed",
  "meas_clim", "meas_daily", "meas_month", "meas_year", "mesh_all", "mesh_species", "mesh_year",
  "org_group_year", "org_norm", "org_watershed", "org_watershed_year", "quality_monthly", "rain_daily",
  "redlist_change", "redlist_map", "sensor_daily", "sensor_hour_month", "site_var", "species2",
  "species_mesh_year", "species_month", "species_year2", "var_catalog", "watershed_meta",
  "watershed_rollup", "zone_clim", "zone_year",
];

/** 落とす原本表（V2_SERVING.md §3.1）と、D3（画面ごと撤去）で加えた機材・手順の2表。 */
const DROPPED_SOURCE_TABLES = [
  "measurements", "sensor_timeseries", "organism_records", "taxa", "redlist_assessments",
  "decisions", "interventions", "quality_transitions", "observers", "events", "event_observers",
  "instruments", "protocols",
];

const FORBIDDEN_TABLES: readonly string[] = [...DERIVED_TABLES, ...DROPPED_SOURCE_TABLES];

/* ------------------------------------------------------------------ */
/* 許可リスト（理由つき。一致しなくなったら落ちる＝腐らない）               */
/* ------------------------------------------------------------------ */

interface Allowed {
  /** web/ からの相対パス */
  file: string;
  /** その表。"*" はそのファイルの禁止表すべて */
  tables: readonly string[] | "*";
  reason: string;
}

const ALLOWED: readonly Allowed[] = [
  {
    file: "src/lib/registry/generated-client.ts",
    tables: ["measurements"],
    reason: "dataset 型 scope の dataset キー（scopeKind: \"dataset\"）。v1 表の参照ではない。恒久",
  },
  {
    file: "src/lib/registry/generated.ts",
    tables: ["measurements", "sensor_timeseries"],
    reason: "registry の生成物。variable_alias.dataset の値（出典の dataset キー）で、v1 表の参照ではない。恒久",
  },
  {
    file: "src/lib/cube/series.ts",
    tables: ["measurements", "sensor_timeseries"],
    reason: "MEASUREMENTS_DATASET / SENSOR_DATASET の定義（registry の dataset キー）。各所はここから import する",
  },
  {
    file: "src/lib/cube/occurrence.ts",
    tables: ["taxa"],
    reason: "和名の出自を表す basis の値（'taxa'）。表の参照ではない",
  },
];

/* ------------------------------------------------------------------ */
/* スキャナ                                                             */
/* ------------------------------------------------------------------ */

/**
 * コメント（/* *\/ と //）だけを空白に置き換える。文字列・テンプレートリテラルの中身は残す
 * （SQL は文字列の中にあるので）。`//` が URL の一部として文字列内にあっても消さないよう、
 * 文字列の状態を追う。テンプレートの `${ ... }` の入れ子も追う。
 */
export function stripComments(src: string): string {
  type Ctx = { kind: "tpl" } | { kind: "expr"; depth: number };
  const stack: Ctx[] = [];
  let out = "";
  let i = 0;
  const n = src.length;
  while (i < n) {
    const top = stack[stack.length - 1];
    const c = src[i];
    const d = src[i + 1];
    if (top?.kind === "tpl") {
      if (c === "\\") {
        out += c + (d ?? "");
        i += 2;
      } else if (c === "`") {
        stack.pop();
        out += c;
        i++;
      } else if (c === "$" && d === "{") {
        stack.push({ kind: "expr", depth: 0 });
        out += "${";
        i += 2;
      } else {
        out += c;
        i++;
      }
      continue;
    }
    // コード（トップレベルまたは ${} の中）
    if (c === "/" && d === "/") {
      while (i < n && src[i] !== "\n") i++;
      continue;
    }
    if (c === "/" && d === "*") {
      const end = src.indexOf("*/", i + 2);
      const stop = end < 0 ? n : end + 2;
      out += " ";
      i = stop;
      continue;
    }
    if (c === "'" || c === '"') {
      let j = i + 1;
      while (j < n && src[j] !== c && src[j] !== "\n") j += src[j] === "\\" ? 2 : 1;
      out += src.slice(i, j + 1);
      i = j + 1;
      continue;
    }
    if (c === "`") {
      stack.push({ kind: "tpl" });
      out += c;
      i++;
      continue;
    }
    if (top?.kind === "expr") {
      if (c === "{") top.depth++;
      else if (c === "}") {
        if (top.depth === 0) stack.pop();
        else top.depth--;
      }
    }
    out += c;
    i++;
  }
  return out;
}

const escapeRe = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** 見つかった (表, 種別) の一覧。種別は A=SQL 文脈、B=引用符つき完全一致。 */
export interface Hit {
  table: string;
  kind: "A" | "B";
}

export function findTableReferences(source: string, tables: readonly string[] = FORBIDDEN_TABLES): Hit[] {
  const code = stripComments(source);
  const alt = tables.map(escapeRe).join("|");
  const hits: Hit[] = [];
  const a = new RegExp(`\\b(?:from|join|into|update|table)\\s+["\`]?(?:\\w+\\.)?(${alt})\\b`, "gi");
  for (let m = a.exec(code); m; m = a.exec(code)) hits.push({ table: m[1].toLowerCase(), kind: "A" });
  const b = new RegExp(`["'\`](${alt})["'\`]`, "g");
  for (let m = b.exec(code); m; m = b.exec(code)) hits.push({ table: m[1], kind: "B" });
  return hits;
}

function isAllowed(file: string, table: string): boolean {
  return ALLOWED.some((a) => a.file === file && (a.tables === "*" || a.tables.includes(table)));
}

/** 許可リストに無い参照だけを返す。 */
export function unallowedReferences(file: string, source: string): Hit[] {
  return findTableReferences(source).filter((h) => !isAllowed(file, h.table));
}

/* ------------------------------------------------------------------ */
/* ファイル走査                                                         */
/* ------------------------------------------------------------------ */

const WEB_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const SRC_ROOT = path.join(WEB_ROOT, "src");

function walk(dir: string, acc: string[] = []): string[] {
  for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
    if (ent.name === "node_modules" || ent.name === "__fixtures__" || ent.name === "__snapshots__") continue;
    const p = path.join(dir, ent.name);
    if (ent.isDirectory()) walk(p, acc);
    else if (/\.tsx?$/.test(ent.name) && !/\.test\.tsx?$/.test(ent.name)) acc.push(p);
  }
  return acc;
}

const FILES = walk(SRC_ROOT).map((abs) => ({
  rel: path.relative(WEB_ROOT, abs).split(path.sep).join("/"),
  abs,
}));
const SOURCE_OF = new Map(FILES.map((f) => [f.rel, fs.readFileSync(f.abs, "utf8")]));

/* ------------------------------------------------------------------ */
/* テスト                                                               */
/* ------------------------------------------------------------------ */

describe("v1 の表を参照しない（web/src）", () => {
  it("走査対象が空でない（走査が壊れて素通りしていない）", () => {
    expect(FILES.length).toBeGreaterThan(50);
    expect(FILES.some((f) => f.rel === "src/lib/cube/series.ts")).toBe(true);
    expect(FILES.some((f) => f.rel.endsWith(".test.ts"))).toBe(false);
  });

  it("許可リスト以外に、禁止表への参照が無い", () => {
    const found: string[] = [];
    for (const { rel } of FILES) {
      for (const h of unallowedReferences(rel, SOURCE_OF.get(rel)!)) found.push(`${rel}: ${h.table} (${h.kind})`);
    }
    expect([...new Set(found)]).toEqual([]);
  });

  it("許可リストの各項目は理由があり、いま実際に1件以上一致している（一致しなくなったら消す）", () => {
    for (const a of ALLOWED) {
      expect(a.reason.trim().length, `${a.file} の理由が空`).toBeGreaterThan(10);
      const src = SOURCE_OF.get(a.file);
      expect(src, `${a.file} が存在しない（許可リストから消す）`).toBeDefined();
      const hit = findTableReferences(src!).map((h) => h.table);
      if (a.tables === "*") {
        expect(hit.length, `${a.file} に禁止表への参照が無い（許可リストから消す）`).toBeGreaterThan(0);
      } else {
        for (const t of a.tables) {
          expect(hit, `${a.file} に ${t} への参照が無い（許可リストから消す）`).toContain(t);
        }
      }
    }
  });

  it("許可リストに同じ (file, table) の重複が無い", () => {
    const keys = ALLOWED.flatMap((a) => (a.tables === "*" ? [`${a.file}:*`] : a.tables.map((t) => `${a.file}:${t}`)));
    expect(new Set(keys).size).toBe(keys.length);
  });
});

describe("カタログの整合（実行時）", () => {
  it("TABLE_ORIGIN / TABLE_META のキーに禁止表が無い", () => {
    const forbidden = new Set(FORBIDDEN_TABLES);
    expect(Object.keys(TABLE_ORIGIN).filter((k) => forbidden.has(k))).toEqual([]);
    expect(Object.keys(TABLE_META).filter((k) => forbidden.has(k))).toEqual([]);
  });

  it("TABLE_META の表はすべて TABLE_ORIGIN にある（逆も）", () => {
    expect(Object.keys(TABLE_META).sort()).toEqual(Object.keys(TABLE_ORIGIN).sort());
  });

  it("schema*.ts の全表が、カタログか禁止表のどちらかに分類されている（未分類を許さない）", () => {
    const schemaFiles = fs
      .readdirSync(path.join(SRC_ROOT, "db"))
      .filter((f) => /^schema.*\.ts$/.test(f));
    expect(schemaFiles).toContain("schema.ts");
    const defined = schemaFiles.flatMap((f) => {
      const src = fs.readFileSync(path.join(SRC_ROOT, "db", f), "utf8");
      return [...src.matchAll(/sqliteTable\(\s*"(\w+)"/g)].map((m) => m[1]);
    });
    expect(defined.length).toBeGreaterThan(35);
    // DROP した表が schema に戻ってきていない（退行防止）
    expect(defined.filter((t) => FORBIDDEN_TABLES.includes(t))).toEqual([]);
    const classified = new Set([...Object.keys(TABLE_ORIGIN), ...FORBIDDEN_TABLES]);
    // `_` で始まる表はシード管理などの内部表
    const unclassified = defined.filter((t) => !t.startsWith("_") && !classified.has(t));
    expect(unclassified).toEqual([]);
  });

  it("SAMPLE_QUERIES が引く表はすべてカタログにある", () => {
    const catalog = new Set(Object.keys(TABLE_ORIGIN));
    for (const q of SAMPLE_QUERIES) {
      expect(findTableReferences(q.sql), q.title).toEqual([]);
      const used = [...q.sql.matchAll(/\b(?:from|join)\s+(\w+)\b(?!\s*\()/gi)].map((m) => m[1]);
      expect(used.length, `${q.title} が表を引いていない`).toBeGreaterThan(0);
      expect(used.filter((t) => !catalog.has(t)), q.title).toEqual([]);
    }
  });
});

describe("スキャナの自己診断", () => {
  const detects = (src: string) => findTableReferences(src).length > 0;

  it("検出する", () => {
    expect(detects("SELECT * FROM d.meas_year")).toBe(true);
    expect(detects("`FROM measurements m`")).toBe(true);
    expect(detects("const t = `SELECT 1 FROM ${x} JOIN species_month USING (binom)`")).toBe(true);
    expect(detects('const names = ["species2"]')).toBe(true);
    expect(detects("INSERT INTO events (a) VALUES (1)")).toBe(true);
    expect(detects("select 1 from\n  watershed_rollup")).toBe(true);
    // 文字列内の // は URL。コメントとして食って後ろを見逃してはいけない
    expect(detects('const u = "https://example.org/"; const q = "SELECT 1 FROM species2";')).toBe(true);
  });

  it("検出しない", () => {
    expect(detects("// FROM meas_year")).toBe(false);
    expect(detects("/* species2 */")).toBe(false);
    expect(detects("/**\n * FROM measurements\n */\nconst a = 1;")).toBe(false);
    expect(detects('className="pointer-events-none"')).toBe(false);
    expect(detects("const events = [];")).toBe(false);
    expect(detects("events.data.map(x => x)")).toBe(false);
    expect(detects("SELECT 1 FROM species2_not_a_table_prefix_x")).toBe(false);
    expect(detects("SELECT 1 FROM sites")).toBe(false);
  });

  it("許可リスト外のファイルでは禁止表の追加が見つかる（変異）", () => {
    for (const rel of ["src/lib/queries.ts", "src/lib/db.ts", "src/lib/cube/catalog.ts"]) {
      const src = SOURCE_OF.get(rel);
      expect(src, rel).toBeDefined();
      expect(unallowedReferences(rel, src!), `${rel} は元から参照ゼロのはず`).toEqual([]);
      expect(unallowedReferences(rel, `${src}\nconst q = "SELECT 1 FROM species2";\n`).length, rel).toBeGreaterThan(0);
    }
  });

  it("許可リストの項目は、許可していない表には効かない", () => {
    const src = SOURCE_OF.get("src/lib/cube/series.ts")!;
    expect(unallowedReferences("src/lib/cube/series.ts", `${src}\nconst q = "SELECT 1 FROM species2";\n`).length).toBeGreaterThan(0);
  });
});
