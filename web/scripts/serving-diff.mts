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
 *   pnpm run serving:diff [--v1-only] [--imputation zero|lod]
 *     [--only <id,...>] [--mutate <name,...>] [--v1-source derived|v1_projection]
 *     [--pretend-synthetic-excluded] [--out reports/serving_switch_diff.md]
 *
 * `--expand`（`all` 固定・`snapshot` は撤去）: 設計書は「全 site_var の組を全部回す
 * (`all`) / 決定論的な部分集合で CI 用に回す (`snapshot`、`snapshot_subset` を
 * YAML で宣言)」の2本立てだったが、`snapshot` は「YAML の `snapshot_subset` を
 * 読まず `every:10` 決め打ちで間引くだけ」の簡略実装で、宣言（設計書）と実装が
 * 食い違っていたため Issue #48 PR-1 統合で削除した。スナップショット
 * （CI 向けの決定論的部分集合）は PR-5 で YAML の `snapshot_subset` を実際に読む
 * 形で作り直す。
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
import type { CubeDb } from "@/lib/cube";

import {
  rowsByKey,
  type CompareSpec,
  type DomainDef,
  type NormRow,
  type QueryDef,
  type ScalarParam,
  type ServingQueriesConfig,
} from "./lib/serving/normalize";
import { enumerateParams, runV1Query } from "./lib/serving/adapters-v1";
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
if (argv.expand !== undefined && argv.expand !== "all") {
  console.error(
    `--expand ${argv.expand} は使えない（\`snapshot\` は Issue #48 PR-1 統合で撤去した。` +
      `YAML の snapshot_subset を読まない簡略実装のまま宣言と食い違っていたため。PR-5 で作り直す）。`,
  );
  process.exit(1);
}
const EXPAND = "all" as const;
const ONLY_IDS = argv.only ? new Set(String(argv.only).split(",").map((s) => s.trim())) : null;
const MUTATE_NAMES = argv.mutate ? String(argv.mutate).split(",").map((s) => s.trim()) : [];
const V1_SOURCE = (argv["v1-source"] as string) === "v1_projection" ? "v1_projection" : "derived";
const PRETEND_SYNTHETIC_EXCLUDED = argv["pretend-synthetic-excluded"] === true;
// `reports/serving_switch_diff.{md,json}` はリポジトリ直下（design: `docs/plans/V2_SERVING_PR1.md`・
// `docs/adr/0029-v1-removal-and-verification-handoff.md`）。`--out` を明示すればそちらを
// 優先するが、既定値・相対パスはどちらも REPO_ROOT からの相対として解決する。
const OUT_MD = path.resolve(REPO_ROOT, String(argv.out));
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
  // `unit_label_registry` 規則が「v2 側が非NULLなら何でも通す」のではなく、実際に
  // その系列の unit_id のレジストリ symbol と一致するかまで確かめるための参照表
  // （`ClassifyContext.expectedUnitSymbol`）。db を読まない純粋な計算なので、
  // `--pretend-synthetic-excluded` で db を開き直す前に1回だけ作れば足りる。
  const expectedUnitSymbol = v2 ? v2.expectedUnitSymbols() : undefined;

  // `--pretend-synthetic-excluded`（設計書 §9-4）: まず素の v2 で「地点の全セルが
  // 合成系列だけ」の place_id 集合を求め（`lib/cube` の `isSynthetic` 由来）、
  // 一旦閉じてから、その place_id を `observation_agg` から除いた仮想の v2 で
  // 開き直す（`db-sqlite.ts` の `excludePlaceIds`）。`ctx.syntheticSiteIds` には
  // 対応する site_id を渡し、`classify.ts` の `synthetic_excluded` 規則を実際に働かせる。
  let syntheticSiteIds: ReadonlySet<string> | undefined;
  let v2Db: CubeDb | null = null;
  if (v2) {
    if (PRETEND_SYNTHETIC_EXCLUDED) {
      const probeDb = v2.openV2Db({ v2: V2_DB_PATH, registry: REGISTRY_DB_PATH, ryuiki: RYUIKI_DB_PATH });
      const syntheticPlaceIds = await v2.computeSyntheticPlaceIds(probeDb);
      const siteIds = await v2.siteIdsForPlaceIds(probeDb, syntheticPlaceIds);
      syntheticSiteIds = new Set(siteIds);
      v2.closeV2Db();
      console.log(
        `--pretend-synthetic-excluded: 合成地点 ${syntheticPlaceIds.length} 件（うち site_id を持つもの ${siteIds.length} 件）を observation_agg から除いて開き直す`,
      );
      v2Db = v2.openV2Db(
        { v2: V2_DB_PATH, registry: REGISTRY_DB_PATH, ryuiki: RYUIKI_DB_PATH },
        { excludePlaceIds: syntheticPlaceIds },
      );
    } else {
      v2Db = v2.openV2Db({ v2: V2_DB_PATH, registry: REGISTRY_DB_PATH, ryuiki: RYUIKI_DB_PATH });
    }
  }

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
      const known = new Set(def.known as KnownRule[]);
      // `--pretend-synthetic-excluded` は合成地点を含みうる問い合わせ全部に影響する
      // （どの問い合わせが触れるかは合成地点がどの水域・ゾーンに属すかに依るので、
      // YAML の `known` に問い合わせごと決め打ちしない——設計書 §9-4 の「PR-2 の予告」
      // としてこのフラグが立っているときだけ全問い合わせに対して働かせる）。
      if (PRETEND_SYNTHETIC_EXCLUDED) known.add("synthetic_excluded");
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

        // `rowsByKey` は同じキーの行が2つあれば例外にする（design: 「片方を捨てると
        // 診断が壊れる」）。これは serving-diff 自身の設計上の保護であって v1/v2 の
        // 例外ではないが、`--mutate include_watershed_cells`（行を複製する変異）が
        // これを実際に踏む——変異1つが工具全体を落として残りの変異を試せなくする
        // のは本末転倒なので、他の2つの問い合わせ呼び出しと同じく「この (id,params)
        // だけ例外として記録して続行」にする（`--mutate` の自己診断は
        // `exceptions.length > 0` も「検出できた」に数える——serving-diff.mts 冒頭）。
        let v1ByKey: ReadonlyMap<string, NormRow>;
        let v2ByKey: ReadonlyMap<string, NormRow>;
        let diffs: RowDiff[];
        try {
          v1ByKey = rowsByKey(v1Rows);
          v2ByKey = rowsByKey(v2Rows);
          diffs = compareRuns(v1ByKey, v2ByKey, def.tolerance ?? {});
        } catch (e) {
          exceptions.push({ id: def.id, params, message: e instanceof Error ? e.message : String(e) });
          continue;
        }

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
          rainGrain: def.id === "rain_monthly_clim" ? "month" : "day",
          syntheticSiteIds,
          declaredRot: classifyMutation?.declaredRot,
          expectedUnitSymbol,
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

  /* -------------------------------- 通常実行 -------------------------------- */
  const outcome = await runOnce(undefined, undefined);

  /* -------------------------- --mutate 自己診断 -------------------------- */
  // 通常実行（変異なし）と同じ 1 回の呼び出しでレポートも作る（design §5.1
  // 「末尾に…変異テストの結果表」）。`--mutate` 自体は「必ず unexplained > 0 で
  // 落ちる」ことの自己診断なので、通常実行の結果（stats/unexplainedSamples/
  // rottenDeclarations）は変えない——変異結果はレポート末尾に追記するだけ。
  let mutationResults: MutationRunResult[] | undefined;
  let anyMutationMissed = false;
  if (MUTATE_NAMES.length && !V1_ONLY) {
    mutationResults = [];
    for (const name of MUTATE_NAMES) {
      const rowMutation = isRowMutation(name) ? name : undefined;
      const classifyMutation = isClassifyMutation(name)
        ? applyClassifyMutation(name, name === "declared_rot" ? { declaredRotTarget: firstDeclaredTarget(expected) } : {})
        : undefined;
      const mutOutcome = await runOnce(classifyMutation, rowMutation);
      const totalUnexplained = [...mutOutcome.stats.values()].reduce((n, s) => n + s.unexplained, 0);
      const caught = totalUnexplained > 0 || mutOutcome.exceptions.length > 0;
      if (!caught) anyMutationMissed = true;
      mutationResults.push({ name, unexplained: totalUnexplained, caughtAsExpected: caught });
    }
    console.log(`--mutate 結果: ${mutationResults.map((r) => `${r.name}=${r.caughtAsExpected ? "OK" : "NG"}`).join(", ")}`);
  }

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
    elapsedMs,
  };

  const reportInput = {
    header,
    stats: [...outcome.stats.values()],
    unexplainedSamples: outcome.unexplained,
    rottenDeclarations: rotten,
    mutationResults,
  };

  fs.mkdirSync(path.dirname(OUT_MD), { recursive: true });
  fs.writeFileSync(OUT_MD, buildReportMarkdown(reportInput));
  fs.writeFileSync(OUT_JSON, JSON.stringify(buildReportJson(reportInput), null, 2));

  const totalUnexplained = [...outcome.stats.values()].reduce((n, s) => n + s.unexplained, 0);
  console.log(`serving-diff: ${elapsedMs}ms, unexplained=${totalUnexplained}, rotten=${rotten.length}`);
  console.log(`report: ${OUT_MD}`);

  // `--mutate` の自己診断（分類器が壊れていないか）が最優先——通常実行の
  // unexplained/rotten より先に見る（設計書 §5.3 の「必ず落ちる」ことの検証が
  // 主目的の呼び出しなので、その失敗を他の終了コードで覆い隠さない）。
  if (anyMutationMissed) {
    console.error("一部の変異が検出されなかった（分類器が壊れている可能性）。");
    process.exit(3);
  }
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
