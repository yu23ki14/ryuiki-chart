#!/usr/bin/env -S node --import ./scripts/lib/serving/register-aliases.mjs
/**
 * serving-diff: v1（`derived.sqlite`/`v1_projection.sqlite`）と v2（`@/lib/cube`
 * 経由の `v2.sqlite`＋`registry.sqlite`＋`ryuiki.sqlite`）を、`serving_queries.yaml`
 * に列挙した測定値系の問い合わせで突き合わせるツール。
 *
 * 設計・経緯: Issue #48 PR-1 設計書（1c: serving-diff）。詳細は
 * `docs/plans/V2_SERVING_PR1.md`（1b がコミット）を参照。
 *
 *   cd web
 *   pnpm run serving:diff [--v1-only] [--imputation zero|lod] [--expand all|snapshot]
 *     [--only <id,...>] [--mutate <name,...>] [--v1-source derived|v1_projection]
 *     [--pretend-synthetic-excluded] [--out reports/serving_switch_diff.md]
 *
 * 実行のしかた（tsx を直接使うとき。package.json の `serving:diff` もこれと同じ）:
 *   npx tsx --import ./scripts/lib/serving/register-aliases.mjs ./scripts/serving-diff.mts
 *
 * v2 アダプタ（`./lib/serving/adapters-v2.ts`）は `@/lib/cube`（Issue #48 PR-1
 * 「1a 問い合わせ層」）に依存する。1a が無い/未着手の間は `--v1-only` でだけ動く
 * （v2 側の import は動的 import で遅延させてあるので、`--v1-only` のときは
 * `@/lib/cube` が存在しなくても serving-diff 自体は起動できる）。
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";
import { execFileSync, spawnSync } from "node:child_process";
import { load as loadYaml } from "js-yaml";
import Database from "better-sqlite3";

import {
  rowsByKey,
  type CompareSpec,
  type DomainDef,
  type NormRow,
  type QueryDef,
  type ScalarParam,
  type ServingQueriesConfig,
} from "./lib/serving/normalize";
import { enumerateParams, runV1Query, snapshotSubset } from "./lib/serving/adapters-v1";
import {
  compareRuns,
  classifyDiff,
  computeRainRecompute,
  declaredMatchTag,
  findRottenDeclarations,
  type ClassifyContext,
  type DeclaredKeyBuilder,
  type DeclaredLookup,
  type ExpectedDiffs,
  type KnownRule,
  type RainL2Row,
  type RainRecompute,
  type RowDiff,
} from "./lib/serving/classify";
import {
  ALL_MUTATION_NAMES,
  applyClassifyMutation,
  applyRowMutation,
  isClassifyMutation,
  isRowMutation,
  rowMutationAppliesTo,
  type ClassifyMutationOptions,
} from "./lib/serving/mutations";
import {
  addClassification,
  buildReportJson,
  buildReportMarkdown,
  emptyQueryStats,
  type MutationRunResult,
  type QueryStats,
  type ReportHeader,
  type RottenDeclaration,
  type UnexplainedSample,
} from "./lib/serving/report";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const WEB_ROOT = path.resolve(HERE, "..");
const REPO_ROOT = path.resolve(WEB_ROOT, "..");

/* ------------------------------------------------------------------ */
/* CLI 引数                                                             */
/* ------------------------------------------------------------------ */

const { values: argv } = parseArgs({
  options: {
    "v1-only": { type: "boolean", default: false },
    imputation: { type: "string", default: "zero" },
    expand: { type: "string", default: "all" },
    only: { type: "string" },
    mutate: { type: "string" },
    "v1-source": { type: "string", default: "derived" },
    "pretend-synthetic-excluded": { type: "boolean", default: false },
    out: { type: "string", default: "reports/serving_switch_diff.md" },
  },
});

const V1_ONLY = argv["v1-only"] === true;
const IMPUTATION = argv.imputation as string;
const EXPAND = (argv.expand as string) === "snapshot" ? "snapshot" : "all";
const ONLY_IDS = argv.only ? new Set(String(argv.only).split(",").map((s) => s.trim())) : null;
const MUTATE_NAMES = argv.mutate ? String(argv.mutate).split(",").map((s) => s.trim()) : [];
const V1_SOURCE = (argv["v1-source"] as string) === "v1_projection" ? "v1_projection" : "derived";
const PRETEND_SYNTHETIC_EXCLUDED = argv["pretend-synthetic-excluded"] === true;
const OUT_MD = path.resolve(WEB_ROOT, String(argv.out));
const OUT_JSON = OUT_MD.replace(/\.md$/, ".json");

for (const name of MUTATE_NAMES) {
  if (!ALL_MUTATION_NAMES.includes(name)) {
    console.error(`未知の --mutate 名: ${name}（既知: ${ALL_MUTATION_NAMES.join(", ")}）`);
    process.exit(1);
  }
}

/* ------------------------------------------------------------------ */
/* v1 側のパス（--v1-source v1_projection は derived.sqlite の代わりに
   b05 の射影 v1_projection.sqlite を「d」スキーマとして ATTACH する。診断用。） */
/* ------------------------------------------------------------------ */

const DB_DIR = process.env.RYUIKI_DB_DIR ?? path.join(REPO_ROOT, "data", "db");
if (V1_SOURCE === "v1_projection") {
  // v1-db-shim.ts は `process.env.RYUIKI_V1_DERIVED_DB` を呼び出しのたびに読む
  // （関数呼び出しでの設定にしない理由は v1-db-shim.ts 冒頭のコメント参照:
  // queries.ts からは CJS require() 経由、ここからは ESM import 経由でこの
  // ファイルが2重にロードされるため、module-level な設定関数は片方にしか効かない）。
  // 実際に db を開く（＝最初のクエリを実行する）より前でありさえすればよい。
  process.env.RYUIKI_V1_DERIVED_DB = path.join(DB_DIR, "v1_projection.sqlite");
}

const V2_DB_PATH = path.join(DB_DIR, "v2.sqlite");
const REGISTRY_DB_PATH = process.env.RYUIKI_REGISTRY_DB ?? path.join(DB_DIR, "registry.sqlite");
const RYUIKI_DB_PATH = path.join(DB_DIR, "ryuiki.sqlite");

/* ------------------------------------------------------------------ */
/* v2 の鮮度チェック（起動時に拒否）                                      */
/* ------------------------------------------------------------------ */

if (!V1_ONLY) {
  const result = spawnSync(
    "scripts/run-python.sh",
    ["scripts/check_v2_fresh.py", "--v2-db", V2_DB_PATH],
    { cwd: WEB_ROOT, stdio: "inherit" },
  );
  if (result.status !== 0) {
    console.error(
      `v2.sqlite が新鮮でない（scripts/check_v2_fresh.py の終了コード ${result.status}）。` +
        `\`cd web && pnpm run build:v2\` で作り直してから再実行すること。`,
    );
    process.exit(1);
  }
}

/* ------------------------------------------------------------------ */
/* serving_queries.yaml / expected_diffs.yaml の読み込み                 */
/* ------------------------------------------------------------------ */

interface RawDomainDef {
  sql?: string;
  db?: string;
  values?: ScalarParam[];
}
interface RawQueryDef {
  id: string;
  v1_table: string | null;
  params?: Record<string, { domain: string }>;
  only_existing?: string;
  compare: CompareSpec;
  tolerance?: Record<string, number>;
  known: string[];
}
interface RawConfig {
  version: number;
  domains: Record<string, RawDomainDef>;
  queries: RawQueryDef[];
}

function loadServingQueries(): ServingQueriesConfig {
  const raw = loadYaml(fs.readFileSync(path.join(WEB_ROOT, "serving_queries.yaml"), "utf8")) as RawConfig;
  const domains: Record<string, DomainDef> = {};
  for (const [name, d] of Object.entries(raw.domains)) {
    domains[name] = { sql: d.sql, db: d.db as "v1" | undefined, values: d.values };
  }
  const queries: QueryDef[] = raw.queries.map((q) => ({
    id: q.id,
    v1Table: q.v1_table,
    params: q.params ?? {},
    onlyExisting: q.only_existing,
    compare: q.compare,
    tolerance: q.tolerance,
    known: q.known,
  }));
  return { version: raw.version, domains, queries };
}

function loadExpectedDiffs(): ExpectedDiffs {
  const file = path.join(REPO_ROOT, "scripts", "reconcile", "expected_diffs.yaml");
  const raw = loadYaml(fs.readFileSync(file, "utf8")) as Record<
    string,
    { key: ScalarParam[]; kind: "row_only_in_candidate" | "row_only_in_baseline" | "value_diff"; columns?: string[] }[]
  >;
  const out: ExpectedDiffs = {};
  for (const [table, entries] of Object.entries(raw)) {
    out[table] = entries.map((e) => ({ key: e.key, kind: e.kind, columns: e.columns }));
  }
  return out;
}

/**
 * `expected_diffs.yaml` のベースラインキー（テーブルごとに列順が違う）を、
 * この問い合わせの params + 行キー（`compare.key` の順）から組み立てる。
 * 設計書 §5.2「declared」・`reports/derived_baseline.json` の `tables[t].key` 参照。
 */
const DECLARED_KEY_BUILDERS: Record<string, DeclaredKeyBuilder> = {
  year_series_site: (p, k) => [p.site_id, p.alias, k[0], p.kind],
  year_series_water: (p, k) => [k[0], p.alias, k[1], p.kind],
  month_series_site: (p, k) => {
    const ym = String(k[0]);
    return [p.site_id, p.alias, Number(ym.slice(0, 4)), Number(ym.slice(5, 7))];
  },
  day_series_site: (p, k) => [p.site_id, p.alias, k[0]],
  site_variables: (p, k) => [p.site_id, k[0], k[1]],
  climatology: (p, k) => [p.alias, k[0]],
  variable_catalog: (_p, k) => [k[0]],
};

function declaredLookupFor(def: QueryDef): DeclaredLookup {
  return { v1Table: def.v1Table, builder: DECLARED_KEY_BUILDERS[def.id] ?? null };
}

/* ------------------------------------------------------------------ */
/* rain の L2 再計算（day_split/rain_div10 が使う）                       */
/* ------------------------------------------------------------------ */

const RAIN_VARIABLE_ID = "common:variable:weather.precipitation";

function loadRainRecompute(): RainRecompute | undefined {
  if (V1_ONLY) return undefined;
  try {
    const db = new Database(V2_DB_PATH, { readonly: true, fileMustExist: true });
    try {
      const rows = db
        .prepare(
          `SELECT period_raw, period_start, value_num FROM observation
           WHERE variable_id = ? AND value_grain = 'hour' AND value_num IS NOT NULL`,
        )
        .all(RAIN_VARIABLE_ID) as { period_raw: string; period_start: string; value_num: number }[];
      const l2: RainL2Row[] = rows.map((r) => ({ periodRaw: r.period_raw, periodStart: r.period_start, valueNum: r.value_num }));
      return computeRainRecompute(l2);
    } finally {
      db.close();
    }
  } catch (e) {
    console.error(`rain の L2 再計算をスキップ（読み込み失敗): ${e instanceof Error ? e.message : String(e)}`);
    return undefined;
  }
}

/* ------------------------------------------------------------------ */
/* v2 アダプタ（動的 import。@/lib/cube が無くても --v1-only は動く）        */
/* ------------------------------------------------------------------ */

type AdaptersV2Module = typeof import("./lib/serving/adapters-v2");

async function loadAdaptersV2(): Promise<AdaptersV2Module> {
  try {
    return await import("./lib/serving/adapters-v2");
  } catch (e) {
    throw new Error(
      `v2 アダプタの読み込みに失敗した（@/lib/cube が無い可能性が高い。1a 未統合の間は --v1-only で実行すること）: ` +
        `${e instanceof Error ? e.message : String(e)}`,
    );
  }
}

/* ------------------------------------------------------------------ */
/* 本体                                                                 */
/* ------------------------------------------------------------------ */

interface RunOutcome {
  stats: Map<string, QueryStats>;
  unexplained: UnexplainedSample[];
  matchedDeclared: Map<string, Set<string>>; // table -> matched tag set
  exceptions: { id: string; params: Record<string, ScalarParam>; message: string }[];
}

async function main() {
  const config = loadServingQueries();
  const expected = loadExpectedDiffs();
  const rain = loadRainRecompute();

  let queryDefs = config.queries;
  if (ONLY_IDS) queryDefs = queryDefs.filter((q) => ONLY_IDS.has(q.id));

  const v2 = V1_ONLY ? null : await loadAdaptersV2();
  const v2Db = v2 ? v2.openV2Db({ v2: V2_DB_PATH, registry: REGISTRY_DB_PATH, ryuiki: RYUIKI_DB_PATH }) : null;

  const t0 = Date.now();

  async function runOnce(
    classifyMutation: ClassifyMutationOptions | undefined,
    rowMutationName: string | undefined,
  ): Promise<RunOutcome> {
    const stats = new Map<string, QueryStats>();
    const unexplained: UnexplainedSample[] = [];
    const matchedDeclared = new Map<string, Set<string>>();
    const exceptions: { id: string; params: Record<string, ScalarParam>; message: string }[] = [];

    for (const def of queryDefs) {
      const s = emptyQueryStats(def.id);
      stats.set(def.id, s);

      let tuples: Record<string, ScalarParam>[];
      try {
        tuples = await enumerateParams(def, config.domains);
      } catch (e) {
        exceptions.push({ id: def.id, params: {}, message: `enumerateParams: ${e instanceof Error ? e.message : e}` });
        continue;
      }
      if (EXPAND === "snapshot") tuples = snapshotSubset(tuples, { every: 10 });

      const known = new Set(def.known as KnownRule[]);
      const declaredLookup = declaredLookupFor(def);

      for (const params of tuples) {
        s.runs += 1;
        let v1Rows: NormRow[];
        try {
          v1Rows = await runV1Query(def.id, params, def.compare);
        } catch (e) {
          exceptions.push({ id: def.id, params, message: e instanceof Error ? e.message : String(e) });
          continue;
        }
        s.rowsV1 += v1Rows.length;

        if (V1_ONLY) continue;

        let v2Rows: NormRow[];
        try {
          v2Rows = await v2!.runV2Query(v2Db!, def.id, params, def.compare);
        } catch (e) {
          exceptions.push({ id: def.id, params, message: `v2: ${e instanceof Error ? e.message : e}` });
          continue;
        }
        if (rowMutationName && isRowMutation(rowMutationName) && rowMutationAppliesTo(rowMutationName, def.id)) {
          v2Rows = applyRowMutation(rowMutationName, def.id, v2Rows);
        }
        s.rowsV2 += v2Rows.length;

        const v1ByKey = rowsByKey(v1Rows);
        const v2ByKey = rowsByKey(v2Rows);
        const diffs: RowDiff[] = compareRuns(v1ByKey, v2ByKey, def.tolerance ?? {});

        const badKeys = new Set(diffs.filter((d) => d.kind === "value_diff" || d.kind === "label_diff").map((d) => JSON.stringify(d.key)));
        for (const k of v1ByKey.keys()) {
          if (v2ByKey.has(k) && !badKeys.has(k)) s.matched += 1;
        }

        const ctx: ClassifyContext = {
          expected,
          declared: declaredLookup,
          params,
          known,
          disabledRules: classifyMutation?.disabledRules,
          rain,
          rainDateFromLabel: def.id === "rain_top_days",
          syntheticSiteIds: PRETEND_SYNTHETIC_EXCLUDED ? new Set<string>() : undefined,
          declaredRot: classifyMutation?.declaredRot,
        };

        for (const diff of diffs) {
          const c = classifyDiff(diff, ctx);
          addClassification(s, c.rule);
          if (c.rule === "declared" && c.declaredMatch) {
            const set = matchedDeclared.get(c.declaredMatch.table) ?? new Set<string>();
            set.add(declaredMatchTag(c.declaredMatch.entry));
            matchedDeclared.set(c.declaredMatch.table, set);
          }
          if (c.rule === "unexplained" && unexplained.length < 20) {
            unexplained.push({ queryId: def.id, params, kind: diff.kind, key: diff.key, columns: diff.columns });
          }
        }
      }
    }

    return { stats, unexplained, matchedDeclared, exceptions };
  }

  /* -------------------------- --mutate 自己診断 -------------------------- */
  if (MUTATE_NAMES.length && !V1_ONLY) {
    const mutationResults: MutationRunResult[] = [];
    let anyMissed = false;
    for (const name of MUTATE_NAMES) {
      const rowMutation = isRowMutation(name) ? name : undefined;
      const classifyMutation = isClassifyMutation(name)
        ? applyClassifyMutation(name, name === "declared_rot" ? { declaredRotTarget: firstDeclaredTarget(expected) } : {})
        : undefined;
      const outcome = await runOnce(classifyMutation, rowMutation);
      const totalUnexplained = [...outcome.stats.values()].reduce((n, s) => n + s.unexplained, 0);
      const caught = totalUnexplained > 0 || outcome.exceptions.length > 0;
      if (!caught) anyMissed = true;
      mutationResults.push({ name, unexplained: totalUnexplained, caughtAsExpected: caught });
    }
    console.log(`--mutate 結果: ${mutationResults.map((r) => `${r.name}=${r.caughtAsExpected ? "OK" : "NG"}`).join(", ")}`);
    if (anyMissed) {
      console.error("一部の変異が検出されなかった（分類器が壊れている可能性）。");
      process.exit(3);
    }
    process.exit(0);
  }

  /* -------------------------------- 通常実行 -------------------------------- */
  const outcome = await runOnce(undefined, undefined);
  const elapsedMs = Date.now() - t0;

  if (V1_ONLY) {
    const totalRuns = [...outcome.stats.values()].reduce((n, s) => n + s.runs, 0);
    const totalRows = [...outcome.stats.values()].reduce((n, s) => n + s.rowsV1, 0);
    console.log(`v1-only: ${queryDefs.length} 問い合わせ / ${totalRuns} runs / ${totalRows} rows / ${elapsedMs}ms`);
    for (const s of outcome.stats.values()) {
      console.log(`  ${s.id}: runs=${s.runs} rows=${s.rowsV1}`);
    }
    if (outcome.exceptions.length) {
      console.error(`${outcome.exceptions.length} 件の例外:`);
      for (const e of outcome.exceptions.slice(0, 20)) {
        console.error(`  [${e.id}] ${JSON.stringify(e.params)}: ${e.message}`);
      }
      process.exit(1);
    }
    process.exit(0);
  }

  const usedTables = new Set(queryDefs.filter((q) => q.known.includes("declared") && q.v1Table).map((q) => q.v1Table!));
  const rotten: RottenDeclaration[] = findRottenDeclarations(expected, usedTables, outcome.matchedDeclared);

  const header: ReportHeader = {
    gitHead: gitHead(),
    v2PipelineFingerprint: v2PipelineFingerprint(),
    registryInputFingerprint: registryInputFingerprint(),
    sqliteVersion: sqliteVersion(),
    imputation: IMPUTATION,
    expand: EXPAND,
    v1Source: V1_SOURCE,
    generatedAt: new Date().toISOString(),
  };

  const reportInput = {
    header,
    stats: [...outcome.stats.values()],
    unexplainedSamples: outcome.unexplained,
    rottenDeclarations: rotten,
  };

  fs.mkdirSync(path.dirname(OUT_MD), { recursive: true });
  fs.writeFileSync(OUT_MD, buildReportMarkdown(reportInput));
  fs.writeFileSync(OUT_JSON, JSON.stringify(buildReportJson(reportInput), null, 2));

  const totalUnexplained = [...outcome.stats.values()].reduce((n, s) => n + s.unexplained, 0);
  console.log(`serving-diff: ${elapsedMs}ms, unexplained=${totalUnexplained}, rotten=${rotten.length}`);
  console.log(`report: ${OUT_MD}`);

  if (outcome.exceptions.length || totalUnexplained > 0) process.exit(1);
  if (rotten.length > 0) process.exit(2);
  process.exit(0);
}

function firstDeclaredTarget(expected: ExpectedDiffs): { table: string; key: ScalarParam[]; kind: "row_only_in_candidate" | "row_only_in_baseline" | "value_diff" } | undefined {
  for (const [table, entries] of Object.entries(expected)) {
    if (entries.length) return { table, key: entries[0].key, kind: entries[0].kind };
  }
  return undefined;
}

function gitHead(): string {
  try {
    return execFileSync("git", ["rev-parse", "HEAD"], { cwd: REPO_ROOT }).toString().trim();
  } catch {
    return "(unknown)";
  }
}

function sqliteVersion(): string {
  try {
    const db = new Database(":memory:");
    const row = db.prepare("select sqlite_version() as v").get() as { v: string };
    db.close();
    return row.v;
  } catch {
    return "(unknown)";
  }
}

function v2PipelineFingerprint(): string | null {
  try {
    const db = new Database(V2_DB_PATH, { readonly: true, fileMustExist: true });
    try {
      const row = db.prepare("SELECT spec_version FROM pipeline_fingerprint LIMIT 1").get() as
        | { spec_version: string }
        | undefined;
      return row?.spec_version ?? null;
    } finally {
      db.close();
    }
  } catch {
    return null;
  }
}

function registryInputFingerprint(): string | null {
  try {
    const db = new Database(REGISTRY_DB_PATH, { readonly: true, fileMustExist: true });
    try {
      const row = db.prepare("SELECT input_fingerprint FROM registry_build LIMIT 1").get() as
        | { input_fingerprint: string }
        | undefined;
      return row?.input_fingerprint ?? null;
    } finally {
      db.close();
    }
  } catch {
    return null;
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
