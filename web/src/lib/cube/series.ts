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
 * `b05_project_v1.py` の `_AKEY_EXPR` と同じ連結順・NULL の扱い
 * （`variable_id || '|' || COALESCE(value_grain,'') || '|' || COALESCE(obs_stat,'') || '|' ||
 * COALESCE(unit_id,'')`）。テスト（`series.test.ts`）で b05 と同じ文字列になることを固定する。
 */
export function seriesKeyString(k: SeriesKey): string {
  return `${k.variableId}|${norm(k.valueGrain)}|${norm(k.obsStat)}|${norm(k.unitId)}`;
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
  /** この組に登録されている出典（`variable_alias.source_id`）の一覧。NULL は出典未記録＝合成。 */
  sourceIds: (string | null)[];
  /** この組に登録されている出典表記（`variable_alias.alias`）の一覧（重複なし）。 */
  aliases: string[];
}

interface TupleGroup {
  key: SeriesKey;
  dataset: string | null;
  sourceIds: (string | null)[];
  aliases: string[];
}

const tupleGroups = new Map<string, TupleGroup>();

/**
 * b05 の T4 不変条件（「同じ (variable_id, grain, stat, unit_id) が measurements と
 * sensor_timeseries の両方の alias に現れていない」）を守るのはこの2つの dataset の
 * 組み合わせだけ（`scripts/b05_project_v1.py` docstring 参照）。土地利用（P-1b、
 * `nlni_l03b_landuse_by_watershed@2006`/`@2016` のような年版つき dataset）は、
 * 同じ日本語区分名が年をまたいで同じ variable_id を共有する設計（P-1b オーナー決定2）
 * のため、意図的に同じ組が複数の dataset にまたがる。ここでは範囲外として無視する
 * （PR-1 の測定値系スコープは土地利用を含まない——design §1.1）。
 */
const T4_GUARDED_DATASETS = new Set(["measurements", "sensor_timeseries"]);

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
    g = { key, dataset: a.dataset, sourceIds: [], aliases: [] };
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
  g.sourceIds.push(a.sourceId);
  if (!g.aliases.includes(a.alias)) g.aliases.push(a.alias);
}

function toSeriesInfo(g: TupleGroup): SeriesInfo {
  return { ...g.key, dataset: norm(g.dataset), sourceIds: g.sourceIds, aliases: g.aliases };
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

export interface SeriesForVariableOpt {
  dataset?: string;
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
    if (mode === "representative") {
      if (!REPRESENTATIVE_OBS_STATS.includes(g.key.obsStat)) continue;
    } else if (Array.isArray(mode)) {
      if (g.key.obsStat === null || !mode.includes(g.key.obsStat)) continue;
    }
    // mode === "all" はフィルタなし
    out.push(toSeriesInfo(g));
  }
  return out;
}

/** 合成データの系列か（`sourceIds` に出典未記録＝NULL を含む）。 */
export function isSynthetic(s: SeriesInfo): boolean {
  return s.sourceIds.includes(null);
}

/**
 * `period_start`（`YYYY-01-01`/`YYYY-04-01`）からラベル年を取り出す。`fiscal_year` は
 * 年度の始まりの年（v1 と同じ。`docs/adr/0024-local-time-and-time-labels.md`——
 * 日時関数を使わず文字列切り出しで行う）。
 */
export function labelYear(periodStart: string): number {
  return Number.parseInt(periodStart.slice(0, 4), 10);
}
