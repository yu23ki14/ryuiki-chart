#!/usr/bin/env -S node --import ./scripts/lib/serving/register-aliases.mjs
/**
 * serving-snapshot: v2（`@/lib/cube` 経由の `v2.sqlite`＋`registry.sqlite`＋`ryuiki.sqlite`＋`cells.sqlite`）に、
 * `serving_queries.yaml` の問い合わせを画面・API・AI と同じ公開関数で流し、結果を残す。
 * 設計: `docs/plans/V2_SERVING_PR5.md` §3.2・§3.3（v1 側と突き合わせる serving-diff の後継）。
 *
 *   cd web
 *   pnpm run serving:snapshot -- [--mode snapshot|fingerprint|diff] [--out <path>] [--only id,id] [--base <path>] [--db-dir <dir>]
 *
 *   --mode snapshot     全 run の全行を JSON に書く（既定。`--out` 省略時は data/sample/serving_snapshot.json。
 *                       CI の sample-gate が `git diff --exit-code` で見る）。1 row = 1 行。
 *   --mode fingerprint  run ごとに行数・数値列の和・行の sha256 だけを書く（全量。`--out` 省略時は標準出力。
 *                       `b00_run_full_gate.py` が `reports/serving_fingerprint.json` の `queries` に入れる）。
 *   --mode diff         スナップショットをメモリで作り、HEAD のスナップショット（`--base` で差し替え）と比べた
 *                       問い合わせごとの markdown 表を標準出力に出す。スナップショット更新 PR の本文に貼る。終了コードは常に 0。
 *   --only              問い合わせ id（カンマ区切り）。snapshot で使うときは `--out` が要る（部分で全量を上書きしない）。
 *   --db-dir            DB の置き場（既定: 環境変数 RYUIKI_DB_DIR、無ければ <repo>/data/db）。registry は RYUIKI_REGISTRY_DB でも指せる。
 *
 * 実行のしかた（tsx を直接使うとき。package.json の `serving:snapshot` もこれと同じ）:
 *   npx tsx --import ./scripts/lib/serving/register-aliases.mjs ./scripts/serving-snapshot.mts
 *
 * - `imputation` は `lod` 固定（画面・API が使うのは lod だけ。zero の系列は b04 の不変条件が守る）。
 * - 限界: 本番の D1 経路（`d1CubeDb`・100 パラメータ・分割クエリ）は通らない。`sqliteCubeDb` と `d1CubeDb` の
 *   等価は `src/lib/cube/db-sqlite.test.ts` 側の責務。
 * - 終了コード: 0=成功／1=空振り検査に失敗（出力は書く）／2=入力の不備（DB が無い・引数・YAML）。
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";
import { execFileSync } from "node:child_process";
import type { CubeDb } from "@/lib/cube";
import { closeV2Db, openV2Db, runV2Query } from "./lib/serving/adapters-v2";
import type { NormRow, QueryDef } from "./lib/serving/normalize";
import {
  SCHEMA_VERSION,
  degenerateProblems,
  diffTable,
  expandParams,
  finalizeRows,
  fingerprintRun,
  formatFingerprint,
  formatSnapshot,
  maxRunsFor,
  parseServingQueries,
  resolveDomain,
  type Fingerprint,
  type Mode,
  type ResolvedDomain,
  type Snapshot,
  type SnapshotQuery,
} from "./lib/serving/snapshot";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const WEB_ROOT = path.resolve(HERE, "..");
const REPO_ROOT = path.resolve(WEB_ROOT, "..");
const SNAPSHOT_REL = "data/sample/serving_snapshot.json";

class UsageError extends Error {}

function fail(msg: string, code = 2): never {
  console.error(msg);
  process.exit(code);
}

// `pnpm run serving:snapshot -- --mode ...` は区切りの `--` もそのまま渡してくる。
const ARGS = process.argv.slice(2).filter((a, i) => !(a === "--" && i === 0));

const { values: argv } = parseArgs({
  args: ARGS,
  options: {
    mode: { type: "string", default: "snapshot" },
    out: { type: "string" },
    only: { type: "string" },
    base: { type: "string" },
    "db-dir": { type: "string" },
  },
});

const MODE_RAW = argv.mode as string;
if (MODE_RAW !== "snapshot" && MODE_RAW !== "fingerprint" && MODE_RAW !== "diff") {
  fail(`--mode ${MODE_RAW} は使えない（snapshot / fingerprint / diff のどれか）。`);
}
const RUN_MODE: Mode = MODE_RAW === "fingerprint" ? "fingerprint" : "snapshot";
const ONLY_IDS = argv.only ? new Set(String(argv.only).split(",").map((s) => s.trim()).filter(Boolean)) : null;
if (MODE_RAW === "snapshot" && ONLY_IDS && !argv.out) {
  fail("--only を付けた --mode snapshot は --out が要る（一部の問い合わせで data/sample/serving_snapshot.json を上書きしないため）。");
}

const DB_DIR = path.resolve(argv["db-dir"] ?? process.env.RYUIKI_DB_DIR ?? path.join(REPO_ROOT, "data", "db"));
const PATHS = {
  v2: path.join(DB_DIR, "v2.sqlite"),
  registry: process.env.RYUIKI_REGISTRY_DB ?? path.join(DB_DIR, "registry.sqlite"),
  ryuiki: path.join(DB_DIR, "ryuiki.sqlite"),
  cells: path.join(DB_DIR, "cells.sqlite"),
};

/** DB が無いときに、何が無くて何をすればよいかが分かるエラーにする（better-sqlite3 の素のエラーに任せない）。 */
function assertDbFiles(): void {
  const missing = Object.entries(PATHS).filter(([, p]) => !fs.existsSync(p));
  if (missing.length === 0) return;
  const list = missing.map(([k, p]) => `  - ${k}: ${p}`).join("\n");
  throw new UsageError(
    `serving-snapshot: 入力の DB が無い（DB の置き場: ${DB_DIR}）。\n${list}\n` +
      "手元なら `cd web && pnpm run build:v2`（v2.sqlite・registry.sqlite）と原本（ryuiki.sqlite・cells.sqlite）を用意する。\n" +
      "CI のサンプルなら `python3 scripts/s02_materialize_sample.py` → r01 → b03〜b13 の後に実行する（DEPLOYMENT.md・ci.yml の sample-gate 参照）。\n" +
      "別の場所に置いたなら --db-dir <dir> か環境変数 RYUIKI_DB_DIR / RYUIKI_REGISTRY_DB で指す。",
  );
}

function loadConfig() {
  const file = path.join(WEB_ROOT, "serving_queries.yaml");
  try {
    return parseServingQueries(fs.readFileSync(file, "utf8"));
  } catch (e) {
    throw new UsageError(`serving_queries.yaml を読めない: ${(e as Error).message}`);
  }
}

interface QueryResult {
  def: QueryDef;
  nDomain: number;
  runs: { params: Record<string, string | number>; rows: NormRow[] }[];
}

async function collect(db: CubeDb, mode: Mode): Promise<QueryResult[]> {
  const config = loadConfig();
  const defs = ONLY_IDS ? config.queries.filter((q) => ONLY_IDS.has(q.id)) : config.queries;
  if (ONLY_IDS) {
    const unknown = [...ONLY_IDS].filter((id) => !config.queries.some((q) => q.id === id));
    if (unknown.length) throw new UsageError(`--only に serving_queries.yaml に無い id がある: ${unknown.join(", ")}`);
  }

  const resolved = new Map<string, ResolvedDomain>();
  const all = (sql: string) => db.all<Record<string, unknown>>(sql);
  const out: QueryResult[] = [];
  for (const def of defs) {
    for (const p of Object.values(def.params)) {
      if (!resolved.has(p.domain)) resolved.set(p.domain, await resolveDomain(p.domain, config.domains[p.domain], all));
    }
    const { nDomain, params } = expandParams(def, Object.fromEntries(resolved), maxRunsFor(def, mode));
    const runs: QueryResult["runs"] = [];
    for (const p of params) {
      // imputation は lod 固定（画面・API が使うのは lod だけ）。catalogSource は既定の summary。
      const rows = await runV2Query(db, def.id, p, def.compare, "lod");
      runs.push({ params: p, rows: finalizeRows(rows) });
    }
    console.error(`  ${def.id}: n_domain=${nDomain} runs=${runs.length} rows=${runs.reduce((s, r) => s + r.rows.length, 0)}`);
    out.push({ def, nDomain, runs });
  }
  return out;
}

function toSnapshot(results: QueryResult[]): Snapshot {
  const queries: SnapshotQuery[] = results.map((r) => ({ id: r.def.id, n_domain: r.nDomain, runs: r.runs }));
  return { schema_version: SCHEMA_VERSION, imputation: "lod", queries };
}

function writeOut(file: string, text: string): void {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, text);
  console.error(`書いた: ${file}`);
}

function loadBase(): Snapshot | null {
  if (argv.base) return JSON.parse(fs.readFileSync(argv.base, "utf8")) as Snapshot;
  try {
    const text = execFileSync("git", ["show", `HEAD:${SNAPSHOT_REL}`], { cwd: REPO_ROOT, encoding: "utf8", maxBuffer: 1 << 30, stdio: ["ignore", "pipe", "ignore"] });
    return JSON.parse(text) as Snapshot;
  } catch {
    return null; // HEAD にまだ無い（初回）
  }
}

async function main(): Promise<void> {
  assertDbFiles();
  const db = openV2Db(PATHS);
  let results: QueryResult[];
  try {
    results = await collect(db, RUN_MODE);
  } finally {
    closeV2Db();
  }

  if (MODE_RAW === "diff") {
    process.stdout.write(diffTable(loadBase(), toSnapshot(results)));
    return;
  }

  if (MODE_RAW === "snapshot") {
    writeOut(argv.out ? path.resolve(argv.out) : path.join(REPO_ROOT, SNAPSHOT_REL), formatSnapshot(toSnapshot(results)));
  } else {
    const fp: Fingerprint = {
      schema_version: SCHEMA_VERSION,
      imputation: "lod",
      queries: results.map((r) => ({
        id: r.def.id,
        n_domain: r.nDomain,
        runs: r.runs.map((run) => fingerprintRun(run, r.def.compare.numeric)),
      })),
    };
    const text = formatFingerprint(fp);
    if (argv.out) writeOut(path.resolve(argv.out), text);
    else process.stdout.write(text);
  }

  const problems = degenerateProblems(results);
  if (problems.length) {
    console.error("空振り検査に失敗:\n" + problems.map((p) => `  - ${p}`).join("\n"));
    process.exit(1);
  }
}

main().catch((e) => {
  if (e instanceof UsageError) fail(e.message);
  console.error(e);
  process.exit(2);
});
