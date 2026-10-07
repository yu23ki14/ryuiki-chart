/**
 * 系列（＝ v1 の alias 相当）。DB を読まない。`@/lib/registry/generated`（レジストリの
 * 生成物、`variable_alias`/`variable` の生テーブル）だけを見る（design §3.2）。
 *
 * 「系列」＝ `(variable_id, obs_stat, unit_id, value_grain)` の組。`observation_agg`
 * （キューブ）は `source_id`/`alias` を列として持たないため、同じ組に複数の
 * `(dataset, alias, source_id)` 行が対応することがある（例: `浮遊物質量 SS` は
 * 合成データ〔source_id NULL〕と `atsugi_river_water_quality` が同じ
 * `(variable_id, day, mean, unit_id)` 組を共有する）。この場合キューブのセル自体が
 * 両方の出典を区別せず既に混ざっている（`observation_agg` に `source_id` 列が無いため）。
 * `seriesForAlias`/`seriesForVariable` はこの「組」単位で `SeriesInfo` を返し、
 * `sourceIds`/`aliases` はその組に実際に登録されている出典・出典表記の一覧（メタ情報）
 * を持つだけで、`queryCells` は `SeriesKey`（組）でしか絞り込まない。
 *
 * 逆に言えば、ある組がどの `dataset` に属するかは一意でなければならない
 * （`scripts/b05_project_v1.py` の T4「同じ (variable_id, grain, stat, unit_id) が
 * measurements と sensor_timeseries の両方に現れない」不変条件と同じ性質）。
 * モジュール読み込み時にこれを検証し、破れていれば例外を投げる。
 */
import {
  GENERATED_VARIABLE_ALIASES,
  GENERATED_VARIABLES,
  type GeneratedVariableAlias,
} from "@/lib/registry/generated";

export type Grain = "day" | "month" | "year" | "fiscal_year";

export interface SeriesKey {
  variableId: string;
  obsStat: string | null;
  unitId: string | null;
  valueGrain: string;
}

function norm(s: string | null | undefined): string {
  return s ?? "";
}

/**
 * registry の dataset キー（`variable_alias.dataset`）。v1 の表名と字面が同じだが表の参照ではない
 * （web で字面を持つのはここ1か所。PR-4 §0-1）。
 */
export const MEASUREMENTS_DATASET = "measurements";
export const SENSOR_DATASET = "sensor_timeseries";

/**
 * `b05_project_v1.py` の `_AKEY_EXPR` と同じ連結順・NULL の扱い
 * （`variable_id || '|' || COALESCE(value_grain,'') || '|' || COALESCE(obs_stat,'') || '|' ||
 * COALESCE(unit_id,'')`）。テスト（`series.test.ts`）で b05 と同じ文字列になることを固定する。
 */
export function seriesKeyString(k: SeriesKey): string {
  return `${k.variableId}|${norm(k.valueGrain)}|${norm(k.obsStat)}|${norm(k.unitId)}`;
}

/** `observation_agg` の生行が共通して持つ、系列を組み立てるのに要る4列（DB 列名）。 */
export interface SeriesKeyRow {
  variable_id: string;
  obs_stat: string | null;
  unit_id: string | null;
  value_grain: string | null;
}

/**
 * DB 行（`variable_id`/`obs_stat`/`unit_id`/`value_grain` の生列）から `SeriesKey` を
 * 組み立てる（`observation.ts`/`catalog.ts` に5箇所あった同じ組み立てを1つにまとめる）。
 */
export function seriesKeyFromRow(r: SeriesKeyRow): SeriesKey {
  return { variableId: r.variable_id, obsStat: r.obs_stat, unitId: r.unit_id, valueGrain: r.value_grain ?? "" };
}

/**
 * SQL 側で `seriesKeyString` と同じ式を組み立てる（`json_each(?)` の値と等値 JOIN する側）。
 * `alias` は FROM 句のテーブルエイリアス（`observation_agg` を指す）。
 *
 * design のたたき台は `SERIES_KEY_SQL` という固定文字列（テーブルエイリアス `c` 決め打ち）
 * だったが、`assertD1Compatible` が ATTACH 時代の `c.`/`d.` 接頭辞を検出する規約
 * （design §3.1・db.ts 参照）と字面上ぶつかるため、エイリアスを引数で受ける関数にした
 * （観測キューブのエイリアスに `c`/`d` を使わない、というだけの表面上の変更で、
 * 連結順・COALESCE の規約自体は `_AKEY_EXPR` と同一）。
 */
export function seriesKeySql(alias: string): string {
  return (
    `${alias}.variable_id || '|' || COALESCE(${alias}.value_grain,'') || '|' || ` +
    `COALESCE(${alias}.obs_stat,'') || '|' || COALESCE(${alias}.unit_id,'')`
  );
}

export interface SeriesInfo extends SeriesKey {
  dataset: string;
  /** この組に登録されている出典（`variable_alias.source_id`）の一覧（重複なし）。NULL は出典未記録＝合成。 */
  sourceIds: (string | null)[];
  /** この組に登録されている出典表記（`variable_alias.alias`）の一覧（重複なし）。 */
  aliases: string[];
  /** 出典（NULL=合成は除く）と版（`variable_alias.edition_key`。土地利用の 2006/2016 など。版が無ければ null）の組（重複なし）。 */
  sourceRefs: SourceRef[];
}

/** 出典と、その系列が引く版。版つき出典（土地利用）は版ごとに別の取得日・ライセンスを持つ。 */
export interface SourceRef {
  sourceId: string;
  editionKey: string | null;
}

interface TupleGroup {
  key: SeriesKey;
  dataset: string | null;
  sourceIds: (string | null)[];
  aliases: string[];
  sourceRefs: SourceRef[];
}

const tupleGroups = new Map<string, TupleGroup>();

/**
 * b05 の T4 不変条件（「同じ (variable_id, grain, stat, unit_id) が measurements と
 * sensor_timeseries の両方の alias に現れていない」）を守るのはこの2つの dataset の
 * 組み合わせだけ（`scripts/b05_project_v1.py` docstring 参照）。土地利用（P-1b、
 * dataset は `nlni_l03b_landuse_by_watershed`、版は `variable_alias.edition_key` の 2006/2016。
 * Issue #39 Phase C で dataset の `@<年>` 後置を廃止した）は、同じ区分が年版をまたいで
 * 同じ variable_id を共有する設計（P-1b オーナー決定2）のため、意図的に同じ組へ版ごとの
 * 別 alias が付く。dataset は版を問わず 1 つで、T4 は measurements と sensor_timeseries
 * だけを見るので対象外（PR-1 の測定値系スコープは土地利用を含まない——design §1.1）。
 */
const T4_GUARDED_DATASETS = new Set([MEASUREMENTS_DATASET, SENSOR_DATASET]);

for (const a of GENERATED_VARIABLE_ALIASES as readonly GeneratedVariableAlias[]) {
  if (!a.variableId) continue;
  const key: SeriesKey = {
    variableId: a.variableId,
    obsStat: a.stat,
    unitId: a.unitId,
    valueGrain: a.grain ?? "",
  };
  const tk = seriesKeyString(key);
  let g = tupleGroups.get(tk);
  if (!g) {
    g = { key, dataset: a.dataset, sourceIds: [], aliases: [], sourceRefs: [] };
    tupleGroups.set(tk, g);
  } else if (
    norm(g.dataset) !== norm(a.dataset) &&
    T4_GUARDED_DATASETS.has(norm(g.dataset)) &&
    T4_GUARDED_DATASETS.has(norm(a.dataset))
  ) {
    throw new Error(
      `series.ts: 組 ${tk} が measurements と sensor_timeseries の両方にまたがっている` +
        `（'${g.dataset}' と '${a.dataset}'）。b05 の T4 不変条件が破れている。`,
    );
  }
  // 重複排除する（元の順序は保つ）: 同じ組に対応する alias が複数あり、それらが
  // 同じ出典（`source_id`）を指すことがある（例: `雪_最深 積雪`/`雪_最深積雪` は
  // 空白の有無が違うだけの2 alias で、どちらも jma_monthly_kanagawa。土地利用の
  // 2006/2016 年版（edition_key）も同じ `source_id` を共有する）。重複排除しないと
  // `envelope.ts` の `resolveProvenance`（`sourceIds` を1件ずつ数える）が同じ
  // 出典の n_rows を alias の本数ぶん水増ししてしまう（Issue #48 PR-1 code-review #2）。
  if (!g.sourceIds.includes(a.sourceId)) g.sourceIds.push(a.sourceId);
  if (!g.aliases.includes(a.alias)) g.aliases.push(a.alias);
  if (a.sourceId !== null && !g.sourceRefs.some((r) => r.sourceId === a.sourceId && r.editionKey === a.editionKey)) {
    g.sourceRefs.push({ sourceId: a.sourceId, editionKey: a.editionKey });
  }
}

function toSeriesInfo(g: TupleGroup): SeriesInfo {
  return { ...g.key, dataset: norm(g.dataset), sourceIds: g.sourceIds, aliases: g.aliases, sourceRefs: g.sourceRefs };
}

/** 逆引き（組 → SeriesInfo）。`b05` の T4 不変条件によりモジュール内で一意。 */
export function seriesInfo(k: SeriesKey): SeriesInfo | undefined {
  const g = tupleGroups.get(seriesKeyString(k));
  return g ? toSeriesInfo(g) : undefined;
}

/** v1 互換（アダプタ用）: `(dataset, alias)` が指す組の集合（1つとは限らない）。 */
export function seriesForAlias(dataset: string, alias: string): SeriesInfo[] {
  const out: SeriesInfo[] = [];
  for (const g of tupleGroups.values()) {
    if (norm(g.dataset) === dataset && g.aliases.includes(alias)) out.push(toSeriesInfo(g));
  }
  return out;
}

const REPRESENTATIVE_OBS_STATS: readonly (string | null)[] = [null, "mean", "point"];

/** `obsStat` が代表統計量（mean/point/NULL）かどうか。`catalog.ts` の
 *  `bundleVariableCatalog`（`stats` に非代表だけを集める。Issue #48 PR-2
 *  code-review #7）も同じ判定を使う。 */
export function isRepresentativeObsStat(obsStat: string | null): boolean {
  return REPRESENTATIVE_OBS_STATS.includes(obsStat);
}

export interface SeriesForVariableOpt {
  dataset?: string;
  /** この出典のどれかが登録されている組だけ（`variable_alias.source_id`。dataset は問わない）。 */
  sourceIds?: readonly string[];
  /** 既定 "representative"（`obsStat` が mean/point/NULL のものだけ）。 */
  obsStats?: "representative" | "all" | string[];
}

/** ある正準 variable_id に属する組の集合（alias 文字列をまたいで束ねる）。 */
export function seriesForVariable(variableId: string, opt?: SeriesForVariableOpt): SeriesInfo[] {
  const mode = opt?.obsStats ?? "representative";
  const out: SeriesInfo[] = [];
  for (const g of tupleGroups.values()) {
    if (g.key.variableId !== variableId) continue;
    if (opt?.dataset !== undefined && norm(g.dataset) !== opt.dataset) continue;
    if (opt?.sourceIds !== undefined && !g.sourceIds.some((id) => id !== null && opt.sourceIds!.includes(id))) continue;
    if (mode === "representative") {
      if (!isRepresentativeObsStat(g.key.obsStat)) continue;
    } else if (Array.isArray(mode)) {
      if (g.key.obsStat === null || !mode.includes(g.key.obsStat)) continue;
    }
    // mode === "all" はフィルタなし
    out.push(toSeriesInfo(g));
  }
  return out;
}

const DEFAULT_DATASET = MEASUREMENTS_DATASET;

/**
 * ある正準 variable_id の「代表系列」（PR-2 design §2.1・§0 決定4）。`seriesForVariable`
 * の薄い包みで、既定 `stat="representative"` は `obsStat ∈ {mean, point, NULL}` の組
 * （`seriesForVariable` の `obsStats: "representative"` と同じ）。`stat` に具体的な
 * `obsStat`（`"p75"`/`"p90"`/`"max"`/`"min"` 等）を渡すと、その `obsStat` の組だけに絞る
 * （D4: 非代表統計量を落とさず `stat` パラメータで選べるようにする）。
 *
 * **フォールバック**（design §9 危険3）: `stat="representative"`（既定）で該当する組が
 * 1つも無い variable（例: `land.max_subsidence` は唯一の alias が `obsStat="max"` で、
 * mean/point/NULL のどれにも当たらない）は、空配列を返す代わりに全系列
 * （`obsStats: "all"`）にフォールバックする——「代表系列が無いので何も表示されない」
 * という事故を避ける。
 */
export function representativeSeries(
  variableId: string,
  dataset: string = DEFAULT_DATASET,
  stat: "representative" | string = "representative",
): SeriesInfo[] {
  return pickSeries(variableId, { dataset }, stat);
}

/**
 * `representativeSeries` の出典指定版。dataset は問わず、`sourceIds` のどれかが登録されている組から選ぶ
 * （センサー系列・土地利用のように measurements 以外の dataset の出典を引くとき）。代表系列とフォールバックの規則は同じ。
 */
export function representativeSeriesForSources(
  variableId: string,
  sourceIds: readonly string[],
  stat: "representative" | string = "representative",
): SeriesInfo[] {
  return pickSeries(variableId, { sourceIds }, stat);
}

function pickSeries(variableId: string, base: Pick<SeriesForVariableOpt, "dataset" | "sourceIds">, stat: string): SeriesInfo[] {
  if (stat === "representative") {
    const rep = seriesForVariable(variableId, { ...base, obsStats: "representative" });
    if (rep.length > 0) return rep;
    return seriesForVariable(variableId, { ...base, obsStats: "all" });
  }
  return seriesForVariable(variableId, { ...base, obsStats: [stat] });
}

export interface BasisInfo {
  basis: "day" | "fiscal_year" | "year";
  /** この `basis` で表示できる粒度（`grain`）。「元データ」から決まる（design §2.1）。 */
  grains: Grain[];
}

/**
 * 系列の集合から「元データ」（`value_grain`）の基準（`basis`）と、そこから表示できる
 * `grain` の一覧を決める（v1 `kind`（daily/annual）の後継。design §2.1・§5）。
 *
 * `day` → 検体値（日次観測）が元データ。年（暦年、`input_grain='day'` で積み上げ）・
 * 月・日の3粒度で表示できる。`fiscal_year` → 年度集計値が元データ（日本の年度、
 * 4月始まり）。表示できるのは年度だけ。`year` → 暦年の集計値が元データ（例:
 * 地盤沈下。`input_grain='same'`）。表示できるのは年（暦年）だけ。
 *
 * `series` に複数の `valueGrain` が混ざっている場合（例: `representativeSeries` を
 * `basis` で絞る前の BOD は day/mean・day/point・fiscal_year/mean の3系列にまたがる）は、
 * 「もっとも粒度が細かい（データが多い）」優先順位 day > fiscal_year > year で
 * 代表の1つを選ぶ——`basis` を省略した呼び出し側（`observation.ts` の
 * `yearSeries`/`monthSeries`/`daySeries` 等）のデフォルト値を決めるためのもので、
 * 実際にどの系列を問い合わせに使うかは呼び出し側が `basis` で明示的に絞り込む。
 *
 * 空配列（該当する系列が1つも無い）は呼び出し側の誤り（存在しない variableId・
 * `stat` を渡した等）として例外にする——`null` を返して呼び出し側に握りつぶされる
 * より、ここで気づける方がよい。
 */
export function basisOf(series: readonly SeriesKey[]): BasisInfo {
  if (series.length === 0) {
    throw new Error("basisOf: series が空（該当する系列が無い）");
  }
  const valueGrains = new Set(series.map((s) => s.valueGrain));
  const basis: "day" | "fiscal_year" | "year" = valueGrains.has("day")
    ? "day"
    : valueGrains.has("fiscal_year")
      ? "fiscal_year"
      : "year";
  return { basis, grains: grainsForBasis(basis) };
}

/** `basis` から表示できる `grain` の一覧（`basisOf` と `catalog.ts` の summary 束ねが共有）。 */
export function grainsForBasis(basis: "day" | "fiscal_year" | "year"): Grain[] {
  return basis === "day" ? ["year", "month", "day"] : basis === "fiscal_year" ? ["fiscal_year"] : ["year"];
}

// `basisOfCell`（セルの性質＝grain/input_grain の組から basis を決める規則）は `cell-basis.ts` の1か所。
// クライアントコンポーネントからも使えるよう別ファイルに置き、ここから再エクスポートする。
export { basisOfCell } from "./cell-basis";

/**
 * `basis`（省略時は `basisOf` が選ぶ既定）から、年セルの問い合わせに使う単一の
 * `grain` と `inputGrain` を決める（`basisOfCell` の逆写像。Issue #48 PR-2 統合後
 * 修正A #1・#3）。`observation.ts` の `yearSeries`・`web/src/app/api/timeseries/route.ts`・
 * `web/src/lib/ai/tools.ts`・`web/src/app/page.tsx`（home）が共有する——旧
 * `seriesForBasis`/`inputGrainForBasis`/`cellGrainForBasis` の3重複箇所を統合した。
 *
 * `day`→(year, day)：検体値からの積み上げ。`fiscal_year`→(fiscal_year, same)：
 * 出典が直接報告した年度値（`input_grain=grain='fiscal_year'`）。`year`→(year, same)：
 * 出典が直接報告した暦年値（例: 地盤沈下。`input_grain=grain='year'`）。
 *
 * 呼び出し側は `series` に `representativeSeries()` の結果（全 `value_grain`）を
 * そのまま渡し、`basis` の絞り込みはこの関数が返す `grain`/`inputGrain` を
 * `CellSpec` に渡すことでセル側（`observation_agg` 自身の `grain`/`input_grain` 列）
 * に行わせる——系列を `value_grain` で事前に絞り込まない。
 */
export function yearCellFilterForBasis(basis: "day" | "fiscal_year" | "year"): { grain: Grain; inputGrain: "day" | "same" } {
  if (basis === "fiscal_year") return { grain: "fiscal_year", inputGrain: "same" };
  if (basis === "year") return { grain: "year", inputGrain: "same" };
  return { grain: "year", inputGrain: "day" };
}

const variableById = new Map(GENERATED_VARIABLES.map((v) => [v.variableId, v]));

/**
 * `SeriesInfo` に `variable.theme` を足す（`caveats.ts` の `SeriesFacetInput` 用）。
 * `variable` の生テーブル（`generated.ts`、サーバ専用）を見るヘルパをこちらに置き、
 * `caveats.ts` をクライアント安全なまま保つ（同ファイルの docstring 参照）。
 */
export function withTheme(series: SeriesInfo): SeriesInfo & { theme: string | null } {
  return { ...series, theme: variableById.get(series.variableId)?.theme ?? null };
}

/**
 * `period_start`（`YYYY-01-01`/`YYYY-04-01`）からラベル年を取り出す。`fiscal_year` は
 * 年度の始まりの年（v1 と同じ。`docs/adr/0024-local-time-and-time-labels.md`——
 * 日時関数を使わず文字列切り出しで行う）。
 */
export function labelYear(periodStart: string): number {
  return Number.parseInt(periodStart.slice(0, 4), 10);
}
