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
import { keyString, type NormRow, type QueryDef, type ScalarParam } from "./normalize";

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
  /**
   * `rain_monthly_clim` の v1 側（`ROUND(SUM(mm)/COUNT(DISTINCT year), 1)`、
   * ラベル日割りの月＝`substr(d,6,2)`）と同じ式で `byLabelDay` から作った月別平年値。
   */
  monthlyLabel: Map<number, number>;
  /**
   * `rain_monthly_clim` の v2 側（`summarize(..., "month_of_year", {measure:
   * "sum_per_year"})`、period_start 日割りの月）と同じ式（生値・`/10` 前・未丸め）で
   * `byPeriodStartDay` から作った月別平年値。`byPeriodStartDay` は既に `/10` 済みなので
   * 生値に戻すため ×10 する（v2 の `mm` 列は `/10` していない——design §0 決定2）。
   */
  monthlyPeriodStartRaw: Map<number, number>;
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

/**
 * 日ごとの mm（`sumByDay` の結果）を月別平年値に集約する。`scale` は日ごとの値に
 * かける倍率（v2 側は `byPeriodStartDay` が既に `/10` 済みのため ×10 して生値に戻す）、
 * `round1` は v1 の `ROUND(...,1)` を再現するかどうか。
 */
function monthlyClimFromDaily(dailyMm: ReadonlyMap<string, number>, opt: { scale: number; round1: boolean }): Map<number, number> {
  const sums = new Map<number, number>();
  const years = new Map<number, Set<number>>();
  for (const [day, mm] of dailyMm) {
    const month = Number.parseInt(day.slice(5, 7), 10);
    const year = Number.parseInt(day.slice(0, 4), 10);
    sums.set(month, (sums.get(month) ?? 0) + mm * opt.scale);
    let yset = years.get(month);
    if (!yset) {
      yset = new Set<number>();
      years.set(month, yset);
    }
    yset.add(year);
  }
  const out = new Map<number, number>();
  for (const [month, sum] of sums) {
    const v = sum / years.get(month)!.size;
    out.set(month, opt.round1 ? Math.round(v * 10) / 10 : v);
  }
  return out;
}

/** `rain_daily`/`rain_monthly_clim`/`rain_top_days` の L2 再計算をまとめて作る。 */
export function computeRainRecompute(rows: readonly RainL2Row[]): RainRecompute {
  const byLabelDay = sumByDay(rows, (r) => r.periodRaw);
  const byPeriodStartDay = sumByDay(rows, (r) => r.periodStart);
  return {
    byLabelDay,
    byPeriodStartDay,
    monthlyLabel: monthlyClimFromDaily(byLabelDay, { scale: 1, round1: true }),
    monthlyPeriodStartRaw: monthlyClimFromDaily(byPeriodStartDay, { scale: 10, round1: false }),
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
  | "float_rounding"
  | "lod_imputation";

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
  /** `rain_monthly_clim` は `diff.key` が「月」（1..12）なので、日ごとではなく
   *  月ごとに合流させた再計算（`RainRecompute.monthlyLabel`/`monthlyPeriodStartRaw`）を使う。
   *  既定 `"day"`（`rain_daily`/`rain_top_days`）。 */
  rainGrain?: "day" | "month";
  /**
   * design §1「診断用 v1互換キューブ」の差分の差分: `--v1compat-db` で開いた
   * 第2の v2 接続（合成データを除外**しない** `v2_v1compat.sqlite`）に、この
   * 問い合わせと同じ params・compare で同じ行を流した結果（キー文字列
   * （`normalize.ts` の `keyString`）→ `NormRow`）。無ければ（`--v1compat-db`
   * 未指定・v1-only）この規則は常に不発。
   */
  v2CompatByKey?: ReadonlyMap<string, NormRow>;
  /**
   * `--imputation lod` 実行専用: 同じ問い合わせを `imputation=zero` でも
   * 引いた結果（キー文字列→`NormRow`）。`lod_imputation` 規則が
   * 「v1 == v2(zero)」を確かめるのに使う。`--imputation zero` 実行では
   * 常に undefined（そもそも lod 診断は行わない）。
   */
  v2ZeroByKey?: ReadonlyMap<string, NormRow>;
  /** `--mutate declared_rot` */
  declaredRot?: DeclaredRotOptions;
  /**
   * alias（`ctx.params.alias` か、無ければ `diff.key[0]` から解決する——
   * `variable_catalog`/`site_variables` は alias が行キー側にしか出ない）ごとの、
   * レジストリ上の正しい unit symbol（`unitSymbol(seriesForAlias(alias)[0].unitId)`、
   * `adapters-v2.ts` の `expectedUnitSymbols()`）。`unit_label_registry` 規則が
   * 「v2 側が非NULLなら何でも通す」のではなく、実際にその系列の `unit_id` の
   * symbol と一致するかまで確かめるのに使う。無ければ（テスト以外では常にある
   * はずだが）この規則は安全側に倒して不発にする。
   */
  expectedUnitSymbol?: ReadonlyMap<string, string | null>;
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

/**
 * v1/v2 それぞれが指す「日」。`rain_top_days` は比較キーが順位（`d` はラベル列）
 * なので、日割りの境界がずれると同じ順位でも v1/v2 で違う日を指しうる
 * （`label_diff`＋`value_diff` が同じ key に同時に出る——`rain_daily`/`rain_monthly_clim`
 * は比較キー自体が日付/月なので常に同じ日になる）。
 */
function dayKeyOfSide(diff: RowDiff, ctx: ClassifyContext, side: "v1" | "v2"): string | undefined {
  if (ctx.rainDateFromLabel) return (side === "v1" ? diff.v1 : diff.v2)?.label.d ?? undefined;
  return dayKeyOf(diff, ctx);
}

function monthKeyOf(diff: RowDiff): number | undefined {
  const k = diff.key[0];
  if (k === undefined) return undefined;
  const n = Number(k);
  return Number.isNaN(n) ? undefined : n;
}

/**
 * `row_only_in_v1`/`row_only_in_v2` の day_split 判定は日次・月次どちらも同じ形
 * （ラベル側にしか無い/period_start 側にしか無い）なので共有する。
 */
function rowOnlySplitExplained(kind: "row_only_in_v1" | "row_only_in_v2", byLabel: number | undefined, byStart: number | undefined): boolean {
  if (kind === "row_only_in_v1") return byLabel !== undefined && byStart === undefined;
  return byStart !== undefined && byLabel === undefined;
}

/** 月別平年値（`rain_monthly_clim`）の day_split 判定。日ごとの判定と同じ形だが、
 *  `monthlyLabel`/`monthlyPeriodStartRaw`（すでに月単位・v2 側は生値スケール）を使う。
 *  月をまたいだ合算・年数での割り算を経由するため、丸め誤差ぶんだけ許容差を持たせる
 *  （`numbersDiffer` を再利用。月別平年値どうしの比較なので `day_split`/`rain_div10` の
 *  日次側の完全一致とは別に許容してよい——floating point の加算順序の違い）。 */
function classifyDaySplitMonthly(diff: RowDiff, rain: RainRecompute): boolean {
  const month = monthKeyOf(diff);
  if (month === undefined) return false;
  const byLabel = rain.monthlyLabel.get(month);
  const byStart = rain.monthlyPeriodStartRaw.get(month);
  if (diff.kind === "row_only_in_v1" || diff.kind === "row_only_in_v2") return rowOnlySplitExplained(diff.kind, byLabel, byStart);
  if (diff.kind === "value_diff" && diff.columns.includes("mm")) {
    const v1mm = diff.v1?.numeric.mm ?? null;
    const v2mm = diff.v2?.numeric.mm ?? null;
    if (v1mm === null || v2mm === null || byLabel === undefined || byStart === undefined) return false;
    // 月別平年値は 12 ヶ月しかなく、日割りがずれた日を1つも含まない月は無い
    // （実測: 549 日の日割りずれが12ヶ月全部に散らばっている）ので、day_split と
    // rain_div10 の守備範囲分けは日次側だけで行う（月次側は分けても
    // `--mutate rain_no_div10_rule` の検証対象が rain_daily/rain_top_days に
    // 残るので、ここまで厳密にする必要はない）。
    return !numbersDiffer(byLabel, v1mm, 1e-6) && !numbersDiffer(byStart, v2mm, 1e-6);
  }
  return false;
}

function classifyDaySplit(diff: RowDiff, ctx: ClassifyContext): boolean {
  if (!ruleEnabled(ctx, "day_split") || !ctx.rain) return false;
  if (ctx.rainGrain === "month") return classifyDaySplitMonthly(diff, ctx.rain);

  const v1Day = dayKeyOfSide(diff, ctx, "v1");
  const v2Day = dayKeyOfSide(diff, ctx, "v2");

  if (diff.kind === "row_only_in_v1" || diff.kind === "row_only_in_v2") {
    // v1 側にしか無い日 = ラベル日割りにはあるが period_start 日割りには無い（またはその逆）。
    const day = diff.kind === "row_only_in_v1" ? v1Day : v2Day;
    if (!day) return false;
    return rowOnlySplitExplained(diff.kind, ctx.rain.byLabelDay.get(day), ctx.rain.byPeriodStartDay.get(day));
  }
  if ((diff.kind === "value_diff" && diff.columns.includes("mm")) || diff.kind === "label_diff") {
    // `rain_top_days`（`rainDateFromLabel`）は同じ順位でも v1Day !== v2Day になりうる
    // （日割りの境界がずれて上位10件の顔ぶれ自体が変わるため。`label_diff`（d が違う）
    // と `value_diff`（mm が違う）が同じ key に同時に出る——どちらも同じ理由で説明できる
    // ので同じ判定にする）。
    if (!v1Day || !v2Day) return false;
    const v1mm = diff.v1?.numeric.mm ?? null;
    const v2mm = diff.v2?.numeric.mm ?? null;
    if (v1mm === null || v2mm === null) return false;
    const byLabel = ctx.rain.byLabelDay.get(v1Day);
    const byStart = ctx.rain.byPeriodStartDay.get(v2Day);
    if (byLabel === undefined || byStart === undefined) return false;
    // 実際に日の境界がずれた日だけを day_split とする（`rain_div10` と守備範囲を
    // 分ける——`--mutate rain_no_div10_rule` で確かめている: day_split が
    // ずれていない日まで拾うと rain_div10 を無効化しても常に day_split で
    // 説明できてしまい、rain_div10 規則自体の検証にならない）。ずれていない日は
    // v1Day===v2Day かつ「同じ日」をラベル日割り・period_start 日割りどちらで
    // 見ても一致する（`byLabelDay.get(v1Day) === byPeriodStartDay.get(v1Day)`）。
    if (v1Day === v2Day && ctx.rain.byLabelDay.get(v1Day) === ctx.rain.byPeriodStartDay.get(v1Day)) return false;
    // `byLabelDay`/`byPeriodStartDay`（`computeRainRecompute`）はどちらも `/10` 後の
    // 実 mm 値（`sumByDay` 参照）。v1 側の `mm` 列はすでに `/10` 済みなのでそのまま
    // 比べられるが、v2 側（キューブの生の合計値）は `/10` していないので、比べる前に
    // 同じ丸めをかける（`rain_div10` の丸めと同じ式）。
    const v2mmDiv10 = Math.round((v2mm / 10) * 100) / 100;
    return byLabel === v1mm && byStart === v2mmDiv10;
  }
  return false;
}

/** `unit_label_registry` の alias 解決: `params.alias` を優先し、無ければ
 *  `diff.key[0]` が文字列のときだけそれを alias とみなす
 *  （`variable_catalog`/`site_variables` は alias が行キー側にしか出ない）。 */
/**
 * `unit_label_registry` の期待値マップのキー解決。alias 単位の問い合わせは
 * `params.alias`（無ければ行キー先頭）、`*_by_variable` 問い合わせは
 * `params.variable_id`（無ければ行キー先頭——`variable_catalog_by_variable`/
 * `site_variables_by_variable` は variable_id が行キー側にしか出ない）。
 * `ctx.expectedUnitSymbol` は alias→symbol と variable_id→symbol の両方を
 * 1つの Map に併せ持つ（`adapters-v2.ts` の `expectedUnitSymbols`/
 * `expectedUnitSymbolsByVariable` を呼び出し側〔`serving-diff.mts`〕がマージする。
 * alias 文字列と variable_id〔`common:variable:...`〕は表記が衝突しない）。
 */
function aliasKeyOf(diff: RowDiff, ctx: ClassifyContext): string | undefined {
  if (typeof ctx.params.alias === "string") return ctx.params.alias;
  if (typeof ctx.params.variable_id === "string") return ctx.params.variable_id;
  return typeof diff.key[0] === "string" ? diff.key[0] : undefined;
}

function classifyUnitLabelRegistry(diff: RowDiff, ctx: ClassifyContext): boolean {
  if (!ruleEnabled(ctx, "unit_label_registry") || diff.kind !== "label_diff" || !diff.columns.includes("unit")) return false;
  const v1Unit = diff.v1?.label.unit ?? null;
  const v2Unit = diff.v2?.label.unit ?? null;
  if (v1Unit !== null || v2Unit === null) return false;
  // unit 以外のラベル列・数値列は完全一致していること（この規則はラベルだけの差分に限る）。
  if (!diff.columns.every((c) => c === "unit")) return false;
  // v2 側の単位が「任意の非NULL」ではなく、この系列のレジストリ上の正しい symbol と
  // 一致することまで確かめる（alias の取り違え等でたまたま非NULLになっただけの
  // ケースを誤って拾わないため——`ctx.expectedUnitSymbol` が無い/alias が解決できない
  // ときは安全側に倒して unexplained にする）。
  if (!ctx.expectedUnitSymbol) return false;
  const alias = aliasKeyOf(diff, ctx);
  if (alias === undefined) return false;
  const expected = ctx.expectedUnitSymbol.get(alias);
  return expected !== undefined && expected === v2Unit;
}

function classifyFloatRounding(diff: RowDiff, ctx: ClassifyContext): boolean {
  if (!ruleEnabled(ctx, "float_rounding") || diff.kind !== "value_diff" || !diff.v1 || !diff.v2) return false;
  return diff.columns.every((c) => numbersDiffer(diff.v1!.numeric[c], diff.v2!.numeric[c], 1e-9) === false);
}

/**
 * `value_diff` で synthetic_excluded を許すのは、地点の合成データが抜けることで
 * 実際に動きうる集計列だけに絞る（/code-review 指摘: 列を見ずに `value_diff` を
 * 全部通すと、たまたま合成地点で起きた無関係な回帰まで「合成地点だから」で
 * 隠してしまう）。PR-1 の測定値系の出力列＋PR-2 の by_variable 問い合わせの
 * 出力列（`n_places`）を尽くす。
 */
const SYNTHETIC_EXCLUDED_VALUE_COLUMNS = new Set([
  "n",
  "n_meas",
  "n_var",
  "n_sites",
  "n_places",
  "n_daily",
  "n_annual",
  "n_censored",
  "avg",
  "min",
  "max",
  "value", // day_series_site_by_variable（single-value 列。PR-2 by_variable）
  "y_from",
  "y_to",
]);

/**
 * `row_only_in_v1` は `diff.columns` が空なので、突き合わせる列の集合を行
 * そのものから取るしかない——数値列だけを見る（`SYNTHETIC_EXCLUDED_VALUE_COLUMNS`
 * と同じ「数値だけ」の考え方。ラベル列（`unit`）は比べない: `unitSymbol()`
 * が「登録はあるが symbol が無い」単位（例: dimensionless）に対して `null` では
 * なく `""` を返すため、v1 の生 NULL と v2 側の `""` が同じ実体を指していても
 * 文字列としては食い違う——`unit_label_registry` 規則が扱う対象であって、
 * synthetic_excluded がここで再現する筋合いではない）。
 */
function rowsMatchOnAllColumns(a: NormRow, b: NormRow, tol = 1e-9): boolean {
  for (const c of Object.keys(a.numeric)) {
    if (numbersDiffer(a.numeric[c], b.numeric[c] ?? null, tol)) return false;
  }
  return true;
}

/**
 * design §1「診断用 v1互換キューブ」の差分の差分。`ctx.v2CompatByKey`
 * （`--v1compat-db` で開いた、合成データを除外**しない** `v2_v1compat.sqlite` に
 * 同じ問い合わせを流した行）と突き合わせる:
 * - `row_only_in_v1`（v2 本番に無い）→ 同じキーが v2compat に存在し、v1 と
 *   （許容誤差内で）一致すれば「合成データが除かれて消えた行」として説明できる。
 * - `value_diff` → 列を `SYNTHETIC_EXCLUDED_VALUE_COLUMNS` に絞り、v1 == v2compat
 *   （合成込みの値は元々 v1 と一致していた）かつ v2compat ≠ v2 本番
 *   （除外後に実際に値が動いた）であれば説明できる。
 * - `row_only_in_v2` は対象外（合成データを除いて行が増えることは無い——常に
 *   unexplained）。
 */
function classifySyntheticExcludedV1Compat(diff: RowDiff, ctx: ClassifyContext): boolean {
  if (!ruleEnabled(ctx, "synthetic_excluded") || !ctx.v2CompatByKey) return false;
  if (diff.kind !== "row_only_in_v1" && diff.kind !== "value_diff") return false;

  const compatRow = ctx.v2CompatByKey.get(keyString(diff.key));
  if (!compatRow) return false;

  if (diff.kind === "row_only_in_v1") {
    if (!diff.v1) return false;
    return rowsMatchOnAllColumns(diff.v1, compatRow);
  }

  // value_diff
  if (!diff.v1 || !diff.v2) return false;
  if (!diff.columns.every((c) => SYNTHETIC_EXCLUDED_VALUE_COLUMNS.has(c))) return false;
  for (const c of diff.columns) {
    if (numbersDiffer(diff.v1.numeric[c], compatRow.numeric[c] ?? null, 1e-9)) return false; // v1 == v2compat
    if (!numbersDiffer(compatRow.numeric[c] ?? null, diff.v2.numeric[c], 0)) return false; // v2compat ≠ v2(本番)
  }
  return true;
}

/**
 * `--imputation lod` 実行専用（design §3 #1）。`value_diff` の数値列が
 * `LOD_IMPUTATION_VALUE_COLUMNS`（avg/min/max/value）に収まり、`ctx.v2ZeroByKey`
 * （同じ問い合わせを imputation=zero で引いた行）と v1 が一致していれば
 * 「値が動いたのは zero→lod の切り替えのせい」として説明できる。行に
 * `n_censored` 列があれば `>0` を要求する（無い合算問い合わせ——`zone_series`/
 * `climatology`/`zone_climatology`/`site_variables`/`longitudinal_highlight`
 * 等——は b04 が全セルで検証済みの不変条件「`value_zero≠value_lod` ⇒
 * `n_censored>0 or n_not_detected>0`」に依拠し、ここでは確認しない）。
 */
const LOD_IMPUTATION_VALUE_COLUMNS = new Set(["avg", "min", "max", "value"]);

function classifyLodImputation(diff: RowDiff, ctx: ClassifyContext): boolean {
  if (!ruleEnabled(ctx, "lod_imputation") || diff.kind !== "value_diff") return false;
  if (!ctx.v2ZeroByKey || !diff.v1 || !diff.v2) return false;
  if (!diff.columns.every((c) => LOD_IMPUTATION_VALUE_COLUMNS.has(c))) return false;

  const zeroRow = ctx.v2ZeroByKey.get(keyString(diff.key));
  if (!zeroRow) return false;
  for (const c of diff.columns) {
    if (numbersDiffer(diff.v1.numeric[c], zeroRow.numeric[c] ?? null, 1e-9)) return false; // v1 == v2(zero)
  }
  // b04 の不変条件は「value_zero≠value_lod ⇒ n_censored>0 **or** n_not_detected>0」
  // という OR（CLAUDE.md 参照）。v1 の meas_year 系の表は `n_censored` しか
  // 持たず `n_not_detected`（不検出・定量下限未満とは別に「検出されなかった」
  // 件数）を区別できない——実測: alias 'cn'（シアン）/'pcb' のような不検出が
  // 多い項目は `n_censored=0` のまま `value_lod` が NULL になる（不検出のみで
  // 定量下限未満の値は無い年）。`n_censored>0` だけを要求すると、この
  // 「不検出のみ」のケースを取りこぼす。v1 に `n_not_detected` が無い以上、
  // 直接は確認できないので、代わりに「lod 側のその列の値が NULL になった」
  // ことを不検出の代理指標として認める（`value_lod` が NULL なのは全件不検出の
  // ときだけ——一部不検出なら AVG は NULL を無視して計算されるので非NULLのまま
  //残る。その場合は `n_censored>0` 側でカバーされることを期待する）。
  if ("n_censored" in diff.v1.numeric) {
    const nCensored = diff.v1.numeric.n_censored ?? 0;
    const anyColumnBecameNull = diff.columns.some((c) => diff.v2!.numeric[c] === null);
    if (!(nCensored > 0 || anyColumnBecameNull)) return false;
  }
  return true;
}

/**
 * `RowDiff` を既知の系統に当てはめる。当てはまらなければ `{ rule: "unexplained" }`。
 * 判定の優先順位: declared -> rain_div10 -> day_split -> synthetic_excluded ->
 * lod_imputation -> unit_label_registry -> float_rounding（設計書 §5.2 の表の順
 * ＋ PR-2 で追加した lod_imputation を synthetic_excluded の直後に挿入）。
 */
export function classifyDiff(diff: RowDiff, ctx: ClassifyContext): Classification {
  if (ruleEnabled(ctx, "declared")) {
    const entry = findDeclared(ctx.expected, ctx.declared, ctx.params, diff, ctx.declaredRot);
    if (entry) return { rule: "declared", declaredMatch: { table: ctx.declared.v1Table!, entry } };
  }
  if (classifyRainDiv10(diff, ctx)) return { rule: "rain_div10" };
  if (classifyDaySplit(diff, ctx)) return { rule: "day_split" };
  if (classifySyntheticExcludedV1Compat(diff, ctx)) return { rule: "synthetic_excluded" };
  if (classifyLodImputation(diff, ctx)) return { rule: "lod_imputation" };
  if (classifyUnitLabelRegistry(diff, ctx)) return { rule: "unit_label_registry" };
  if (classifyFloatRounding(diff, ctx)) return { rule: "float_rounding" };
  return { rule: "unexplained" };
}

export type { QueryDef };
