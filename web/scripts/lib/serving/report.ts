/**
 * `reports/serving_switch_diff.md`（人向け）と `.json`（機械可読）を組み立てる。
 * DB を読まない・触らない、集計済みの値を受け取って文字列にするだけの層
 * （`report.test.ts` がスナップショットなしで組み立て結果の形を確認する）。
 */
import type { ScalarParam } from "./normalize";
import type { KnownRule } from "./classify";

export interface ReportHeader {
  gitHead: string;
  v2PipelineFingerprint: string | null;
  registryInputFingerprint: string | null;
  sqliteVersion: string;
  imputation: string;
  expand: string;
  v1Source: string;
  generatedAt: string;
  /** 全問い合わせを回すのにかかった時間（ミリ秒）。 */
  elapsedMs: number;
}

export interface QueryStats {
  id: string;
  runs: number;
  rowsV1: number;
  rowsV2: number;
  matched: number;
  declared: number;
  day_split: number;
  synthetic_excluded: number;
  lod_imputation: number;
  unit_label_registry: number;
  float_rounding: number;
  // 生物系の5規則（PR-3b。1 diff = 1 キーの動きなので、これが規則ごとの `moved`〔キー数〕になる）。
  watershed_memo: number;
  species_n_definition: number;
  month_cell_membership: number;
  vernacular_label_rule: number;
  undated_excluded: number;
  unexplained: number;
}

export function emptyQueryStats(id: string): QueryStats {
  return {
    id,
    runs: 0,
    rowsV1: 0,
    rowsV2: 0,
    matched: 0,
    declared: 0,
    day_split: 0,
    synthetic_excluded: 0,
    lod_imputation: 0,
    unit_label_registry: 0,
    float_rounding: 0,
    watershed_memo: 0,
    species_n_definition: 0,
    month_cell_membership: 0,
    vernacular_label_rule: 0,
    undated_excluded: 0,
    unexplained: 0,
  };
}

/**
 * 1つの diff の分類結果（`classify.ts` の `Classification.rules`、説明の鎖が
 * 使った規則の集合）を集計へ足す。空集合なら unexplained を1増やす。空でなければ
 * **集合の各要素について1回ずつ**その列を増やす——1つの diff が複数の段
 * （例: declared＋synthetic_excluded＋lod_imputation）にまたがって説明された
 * 場合、この1回の呼び出しで複数の列が同時に増える。したがって
 * `declared+day_split+…+unexplained` の合計は診断の総数（`matched` を除く
 * 行数）と必ずしも一致しない——1行が複数系統に数えられるのは意図した仕様
 * （`docs/plans/V2_SERVING_PR2.md` §1・§3）。
 */
export function addClassification(stats: QueryStats, rules: ReadonlySet<KnownRule>): void {
  if (rules.size === 0) {
    stats.unexplained += 1;
    return;
  }
  for (const rule of rules) stats[rule] += 1;
}

export interface UnexplainedSample {
  queryId: string;
  params: Record<string, ScalarParam>;
  kind: string;
  key: ScalarParam[];
  columns: string[];
}

export interface RottenDeclaration {
  table: string;
  key: ScalarParam[];
  kind: string;
}

export interface MutationRunResult {
  name: string;
  unexplained: number;
  /** 変異が意図どおり「必ず落ちる」ことを確認できたか。 */
  caughtAsExpected: boolean;
  note?: string;
}

export interface ReportInput {
  header: ReportHeader;
  stats: QueryStats[];
  /**
   * `vernacular_label_rule` が説明した表示名の動きの件数（問い合わせ id → カテゴリ（`日本語→英名等` 等）→ 件数）。
   * 設計書 §3.4-2「`label_moved`（カテゴリ別）をレポートに出す」。無ければ省略。
   */
  labelMoved?: Record<string, Record<string, number>>;
  unexplainedSamples: UnexplainedSample[];
  rottenDeclarations: RottenDeclaration[];
  mutationResults?: MutationRunResult[];
}

// `as const` で6つのリテラルの union に絞る（`(keyof QueryStats)[]` という広い型に
// すると、`total[c] += s[c]` の `c` が `id`（string）まで含む union になり、
// 数値の加算が `never` に落ちて型検査が通らない）。
const KNOWN_RULE_COLUMNS = [
  "declared",
  "day_split",
  "synthetic_excluded",
  "lod_imputation",
  "unit_label_registry",
  "float_rounding",
  "watershed_memo",
  "species_n_definition",
  "month_cell_membership",
  "vernacular_label_rule",
  "undated_excluded",
] as const satisfies readonly (keyof QueryStats)[];

function mdEscape(v: unknown): string {
  return String(v).replace(/\|/g, "\\|");
}

/** Markdown の表を1つ組み立てる（`report.ts` に4回複製されていた見出し行・区切り行・
 *  データ行の組み立てを1つにまとめる）。 */
function mdTable(header: readonly string[], rows: readonly (readonly unknown[])[]): string {
  const lines = [
    `| ${header.join(" | ")} |`,
    `| ${header.map(() => "---").join(" | ")} |`,
    ...rows.map((row) => `| ${row.map(mdEscape).join(" | ")} |`),
  ];
  return lines.join("\n");
}

function statsTableMd(stats: QueryStats[]): string {
  const header = ["id", "runs", "rows_v1", "rows_v2", "matched", ...KNOWN_RULE_COLUMNS, "unexplained"];
  const rows = stats.map((s) => [s.id, s.runs, s.rowsV1, s.rowsV2, s.matched, ...KNOWN_RULE_COLUMNS.map((c) => s[c]), s.unexplained]);
  return mdTable(header, rows);
}

/** 生物系5規則の `moved`（キー数）。受け入れ表 §3.4-2 がこの表の値を見る。 */
const BIOTA_RULE_COLUMNS = [
  "watershed_memo",
  "species_n_definition",
  "month_cell_membership",
  "vernacular_label_rule",
  "undated_excluded",
] as const satisfies readonly (keyof QueryStats)[];

function biotaMovedMd(stats: QueryStats[]): string {
  const rows: (readonly unknown[])[] = [];
  for (const s of stats) {
    for (const rule of BIOTA_RULE_COLUMNS) {
      if (s[rule] > 0) rows.push([rule, s.id, s[rule]]);
    }
  }
  if (!rows.length) return "（無し）";
  return mdTable(["rule", "query", "moved（キー数）"], rows);
}

function labelMovedMd(labelMoved: Record<string, Record<string, number>> | undefined): string {
  const rows: (readonly unknown[])[] = [];
  for (const [id, cats] of Object.entries(labelMoved ?? {})) {
    for (const [cat, n] of Object.entries(cats).sort((a, b) => b[1] - a[1])) rows.push([id, cat, n]);
  }
  if (!rows.length) return "（無し）";
  return mdTable(["query", "label_moved（v1→v2 の文字種）", "件数"], rows);
}

function totalsOf(stats: QueryStats[]): QueryStats {
  const total = emptyQueryStats("total");
  for (const s of stats) {
    total.runs += s.runs;
    total.rowsV1 += s.rowsV1;
    total.rowsV2 += s.rowsV2;
    total.matched += s.matched;
    total.unexplained += s.unexplained;
    for (const c of KNOWN_RULE_COLUMNS) total[c] += s[c];
  }
  return total;
}

function unexplainedSampleMd(samples: UnexplainedSample[]): string {
  if (!samples.length) return "（無し）";
  const header = ["query", "params", "kind", "key", "columns"];
  const rows = samples
    .slice(0, 20)
    .map((s) => [s.queryId, JSON.stringify(s.params), s.kind, JSON.stringify(s.key), s.columns.join(",")]);
  return mdTable(header, rows);
}

function rottenMd(rotten: RottenDeclaration[]): string {
  if (!rotten.length) return "（無し。宣言済み差分は全て少なくとも1回は使われた）";
  const header = ["table", "key", "kind"];
  const rows = rotten.map((r) => [r.table, JSON.stringify(r.key), r.kind]);
  return mdTable(header, rows);
}

function mutationsMd(results: MutationRunResult[] | undefined): string {
  if (!results || !results.length) return "";
  const header = ["mutation", "unexplained", "検出できたか"];
  const rows = results.map((r) => [r.name, r.unexplained, r.caughtAsExpected ? "OK" : "NG" + (r.note ? `（${r.note}）` : "")]);
  return ["", "## 変異テスト（`--mutate`）", "", mdTable(header, rows)].join("\n");
}

export function buildReportMarkdown(input: ReportInput): string {
  const { header, stats } = input;
  const total = totalsOf(stats);
  return [
    "# serving-diff レポート",
    "",
    `- git HEAD: \`${header.gitHead}\``,
    `- v2 pipeline_fingerprint: \`${header.v2PipelineFingerprint ?? "(v1-only)"}\``,
    `- registry_build.input_fingerprint: \`${header.registryInputFingerprint ?? "(v1-only)"}\``,
    `- better-sqlite3 の SQLite 版: \`${header.sqliteVersion}\``,
    `- imputation: \`${header.imputation}\` / expand: \`${header.expand}\` / v1-source: \`${header.v1Source}\``,
    `- 生成日時: ${header.generatedAt}`,
    `- 所要時間: ${(header.elapsedMs / 1000).toFixed(1)}s`,
    "",
    "## 問い合わせごとの集計",
    "",
    statsTableMd(stats),
    "",
    `合計: runs=${total.runs} rows_v1=${total.rowsV1} rows_v2=${total.rowsV2} matched=${total.matched} unexplained=${total.unexplained}`,
    header.imputation === "lod"
      ? `lod_moved（zero→lod で値が動いたと確認できたキー数の合計。上表の \`lod_imputation\` 列と同じ）: ${total.lod_imputation}`
      : "",
    "",
    "## 生物系の規則ごとの moved（PR-3b）",
    "",
    biotaMovedMd(stats),
    "",
    "### 表示名の動き（`vernacular_label_rule` の label_moved）",
    "",
    labelMovedMd(input.labelMoved),
    "",
    "## 宣言済み差分の腐り（対象問い合わせが1件も対応しなかった宣言）",
    "",
    rottenMd(input.rottenDeclarations),
    "",
    "## unexplained の先頭20件",
    "",
    unexplainedSampleMd(input.unexplainedSamples),
    mutationsMd(input.mutationResults),
    "",
  ].join("\n");
}

export function buildReportJson(input: ReportInput): unknown {
  return {
    header: input.header,
    stats: input.stats,
    totals: totalsOf(input.stats),
    labelMoved: input.labelMoved ?? {},
    unexplainedSamples: input.unexplainedSamples,
    rottenDeclarations: input.rottenDeclarations,
    mutationResults: input.mutationResults ?? [],
  };
}
