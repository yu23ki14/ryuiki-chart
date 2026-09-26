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
  rain_div10: number;
  day_split: number;
  synthetic_excluded: number;
  unit_label_registry: number;
  float_rounding: number;
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
    rain_div10: 0,
    day_split: 0,
    synthetic_excluded: 0,
    unit_label_registry: 0,
    float_rounding: 0,
    unexplained: 0,
  };
}

export function addClassification(stats: QueryStats, rule: KnownRule | "unexplained"): void {
  if (rule === "unexplained") {
    stats.unexplained += 1;
    return;
  }
  stats[rule] += 1;
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
  unexplainedSamples: UnexplainedSample[];
  rottenDeclarations: RottenDeclaration[];
  mutationResults?: MutationRunResult[];
}

// `as const` で6つのリテラルの union に絞る（`(keyof QueryStats)[]` という広い型に
// すると、`total[c] += s[c]` の `c` が `id`（string）まで含む union になり、
// 数値の加算が `never` に落ちて型検査が通らない）。
const KNOWN_RULE_COLUMNS = [
  "declared",
  "rain_div10",
  "day_split",
  "synthetic_excluded",
  "unit_label_registry",
  "float_rounding",
] as const satisfies readonly (keyof QueryStats)[];

function mdEscape(v: unknown): string {
  return String(v).replace(/\|/g, "\\|");
}

function statsTableMd(stats: QueryStats[]): string {
  const header = ["id", "runs", "rows_v1", "rows_v2", "matched", ...KNOWN_RULE_COLUMNS, "unexplained"];
  const lines = [
    `| ${header.join(" | ")} |`,
    `| ${header.map(() => "---").join(" | ")} |`,
    ...stats.map((s) => {
      const row = [s.id, s.runs, s.rowsV1, s.rowsV2, s.matched, ...KNOWN_RULE_COLUMNS.map((c) => s[c]), s.unexplained];
      return `| ${row.map(mdEscape).join(" | ")} |`;
    }),
  ];
  return lines.join("\n");
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
  const lines = [
    `| ${header.join(" | ")} |`,
    `| ${header.map(() => "---").join(" | ")} |`,
    ...samples
      .slice(0, 20)
      .map((s) =>
        `| ${[s.queryId, JSON.stringify(s.params), s.kind, JSON.stringify(s.key), s.columns.join(",")]
          .map(mdEscape)
          .join(" | ")} |`,
      ),
  ];
  return lines.join("\n");
}

function rottenMd(rotten: RottenDeclaration[]): string {
  if (!rotten.length) return "（無し。宣言済み差分は全て少なくとも1回は使われた）";
  const header = ["table", "key", "kind"];
  const lines = [
    `| ${header.join(" | ")} |`,
    `| ${header.map(() => "---").join(" | ")} |`,
    ...rotten.map((r) => `| ${[r.table, JSON.stringify(r.key), r.kind].map(mdEscape).join(" | ")} |`),
  ];
  return lines.join("\n");
}

function mutationsMd(results: MutationRunResult[] | undefined): string {
  if (!results || !results.length) return "";
  const header = ["mutation", "unexplained", "検出できたか"];
  const lines = [
    "",
    "## 変異テスト（`--mutate`）",
    "",
    `| ${header.join(" | ")} |`,
    `| ${header.map(() => "---").join(" | ")} |`,
    ...results.map(
      (r) =>
        `| ${[r.name, r.unexplained, r.caughtAsExpected ? "OK" : "NG" + (r.note ? `（${r.note}）` : "")]
          .map(mdEscape)
          .join(" | ")} |`,
    ),
  ];
  return lines.join("\n");
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
    unexplainedSamples: input.unexplainedSamples,
    rottenDeclarations: input.rottenDeclarations,
    mutationResults: input.mutationResults ?? [],
  };
}
