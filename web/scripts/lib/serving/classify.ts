/**
 * v1/v2 の行を突き合わせて素の食い違い（`RowDiff`）を作る（`compareRuns`）のと、
 * 素の食い違いを「既知の系統」に当てはめる（`classifyDiff`）のと、2つの役目を持つ。
 *
 * 設計書 §5.2「既知の系統の判定規則」をそのまま実装する。ここは v1/v2 の DB を
 * 直接読まない——読む必要がある規則（`day_split`）は、あらかじめ
 * 読んでおいた L2（`observation`）の行の配列や、宣言済み差分（`expected_diffs.yaml`）の
 * 索引を `ClassifyContext` として受け取る。これにより、フィクスチャ（DB 無し）だけで
 * 全規則をテストできる（`classify.test.ts`）。
 *
 * `rain_div10`（v2の`mm`を/10したものがv1と一致するか）は Issue #48 PR-2 で撤去した:
 * `rain_daily`/`rain_top_days`（day 粒度の day_split が rain_div10 と守備範囲を分けて
 * 判定していた唯一の問い合わせ）が読み手ゼロで削除され（design D5）、残る
 * `rain_monthly_clim`（month 粒度）の `classifyDaySplitMonthly` は、そもそも
 * 「rain_div10 と分けなくてよい」前提で書かれていた（549日の日割りずれが12ヶ月
 * 全部に散らばっており、月次の再計算が /10 の換算を式に含んだまま v1/v2 の実値と
 * 完全一致するため）。実測（`--only rain_monthly_clim --mutate rain_no_div10_rule`）で
 * rain_div10 が実際に1件も選ばれない（day_split が全件を先に説明する）ことを確認して
 * 撤去した。`day_split` 側の式自体は変えていない（Issue #48 PR-2 統合後 修正C）。
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
/* L2（observation）の再計算（day_split）                               */
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
/* classifyDiff 本体: 「説明の鎖」                                        */
/*                                                                      */
/* Issue #48 PR-2 統合後 論点C（`docs/plans/V2_SERVING_PR2.md` §1・§3、    */
/* ADR-0029 2026-09-27 追記の書き換え）。行キーごとに                     */
/*   v1 →(declared)→ compat_zero →(synthetic_excluded)→ v2_zero          */
/*     →(lod_imputation、lod 実行時のみ)→ v2_lod                         */
/* という値の鎖を辿り、隣り合う2点が「値が等しい（許容差内）」か「その段の  */
/* 規則で説明できる」かのどちらかであることを列ごとに確かめる              */
/* （`explainColumnChain`）。1つの value_diff の複数列がそれぞれ違う段で    */
/* 差を持つ（例: n は宣言済みバグ、n_sites は合成データの除外）ことも、    */
/* 1つの列が複数段にまたがって差を持つ（例: avg が below_lod バグ＋合成    */
/* データの除外＋zero→lod の3つ全てで動く）こともあるため、列ごとに独立に  */
/* 鎖を辿り、diff 全体としては「使った規則の集合」（`Classification.rules`。  */
/* 例: `{declared, synthetic_excluded, lod_imputation}`）を返す——単一の    */
/* `rule` ではなく集合にすることで、新しい重なりが見つかるたびに専用の     */
/* 組み合わせ関数を積み増す必要が無くなる（旧 `classifyDeclaredWithSyntheticRemainder`  */
/* は撤去。ADR-0029 2026-09-27 追記が「新たな重なりにはこの関数に特例を    */
/* 積まない」と書いていた設計上の負債を、特例を無くすことで解消する）。     */
/*                                                                      */
/* `v2CompatByKey`（compat_zero）が無い問い合わせ（`--v1compat-db` 未指定・ */
/* v1-only 相当）では、鎖の compat_zero の節をそのまま飛ばし、v1 から      */
/* v2_zero へ直接 declared で橋渡しする（v1compat db が無かった PR-1 期の   */
/* 挙動と同じ）。`v2ZeroByKey`（＝`--imputation lod` 実行時のみ設定される） */
/* が無ければ lod の節も無く、鎖は v1/compat_zero/v2_zero の3点で終わる    */
/* （v2_zero は「今の imputation での実際の最終値」と同じものになる）。     */
/*                                                                      */
/* day_split・unit_label_registry・float_rounding・by_variable の束ねは    */
/* この鎖の対象外（今の位置づけのまま、鎖が不発だったときのフォールバック   */
/* として試す）。                                                        */
/* ------------------------------------------------------------------ */

export type KnownRule =
  | "declared"
  | "day_split"
  | "synthetic_excluded"
  | "unit_label_registry"
  | "float_rounding"
  | "lod_imputation"
  // 生物系（Issue #48 PR-3b、`docs/plans/V2_SERVING_PR3B.md` §3.1。ADR-0029 追記）。
  | "watershed_memo"
  | "species_n_definition"
  | "month_cell_membership"
  | "vernacular_label_rule"
  | "undated_excluded";

/**
 * 生物系の5規則（`watershed_memo`/`species_n_definition`/`month_cell_membership`/
 * `vernacular_label_rule`/`undated_excluded`）が「独立に組んだ中間点」として使う期待値
 * （`biota-expect.ts` が L2・registry・`ryuiki.sqlite`・`v1_projection_occurrence.sqlite` から
 * 別 SQL で作る。**`lib/cube` は import しない**——正解を v2 の経路で作らない。設計書 §5.4-3）。
 * classify.ts は DB を読まないので、読み込み済みのデータだけを受け取る。
 * 載っていない項目の規則は不発（unexplained のまま）にする。
 */
export interface BiotaExpectations {
  /** `watershed_year` の中間点。キーは `watershedYearKey(watershed_id, year)`。 */
  wsYear?: ReadonlyMap<string, WsYearExpect>;
  /** `watershed_rollup` の中間点（`org_watershed_exact`）。キーは watershed_id。 */
  wsAll?: ReadonlyMap<string, WsAllExpect>;
  /** `species_months`: v1 の規則（`period_raw` の月・年>=2018）で数えた件数。キーは `binomMonthKey`。 */
  monthV1?: ReadonlyMap<string, number>;
  /** `species_months`: v2 の月セルの所属規則（同一月に収まる記録・`period_start`>=2018）で数えた件数。 */
  monthV2?: ReadonlyMap<string, number>;
  /** 期待する表示名（binom → label。D4: 記録由来の和名補完を使う）。 */
  labels?: ReadonlyMap<string, string>;
  /** `ryuiki.sqlite` の `organism_records` で日付の無い件数（`observed_on` が NULL または 4 桁未満）。 */
  undated?: { records: number; gbif: number; inat: number };
}

export interface WsYearExpect {
  /** `org_watershed_year_exact`（b08。記録自身の流域）。 */
  n: number;
  alienN: number;
  redlistN: number;
  /** exact の species_n（学名全文の DISTINCT。v1 と同じ定義）。 */
  speciesNameN: number;
  /** 同じキーを L2 から `COUNT(DISTINCT taxon_id)` で数えた値（v2 の定義）。 */
  speciesTaxonN: number | null;
}

export interface WsAllExpect {
  n: number;
  alienN: number;
  redlistN: number;
}

export function watershedYearKey(watershedId: string | number, year: string | number): string {
  return `${watershedId}\u0000${year}`;
}

export function binomMonthKey(binom: string | number, month: string | number): string {
  return `${binom}\u0000${month}`;
}

export interface ClassifyContext {
  /** 問い合わせ id（生物系の規則は id ごとに判定を変える）。 */
  queryId?: string;
  /** 生物系の期待値（`--only` で生物系を回さないときは undefined）。 */
  biota?: BiotaExpectations;
  expected: ExpectedDiffs;
  declared: DeclaredLookup;
  params: Readonly<Record<string, ScalarParam>>;
  /** この問い合わせに当てはまりうる既知の系統（`serving_queries.yaml` の `known`）。 */
  known: ReadonlySet<KnownRule>;
  /** `--mutate day_split_rule_off` 等、規則を丸ごと無効化する。 */
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
   *
   * **常に `imputation=zero` で引いた結果**（`serving-diff.mts` 呼び出し側が
   * `--imputation lod` 実行でも固定で `"zero"` を渡す）。v1 は zero 相当の
   * 意味論しか知らないため、v1 と比べる基準（compat）も zero に揃える必要が
   * ある——lod で引くと「合成データを含む・かつ値も動く」セルで `v1 ==
   * compatRow` が成り立たず規則が不発になる（Issue #48 PR-2 統合後 修正B）。
   */
  v2CompatByKey?: ReadonlyMap<string, NormRow>;
  /**
   * `--imputation lod` 実行専用: 同じ問い合わせを `imputation=zero` でも
   * 引いた結果（キー文字列→`NormRow`）。`lod_imputation` 規則が
   * 「v1 == v2(zero)」を確かめるのに使う。`--imputation zero` 実行では
   * 常に undefined（そもそも lod 診断は行わない）。
   */
  v2ZeroByKey?: ReadonlyMap<string, NormRow>;
  /**
   * `serving-diff.mts` が行変異（`--mutate lod_instead_of_zero`/`swap_kind` 等）を
   * 適用する**前**に、この問い合わせ・この params・現在の imputation でそのまま
   * 引いた v2 の生の行（キー文字列→`NormRow`）。`diff.v2` が本当に v2 が計算した
   * 値かどうか（＝行変異で書き換えられていないか）を確かめるためだけに使う
   * （`v2MatchesTrueRow`）。無ければ（既存の単体テスト・v1-only 相当のフィクスチャ）
   * 検証をスキップしてこれまでどおり信頼する。
   *
   * Issue #48 PR-2 統合後 修正C: これが無いと、`synthetic_excluded`/`lod_imputation`
   * は「`compatRow`（または `v2ZeroByKey`）と `v1` が一致し、`diff.v2` がそれと
   * 食い違う」ことしか見ていない——行変異が `diff.v2` を任意の値に書き換えても
   * 同じ条件を満たしてしまい、`swap_kind`/`lod_instead_of_zero` を「合成データの
   * 除外」や「zero→lod」で説明したことにして見逃していた（実測: `--only
   * year_series_site,year_series_water --mutate swap_kind` で 45,335 件が
   * 誤って `synthetic_excluded` に落ちていた。対象の site_id は210件に及び、
   * 実際に合成データの影響を受ける24地点をはるかに超える——規則が「本当に
   * 合成データが原因か」を一切確かめていなかった証拠）。
   */
  v2TrueByKey?: ReadonlyMap<string, NormRow>;
  /**
   * `v2TrueByKey` と同じ「行変異適用前の生の v2 行」だが、常に `imputation=zero`
   * で引いたもの（`--imputation zero` 実行では `v2TrueByKey` と同一の行、
   * `--imputation lod` 実行では `v2ZeroByKey` と同一の行——どちらも
   * `serving-diff.mts` が計算するだけで、追加の DB 問い合わせは増えない）。
   *
   * 「説明の鎖」（モジュール冒頭参照）の compat_zero↔v2_zero の段（`explainColumnChain`）
   * が、この「本当の v2_zero 値」を橋渡し先として使う。無ければ（`--v1compat-db`
   * 未指定・running lod でない等）その列の compat_zero→v2_zero の段は
   * `ctx.v2ZeroByKey` にフォールバックする（無ければ「今の imputation の最終値が
   * そのまま v2_zero」とみなす——`--imputation zero` 実行では常にそう）。
   *
   * Issue #48 PR-2 統合後 修正C（旧実装での経緯）: これが無いと、`--imputation lod`
   * 実行で `compatRow`（常に zero）と `diff.v2`（現在の imputation）を直接比べる
   * だけになり、合成データの影響が一切無い地点の「zero→lod」の差分まで
   * `synthetic_excluded` が説明してしまっていた。「説明の鎖」では
   * compat_zero↔v2_zero と v2_zero↔v2_lod を別々の段として扱う（段ごとに
   * 規則を分ける）ことで、この取り違えが構造的に起きなくなった。
   */
  v2TrueZeroByKey?: ReadonlyMap<string, NormRow>;
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
  /**
   * `*_by_variable` 問い合わせ（`v1Table` が無いため `declared`/`ctx.declared` の
   * 単一キー組み立てが使えない）専用: この variable_id が束ねる alias 群のうち、
   * `scripts/reconcile/expected_diffs.yaml` の対応表（alias 単位の v1 表）を
   * 探すための情報。alias 一覧の解決自体は `merge-v1.ts` 経由で `registry.sqlite`
   * を読む必要があるため `serving-diff.mts`（`BY_VARIABLE_DECLARED_SPECS`）が
   * params から解決して埋める——classify.ts はここでも DB を直接読まない
   * （モジュール docstring参照）。`declaredCandidates` が使う。
   */
  byVariableDeclared?: {
    v1Table: string;
    /** variable_id が params ではなく行キー側にある問い合わせ（`variable_catalog_by_variable`
     *  等）もあるため、alias 解決は行キーを受け取ってから行う（`serving-diff.mts` の
     *  `BY_VARIABLE_DECLARED_SPECS`/`byVariableDeclaredFor` 参照）。*/
    aliasesFor: (rowKey: readonly ScalarParam[]) => readonly string[];
    buildKey: (alias: string, rowKey: readonly ScalarParam[]) => ScalarParam[];
  };
}

export interface Classification {
  /**
   * この diff を説明するのに使った規則の集合。空集合なら unexplained。
   * 複数要素は、鎖の複数の段にまたがって説明されたことを示す
   * （例: `{declared, synthetic_excluded, lod_imputation}`）。レポートでは
   * この集合の要素それぞれについて1系統ずつ数える（1行が複数系統に数えられる）。
   */
  rules: ReadonlySet<KnownRule>;
  /**
   * `declared` が段1（v1↔compat_zero、または compat_zero が無いときは
   * v1↔v2_zero）で実際に使われた宣言（`findRottenDeclarations` に渡す
   * 消費済みキーの記録用）。**overall が unexplained でも、段1で使われて
   * いれば必ずここに載る**（設計: 「宣言の腐り判定は段1で使われたかで数える」
   * ——他の列・他の段が原因で diff 全体が unexplained になっても、この宣言
   * 自体は実際に消費されている）。複数列・複数 by_variable alias 候補が
   * それぞれ別のエントリに一致すれば複数件になりうる。
   */
  declaredMatches: { table: string; entry: DeclaredEntry }[];
  /**
   * `vernacular_label_rule` が説明した表示名の動きの分類（`labelCategory(v1) + "→" + labelCategory(v2)`。
   * 例: `日本語→日本語`）。レポートの `label_moved` の件数に使う（設計書 §3.1・§3.4-2）。
   */
  labelMoves?: string[];
}

/** `rules` が空 = unexplained。読みやすさのための小さな補助関数。 */
export function isUnexplained(c: Classification): boolean {
  return c.rules.size === 0;
}

function ruleEnabled(ctx: ClassifyContext, rule: KnownRule): boolean {
  return ctx.known.has(rule) && !ctx.disabledRules?.has(rule);
}

/** 空の分類（unexplained）。呼び出しのたびに新しいオブジェクトを作る
 *  （`declaredMatches` 配列を呼び出し元同士で共有しないため）。 */
function emptyClassification(): Classification {
  return { rules: new Set(), declaredMatches: [] };
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
 *  （`numbersDiffer` を再利用。月別平年値どうしの比較なので、日次側の完全一致とは
 *  別に許容してよい——floating point の加算順序の違い）。 */
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
    // （実測: 549 日の日割りずれが12ヶ月全部に散らばっている）ので、この月次判定は
    // 「ずれていない月まで拾わない」よう絞り込む必要が無い（day_split が
    // rain_monthly_clim の value_diff を常に完全に説明できる。かつて存在した
    // `rain_div10` 規則がこの問い合わせで1件も選ばれなかったのはこのため——
    // Issue #48 PR-2 統合後 修正C参照）。
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
    // 実際に日の境界がずれた日だけを day_split とする（ずれていない日まで拾うと、
    // 本来別の原因で食い違っている行まで day_split が飲み込んでしまう）。
    // ずれていない日は v1Day===v2Day かつ「同じ日」をラベル日割り・period_start
    // 日割りどちらで見ても一致する（`byLabelDay.get(v1Day) === byPeriodStartDay.get(v1Day)`）。
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
 * `diff.v2` が本当に v2 が計算した値そのものか（`serving-diff.mts` の行変異で
 * 書き換えられていないか）を確かめる（`ClassifyContext.v2TrueByKey` docstring参照）。
 * `ctx.v2TrueByKey` が無い/該当キーが無ければ検証できないので、これまでどおり
 * 信頼する（`true` を返す）——既存の単体テスト・v1-only 相当のフィクスチャは
 * この場を渡さない。
 */
function v2MatchesTrueRow(diff: RowDiff, ctx: ClassifyContext): boolean {
  if (!ctx.v2TrueByKey || !diff.v2) return true;
  const trueRow = ctx.v2TrueByKey.get(keyString(diff.key));
  if (!trueRow) return true;
  return rowsMatchOnAllColumns(diff.v2, trueRow);
}

/**
 * `diff` に含まれる declared 候補（table, key）を、`ctx.declared`（単一の
 * v1Table/builder）と `ctx.byVariableDeclared`（`*_by_variable` 問い合わせの
 * 束ねエイリアス群）の両方から集める。「段1」（declared）の唯一の入り口——
 * value_diff・row_only のどちらの探索もこれを共有する。
 */
function declaredCandidates(diff: RowDiff, ctx: ClassifyContext): { table: string; key: ScalarParam[] }[] {
  const out: { table: string; key: ScalarParam[] }[] = [];
  if (ctx.declared.v1Table && ctx.declared.builder) {
    out.push({ table: ctx.declared.v1Table, key: ctx.declared.builder(ctx.params, diff.key) });
  }
  if (ctx.byVariableDeclared) {
    for (const alias of ctx.byVariableDeclared.aliasesFor(diff.key)) {
      out.push({ table: ctx.byVariableDeclared.v1Table, key: ctx.byVariableDeclared.buildKey(alias, diff.key) });
    }
  }
  return out;
}

/**
 * row_only 系（`row_only_in_baseline`/`row_only_in_candidate`）の declared 一致。
 * 列を持たないため、宣言のキー一致だけで確定する（値は見ない——これは元々
 * `findDeclared`/旧 `classifyDeclaredWithSyntheticRemainder` の row_only 分岐と
 * 同じ振る舞い）。
 */
function findDeclaredRowMatch(
  diff: RowDiff,
  ctx: ClassifyContext,
  kind: "row_only_in_baseline" | "row_only_in_candidate",
): { table: string; entry: DeclaredEntry } | undefined {
  if (!ruleEnabled(ctx, "declared")) return undefined;
  for (const { table, key } of declaredCandidates(diff, ctx)) {
    const entries = ctx.expected[table] ?? [];
    for (const entry of entries) {
      if (isRotted(ctx.declaredRot, table, entry)) continue;
      if (entry.kind !== kind) continue;
      if (keyEquals(entry.key, key)) return { table, entry };
    }
  }
  return undefined;
}

/**
 * 1つの数値列について、`kind: "value_diff"` の宣言がその列を覆っているか
 * （`entry.columns` に列名が含まれるか）を確かめる。「段1」（declared）が
 * 数値列を橋渡しできるかどうかを、列ごとに独立して判定する——これにより、
 * 同じ diff の中で「この列は宣言済みバグ、あの列は合成データの除外」という
 * 列ごとに異なる説明の組み合わせが、専用の組み合わせ関数を書かずに済む。
 */
function findDeclaredColumnMatch(diff: RowDiff, ctx: ClassifyContext, column: string): { table: string; entry: DeclaredEntry } | undefined {
  if (!ruleEnabled(ctx, "declared")) return undefined;
  for (const { table, key } of declaredCandidates(diff, ctx)) {
    const entries = ctx.expected[table] ?? [];
    for (const entry of entries) {
      if (isRotted(ctx.declaredRot, table, entry)) continue;
      if (entry.kind !== "value_diff") continue;
      if (!keyEquals(entry.key, key)) continue;
      if ((entry.columns ?? []).includes(column)) return { table, entry };
    }
  }
  return undefined;
}

const CHAIN_EPS = 1e-9;

/**
 * 段3（v2_zero -> v2_lod、`lod_imputation`）で説明を許す数値列。lod への
 * 切り替えで実際に動きうる代表値・統計量だけに絞る（`n`/`n_censored` 等の
 * 件数列は imputation では変わらないはずなので対象外——`SYNTHETIC_EXCLUDED_VALUE_COLUMNS`
 * より狭い）。
 */
const LOD_IMPUTATION_VALUE_COLUMNS = new Set(["avg", "min", "max", "value"]);

/**
 * `row_only_in_v1`/`row_only_in_v2` を「説明の鎖」で辿る。列を持たないため
 * value_diff ほど段を細かく分けられない——存在の有無は1段でしか判定できない
 * ので、row_only はどちらの kind も「declared（段1）」か「synthetic_excluded
 * （段2、`row_only_in_v1` だけ）」のどちらか一方で説明する（両方が同時に要る
 * ケースは無い——値が無い以上「宣言はこの列だけ覆う」という粒度が存在しない）。
 */
function explainRowOnly(diff: RowDiff, ctx: ClassifyContext): Classification {
  if (diff.kind === "row_only_in_v1") {
    if (!diff.v1) return emptyClassification();
    // 本当は消えていない（行変異で v2ByKey から消しただけの）行は対象外
    // （`ClassifyContext.v2TrueByKey` docstring参照）。
    if (ctx.v2TrueByKey?.has(keyString(diff.key))) return emptyClassification();

    const declared = findDeclaredRowMatch(diff, ctx, "row_only_in_baseline");
    if (declared) return { rules: new Set(["declared"]), declaredMatches: [declared] };

    if (!ruleEnabled(ctx, "synthetic_excluded") || !ctx.v2CompatByKey) return emptyClassification();
    const compatRow = ctx.v2CompatByKey.get(keyString(diff.key));
    if (!compatRow || !rowsMatchOnAllColumns(diff.v1, compatRow)) return emptyClassification();
    return { rules: new Set(["synthetic_excluded"]), declaredMatches: [] };
  }

  if (diff.kind === "row_only_in_v2") {
    if (!diff.v2) return emptyClassification();
    // 合成データの除外で行が増えることは無い——row_only_in_v2 は declared だけが対象。
    const declared = findDeclaredRowMatch(diff, ctx, "row_only_in_candidate");
    if (declared) return { rules: new Set(["declared"]), declaredMatches: [declared] };
    return emptyClassification();
  }

  return emptyClassification();
}

/**
 * 1つの数値列について、鎖
 *   v1 →(declared)→ compat_zero →(synthetic_excluded)→ v2_zero →(lod_imputation)→ v2_lod
 * を辿る。隣り合う2点は「等しい（`CHAIN_EPS` 許容）」か「その段の規則で
 * 説明できる」かのどちらかでなければならない——どちらも満たさなければ
 * この列は explained できない（`false` を返す）。
 *
 * `compat_zero`（`ctx.v2CompatByKey`）が無ければその段を飛ばし、v1 から
 * v2_zero へ declared で直接橋渡しする（`--v1compat-db` 未指定・v1-only 相当。
 * PR-1 期の挙動と同じ）。v2_zero が取れない（`ctx.v2TrueZeroByKey`/
 * `ctx.v2ZeroByKey` のどちらも無い）ときは、lod 実行でなければ「今の
 * imputation の最終値がそのまま v2_zero」とみなす（`--imputation zero` 実行
 * では常にそう——鎖はそこで終わる）。
 *
 * 見つかった規則・宣言一致は `acc` に積む——**列の途中で説明できなくなっても
 * 打ち切らず、それまでに見つかった宣言一致は `acc.declaredMatches` に残す**
 * （「宣言の腐り判定は段1で使われたかで数える」——他の理由でこの diff が
 * 結局 unexplained になっても、宣言自体は消費されたとみなす）。
 */
function explainColumnChain(
  column: string,
  diff: RowDiff,
  ctx: ClassifyContext,
  keyStr: string,
  acc: { rules: Set<KnownRule>; declaredMatches: { table: string; entry: DeclaredEntry }[] },
): boolean {
  const v1v = diff.v1!.numeric[column] ?? null;
  const finalV = diff.v2!.numeric[column] ?? null;

  const hasCompat = ctx.v2CompatByKey !== undefined;
  const compatRow = ctx.v2CompatByKey?.get(keyStr);
  const compatV = compatRow ? (compatRow.numeric[column] ?? null) : null;

  const runningLod = ctx.v2ZeroByKey !== undefined;
  const zeroSource = ctx.v2TrueZeroByKey ?? ctx.v2ZeroByKey;
  const zeroRow = zeroSource?.get(keyStr);
  const zeroKnown = zeroRow !== undefined || !runningLod;
  const zeroV = zeroRow ? (zeroRow.numeric[column] ?? null) : finalV; // zeroKnown かつ zeroRow 無し = lod 実行でない = final が zero

  let cur = v1v;

  // 段1: v1 -> compat_zero
  if (hasCompat) {
    if (numbersDiffer(cur, compatV, CHAIN_EPS)) {
      const entry = findDeclaredColumnMatch(diff, ctx, column);
      if (!entry) return false;
      acc.rules.add("declared");
      acc.declaredMatches.push(entry);
    }
    cur = compatV;
  }

  // 段2: (v1 | compat_zero) -> v2_zero
  if (!zeroKnown) {
    // running lod だが v2_zero の値が取れない: これ以上は検証できない。
    return !numbersDiffer(cur, finalV, CHAIN_EPS);
  }
  if (numbersDiffer(cur, zeroV, CHAIN_EPS)) {
    if (hasCompat) {
      if (!ruleEnabled(ctx, "synthetic_excluded") || !SYNTHETIC_EXCLUDED_VALUE_COLUMNS.has(column)) return false;
      acc.rules.add("synthetic_excluded");
    } else {
      // compat_zero が無い: v1 -> v2_zero を declared で直接橋渡しする
      // （`--v1compat-db` 未指定のときの唯一の橋渡し）。
      const entry = findDeclaredColumnMatch(diff, ctx, column);
      if (!entry) return false;
      acc.rules.add("declared");
      acc.declaredMatches.push(entry);
    }
  }
  cur = zeroV;

  // 段3: v2_zero -> v2_lod（lod 実行時のみ）
  if (!runningLod) {
    return !numbersDiffer(cur, finalV, CHAIN_EPS);
  }
  if (numbersDiffer(cur, finalV, CHAIN_EPS)) {
    if (!ruleEnabled(ctx, "lod_imputation") || !LOD_IMPUTATION_VALUE_COLUMNS.has(column)) return false;
    // b04 の不変条件は「value_zero≠value_lod ⇒ n_censored>0 **or**
    // n_not_detected>0」という OR（CLAUDE.md 参照）。v1 は n_not_detected を
    // 区別できないので、lod 側のその列の値が NULL になった（全件不検出）ことを
    // 代理指標として認める（実測: alias 'cn'/'pcb' のような不検出が多い項目）。
    //
    // n_censored は **v1 ではなく v2_zero（無ければ compat_zero）から** 取る——
    // v1 自身がこの列で説明を要する行（below_lod バグで n_censored 込みの
    // 複数列が同時に動く行）では、v1 の n_censored もそのバグの影響を受けて
    // 壊れている（実測: 中津川 SS 2005年度 annual は v1 の n_censored=0 だが
    // 本当は 2——below_lod 行を丸ごと落としているため）。段1で declared が
    // 橋渡しした後の「正しい」n_censored（`zeroRow`/`compatRow`）を使わないと、
    // 3原因が重なる行で lod_imputation が不当に不発になる。
    const nCensoredRow = zeroRow ?? compatRow ?? diff.v1!;
    const nCensored = nCensoredRow.numeric.n_censored ?? 0;
    const becameNull = finalV === null;
    if ("n_censored" in nCensoredRow.numeric && !(nCensored > 0 || becameNull)) return false;
    acc.rules.add("lod_imputation");
  }
  return true;
}

/**
 * `value_diff` を「説明の鎖」で辿る。`diff.columns` の各列を独立に
 * `explainColumnChain` へ通し、**全ての列が説明できたときだけ** `rules` を
 * 返す（1列でも説明できなければ diff 全体が unexplained——ただし
 * `declaredMatches` はそれまでに見つかった分を保持する）。
 */
function explainValueDiff(diff: RowDiff, ctx: ClassifyContext): Classification {
  if (diff.kind !== "value_diff" || !diff.v1 || !diff.v2) return emptyClassification();
  // `diff.v2` が本当に v2 が計算した値そのものか（行変異で書き換えられて
  // いないか）を先に確かめる——これが崩れていれば、鎖のどの段も信用できない
  // （`ClassifyContext.v2TrueByKey` docstring参照）。
  if (!v2MatchesTrueRow(diff, ctx)) return emptyClassification();

  const keyStr = keyString(diff.key);
  const rules = new Set<KnownRule>();
  const declaredMatches: { table: string; entry: DeclaredEntry }[] = [];
  let allOk = true;
  for (const column of diff.columns) {
    const ok = explainColumnChain(column, diff, ctx, keyStr, { rules, declaredMatches });
    if (!ok) allOk = false;
  }
  return { rules: allOk ? rules : new Set(), declaredMatches };
}

/* ------------------------------------------------------------------ */
/* 生物系の5規則（Issue #48 PR-3b、`docs/plans/V2_SERVING_PR3B.md` §3.1）     */
/*                                                                      */
/* 説明の鎖は「v1 →(規則)→ 独立に組んだ中間点 →(=)→ v2」。中間点は            */
/* `ctx.biota`（`biota-expect.ts` が L2 等から別 SQL で作る）。「v2 が中間点と  */
/* 一致する」ことを必ず確かめる——一致しなければ unexplained（規則が「何でも   */
/* 説明する穴」にならない。`label_wrong` 変異がこれを見る）。                  */
/* ------------------------------------------------------------------ */

/**
 * 表示名の文字種の分類（D4 の判断材料の表と同じ。設計書 §0 D4）。
 * 日本語＝かなを含む／学名のみ＝名前が binom そのもの／中国語等＝漢字のみ（かなもラテン文字も無い）／
 * 英名等＝それ以外。
 */
export function labelCategory(label: string | null, binom: string): string {
  if (label === null || label === "" || label === binom) return "学名のみ";
  if (/[぀-ヿㇰ-ㇿｦ-ﾟ]/.test(label)) return "日本語";
  if (/[A-Za-z]/.test(label)) return "英名等";
  if (/[㐀-鿿]/.test(label)) return "中国語等";
  return "英名等";
}

function numOf(row: NormRow | undefined, col: string): number | null {
  return row ? (row.numeric[col] ?? null) : null;
}

/** 生物系の規則を有効にしてよいか（known に入っていて、変異で無効化されていない）。 */
function bioRule(ctx: ClassifyContext, rule: KnownRule, used: Set<KnownRule>): boolean {
  if (!ruleEnabled(ctx, rule)) return false;
  used.add(rule);
  return true;
}

const WS_COLUMN_OF: Readonly<Record<string, "n" | "alienN" | "redlistN">> = {
  n: "n",
  alien_n: "alienN",
  redlist_n: "redlistN",
  org_n: "n",
  org_alien_n: "alienN",
  org_redlist_n: "redlistN",
};

/**
 * `watershed_rollup`／`watershed_year`: v1 →(memo)→ exact（b08 が L2 から別 SQL で組む）→(=)→ v2。
 * `species_n`（`watershed_year` のみ）は v1 →(memo)→ exact(学名 DISTINCT) →(definition)→ L2 の
 * `COUNT(DISTINCT taxon_id)` →(=)→ v2。
 */
function explainWatershed(diff: RowDiff, ctx: ClassifyContext, b: BiotaExpectations): Classification {
  const isYear = ctx.queryId === "watershed_year";
  const ex: WsYearExpect | WsAllExpect | undefined = isYear
    ? b.wsYear?.get(watershedYearKey(diff.key[0], diff.key[1]))
    : b.wsAll?.get(String(diff.key[0]));
  if (!isYear && !b.wsAll) return emptyClassification();
  if (isYear && !b.wsYear) return emptyClassification();
  const used = new Set<KnownRule>();

  if (diff.kind === "row_only_in_v1") {
    // exact（＝v2 と一致するはずの中間点）にも無い行 = v1 のメモが作った行。
    if (ex !== undefined || !bioRule(ctx, "watershed_memo", used)) return emptyClassification();
    return { rules: used, declaredMatches: [] };
  }
  if (diff.kind === "row_only_in_v2") {
    if (ex === undefined || !diff.v2 || !bioRule(ctx, "watershed_memo", used)) return emptyClassification();
    for (const [col, k] of Object.entries(WS_COLUMN_OF)) {
      const v2v = numOf(diff.v2, col);
      if (v2v !== null && v2v !== ex[k]) return emptyClassification();
    }
    if (isYear) {
      const y = ex as WsYearExpect;
      if (y.speciesTaxonN === null || numOf(diff.v2, "species_n") !== y.speciesTaxonN) return emptyClassification();
    }
    return { rules: used, declaredMatches: [] };
  }
  if (diff.kind !== "value_diff" || !diff.v1 || !diff.v2 || ex === undefined) return emptyClassification();

  for (const col of diff.columns) {
    if (col === "species_n" && isYear) {
      const y = ex as WsYearExpect;
      const v1v = numOf(diff.v1, col);
      const v2v = numOf(diff.v2, col);
      if (y.speciesTaxonN === null || v2v !== y.speciesTaxonN) return emptyClassification();
      let explained = false;
      if (v1v !== y.speciesNameN) {
        if (!bioRule(ctx, "watershed_memo", used)) return emptyClassification();
        explained = true;
      }
      if (y.speciesNameN !== y.speciesTaxonN) {
        if (!bioRule(ctx, "species_n_definition", used)) return emptyClassification();
        explained = true;
      }
      if (!explained) return emptyClassification();
      continue;
    }
    const k = WS_COLUMN_OF[col];
    if (!k) return emptyClassification();
    if (numOf(diff.v2, col) !== ex[k]) return emptyClassification();
    if (!bioRule(ctx, "watershed_memo", used)) return emptyClassification();
  }
  return { rules: used, declaredMatches: [] };
}

/**
 * `species_months`: v1 の件数が「v1 の所属規則（`period_raw` の月）で数えた期待値」と、v2 の件数が
 * 「v2 の月セルの所属規則（同一月に収まる記録）で数えた期待値」と一致するときだけ説明する。
 */
function explainMonthCellMembership(diff: RowDiff, ctx: ClassifyContext, b: BiotaExpectations): Classification {
  const binom = ctx.params.binom;
  if (binom === undefined || !b.monthV1 || !b.monthV2) return emptyClassification();
  const k = binomMonthKey(binom, diff.key[0]);
  const e1 = b.monthV1.get(k) ?? 0;
  const e2 = b.monthV2.get(k) ?? 0;
  if (e1 === e2) return emptyClassification();
  const v1n = diff.kind === "row_only_in_v2" ? 0 : (numOf(diff.v1, "n") ?? 0);
  const v2n = diff.kind === "row_only_in_v1" ? 0 : (numOf(diff.v2, "n") ?? 0);
  if (v1n !== e1 || v2n !== e2) return emptyClassification();
  const used = new Set<KnownRule>();
  if (!bioRule(ctx, "month_cell_membership", used)) return emptyClassification();
  return { rules: used, declaredMatches: [] };
}

/**
 * 表示名（`species_labels`/`species_catalog`/`species_share_trend` の `label` 列）: v2 の表示名が
 * registry・`vernacular_ja.csv`・`summary_taxon_catalog` から独立に再計算した期待ラベルと一致する
 * ときだけ `vernacular_label_rule` で説明する。`label` 以外のラベル列（`species_catalog` の
 * `cls`/`family`/`taxon_group`）は宣言済み差分（`declared`。Sirosporium の `cls`）だけが説明できる。
 */
function explainLabelDiff(diff: RowDiff, ctx: ClassifyContext, b: BiotaExpectations): Classification {
  if (diff.kind !== "label_diff" || !diff.v1 || !diff.v2 || !b.labels) return emptyClassification();
  const binom = String(diff.key[0]);
  const used = new Set<KnownRule>();
  const declaredMatches: { table: string; entry: DeclaredEntry }[] = [];
  const labelMoves: string[] = [];
  let ok = true;
  for (const col of diff.columns) {
    if (col === "label") {
      const v2l = diff.v2.label.label ?? null;
      const expected = b.labels.get(binom);
      if (expected === undefined || v2l !== expected || !bioRule(ctx, "vernacular_label_rule", used)) {
        ok = false;
        continue;
      }
      labelMoves.push(`${labelCategory(diff.v1.label.label ?? null, binom)}→${labelCategory(v2l, binom)}`);
      continue;
    }
    const m = findDeclaredColumnMatch(diff, ctx, col);
    if (!m) {
      ok = false;
      continue;
    }
    used.add("declared");
    declaredMatches.push(m);
  }
  return ok ? { rules: used, declaredMatches, labelMoves } : { rules: new Set(), declaredMatches };
}

/** `biota_totals`: v1 − v2 が `ryuiki.sqlite` の日付の無い件数（全体・gbif・inat）と一致するときだけ説明する。 */
function explainUndated(diff: RowDiff, ctx: ClassifyContext, b: BiotaExpectations): Classification {
  if (diff.kind !== "value_diff" || !diff.v1 || !diff.v2 || !b.undated) return emptyClassification();
  const delta: Record<string, number> = { records: b.undated.records, gbif: b.undated.gbif, inat: b.undated.inat };
  const used = new Set<KnownRule>();
  for (const col of diff.columns) {
    const d = delta[col];
    const v1v = numOf(diff.v1, col);
    const v2v = numOf(diff.v2, col);
    if (d === undefined || v1v === null || v2v === null || v1v - v2v !== d) return emptyClassification();
    if (!bioRule(ctx, "undated_excluded", used)) return emptyClassification();
  }
  return { rules: used, declaredMatches: [] };
}

/**
 * 生物系の問い合わせ（`ctx.queryId`）の diff を、5規則で説明する。対象外の問い合わせ・diff の種類は
 * `undefined`（既存の鎖に任せる）。説明できなければ空の分類（unexplained）を返す。
 */
function classifyBiota(diff: RowDiff, ctx: ClassifyContext): Classification | undefined {
  const b = ctx.biota;
  if (!b) return undefined;
  switch (ctx.queryId) {
    case "watershed_rollup":
    case "watershed_year":
      return explainWatershed(diff, ctx, b);
    case "species_months":
      return explainMonthCellMembership(diff, ctx, b);
    case "species_labels":
    case "species_catalog":
    case "species_share_trend":
      return diff.kind === "label_diff" ? explainLabelDiff(diff, ctx, b) : undefined;
    case "biota_totals":
      return explainUndated(diff, ctx, b);
    default:
      return undefined;
  }
}

/**
 * `RowDiff` を既知の系統に当てはめる。まず「説明の鎖」（`explainRowOnly`/
 * `explainValueDiff`。declared・synthetic_excluded・lod_imputation を統合）を
 * 試し、それで説明しきれなければ day_split（rain 系のみ）・
 * unit_label_registry（label_diff のみ）・float_rounding の順にフォールバックする
 * （設計書 §5.2 の順序のうち、鎖に統合した3規則の相対位置はそのまま
 * 「最優先」を保ち、day_split・unit_label_registry・float_rounding は今の
 * 位置づけのまま——`docs/plans/V2_SERVING_PR2.md` §1・§3）。
 */
export function classifyDiff(diff: RowDiff, ctx: ClassifyContext): Classification {
  const biota = classifyBiota(diff, ctx);
  if (biota) return biota;

  if (diff.kind === "row_only_in_v1" || diff.kind === "row_only_in_v2") {
    const chain = explainRowOnly(diff, ctx);
    if (chain.rules.size > 0) return chain;
    if (classifyDaySplit(diff, ctx)) return { rules: new Set(["day_split"]), declaredMatches: chain.declaredMatches };
    return chain;
  }

  if (diff.kind === "value_diff") {
    const chain = explainValueDiff(diff, ctx);
    if (chain.rules.size > 0) return chain;
    if (classifyDaySplit(diff, ctx)) return { rules: new Set(["day_split"]), declaredMatches: chain.declaredMatches };
    if (classifyFloatRounding(diff, ctx)) return { rules: new Set(["float_rounding"]), declaredMatches: chain.declaredMatches };
    return chain;
  }

  // label_diff: unit_label_registry だけが対象（宣言・synthetic・lod は数値列専用）。
  if (classifyUnitLabelRegistry(diff, ctx)) return { rules: new Set(["unit_label_registry"]), declaredMatches: [] };
  return emptyClassification();
}

export type { QueryDef };
