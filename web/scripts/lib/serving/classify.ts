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
  /** `rain_monthly_clim` は `diff.key` が「月」（1..12）なので、日ごとではなく
   *  月ごとに合流させた再計算（`RainRecompute.monthlyLabel`/`monthlyPeriodStartRaw`）を使う。
   *  既定 `"day"`（`rain_daily`/`rain_top_days`）。 */
  rainGrain?: "day" | "month";
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

/**
 * `value_diff` で synthetic_excluded を許すのは、地点の合成データが抜けることで
 * 実際に動きうる集計列だけに絞る（/code-review 指摘: 列を見ずに `value_diff` を
 * 全部通すと、たまたま合成地点で起きた無関係な回帰まで「合成地点だから」で
 * 隠してしまう）。PR-1 の測定値系の出力列はこの集合に尽きる。
 */
const SYNTHETIC_EXCLUDED_VALUE_COLUMNS = new Set([
  "n",
  "n_meas",
  "n_var",
  "n_sites",
  "n_daily",
  "n_annual",
  "n_censored",
  "avg",
  "min",
  "max",
  "y_from",
  "y_to",
]);

/**
 * `--pretend-synthetic-excluded` 専用。地点1件に紐づく問い合わせ
 * （`sites_list`/`sites_in_water_body`/`site_variables`/`year_series_site`/
 * `month_series_site`/`day_series_site`/`year_series_water`）は、その地点が
 * 合成地点なら `row_only_in_v1`（行ごと消える）にも `value_diff`（`sites_list`
 * のように地点の行自体は LEFT JOIN で残り、集計列だけ 0 に落ちる）にもなりうる
 * ——どちらも「この地点の行だから」で説明できる。
 *
 * ゾーン・alias・水域単位の集計（`zone_series`/`climatology`/`zone_climatology`/
 * `variable_catalog`/`water_bodies`/`water_bodies_for_variable`）は複数地点の
 * 合算なので、行自体に「どの地点由来か」が無く、ここでは判定しない
 * （PR-1 は「合成地点の集合だけを確定させ、単一地点に閉じる問い合わせで
 * unexplained 0 を確かめる」までが範囲——設計書 §9-4「PR-2 の予告」。
 * 残りは PR-2 で合成データを実際に外すときに扱う）。
 */
function classifySyntheticExcluded(diff: RowDiff, ctx: ClassifyContext): boolean {
  if (!ruleEnabled(ctx, "synthetic_excluded")) return false;
  if (diff.kind !== "row_only_in_v1" && diff.kind !== "value_diff") return false;
  if (diff.kind === "value_diff" && !diff.columns.every((c) => SYNTHETIC_EXCLUDED_VALUE_COLUMNS.has(c))) return false;
  // site_id は問い合わせによって置き場所が違う: params（1地点を固定して呼ぶ
  // `site_variables`/`year_series_site`/`month_series_site`/`day_series_site`。
  // これらは `key[0]` が年月日・alias 等の別の文字列なので必ず params を先に見る）、
  // 出力の label 列（無い問い合わせが多い）、出力のキーの先頭
  // （`sites_list`/`sites_in_water_body`/`year_series_water` は params に
  // site_id が無いのでここまで落ちてくる）のいずれか。
  const siteId =
    (typeof ctx.params.site_id === "string" ? ctx.params.site_id : undefined) ??
    diff.v1?.label.site_id ??
    (typeof diff.key[0] === "string" ? diff.key[0] : undefined);
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
