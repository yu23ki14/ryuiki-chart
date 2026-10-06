/**
 * serving-snapshot（`web/scripts/serving-snapshot.mts`）の純関数部分。DB を読まない（DB を読む関数は
 * 引数で受け取る）ので、`snapshot.test.ts` が実 DB なしで確かめる。
 *
 * 設計: `docs/plans/V2_SERVING_PR5.md` §3.2・§3.3。
 *   - 展開: ドメインの値を決定論的な全順序で並べ、直積の先頭・末尾を含む等間隔の `max_runs` 件を選ぶ。
 *   - 行の正規化: `key` の辞書式で整列・数値は有効数字12桁に丸める（浮動小数の末尾差を吸収）。
 *   - 出力: スナップショット（全行。日時・git head・SQLite の版・パスを入れない）・指紋（行数・和・hash）・
 *     before/after 表（markdown）。
 *   - 空振り検査: 全 run が0行／`n` の最大が1以下の問い合わせを検出する。
 */
import { createHash } from "node:crypto";
import { load as loadYaml } from "js-yaml";
import type { CompareSpec, DomainDef, MaxRuns, NormRow, QueryDef, ScalarParam, ServingQueriesConfig } from "./normalize";

export const SCHEMA_VERSION = 1;
export type Mode = "snapshot" | "fingerprint";
export const DEFAULT_MAX_RUNS: Record<Mode, number> = { snapshot: 12, fingerprint: 60 };

/* ------------------------------------------------------------------ */
/* serving_queries.yaml の読み込み・検証                                  */
/* ------------------------------------------------------------------ */

const DOMAIN_DBS = new Set(["v2", "registry", "ryuiki", "cells"]);

function asPositiveInt(v: unknown, where: string): number {
  if (typeof v !== "number" || !Number.isInteger(v) || v < 1) throw new Error(`${where} は 1 以上の整数でなければならない: ${String(v)}`);
  return v;
}

/** YAML のテキストを検証して `ServingQueriesConfig` にする（snake_case → camelCase もここで）。 */
export function parseServingQueries(text: string): ServingQueriesConfig {
  const raw = loadYaml(text) as {
    version?: number;
    domains?: Record<string, { db?: string; sql?: string; columns?: string[]; values?: ScalarParam[] }>;
    queries?: {
      id?: string;
      params?: Record<string, { domain?: string; column?: string }>;
      compare?: Partial<CompareSpec>;
      max_runs?: number | MaxRuns;
      allow_empty?: boolean;
    }[];
  };
  if (!raw || typeof raw !== "object") throw new Error("serving_queries.yaml が空か、オブジェクトでない");
  const domains: Record<string, DomainDef> = {};
  for (const [name, d] of Object.entries(raw.domains ?? {})) {
    if (d.values !== undefined) {
      if (!Array.isArray(d.values) || d.values.length === 0) throw new Error(`domains.${name}.values は空でない配列でなければならない`);
      domains[name] = { values: d.values };
      continue;
    }
    if (!d.sql || !d.db) throw new Error(`domains.${name} は values か (db + sql) のどちらかが要る`);
    if (!DOMAIN_DBS.has(d.db)) throw new Error(`domains.${name}.db は v2/registry/ryuiki/cells のどれか: ${d.db}`);
    domains[name] = { db: d.db as DomainDef["db"], sql: d.sql, columns: d.columns };
  }
  const queries: QueryDef[] = [];
  const seen = new Set<string>();
  for (const q of raw.queries ?? []) {
    if (!q.id) throw new Error("queries[].id が無い");
    if (seen.has(q.id)) throw new Error(`queries の id が重複: ${q.id}`);
    seen.add(q.id);
    const compare = q.compare;
    if (!compare || !Array.isArray(compare.key) || !Array.isArray(compare.numeric) || !Array.isArray(compare.label)) {
      throw new Error(`queries.${q.id}.compare は key/numeric/label の3つが要る`);
    }
    const params: QueryDef["params"] = {};
    for (const [pname, p] of Object.entries(q.params ?? {})) {
      const dom = p.domain ? domains[p.domain] : undefined;
      if (!p.domain || !dom) throw new Error(`queries.${q.id}.params.${pname} の domain が domains に無い: ${String(p.domain)}`);
      if (dom.columns && dom.columns.length > 1) {
        const col = p.column ?? pname;
        if (!dom.columns.includes(col)) throw new Error(`queries.${q.id}.params.${pname}: ドメイン ${p.domain} に列 ${col} が無い（${dom.columns.join(",")}）`);
      }
      params[pname] = { domain: p.domain, ...(p.column ? { column: p.column } : {}) };
    }
    let maxRuns: MaxRuns | undefined;
    if (typeof q.max_runs === "number") {
      const n = asPositiveInt(q.max_runs, `queries.${q.id}.max_runs`);
      maxRuns = { snapshot: n, fingerprint: n };
    } else if (q.max_runs) {
      maxRuns = {};
      if (q.max_runs.snapshot !== undefined) maxRuns.snapshot = asPositiveInt(q.max_runs.snapshot, `queries.${q.id}.max_runs.snapshot`);
      if (q.max_runs.fingerprint !== undefined) maxRuns.fingerprint = asPositiveInt(q.max_runs.fingerprint, `queries.${q.id}.max_runs.fingerprint`);
    }
    queries.push({
      id: q.id,
      params,
      compare: { key: compare.key, numeric: compare.numeric, label: compare.label },
      ...(maxRuns ? { maxRuns } : {}),
      ...(q.allow_empty === true ? { allowEmpty: true } : {}),
    });
  }
  return { version: raw.version ?? 1, domains, queries };
}

/* ------------------------------------------------------------------ */
/* 順序・丸め・等間隔選択                                                */
/* ------------------------------------------------------------------ */

/** 全順序: 数値は数値順、文字列は UTF-16 コード単位順（`<` 比較。ロケールに依らない）、数値は文字列より前。 */
export function compareScalar(a: ScalarParam, b: ScalarParam): number {
  const an = typeof a === "number";
  const bn = typeof b === "number";
  if (an && bn) return a < b ? -1 : a > b ? 1 : 0;
  if (an !== bn) return an ? -1 : 1;
  const as = a as string;
  const bs = b as string;
  return as < bs ? -1 : as > bs ? 1 : 0;
}

/** 列順の辞書式。 */
export function compareTuple(a: readonly ScalarParam[], b: readonly ScalarParam[]): number {
  const n = Math.min(a.length, b.length);
  for (let i = 0; i < n; i++) {
    const c = compareScalar(a[i], b[i]);
    if (c !== 0) return c;
  }
  return a.length - b.length;
}

/**
 * 浮動小数の末尾差（SQLite の版・加算順）を吸収する丸め。整数（安全整数の範囲）はそのまま。
 * `-0` は `0`。`NaN`/`Infinity` は例外（隠さない）。
 */
export function roundNumber(x: number): number {
  if (!Number.isFinite(x)) throw new Error(`有限でない数値がスナップショットに入った: ${String(x)}`);
  if (Number.isInteger(x) && Math.abs(x) <= Number.MAX_SAFE_INTEGER) return x === 0 ? 0 : x;
  const r = Number(x.toPrecision(12));
  return r === 0 ? 0 : r;
}

/** 先頭・末尾を含む等間隔の `max` 個の添字（`n <= max` なら全部）。 */
export function evenIndices(n: number, max: number): number[] {
  if (n <= 0) return [];
  if (n <= max) return Array.from({ length: n }, (_, i) => i);
  if (max <= 1) return [0];
  const out: number[] = [];
  for (let k = 0; k < max; k++) out.push(Math.round((k * (n - 1)) / (max - 1)));
  return out;
}

/* ------------------------------------------------------------------ */
/* パラメータの展開                                                      */
/* ------------------------------------------------------------------ */

export interface ResolvedDomain {
  columns: string[];
  /** 重複を除き `compareTuple` で整列済み。 */
  tuples: ScalarParam[][];
}

function toScalar(v: unknown): ScalarParam | null {
  if (typeof v === "number" || typeof v === "string") return v;
  if (typeof v === "bigint") return Number(v);
  return null;
}

/** ドメインの値を並べて返す。`all` は SQL を流して行を返す関数（executor が `CubeDb.all` を渡す）。 */
export async function resolveDomain(
  name: string,
  def: DomainDef,
  all: (sql: string) => Promise<Record<string, unknown>[]>,
): Promise<ResolvedDomain> {
  let columns: string[];
  let tuples: ScalarParam[][];
  if (def.values) {
    columns = [name];
    tuples = def.values.map((v) => [v]);
  } else {
    const rows = await all(def.sql as string);
    const first = rows.length ? Object.keys(rows[0])[0] : undefined;
    columns = def.columns ?? (first ? [first] : [name]);
    tuples = [];
    for (const r of rows) {
      const t = columns.map((c) => toScalar(r[c]));
      if (t.some((v) => v === null)) continue; // NULL を含む組は列挙しない
      tuples.push(t as ScalarParam[]);
    }
  }
  tuples.sort(compareTuple);
  const uniq: ScalarParam[][] = [];
  for (const t of tuples) {
    const prev = uniq[uniq.length - 1];
    if (!prev || compareTuple(prev, t) !== 0) uniq.push(t);
  }
  return { columns, tuples: uniq };
}

export interface ExpandedParams {
  /** 直積の全件数（ドメインが縮んだことが見えるように記録する）。 */
  nDomain: number;
  params: Record<string, ScalarParam>[];
}

export function maxRunsFor(def: QueryDef, mode: Mode): number {
  return def.maxRuns?.[mode] ?? DEFAULT_MAX_RUNS[mode];
}

/**
 * 問い合わせのパラメータを展開する。同じドメインを引く param は1つの軸（組）。軸ごとに全順序で並べ、
 * 直積（先頭の軸が最上位）から等間隔に `max` 件選ぶ。出力の params はキー昇順。
 */
export function expandParams(def: QueryDef, domains: Record<string, ResolvedDomain>, max: number): ExpandedParams {
  const axisOrder: string[] = [];
  const bindings = new Map<string, { param: string; col: number }[]>();
  for (const [param, p] of Object.entries(def.params)) {
    const dom = domains[p.domain];
    if (!dom) throw new Error(`${def.id}: ドメイン ${p.domain} が解決されていない`);
    const colName = p.column ?? param;
    const col = dom.columns.length === 1 ? 0 : dom.columns.indexOf(colName);
    if (col < 0) throw new Error(`${def.id}: ドメイン ${p.domain} に列 ${colName} が無い`);
    if (!bindings.has(p.domain)) {
      bindings.set(p.domain, []);
      axisOrder.push(p.domain);
    }
    bindings.get(p.domain)!.push({ param, col });
  }
  if (axisOrder.length === 0) return { nDomain: 1, params: [{}] };

  const sizes = axisOrder.map((d) => domains[d].tuples.length);
  const nDomain = sizes.reduce((a, b) => a * b, 1);
  if (nDomain === 0) return { nDomain: 0, params: [] };

  const out: Record<string, ScalarParam>[] = [];
  for (const idx of evenIndices(nDomain, max)) {
    // 混合基数（先頭の軸が最上位）
    let rest = idx;
    const pick: number[] = new Array(axisOrder.length);
    for (let a = axisOrder.length - 1; a >= 0; a--) {
      pick[a] = rest % sizes[a];
      rest = Math.floor(rest / sizes[a]);
    }
    const entries: [string, ScalarParam][] = [];
    axisOrder.forEach((d, a) => {
      const tuple = domains[d].tuples[pick[a]];
      for (const { param, col } of bindings.get(d)!) entries.push([param, tuple[col]]);
    });
    entries.sort((x, y) => (x[0] < y[0] ? -1 : x[0] > y[0] ? 1 : 0));
    out.push(Object.fromEntries(entries));
  }
  return { nDomain, params: out };
}

/* ------------------------------------------------------------------ */
/* 行の正規化                                                            */
/* ------------------------------------------------------------------ */

/** 数値を丸め（`NaN`/`Infinity` は例外）、`key` の辞書式で整列する（同順位は行全体の JSON で決める）。 */
export function finalizeRows(rows: readonly NormRow[]): NormRow[] {
  const rounded = rows.map((r) => ({
    key: r.key,
    numeric: Object.fromEntries(Object.entries(r.numeric).map(([k, v]) => [k, v === null ? null : roundNumber(v)])),
    label: r.label,
  }));
  const decorated = rounded.map((r) => ({ r, j: JSON.stringify(r) }));
  decorated.sort((a, b) => compareTuple(a.r.key, b.r.key) || (a.j < b.j ? -1 : a.j > b.j ? 1 : 0));
  return decorated.map((d) => d.r);
}

/* ------------------------------------------------------------------ */
/* スナップショット                                                      */
/* ------------------------------------------------------------------ */

export interface SnapshotRun {
  params: Record<string, ScalarParam>;
  rows: NormRow[];
}
export interface SnapshotQuery {
  id: string;
  n_domain: number;
  runs: SnapshotRun[];
}
export interface Snapshot {
  schema_version: number;
  imputation: "lod";
  queries: SnapshotQuery[];
}

/** 最上位・run は改行、1 row = 1 行（`git diff` で行単位に読める）。同じ入力ならバイト一致。 */
export function formatSnapshot(s: Snapshot): string {
  const lines: string[] = [];
  lines.push("{");
  lines.push(`"schema_version": ${s.schema_version},`);
  lines.push(`"imputation": ${JSON.stringify(s.imputation)},`);
  lines.push('"queries": [');
  s.queries.forEach((q, qi) => {
    lines.push(`{"id": ${JSON.stringify(q.id)}, "n_domain": ${q.n_domain}, "runs": [`);
    q.runs.forEach((run, ri) => {
      const tail = ri === q.runs.length - 1 ? "" : ",";
      if (run.rows.length === 0) {
        lines.push(`{"params": ${JSON.stringify(run.params)}, "rows": []}${tail}`);
        return;
      }
      lines.push(`{"params": ${JSON.stringify(run.params)}, "rows": [`);
      run.rows.forEach((row, i) => lines.push(JSON.stringify(row) + (i === run.rows.length - 1 ? "" : ",")));
      lines.push(`]}${tail}`);
    });
    lines.push(`]}${qi === s.queries.length - 1 ? "" : ","}`);
  });
  lines.push("]");
  lines.push("}");
  return lines.join("\n") + "\n";
}

/* ------------------------------------------------------------------ */
/* 指紋                                                                  */
/* ------------------------------------------------------------------ */

export interface FingerprintRun {
  params: Record<string, ScalarParam>;
  n_rows: number;
  /** `numeric` 列ごとの和（丸め済み。NULL は足さない）。 */
  sums: Record<string, number>;
  /** 正規化済み行の JSON の sha256。 */
  hash: string;
}
export interface FingerprintQuery {
  id: string;
  n_domain: number;
  runs: FingerprintRun[];
}
export interface Fingerprint {
  schema_version: number;
  imputation: "lod";
  queries: FingerprintQuery[];
}

export function fingerprintRun(run: SnapshotRun, numericCols: readonly string[]): FingerprintRun {
  const sums: Record<string, number> = {};
  for (const c of numericCols) {
    let sum = 0;
    for (const r of run.rows) sum += r.numeric[c] ?? 0;
    sums[c] = roundNumber(sum);
  }
  return {
    params: run.params,
    n_rows: run.rows.length,
    sums,
    hash: createHash("sha256").update(JSON.stringify(run.rows)).digest("hex"),
  };
}

/** run を1行ずつ書く（全量の指紋はレビューで読む前提ではないが、`git diff` が run 単位で出るように）。 */
export function formatFingerprint(f: Fingerprint): string {
  const lines: string[] = ["{", `"schema_version": ${f.schema_version},`, `"imputation": ${JSON.stringify(f.imputation)},`, '"queries": ['];
  f.queries.forEach((q, qi) => {
    lines.push(`{"id": ${JSON.stringify(q.id)}, "n_domain": ${q.n_domain}, "runs": [`);
    q.runs.forEach((run, ri) => lines.push(JSON.stringify(run) + (ri === q.runs.length - 1 ? "" : ",")));
    lines.push(`]}${qi === f.queries.length - 1 ? "" : ","}`);
  });
  lines.push("]", "}");
  return lines.join("\n") + "\n";
}

/* ------------------------------------------------------------------ */
/* 空振り検査                                                            */
/* ------------------------------------------------------------------ */

/**
 * 旧 `s05`・`test_sample_aggregation_is_not_degenerate` の後継。問題の説明文を返す（空なら合格）。
 * (a) `allow_empty` でない問い合わせの run がすべて0行（run が0件も含む）。
 * (b) `numeric` に `n` を持つ問い合わせで、全 run の `n` の最大が1以下（1件をそのまま写しただけ）。
 */
export function degenerateProblems(
  results: readonly { def: QueryDef; runs: readonly { rows: readonly NormRow[] }[] }[],
): string[] {
  const problems: string[] = [];
  for (const { def, runs } of results) {
    if (def.allowEmpty) continue;
    if (runs.every((r) => r.rows.length === 0)) {
      problems.push(`${def.id}: ${runs.length} run がすべて0行（空振り。空が正常なら serving_queries.yaml に allow_empty: true と理由を書く）`);
      continue;
    }
    if (def.compare.numeric.includes("n")) {
      let max = Number.NEGATIVE_INFINITY;
      for (const r of runs) for (const row of r.rows) if (row.numeric.n !== null && row.numeric.n !== undefined && row.numeric.n > max) max = row.numeric.n;
      if (max <= 1) problems.push(`${def.id}: 全 run の n の最大が ${max}（1件をそのまま写しただけで、集計が効いていない）`);
    }
  }
  return problems;
}

/* ------------------------------------------------------------------ */
/* before/after 表（--mode diff）                                         */
/* ------------------------------------------------------------------ */

function sumNumeric(q: SnapshotQuery): Map<string, number> {
  const m = new Map<string, number>();
  for (const run of q.runs) {
    for (const row of run.rows) {
      for (const [k, v] of Object.entries(row.numeric)) if (v !== null) m.set(k, (m.get(k) ?? 0) + v);
    }
  }
  return m;
}

function cell(s: string): string {
  return s.replace(/\|/g, "\\|");
}

/**
 * スナップショット更新 PR の本文に貼る、問い合わせごとの markdown 表。
 * run は `params` で突き合わせる。「変わった run」は同じ params で行が違うもの。
 */
export function diffTable(base: Snapshot | null, cur: Snapshot): string {
  const lines: string[] = [];
  lines.push("| 問い合わせ | run 数 | 行数 | 変わった run | 数値列の和の変化 |");
  lines.push("|---|---|---|---|---|");
  const baseById = new Map((base?.queries ?? []).map((q) => [q.id, q]));
  const curIds = new Set(cur.queries.map((q) => q.id));
  const ids = [...cur.queries.map((q) => q.id), ...[...baseById.keys()].filter((id) => !curIds.has(id))];
  const curById = new Map(cur.queries.map((q) => [q.id, q]));
  let changedQueries = 0;
  for (const id of ids) {
    const b = baseById.get(id);
    const c = curById.get(id);
    if (!c) {
      changedQueries++;
      lines.push(`| ${cell(id)} | ${b!.runs.length} → (削除) | ${b!.runs.reduce((s, r) => s + r.rows.length, 0)} → (削除) | - | 問い合わせが無くなった |`);
      continue;
    }
    const cRows = c.runs.reduce((s, r) => s + r.rows.length, 0);
    if (!b) {
      changedQueries++;
      lines.push(`| ${cell(id)} | (新規) → ${c.runs.length} | (新規) → ${cRows} | - | 新規 |`);
      continue;
    }
    const bRows = b.runs.reduce((s, r) => s + r.rows.length, 0);
    const bByParams = new Map(b.runs.map((r) => [JSON.stringify(r.params), r]));
    let changed = 0;
    for (const r of c.runs) {
      const prev = bByParams.get(JSON.stringify(r.params));
      if (prev && JSON.stringify(prev.rows) !== JSON.stringify(r.rows)) changed++;
    }
    const bSum = sumNumeric(b);
    const cSum = sumNumeric(c);
    const sumChanges: string[] = [];
    for (const col of new Set([...bSum.keys(), ...cSum.keys()])) {
      const x = roundNumber(bSum.get(col) ?? 0);
      const y = roundNumber(cSum.get(col) ?? 0);
      if (x !== y) sumChanges.push(`${col}: ${x} → ${y}`);
    }
    const same = b.runs.length === c.runs.length && bRows === cRows && changed === 0 && sumChanges.length === 0 && b.n_domain === c.n_domain;
    if (!same) changedQueries++;
    const dom = b.n_domain === c.n_domain ? "" : `（n_domain ${b.n_domain} → ${c.n_domain}）`;
    lines.push(
      `| ${cell(id)} | ${b.runs.length === c.runs.length ? String(c.runs.length) : `${b.runs.length} → ${c.runs.length}`}${dom} | ` +
        `${bRows === cRows ? String(cRows) : `${bRows} → ${cRows}`} | ${changed} | ${sumChanges.length ? cell(sumChanges.join("; ")) : "変化なし"} |`,
    );
  }
  lines.push("");
  lines.push(
    base
      ? `変化のあった問い合わせ: ${changedQueries} / ${ids.length}`
      : "比較元のスナップショットが無い（全問い合わせが新規）。",
  );
  return lines.join("\n") + "\n";
}
