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
  /** `db: v1` は derived.sqlite/ryuiki.sqlite に対して実行し最初の列を値の列にする。
   *  `db: registry` は `registry.sqlite` に対して実行する（`variable_id` ドメイン
   *  ——v1 db は variable_id を知らないため）。 */
  sql?: string;
  db?: "v1" | "registry";
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
  /** 廃止した列（v1 にあって v2 に無い。比べず、レポートに1行出す。PR-4 D2）。 */
  retired?: string[];
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

/**
 * 同じキー列の値を持つ行が複数ありうる問い合わせ（例: `redlist_species`）のために、行に連番 `ord`
 * を足す。キー列が同じ行の中では「全列の JSON の昇順」で番号を振るので、v1・v2 に同じ行の集合が
 * あれば並び順に依らず同じ `ord` が付く（`rowsByKey` の重複キー例外を避ける。診断の正確さのため
 * 片方を捨てない）。
 */
export function withOrdinal<T extends RawRow>(rows: readonly T[], keyCols: readonly string[]): (T & { ord: number })[] {
  const decorated = rows.map((r) => ({ r, key: JSON.stringify(keyCols.map((c) => r[c] ?? null)), all: JSON.stringify(r) }));
  decorated.sort((a, b) => (a.key < b.key ? -1 : a.key > b.key ? 1 : a.all < b.all ? -1 : a.all > b.all ? 1 : 0));
  const seen = new Map<string, number>();
  return decorated.map(({ r, key }) => {
    const ord = seen.get(key) ?? 0;
    seen.set(key, ord + 1);
    return { ...r, ord };
  });
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

/** `redlist_group` ドメインの '' は「全分類群」（group を渡さない）。 */
export function redlistGroupParam(v: ScalarParam): string | undefined {
  return v === "" ? undefined : String(v);
}
