#!/usr/bin/env node
/**
 * ローカル D1（miniflare）に原本 SQLite の中身を流し込む。開発環境専用。
 *
 *   node scripts/seed-d1-local.mjs [--force]
 *
 * 仕組み:
 *   wrangler の `--local` な D1 は .wrangler/state/v3/d1/ 配下のただの SQLite ファイル。
 *   340万行を `wrangler d1 execute --file` で流すと現実的な時間で終わらないので、
 *   マイグレーション適用済みのそのファイルへ better-sqlite3 で直接 INSERT する。
 *
 * 原本 (data/db/*.sqlite) は readonly で開く。書き換えない。
 *
 * 冪等性:
 *   原本 3 ファイルのフィンガープリント（サイズ + mtime）を `_seed_state` に記録する。
 *   一致していれば何もしない。原本を作り直したときだけ入れ直す。
 *
 * 本番の D1 はこの手が使えない（ファイルが手元に無い）。
 * `npm run db:export` で .sql を書き出して `wrangler d1 execute --remote --file` に渡す。
 */
import Database from "better-sqlite3";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.resolve(__dirname, "..");
const REPO = path.resolve(WEB, "..");
const DB_DIR = process.env.RYUIKI_DB_DIR ?? path.join(REPO, "data", "db");
const D1_STATE = path.join(WEB, ".wrangler", "state", "v3", "d1", "miniflare-D1DatabaseObject");

/**
 * 原本ファイルと、そこに入っているテーブルの引き当て。`hint` はそのファイルが
 * 無いときのエラーメッセージ（`fingerprint()` が使う。コードレビュー指摘: 以前は
 * `fingerprint()` 側に入れ子の三項演算子でファイル名ごとの文言を持っていたが、
 * `SOURCES` に要素を足すたびに追随し忘れる余地があった——ヒントも1つの要素の
 * 中で完結させる）。
 */
const SOURCES = [
  { alias: "ryuiki", file: "ryuiki.sqlite", required: true, hint: "data/db/ に原本を置く。" },
  { alias: "cells", file: "cells.sqlite", required: true, hint: "data/db/ に原本を置く。" },
  {
    alias: "derived", file: "derived.sqlite", required: true,
    hint: "集計 DB は `npm run build:derived` で作る（初回のみ・約1分）。",
  },
  {
    alias: "registry", file: "registry.sqlite", required: true,
    hint: "語彙レジストリは `npm run build:registry` で作る（scripts/r01_build_registry.py）。",
  },
  // Issue #48 PR-0: キューブ（observation_agg/occurrence_agg）の入力。v2.sqlite には
  // L2（observation/occurrence/occurrence_place）も同居しているが、D1 のスキーマ
  // （schema-cube.ts）がキューブ2表しか宣言していないので、下の owner map 経由で
  // 自動的にキューブだけが対象になる（D1 に無いテーブル名は targets に現れない）。
  {
    alias: "v2", file: "v2.sqlite", required: true,
    hint: "v2（observation_agg/occurrence_agg のキューブ）は `npm run build:v2` で作る。",
  },
];

const RUN_PYTHON = path.join(WEB, "scripts", "run-python.sh");
const CHECK_V2_FRESH_PY = "scripts/check_v2_fresh.py";
const V2_REBUILD_HINT = "`pnpm run build:v2` で作り直すこと。";

/**
 * `v2.sqlite` が「今のパイプラインの spec で書かれ、かつ今の原本・入力・
 * registry.sqlite・パイプラインのコードから作ったもの」かを Python 側
 * （`scripts/check_v2_fresh.py`。正本は `scripts/migrate/common.py` の
 * `V2_CUBE_SPEC_VERSIONS`・`compute_v2_input_fingerprint()`）に判定させる。
 * **古い v2.sqlite を拒否する**（Issue #48「見落としそうな危険」4: 手元の
 * `data/db/v2.sqlite` が PR #26 より前の13列キー〔`imputation`/`value` 列を持ち
 * `pipeline_fingerprint` 表自体が無い旧形〕のまま放置されていることがある。
 * 気づかずシードすると、D1 のキューブが黙って旧形の値で埋まる）。
 *
 * ここでは判定に使う値そのものを持たない（コードレビュー指摘: 以前は
 * `V2_SPEC_VERSIONS` という手書きの写しをここに持っていたが、b03/b04 が
 * spec_version を上げても JS 側の写しは自動で追随せず、黙ってずれる）。
 * 判定は `scripts/check_v2_fresh.py`（`scripts/r01_build_registry.py
 * --check-fresh` と同じ 0=新鮮/10=古い/それ以外=判定不能の終了コード）に
 * 一本化し、ここでは**0以外を全部拒否する**——シードは「D1 に何を入れるか」の
 * 最後の関門なので、判定不能（Python が起動できない等）を「古いかもしれないが
 * 今回は見逃す」という寛容な扱いにはしない（`ensure-v2.sh` の自動再ビルド判断
 * とは目的が違う。そちらは「余計な再ビルドを避ける」ための最適化なので判定
 * できなければ既存ファイルを使い続ける寛容さでよいが、こちらは安全側に倒す）。
 * 入力＋コードの指紋の計算はサブプロセスを1つ増やす程度のコストなので
 * （`scripts/migrate/common.py` の実測: 1秒未満）、`ensure-v2.sh` 直後の
 * 二重計算をここで避ける最適化はしない。
 */
function assertV2SpecFresh(v2Path) {
  const result = spawnSync(RUN_PYTHON, [CHECK_V2_FRESH_PY, "--v2-db", v2Path], { cwd: WEB, encoding: "utf8" });
  if (result.error) {
    throw new Error(
      `v2.sqlite の鮮度判定（${CHECK_V2_FRESH_PY}）を起動できない: ${result.error.message}\n${V2_REBUILD_HINT}`,
    );
  }
  if (result.status !== 0) {
    const detail = (result.stderr || result.stdout || "").trim();
    throw new Error(
      `${v2Path} が古い（${CHECK_V2_FRESH_PY} の終了コード ${result.status}）。` +
        (detail ? `\n${detail}` : "") +
        `\n${V2_REBUILD_HINT}`,
    );
  }
}

/** マイグレーションと wrangler / miniflare の管理テーブル。シードの対象外。 */
const SKIP_TABLES = new Set(["d1_migrations", "_seed_state"]);
const isInternal = (name) => name.startsWith("_cf_") || name.startsWith("sqlite_") || SKIP_TABLES.has(name);

const t0 = Date.now();
const log = (...a) => console.log(`[seed ${((Date.now() - t0) / 1000).toFixed(1)}s]`, ...a);
const qi = (n) => `"${String(n).replace(/"/g, '""')}"`;

/**
 * miniflare は D1 の実体ファイルを `database_id` などから導出したハッシュ名で
 * `.wrangler/state/v3/d1/miniflare-D1DatabaseObject/<hash>.sqlite` に置く。ハッシュの
 * 導出規則は wrangler のバージョンが変わると変わることがあり、`docker-compose.yml` の
 * 名前付きボリューム（`d1-state`）はイメージを作り直しても中身を引き継ぐため、
 * 「古い wrangler で作った <旧hash>.sqlite が残ったまま、新しい wrangler が
 * <新hash>.sqlite を新規に作る」という状態が起こりうる（実際に発生した障害の原因）。
 * `wrangler.jsonc` の d1_databases 定義自体は Phase A を通じて1本（database_id 固定）
 * のままなので、コード側の不整合ではなく「持ち越した状態」の問題。
 *
 * 対処: ファイルが複数あるときは即エラーにはせず、直前の `npm run db:migrate` が
 * 触ったばかりの＝最も mtime が新しいものを「現在使うべき実体」として選ぶ
 * （entrypoint は migrate → seed の順で必ず直列に呼ぶので、今回のマイグレーションが
 * 触ったファイルが常に最新になる）。古いファイルは消さずに警告だけ出す。
 * 黙って選ぶのではなく、選んだ理由と捨てた候補を必ずログに残す。
 */
function findLocalD1() {
  if (!fs.existsSync(D1_STATE)) {
    throw new Error(
      `ローカル D1 が見つからない: ${D1_STATE}\n` +
        `先に \`npm run db:migrate\` (wrangler d1 migrations apply) を実行する。`,
    );
  }
  const files = fs
    .readdirSync(D1_STATE)
    .filter((f) => f.endsWith(".sqlite") && f !== "metadata.sqlite")
    .map((f) => path.join(D1_STATE, f));
  if (files.length === 0) {
    throw new Error(
      `ローカル D1 の SQLite ファイルが無い: ${D1_STATE}\n` +
        `先に \`npm run db:migrate\` (wrangler d1 migrations apply) を実行する。`,
    );
  }
  if (files.length === 1) return files[0];

  // 複数ある: 直前の db:migrate が触った(mtime が最新の)ものを採用し、他は警告に出す。
  const withStat = files.map((f) => ({ f, mtimeMs: fs.statSync(f).mtimeMs }));
  withStat.sort((a, b) => b.mtimeMs - a.mtimeMs);
  const [chosen, ...stale] = withStat;
  log(
    `⚠ ローカル D1 の SQLite ファイルが ${files.length} 個ある（wrangler のバージョン更新等で` +
      `古いファイルが d1-state ボリュームに残ったと思われる）。最も新しく更新された ` +
      `${chosen.f} を使う。`,
  );
  for (const s of stale) {
    log(`  未使用（古い可能性）: ${s.f} (mtime=${new Date(s.mtimeMs).toISOString()})`);
  }
  log(
    "  古いファイルが不要なら `pnpm run db:reset`（.wrangler/state/v3/d1 ごと消して作り直す）" +
      "で整理できる。",
  );
  return chosen.f;
}

/** 原本の同一性。中身のハッシュは 1.1GB 読むので、サイズと mtime で足りる。 */
function fingerprint() {
  const parts = [];
  for (const s of SOURCES) {
    const p = path.join(DB_DIR, s.file);
    if (!fs.existsSync(p)) {
      if (!s.required) continue;
      throw new Error(`原本が無い: ${p}\n${s.hint}`);
    }
    const st = fs.statSync(p);
    parts.push(`${s.file}:${st.size}:${Math.floor(st.mtimeMs)}`);
  }
  return parts.join("|");
}

function main() {
  const force = process.argv.includes("--force");
  const fp = fingerprint();
  const d1Path = findLocalD1();

  const db = new Database(d1Path);
  db.pragma("busy_timeout = 30000");

  const applied = db
    .prepare("SELECT count(*) n FROM sqlite_master WHERE type='table' AND name='_seed_state'")
    .get().n;
  if (!applied) throw new Error("マイグレーション未適用。先に `npm run db:migrate` を実行する。");

  const prev = db.prepare("SELECT value FROM _seed_state WHERE key = 'sources'").get();
  if (!force && prev?.value === fp) {
    log("投入済み（原本に変化なし）。スキップする。");
    db.close();
    return;
  }
  if (prev && !force) log("原本が変わっている。入れ直す。");

  // 原本は読み取り専用で開く
  const src = {};
  for (const s of SOURCES) {
    const p = path.join(DB_DIR, s.file);
    if (!fs.existsSync(p)) continue;
    src[s.alias] = new Database(p, { readonly: true, fileMustExist: true });
  }
  if (src.v2) assertV2SpecFresh(path.join(DB_DIR, "v2.sqlite"));

  /** テーブル名 -> どの原本にあるか */
  const owner = new Map();
  for (const [alias, conn] of Object.entries(src)) {
    for (const { name } of conn
      .prepare("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
      .all()) {
      if (!owner.has(name)) owner.set(name, alias);
    }
  }

  const targets = db
    .prepare("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    .all()
    .map((r) => r.name)
    .filter((n) => !isInternal(n));

  const missing = targets.filter((t) => !owner.has(t));
  if (missing.length) log(`⚠ 原本に無いテーブル（空のまま）: ${missing.join(", ")}`);

  // インデックスを外してから入れて、最後に張り直す。organism_records だけで数分変わる。
  const indexes = db
    .prepare(
      "SELECT name, sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL AND tbl_name IN " +
        `(${targets.map(() => "?").join(",")})`,
    )
    .all(...targets);

  // 外部キー: cells -> documents。テーブルを名前順に入れるので投入中は外す。
  // 入れ終わってから foreign_key_check で確かめる。
  const fkWas = db.pragma("foreign_keys", { simple: true });
  db.pragma("foreign_keys = OFF");
  db.pragma("synchronous = OFF");
  let restored = false;
  const restoreIndexes = () => {
    if (restored) return;
    restored = true;
    log(`インデックスを張り直す (${indexes.length})`);
    for (const ix of indexes) {
      try {
        db.exec(ix.sql);
      } catch (e) {
        if (!/already exists/.test(String(e))) throw e;
      }
    }
  };

  try {
    for (const ix of indexes) db.exec(`DROP INDEX IF EXISTS ${qi(ix.name)}`);

    let total = 0;
    for (const table of targets) {
      const alias = owner.get(table);
      if (!alias) continue;
      const conn = src[alias];
      const cols = db.prepare(`PRAGMA table_info(${qi(table)})`).all().map((c) => c.name);
      const srcColsArr = conn.prepare(`PRAGMA table_info(${qi(table)})`).all().map((c) => c.name);
      const srcCols = new Set(srcColsArr);
      const use = cols.filter((c) => srcCols.has(c));
      const dropped = cols.filter((c) => !srcCols.has(c));

      if (alias === "v2") {
        // v2 由来の表（observation_agg/occurrence_agg）は列集合の完全一致を
        // 要求する（コードレビュー指摘: 以前は別関数 `assertV2ColumnsMatchD1` で
        // 投入ループの前に同じ `PRAGMA table_info` の突き合わせを二重に持って
        // いた。ここに一本化する——他の原本は列が欠けていても NULL のまま
        // 続行してよいが、v2 だけは PR #26 以前の13列キー等を確実に検出する
        // ため、不一致なら即エラーにする）。
        const sameSet = dropped.length === 0 && srcColsArr.length === cols.length;
        if (!sameSet) {
          throw new Error(
            `${table} の列集合が D1（web/src/db/schema-cube.ts から生成したスキーマ）と` +
              "一致しない。\n" +
              `  D1:        [${cols.join(", ")}]\n` +
              `  v2.sqlite: [${srcColsArr.join(", ")}]\n` +
              "PR #26 以前の13列キー（imputation/value 列）の可能性がある。" +
              V2_REBUILD_HINT,
          );
        }
      } else if (dropped.length) {
        log(`⚠ ${table}: 原本に無い列は NULL のまま: ${dropped.join(", ")}`);
      }

      const list = use.map(qi).join(",");
      const ins = db.prepare(`INSERT INTO ${qi(table)} (${list}) VALUES (${use.map(() => "?").join(",")})`);
      const sel = conn.prepare(`SELECT ${list} FROM ${qi(table)}`).raw(true);

      db.prepare(`DELETE FROM ${qi(table)}`).run();
      let n = 0;
      db.transaction(() => {
        for (const row of sel.iterate()) {
          ins.run(row);
          n++;
        }
      })();
      total += n;
      log(`${table} ← ${alias}: ${n.toLocaleString()} 行`);
    }

    restoreIndexes();

    const violations = db.pragma("foreign_key_check");
    if (violations.length) {
      throw new Error(`外部キー違反 ${violations.length} 件: ${JSON.stringify(violations.slice(0, 3))}`);
    }

    db.prepare(
      "INSERT INTO _seed_state (key, value, updated_at) VALUES ('sources', ?, ?) " +
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
    ).run(fp, new Date().toISOString());
    log(`完了: ${targets.length} テーブル / ${total.toLocaleString()} 行`);
  } finally {
    restoreIndexes();
    db.pragma(`foreign_keys = ${fkWas ? "ON" : "OFF"}`);
    for (const c of Object.values(src)) c.close();
    db.close();
  }
}

main();
