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
 *     [--v1compat-db data/db/v2_v1compat.sqlite] [--out reports/serving_switch_diff.md]
 *
 * `--v1compat-db`（design §1「診断用 v1互換キューブ」）: 合成データを除外**しない**
 * 第2の v2.sqlite（`scripts/b03_build_observation.py --include-synthetic` → b04 →
 * `--out` で作る）を開き、本番の v2 接続と同じ問い合わせを流して
 * `synthetic_excluded` 規則の「差分の差分」判定に使う。省略時はこの規則は不発
 * （`v1-only`・レジストリ未整備の環境でも動かせるように必須にはしない）。
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
import { openV1CompatDb } from "./lib/serving/v1-compat";
import * as mergeV1 from "./lib/serving/merge-v1";
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
  isV1Mutation,
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
    "v1compat-db": { type: "string" },
    out: { type: "string", default: "reports/serving_switch_diff.md" },
  },
});

const V1_ONLY = argv["v1-only"] === true;
const IMPUTATION_RAW = argv.imputation as string;
if (IMPUTATION_RAW !== "zero" && IMPUTATION_RAW !== "lod") {
  console.error(`--imputation ${IMPUTATION_RAW} は使えない（zero か lod のどちらか）。`);
  process.exit(1);
}
const IMPUTATION: "zero" | "lod" = IMPUTATION_RAW;
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
const V1COMPAT_DB = argv["v1compat-db"] ? path.resolve(REPO_ROOT, String(argv["v1compat-db"])) : undefined;
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

/**
 * `*_by_variable` 問い合わせ（`v1_table: null`）向けの declared 対応表
 * （`classify.ts` の `ClassifyContext.byVariableDeclared`/
 * `classifyDeclaredWithSyntheticRemainder` docstring参照。Issue #48 PR-2
 * 統合後 修正B）。それぞれ「束ねる前の alias 単位」の問い合わせ（`day_series_site`
 * 等）が使う v1 表・キーの形をそのまま踏襲する——`buildKey` は対応する
 * `DECLARED_KEY_BUILDERS` のエントリと同じ列順で組み立てる（違いは alias を
 * `params.alias` からではなく、束ねの候補として1つずつ試す点だけ）。
 *
 * `variableIdOf`: variable_id は問い合わせによって `params.variable_id`
 * （`site_id`/`variable_id` を params に持つもの）か、行キーそのもの
 * （`variable_catalog_by_variable` は `params: {}` で `key: [variable_id]`——
 * variable_id が全件を回す軸なので params ではなく行キーに乗る）のどちらかに
 * 来る。行ごとに変わりうる（`variable_catalog_by_variable`）ため、alias 解決は
 * `params` だけで1回ではなく、行キーを受け取ってから行う（`aliasesOf` を
 * `classifyDeclaredWithSyntheticRemainder` が diff ごとに呼ぶ）。
 *
 * `aliasesOf`（この variable_id が束ねる alias の候補一覧）は
 * `adapters-v1.ts` の各 `*_by_variable` case が実際に v1 側で使うのと
 * **同じ絞り込み**にする（`allAliasesFor`＝ `variable_catalog`/`site_var`/
 * `meas_clim` 系〔全 alias を束ねる〕、`aliasesForBasis(..., "day")`＝
 * `meas_daily`/`meas_month` 系〔day grain を持つ alias だけ〕）——絞り込みが
 * 違うと、束ねの母集合が v1 側の実際の計算と食い違ったまま declared を
 * 探すことになる。
 */
interface ByVariableDeclaredSpec {
  v1Table: string;
  variableIdOf: (params: Readonly<Record<string, ScalarParam>>, rowKey: readonly ScalarParam[]) => string;
  aliasesOf: (variableId: string) => readonly string[];
  buildKey: (alias: string, params: Readonly<Record<string, ScalarParam>>, rowKey: readonly ScalarParam[]) => ScalarParam[];
}

const BY_VARIABLE_DECLARED_SPECS: Record<string, ByVariableDeclaredSpec> = {
  variable_catalog_by_variable: {
    v1Table: "var_catalog",
    variableIdOf: (_p, k) => String(k[0]),
    aliasesOf: (variableId) => mergeV1.allAliasesFor(REGISTRY_DB_PATH, "measurements", variableId),
    buildKey: (alias) => [alias],
  },
  site_variables_by_variable: {
    v1Table: "site_var",
    variableIdOf: (_p, k) => String(k[0]),
    aliasesOf: (variableId) => mergeV1.allAliasesFor(REGISTRY_DB_PATH, "measurements", variableId),
    buildKey: (alias, p, k) => [p.site_id, alias, k[1] === "day" ? "daily" : "annual"],
  },
  month_series_site_by_variable: {
    v1Table: "meas_month",
    variableIdOf: (p) => String(p.variable_id),
    aliasesOf: (variableId) => mergeV1.aliasesForBasis(REGISTRY_DB_PATH, "measurements", variableId, "day"),
    buildKey: (alias, p, k) => {
      const ym = String(k[0]);
      return [p.site_id, alias, Number(ym.slice(0, 4)), Number(ym.slice(5, 7))];
    },
  },
  day_series_site_by_variable: {
    v1Table: "meas_daily",
    variableIdOf: (p) => String(p.variable_id),
    aliasesOf: (variableId) => mergeV1.aliasesForBasis(REGISTRY_DB_PATH, "measurements", variableId, "day"),
    buildKey: (alias, p, k) => [p.site_id, alias, k[0]],
  },
  climatology_by_variable: {
    v1Table: "meas_clim",
    variableIdOf: (p) => String(p.variable_id),
    aliasesOf: (variableId) => mergeV1.aliasesForBasis(REGISTRY_DB_PATH, "measurements", variableId, "day"),
    buildKey: (alias, _p, k) => [alias, k[0]],
  },
};

function byVariableDeclaredFor(
  def: QueryDef,
  params: Readonly<Record<string, ScalarParam>>,
): ClassifyContext["byVariableDeclared"] {
  const spec = BY_VARIABLE_DECLARED_SPECS[def.id];
  if (!spec) return undefined;
  return {
    v1Table: spec.v1Table,
    aliasesFor: (rowKey) => spec.aliasesOf(spec.variableIdOf(params, rowKey)),
    buildKey: (alias, rowKey) => spec.buildKey(alias, params, rowKey),
  };
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
  // （`ClassifyContext.expectedUnitSymbol`）。`registry.sqlite` を専用の別接続で
  // 直接読むだけなので、`v2Db` を開く前に1回だけ作れば足りる（Issue #48 PR-1
  // code-review #3: 以前は `seriesForAlias` 経由——v2 側の unit 計算と同じ式——で
  // 「期待値」を計算していて、常に一致してしまう見かけ上の検証だった）。
  // alias 単位（既存の問い合わせ）と variable_id 単位（`*_by_variable`）の
  // 期待値マップを1つに併せ持つ（`classify.ts` の `aliasKeyOf` docstring参照
  // ——alias 文字列と `common:variable:...` は表記が衝突しない）。
  const expectedUnitSymbol = v2
    ? new Map([...v2.expectedUnitSymbols(REGISTRY_DB_PATH), ...v2.expectedUnitSymbolsByVariable(REGISTRY_DB_PATH)])
    : undefined;

  const v2Db: CubeDb | null = v2 ? v2.openV2Db({ v2: V2_DB_PATH, registry: REGISTRY_DB_PATH, ryuiki: RYUIKI_DB_PATH }) : null;

  // `--v1compat-db`（design §1「診断用 v1互換キューブ」）: 合成データを除外
  // **しない** v2 を第2接続として開く。`synthetic_excluded` 規則の「差分の差分」
  // 判定（`classify.ts`）専用で、本番の `v2Db` とは別のファイル・別の接続。
  const v1CompatDb: CubeDb | null = v2 && V1COMPAT_DB ? openV1CompatDb({ v1compat: V1COMPAT_DB, registry: REGISTRY_DB_PATH, ryuiki: RYUIKI_DB_PATH }) : null;
  if (!V1_ONLY && !v1CompatDb) {
    console.error(
      "--v1compat-db が指定されていない: synthetic_excluded 規則は不発になる（v1/v2 の食い違いが合成データ除外に" +
        "由来する場合でも unexplained に数えられる）。",
    );
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
    const mergeDisabled = !!rowMutationName && isV1Mutation(rowMutationName);

    for (const def of queryDefs) {
      const s = emptyQueryStats(def.id);
      stats.set(def.id, s);

      let tuples: Record<string, ScalarParam>[];
      try {
        tuples = await enumerateParams(def, config.domains, REGISTRY_DB_PATH);
      } catch (e) {
        exceptions.push({ id: def.id, params: {}, message: `enumerateParams: ${e instanceof Error ? e.message : e}` });
        continue;
      }
      const known = new Set(def.known as KnownRule[]);
      const declaredLookup = declaredLookupFor(def);

      for (const params of tuples) {
        s.runs += 1;
        let v1Rows: NormRow[];
        try {
          v1Rows = await runV1Query(def.id, params, def.compare, REGISTRY_DB_PATH, { mergeDisabled });
        } catch (e) {
          exceptions.push({ id: def.id, params, message: e instanceof Error ? e.message : String(e) });
          continue;
        }
        s.rowsV1 += v1Rows.length;

        if (V1_ONLY) continue;

        let v2Rows: NormRow[];
        try {
          v2Rows = await v2!.runV2Query(v2Db!, def.id, params, def.compare, IMPUTATION);
        } catch (e) {
          exceptions.push({ id: def.id, params, message: `v2: ${e instanceof Error ? e.message : e}` });
          continue;
        }
        if (rowMutationName && isRowMutation(rowMutationName) && rowMutationAppliesTo(rowMutationName, def.id)) {
          v2Rows = applyRowMutation(rowMutationName, def.id, v2Rows);
        }
        s.rowsV2 += v2Rows.length;

        // `synthetic_excluded`（design §1「差分の差分」）用: 同じ問い合わせを
        // v1compat 接続で流す。診断専用のため失敗しても本体の突き合わせは
        // 続行する（この (id,params) では synthetic_excluded が不発になるだけ）。
        //
        // imputation は常に `"zero"` を固定で渡す（`IMPUTATION`——`--imputation lod`
        // 実行時でも）。v1 は昔から「定量下限未満は 0」という zero 相当の集計法
        // しか知らない——`v1CompatByKey` は「もし合成データを除外していなかった
        // ら v1 はどう見えるか」を再現する基準値なので、v1 の意味論（zero）に
        // 揃える必要がある。`--imputation lod` 実行時に current imputation
        // （lod）のまま流すと、「合成データを含む」かつ「値が動く」セルの両方に
        // 該当する行（実測: `zone_series`/`climatology`/`zone_climatology` と
        // その `_by_variable` 双子で計132件、Issue #48 PR-2 統合後 修正Bで
        // 判明）で `v1 == compatRow` が成り立たなくなり
        // （v1 は zero 相当なのに compatRow は lod 済みの値のため）、
        // `classifySyntheticExcludedV1Compat` が不発になる——結果、`known` に
        // `synthetic_excluded`・`lod_imputation` の両方があっても、どちらの
        // 単独規則も「片方の効果だけ」しか説明できず unexplained に落ちる。
        // compat を常に zero で引けば、`v1 == compatRow(zero)` の一致判定で
        // 「合成データを含む・含まない」の軸だけを確認でき、`compatRow(zero) ≠
        // v2(本番、現在の imputation)` という既存のチェック（`classifySyntheticExcludedV1Compat`
        // 内）が「合成データの除外」と「zero→lod」の両方が重なった差分も
        // まとめて説明する（`diff.v1 !== diff.v2` は `RowDiff` の定義上すでに
        // 真なので、この既存チェックは特別な追加条件なしに両対応する）。
        let v2CompatByKey: ReadonlyMap<string, NormRow> | undefined;
        if (v1CompatDb) {
          try {
            // 既定の `{kind:'summary'}` のまま呼ぶ（画面・API・AI と同じ経路）。
            // `scripts/b13_build_summary.py` を v1compat 段にも足したので
            // （`scripts/b00_run_full_gate.py`/CI `sample-gate`）、
            // `v2_v1compat.sqlite` の summary 2表も --include-synthetic 後の
            // observation_agg から作り直されており、本番と同じ値しか返らない
            // という旧問題（`{kind:'live'}` で回避していた）は解消済み。
            const rows = await v2!.runV2Query(v1CompatDb, def.id, params, def.compare, "zero");
            v2CompatByKey = rowsByKey(rows);
          } catch (e) {
            console.error(`v1compat: [${def.id}] ${JSON.stringify(params)}: ${e instanceof Error ? e.message : e}`);
          }
        }

        // `lod_imputation`（design §3 #1）用: `--imputation lod` のときだけ、
        // 同じ問い合わせを imputation=zero でも引く（v1 と比べる基準値）。
        let v2ZeroByKey: ReadonlyMap<string, NormRow> | undefined;
        if (IMPUTATION === "lod") {
          try {
            const zeroRows = await v2!.runV2Query(v2Db!, def.id, params, def.compare, "zero");
            v2ZeroByKey = rowsByKey(zeroRows);
          } catch (e) {
            console.error(`v2(zero): [${def.id}] ${JSON.stringify(params)}: ${e instanceof Error ? e.message : e}`);
          }
        }

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
          rainDateFromLabel: false, // `rain_top_days` は D5 で削除済み（PR-2）
          rainGrain: def.id === "rain_monthly_clim" ? "month" : "day",
          v2CompatByKey,
          v2ZeroByKey,
          declaredRot: classifyMutation?.declaredRot,
          expectedUnitSymbol,
          byVariableDeclared: byVariableDeclaredFor(def, params),
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
      // `runOnce` の第2引数は「行変異名」だったが、`isV1Mutation`（`merge_rule_off`）
      // も同じ引数に相乗りさせる（`runOnce` 内で `isRowMutation`/`isV1Mutation` は
      // 排他的なので、どちらの変異名を渡しても意図した1箇所にしか効かない）。
      const rowMutation = isRowMutation(name) || isV1Mutation(name) ? name : undefined;
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
