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
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.resolve(__dirname, "..");
const REPO = path.resolve(WEB, "..");
const DB_DIR = process.env.RYUIKI_DB_DIR ?? path.join(REPO, "data", "db");
const D1_STATE = path.join(WEB, ".wrangler", "state", "v3", "d1", "miniflare-D1DatabaseObject");

/** 原本ファイルと、そこに入っているテーブルの引き当て */
const SOURCES = [
  { alias: "ryuiki", file: "ryuiki.sqlite", required: true },
  { alias: "cells", file: "cells.sqlite", required: true },
  { alias: "derived", file: "derived.sqlite", required: true },
];

/** マイグレーションと wrangler / miniflare の管理テーブル。シードの対象外。 */
const SKIP_TABLES = new Set(["d1_migrations", "_seed_state"]);
const isInternal = (name) => name.startsWith("_cf_") || name.startsWith("sqlite_") || SKIP_TABLES.has(name);

const t0 = Date.now();
const log = (...a) => console.log(`[seed ${((Date.now() - t0) / 1000).toFixed(1)}s]`, ...a);
const qi = (n) => `"${String(n).replace(/"/g, '""')}"`;

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
  if (files.length !== 1) {
    throw new Error(`ローカル D1 の SQLite ファイルを一意に決められない: ${JSON.stringify(files)}`);
  }
  return files[0];
}

/** 原本の同一性。中身のハッシュは 1.1GB 読むので、サイズと mtime で足りる。 */
function fingerprint() {
  const parts = [];
  for (const s of SOURCES) {
    const p = path.join(DB_DIR, s.file);
    if (!fs.existsSync(p)) {
      if (!s.required) continue;
      throw new Error(
        `原本が無い: ${p}\n` +
          (s.file === "derived.sqlite"
            ? "集計 DB は `npm run build:derived` で作る（初回のみ・約1分）。"
            : "data/db/ に原本を置く。"),
      );
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
      const srcCols = new Set(conn.prepare(`PRAGMA table_info(${qi(table)})`).all().map((c) => c.name));
      const use = cols.filter((c) => srcCols.has(c));
      const dropped = cols.filter((c) => !srcCols.has(c));
      if (dropped.length) log(`⚠ ${table}: 原本に無い列は NULL のまま: ${dropped.join(", ")}`);

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
