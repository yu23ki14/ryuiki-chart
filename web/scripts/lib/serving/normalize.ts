/**
 * v2 アダプタが返す生の行を、スナップショット・指紋に載せる共通の形（`NormRow`）に正規化する。
 * DB を読まない・SQL を書かない、ただの整形関数。`serving_queries.yaml` の型もここに置く。
 */

/** クエリのパラメータ・行キーに使うスカラー値。 */
export type ScalarParam = string | number;

export interface NormRow {
  /** `serving_queries.yaml` の `compare.key` で指定した列を、その順序のまま並べたもの。 */
  key: ScalarParam[];
  /** `compare.numeric` の列。無い/NULL は `null`。 */
  numeric: Record<string, number | null>;
  /** `compare.label` の列。無い/NULL は `null`。 */
  label: Record<string, string | null>;
}

export interface QueryRun {
  id: string;
  params: Record<string, ScalarParam>;
  rows: NormRow[];
}

/** 1件の生行（アダプタが DB から受け取った素の JS オブジェクト）。 */
export type RawRow = Record<string, unknown>;

function toScalarParam(v: unknown): ScalarParam {
  if (typeof v === "number" || typeof v === "string") return v;
  if (v === null || v === undefined) return "";
  return String(v);
}

function toNumberOrNull(v: unknown): number | null {
  if (v === null || v === undefined) return null;
  if (typeof v === "number") return v;
  if (typeof v === "string" && v.trim() !== "" && !Number.isNaN(Number(v))) return Number(v);
  return null;
}

function toStringOrNull(v: unknown): string | null {
  if (v === null || v === undefined) return null;
  return String(v);
}

/**
 * 生の行の配列を `NormRow[]` に変換する。`keyCols`/`numericCols`/`labelCols` は
 * `serving_queries.yaml` の `compare.key`/`compare.numeric`/`compare.label` に対応する
 * （列名は v1/v2 どちらのアダプタも同じ名前に揃えてから渡すこと。unit のような列名は
 * v1 側がそのまま `unit`、v2 側は `symbol(cell.unitId)` を `unit` という名前に付け替えて渡す）。
 */
export function toNormRows(
  rows: readonly RawRow[],
  keyCols: readonly string[],
  numericCols: readonly string[],
  labelCols: readonly string[],
): NormRow[] {
  return rows.map((row) => ({
    key: keyCols.map((c) => toScalarParam(row[c])),
    numeric: Object.fromEntries(numericCols.map((c) => [c, toNumberOrNull(row[c])])),
    label: Object.fromEntries(labelCols.map((c) => [c, toStringOrNull(row[c])])),
  }));
}

/** `serving_queries.yaml` の `compare:` ブロック。 */
export interface CompareSpec {
  key: string[];
  numeric: string[];
  label: string[];
}

/** `serving_queries.yaml` の `domains:` の1エントリ。 */
export interface DomainDef {
  /** `sql` を流す DB の名前（`v2`/`registry`/`ryuiki`/`cells`）。executor はこの4つを ATTACH した
   *  1本の接続（`sqliteCubeDb`）で流す（表名は4つで重ならないので非修飾で書く）。`values` のときは不要。 */
  db?: "v2" | "registry" | "ryuiki" | "cells";
  /** 実在する組だけを返す SQL。結果の列を `columns` の順に読む（`columns` が無ければ最初の列だけ）。 */
  sql?: string;
  /** 複数列を1つのドメイン（1つの軸）にするときの列名。問い合わせの `params.<name>.column`（省略時は param 名）が引く。 */
  columns?: string[];
  /** リテラルの列挙（`sql` の代わり）。 */
  values?: ScalarParam[];
}

/** 問い合わせごとの run 数の上限（snapshot / fingerprint）。 */
export interface MaxRuns {
  snapshot?: number;
  fingerprint?: number;
}

/** `serving_queries.yaml` の `queries:` の1エントリ。 */
export interface QueryDef {
  id: string;
  /** パラメータ名 -> ドメイン名（複数列ドメインなら列名 `column`）。同じドメインを引く param は1つの軸（組）になる。 */
  params: Record<string, { domain: string; column?: string }>;
  compare: CompareSpec;
  /** 未指定は mode の既定（snapshot 12 / fingerprint 60）。 */
  maxRuns?: MaxRuns;
  /** 空が正常な問い合わせ（空振り検査の対象外）。理由を YAML のコメントに書く。 */
  allowEmpty?: boolean;
}

export interface ServingQueriesConfig {
  version: number;
  domains: Record<string, DomainDef>;
  queries: QueryDef[];
}

/** `species_share_trend` の期間 A/B（`<aFrom>-<aTo>:<bFrom>-<bTo>`。`serving_queries.yaml` の `trend_periods`）。 */
export function parseTrendPeriods(v: ScalarParam): [[number, number], [number, number]] {
  const m = /^(\d{4})-(\d{4}):(\d{4})-(\d{4})$/.exec(String(v));
  if (!m) throw new Error(`periods の形が不正: ${String(v)}`);
  return [
    [Number(m[1]), Number(m[2])],
    [Number(m[3]), Number(m[4])],
  ];
}
