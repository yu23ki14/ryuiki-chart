/**
 * v1/v2 それぞれのアダプタが返す生の行を、比較できる共通の形に正規化する。
 * 設計書（Issue #48 PR-1 設計、§4.2「共通の行形」）の `NormRow`/`QueryRun` をそのまま実装する。
 *
 * どちらのアダプタも DB を読まない・SQL を書かない、ただの整形関数。
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

/** `NormRow.key` を Map のキーに使うための文字列化。 */
export function keyString(key: readonly ScalarParam[]): string {
  return JSON.stringify(key);
}

/** `serving_queries.yaml` の `compare:` ブロック。 */
export interface CompareSpec {
  key: string[];
  numeric: string[];
  label: string[];
}

/** `serving_queries.yaml` の `domains:` の1エントリ。 */
export interface DomainDef {
  /** v1 db に対して実行し、最初の列を値の列にする（`db: v1` のとき必須）。 */
  sql?: string;
  db?: "v1";
  /** リテラルの列挙（`sql` の代わり）。 */
  values?: ScalarParam[];
}

/** `serving_queries.yaml` の `queries:` の1エントリ。 */
export interface QueryDef {
  id: string;
  /** 宣言済み差分（`expected_diffs.yaml`）の照合先。無ければ `null`。 */
  v1Table: string | null;
  /** パラメータ名 -> ドメイン名。`only_existing` がある問い合わせでは無視してよい
   *  （enumerateParams は only_existing を優先する）が、型・ドキュメントとしては残す。 */
  params: Record<string, { domain: string }>;
  /** パラメータの組をドメインの直積ではなく、この SQL（v1 db）の結果行から直接取る。 */
  onlyExisting?: string;
  compare: CompareSpec;
  /** 既定は完全一致（許容差 0）。ここに載っている数値列だけ相対許容差を許す。 */
  tolerance?: Record<string, number>;
  /** この問い合わせに当てはまりうる既知の系統（`classify.ts` の `KnownRule`）。 */
  known: string[];
}

export interface ServingQueriesConfig {
  version: number;
  domains: Record<string, DomainDef>;
  queries: QueryDef[];
}

export function rowsByKey(rows: readonly NormRow[]): Map<string, NormRow> {
  const m = new Map<string, NormRow>();
  for (const r of rows) {
    // 同じキーの行が2つあれば、それ自体がアダプタ側のバグ（GROUP BY の取りこぼし等）。
    // 静かに片方を捨てると診断が壊れるので、ここで気づけるように投げる。
    const k = keyString(r.key);
    if (m.has(k)) {
      throw new Error(`重複した行キー: ${k}`);
    }
    m.set(k, r);
  }
  return m;
}
