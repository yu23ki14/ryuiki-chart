/**
 * v1/v2 の行を突き合わせて素の食い違い（`RowDiff`）を作る（`compareRuns`）のと、
 * 素の食い違いを「既知の系統」に当てはめる（`classifyDiff`）のと、2つの役目を持つ。
 *
 * 設計書 §5.2「既知の系統の判定規則」をそのまま実装する。ここは v1/v2 の DB を
 * 直接読まない——読む必要がある規則（`day_split`/`rain_div10`）は、あらかじめ
 * 読んでおいた L2（`observation`）の行の配列や、宣言済み差分（`expected_diffs.yaml`）の
 * 索引を `ClassifyContext` として受け取る。これにより、フィクスチャ（DB 無し）だけで
 * 全規則をテストできる（`classify.test.ts`）。
 */
import type { NormRow, QueryDef, ScalarParam } from "./normalize";

/* ------------------------------------------------------------------ */
/* 素の食い違い（RowDiff）                                              */
/* ------------------------------------------------------------------ */

export type RowDiffKind = "row_only_in_v1" | "row_only_in_v2" | "value_diff" | "label_diff";

export interface RowDiff {
  key: ScalarParam[];
  kind: RowDiffKind;
  /** value_diff/label_diff のときだけ、食い違った列名の集合（空にはしない）。 */
  columns: string[];
  v1?: NormRow;
  v2?: NormRow;
}

function numbersDiffer(a: number | null, b: number | null, tol: number): boolean {
  if (a === null && b === null) return false;
  if (a === null || b === null) return true;
  if (tol <= 0) return a !== b;
  if (a === b) return false;
  const denom = Math.max(Math.abs(a), Math.abs(b), 1e-12);
  return Math.abs(a - b) / denom > tol;
}

/**
 * キーで突き合わせて `row_only_in_v1`/`row_only_in_v2`/`value_diff`/`label_diff` を作る。
 * 1つの行が数値列・ラベル列の両方で食い違っていれば、`value_diff` と `label_diff` の
 * 2つの `RowDiff`（同じ key）を返す。
 */
export function compareRuns(
  v1ByKey: ReadonlyMap<string, NormRow>,
  v2ByKey: ReadonlyMap<string, NormRow>,
  tolerance: Readonly<Record<string, number>> = {},
): RowDiff[] {
  const out: RowDiff[] = [];
  const seen = new Set<string>();

  for (const [k, v1Row] of v1ByKey) {
    seen.add(k);
    const v2Row = v2ByKey.get(k);
    if (!v2Row) {
      out.push({ key: v1Row.key, kind: "row_only_in_v1", columns: [], v1: v1Row });
      continue;
    }
    const numericCols = Object.keys(v1Row.numeric);
    const valueCols = numericCols.filter((c) => numbersDiffer(v1Row.numeric[c], v2Row.numeric[c], tolerance[c] ?? 0));
    if (valueCols.length) {
      out.push({ key: v1Row.key, kind: "value_diff", columns: valueCols, v1: v1Row, v2: v2Row });
    }
    const labelCols = Object.keys(v1Row.label).filter((c) => v1Row.label[c] !== v2Row.label[c]);
    if (labelCols.length) {
      out.push({ key: v1Row.key, kind: "label_diff", columns: labelCols, v1: v1Row, v2: v2Row });
    }
  }
  for (const [k, v2Row] of v2ByKey) {
    if (!seen.has(k)) {
      out.push({ key: v2Row.key, kind: "row_only_in_v2", columns: [], v2: v2Row });
    }
  }
  return out;
}

/* ------------------------------------------------------------------ */
/* 宣言済み差分（expected_diffs.yaml）の索引                             */
/* ------------------------------------------------------------------ */

export type DeclaredKind = "row_only_in_candidate" | "row_only_in_baseline" | "value_diff";

export interface DeclaredEntry {
  key: ScalarParam[];
  kind: DeclaredKind;
  columns?: string[];
}

/** table -> DeclaredEntry[]（`expected_diffs.yaml` をそのまま読んだ形）。 */
export type ExpectedDiffs = Record<string, DeclaredEntry[]>;

const DIFF_KIND_TO_DECLARED_KIND: Record<RowDiffKind, DeclaredKind | null> = {
  row_only_in_v1: "row_only_in_baseline",
  row_only_in_v2: "row_only_in_candidate",
  value_diff: "value_diff",
  label_diff: null, // expected_diffs.yaml に label_diff という宣言種別は無い
};

function keyEquals(a: readonly ScalarParam[], b: readonly ScalarParam[]): boolean {
  return a.length === b.length && a.every((v, i) => String(v) === String(b[i]));
}

/**
 * `v1_table` と、この問い合わせのパラメータ・行キーから `expected_diffs.yaml` の
 * ベースラインキー（`site_id, variable, year, kind` 等、テーブルごとに列順が違う）を
 * 組み立てる関数。問い合わせ id ごとに違う（設計書の各問い合わせの `params`/`compare.key`
 * から機械的に決まる）ので、`serving-diff.mts` がテーブルの列順に合わせて渡す。
 */
export type DeclaredKeyBuilder = (params: Readonly<Record<string, ScalarParam>>, rowKey: readonly ScalarParam[]) => ScalarParam[];

export interface DeclaredLookup {
  v1Table: string | null;
  builder: DeclaredKeyBuilder | null;
}

/** `--mutate declared_rot` 用: 特定の宣言（table+key+kind）を無視する。 */
export interface DeclaredRotOptions {
  table: string;
  key: ScalarParam[];
  kind: DeclaredKind;
}

function isRotted(rot: DeclaredRotOptions | undefined, table: string, entry: DeclaredEntry): boolean {
  return !!rot && rot.table === table && rot.kind === entry.kind && keyEquals(rot.key, entry.key);
}

function findDeclared(
  expected: ExpectedDiffs,
  lookup: DeclaredLookup,
  params: Readonly<Record<string, ScalarParam>>,
  diff: RowDiff,
  rot: DeclaredRotOptions | undefined,
): DeclaredEntry | undefined {
  if (!lookup.v1Table || !lookup.builder) return undefined;
  const declaredKind = DIFF_KIND_TO_DECLARED_KIND[diff.kind];
  if (!declaredKind) return undefined;
  const entries = expected[lookup.v1Table] ?? [];
  const wantKey = lookup.builder(params, diff.key);
  return entries.find((e) => {
    if (isRotted(rot, lookup.v1Table!, e)) return false;
    if (e.kind !== declaredKind) return false;
    if (!keyEquals(e.key, wantKey)) return false;
    if (declaredKind === "value_diff") {
      const cols = e.columns ?? [];
      return diff.columns.every((c) => cols.includes(c));
    }
    return true;
  });
}

/**
 * 宣言済み差分の「腐り」検出（b02 と同じ思想）。`known: [declared]` を持つ問い合わせが
 * 1件も対応する差分を出さなかった宣言を返す（実際に使われたキーの集合を呼び出し側が
 * 記録し、ここで expected 全体との差を取る）。
 */
export function findRottenDeclarations(
  expected: ExpectedDiffs,
  usedTables: ReadonlySet<string>,
  matchedKeys: ReadonlyMap<string, ReadonlySet<string>>,
): { table: string; key: ScalarParam[]; kind: DeclaredKind }[] {
  const rotten: { table: string; key: ScalarParam[]; kind: DeclaredKind }[] = [];
  for (const table of Object.keys(expected)) {
    if (!usedTables.has(table)) continue; // この serving-diff の対象クエリが触れない表は対象外
    const matched = matchedKeys.get(table) ?? new Set();
    for (const entry of expected[table]) {
      const k = `${entry.kind}\u0000${JSON.stringify(entry.key)}`;
      if (!matched.has(k)) rotten.push({ table, key: entry.key, kind: entry.kind });
    }
  }
  return rotten;
}

export function declaredMatchTag(entry: DeclaredEntry): string {
  return `${entry.kind}\u0000${JSON.stringify(entry.key)}`;
}

/* ------------------------------------------------------------------ */
/* L2（observation）の再計算（rain_div10 / day_split）                   */
/* ------------------------------------------------------------------ */

/** v2.sqlite の `observation`（L2）から RAIN（sagamihara の毎時降雨）だけを抜いた行。 */
export interface RainL2Row {
  periodRaw: string; // 例: "2020-01-01T00:00:00" 相当の生ラベル（+09:00 等は含めない前提）
  periodStart: string; // b03 が計算した「ラベル-1時間」の区間開始
  valueNum: number;
}

export interface RainRecompute {
  /** v1 のラベル日割り（`substr(period_raw,1,10)`）で Σvalue_num/10 を丸めた、日ごとの mm。 */
  byLabelDay: Map<string, number>;
  /** period_start の日割り（`substr(period_start,1,10)`）で Σvalue_num/10 を丸めた、日ごとの mm。 */
  byPeriodStartDay: Map<string, number>;
}

function sumByDay(rows: readonly RainL2Row[], pick: (r: RainL2Row) => string): Map<string, number> {
  const sums = new Map<string, number>();
  for (const r of rows) {
    const day = pick(r).slice(0, 10);
    sums.set(day, (sums.get(day) ?? 0) + r.valueNum);
  }
  const out = new Map<string, number>();
  for (const [day, sum] of sums) out.set(day, Math.round((sum / 10) * 100) / 100);
  return out;
}

/** `rain_daily`/`rain_monthly_clim`/`rain_top_days` の L2 再計算をまとめて作る。 */
export function computeRainRecompute(rows: readonly RainL2Row[]): RainRecompute {
  return {
    byLabelDay: sumByDay(rows, (r) => r.periodRaw),
    byPeriodStartDay: sumByDay(rows, (r) => r.periodStart),
  };
}

/* ------------------------------------------------------------------ */
/* classifyDiff 本体                                                    */
/* ------------------------------------------------------------------ */

export type KnownRule =
  | "declared"
  | "rain_div10"
  | "day_split"
  | "synthetic_excluded"
  | "unit_label_registry"
  | "float_rounding";

export interface ClassifyContext {
  expected: ExpectedDiffs;
  declared: DeclaredLookup;
  params: Readonly<Record<string, ScalarParam>>;
  /** この問い合わせに当てはまりうる既知の系統（`serving_queries.yaml` の `known`）。 */
  known: ReadonlySet<KnownRule>;
  /** `--mutate rain_no_div10_rule` / `day_split_rule_off` 用に規則を丸ごと無効化する。 */
  disabledRules?: ReadonlySet<KnownRule>;
  /** rain 系の3問い合わせだけが使う。日付キーは `diff.key` の最初の要素
   *  （`rain_daily`/`rain_monthly_clim` は `d`/`month`、`rain_top_days` は `label.d`）。 */
  rain?: RainRecompute;
  /** `rain_top_days` は month/day 単位ではなく順位で比較するため、日付は
   *  `v1`/`v2` の `label.d` から取る（呼び出し側が rain も渡すこと）。 */
  rainDateFromLabel?: boolean;
  /** `--pretend-synthetic-excluded`（PR-2 準備）。PR-1 では既定で空集合＝常に不発。 */
  syntheticSiteIds?: ReadonlySet<string>;
  /** `--mutate declared_rot` */
  declaredRot?: DeclaredRotOptions;
}

export interface Classification {
  rule: KnownRule | "unexplained";
  /** declared のとき、`findRottenDeclarations` に渡す消費済みキーの記録用。 */
  declaredMatch?: { table: string; entry: DeclaredEntry };
}

function ruleEnabled(ctx: ClassifyContext, rule: KnownRule): boolean {
  return ctx.known.has(rule) && !ctx.disabledRules?.has(rule);
}

function classifyRainDiv10(diff: RowDiff, ctx: ClassifyContext): boolean {
  if (!ruleEnabled(ctx, "rain_div10") || diff.kind !== "value_diff" || !diff.columns.includes("mm")) return false;
  if (!diff.v1 || !diff.v2) return false;
  const v1mm = diff.v1.numeric.mm;
  const v2mm = diff.v2.numeric.mm;
  if (v1mm === null || v2mm === null) return false;
  return Math.round((v2mm / 10) * 100) / 100 === v1mm;
}

function dayKeyOf(diff: RowDiff, ctx: ClassifyContext): string | undefined {
  if (ctx.rainDateFromLabel) return diff.v1?.label.d ?? diff.v2?.label.d ?? undefined;
  const k = diff.key[0];
  return k === undefined ? undefined : String(k);
}

function classifyDaySplit(diff: RowDiff, ctx: ClassifyContext): boolean {
  if (!ruleEnabled(ctx, "day_split") || !ctx.rain) return false;
  const day = dayKeyOf(diff, ctx);
  if (!day) return false;
  const byLabel = ctx.rain.byLabelDay.get(day);
  const byStart = ctx.rain.byPeriodStartDay.get(day);
  if (diff.kind === "row_only_in_v1") {
    // v1 側にしか無い日 = ラベル日割りにはあるが period_start 日割りには無い（またはその逆）。
    return byLabel !== undefined && byStart === undefined;
  }
  if (diff.kind === "row_only_in_v2") {
    return byStart !== undefined && byLabel === undefined;
  }
  if (diff.kind === "value_diff" && diff.columns.includes("mm")) {
    const v1mm = diff.v1?.numeric.mm ?? null;
    const v2mm = diff.v2?.numeric.mm ?? null;
    return v1mm !== null && v2mm !== null && byLabel === v1mm && byStart === v2mm;
  }
  return false;
}

function classifyUnitLabelRegistry(diff: RowDiff): boolean {
  if (diff.kind !== "label_diff" || !diff.columns.includes("unit")) return false;
  const v1Unit = diff.v1?.label.unit ?? null;
  const v2Unit = diff.v2?.label.unit ?? null;
  if (v1Unit !== null || v2Unit === null) return false;
  // unit 以外のラベル列・数値列は完全一致していること（この規則はラベルだけの差分に限る）。
  return diff.columns.every((c) => c === "unit");
}

function classifyFloatRounding(diff: RowDiff, ctx: ClassifyContext): boolean {
  if (!ruleEnabled(ctx, "float_rounding") || diff.kind !== "value_diff" || !diff.v1 || !diff.v2) return false;
  return diff.columns.every((c) => numbersDiffer(diff.v1!.numeric[c], diff.v2!.numeric[c], 1e-9) === false);
}

function classifySyntheticExcluded(diff: RowDiff, ctx: ClassifyContext): boolean {
  if (!ruleEnabled(ctx, "synthetic_excluded") || diff.kind !== "row_only_in_v1") return false;
  const siteId = diff.v1?.label.site_id ?? (typeof diff.key[0] === "string" ? diff.key[0] : undefined);
  return !!siteId && !!ctx.syntheticSiteIds?.has(siteId);
}

/**
 * `RowDiff` を既知の系統に当てはめる。当てはまらなければ `{ rule: "unexplained" }`。
 * 判定の優先順位: declared -> rain_div10 -> day_split -> synthetic_excluded ->
 * unit_label_registry -> float_rounding（設計書 §5.2 の表の順）。
 */
export function classifyDiff(diff: RowDiff, ctx: ClassifyContext): Classification {
  if (ruleEnabled(ctx, "declared")) {
    const entry = findDeclared(ctx.expected, ctx.declared, ctx.params, diff, ctx.declaredRot);
    if (entry) return { rule: "declared", declaredMatch: { table: ctx.declared.v1Table!, entry } };
  }
  if (classifyRainDiv10(diff, ctx)) return { rule: "rain_div10" };
  if (classifyDaySplit(diff, ctx)) return { rule: "day_split" };
  if (classifySyntheticExcluded(diff, ctx)) return { rule: "synthetic_excluded" };
  if (classifyUnitLabelRegistry(diff)) return { rule: "unit_label_registry" };
  if (classifyFloatRounding(diff, ctx)) return { rule: "float_rounding" };
  return { rule: "unexplained" };
}

export type { QueryDef };
