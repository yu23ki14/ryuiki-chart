#!/usr/bin/env node
/**
 * ローカル D1 の中身を、本番 D1 に流し込める .sql に書き出す。
 *
 *   node scripts/export-d1-sql.mjs [--out dist/d1] [--table <名前,名前…>] [--db <path>] [--max-mb 20]
 *
 * 既定ではローカル D1 (.wrangler/…) を読む。`--db` で任意の SQLite を指定できる
 * （原本 data/db/ryuiki.sqlite から一部のテーブルだけ本番へ足したいとき。
 *   ローカル D1 を 1.2GB 作り直さずに済む）。列はマイグレーション後の本番と一致していること。
 *
 * 出したファイルは番号順に:
 *   pnpm wrangler d1 execute ryuiki --remote --file=dist/d1/0001_documents.sql
 *
 * なぜ `wrangler d1 export` を使わないか:
 *   `wrangler d1 export ryuiki --local --output=...` は全件を一度に組み立てるので、
 *   organism_records (82万行) や DB 全体では workerd の V8 がヒープ上限に当たって落ちる
 *   （"Reached heap limit"）。ここでは 1 行ずつ流して書き出す。
 *
 * 出力の作り:
 *   - 値は SQL リテラルで埋め込む（バインドではないので D1 の 100 パラメータ制限は無関係）
 *   - 複数行を 1 つの INSERT にまとめる。D1 の SQL 文長 100KB に対して余裕を見て 64KB で切る
 *   - ファイルは既定 20MB ごとに分ける。90MB にすると `wrangler d1 execute --remote --file` の
 *     アップロード（R2 への PUT）がほぼ確実に fetch failed で落ちる。20MB なら通る
 *   - documents -> cells の外部キーがあるので、参照される側を先に出す
 */
import Database from "better-sqlite3";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.resolve(__dirname, "..");
const D1_STATE = path.join(WEB, ".wrangler", "state", "v3", "d1", "miniflare-D1DatabaseObject");

/** D1 の SQL 文長上限は 100KB。安全側で切る。文字数ではなく **バイト数** で測ること
 *  （日本語は UTF-8 で 1 文字 3 バイト。文字数で測ると 3 倍近くなり SQLITE_TOOBIG になる）。 */
const MAX_STATEMENT_BYTES = 64 * 1024;

/** 外部キーの親を先に。ここに無いテーブルは名前順。 */
const FIRST = ["documents"];

/** マイグレーション・シード状態・miniflare の内部テーブルは出さない。 */
const isInternal = (n) =>
  n.startsWith("_cf_") || n.startsWith("sqlite_") || n === "d1_migrations" || n === "_seed_state";

const arg = (name, fallback) => {
  const i = process.argv.indexOf(name);
  return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : fallback;
};

const t0 = Date.now();
const log = (...a) => console.log(`[export ${((Date.now() - t0) / 1000).toFixed(1)}s]`, ...a);
const qi = (n) => `"${String(n).replace(/"/g, '""')}"`;

/** SQLite の値を SQL リテラルにする。 */
function lit(v) {
  if (v === null || v === undefined) return "NULL";
  if (typeof v === "number") return Number.isFinite(v) ? String(v) : "NULL";
  if (typeof v === "bigint") return v.toString();
  if (Buffer.isBuffer(v) || v instanceof Uint8Array) return `X'${Buffer.from(v).toString("hex")}'`;
  return `'${String(v).replace(/'/g, "''")}'`;
}

function findLocalD1() {
  if (!fs.existsSync(D1_STATE)) {
    throw new Error(`ローカル D1 が無い: ${D1_STATE}\n先に \`pnpm run db:setup\` を実行する。`);
  }
  const files = fs
    .readdirSync(D1_STATE)
    .filter((f) => f.endsWith(".sqlite") && f !== "metadata.sqlite")
    .map((f) => path.join(D1_STATE, f));
  if (files.length !== 1) throw new Error(`D1 の SQLite を一意に決められない: ${JSON.stringify(files)}`);
  return files[0];
}

/** 1 つの UPDATE で追記する文字数。日本語 3 バイト/文字でも 24KB 程度に収まる。 */
const BIG_CHUNK_CHARS = 8000;

/**
 * 1 行だけで D1 の SQL 文長上限に収まらない行を書く。
 * 大きい TEXT 列を空で INSERT してから `col = col || '…'` で継ぎ足す。
 * 継ぎ足す先の行は主キーで特定する。主キーが無いテーブルは分割しない列すべてで特定し、
 * それが一意にならなければ黙って壊れるより落とす。
 */
function writeBigRow(w, db, table, cols, pkCols, row, head) {
  const sizes = cols.map((c, i) => ({ i, c, b: Buffer.byteLength(lit(row[i]), "utf8") }));
  const chunked = new Set();
  let rest = sizes.reduce((acc, x) => acc + x.b + 1, 0) + Buffer.byteLength(head, "utf8");
  for (const s of [...sizes].sort((a, b) => b.b - a.b)) {
    if (rest <= MAX_STATEMENT_BYTES) break;
    if (pkCols.includes(s.c)) continue; // 主キーは分割できない
    if (typeof row[s.i] !== "string") continue; // 追記できるのは TEXT だけ
    chunked.add(s.i);
    rest -= s.b - 2; // '' に置き換わる
  }
  if (rest > MAX_STATEMENT_BYTES) {
    throw new Error(`${table}: 分割しても 1 行が ${rest} バイトあり D1 に入らない`);
  }

  const keyIdx = pkCols.length
    ? cols.map((c, i) => i).filter((i) => pkCols.includes(cols[i]))
    : cols.map((c, i) => i).filter((i) => !chunked.has(i));
  const where = keyIdx.map((i) => `${qi(cols[i])} IS ${lit(row[i])}`).join(" AND ");
  const hits = db.prepare(`SELECT count(*) AS c FROM ${qi(table)} WHERE ${where}`).get().c;
  if (hits !== 1) throw new Error(`${table}: 大きい行を一意に特定できない (${hits} 行に一致)`);

  w.write(head + `(${cols.map((c, i) => (chunked.has(i) ? "''" : lit(row[i]))).join(",")});\n`);
  for (const i of chunked) {
    const text = String(row[i]);
    for (let p = 0; p < text.length; p += BIG_CHUNK_CHARS) {
      const part = text.slice(p, p + BIG_CHUNK_CHARS).replace(/'/g, "''");
      w.write(`UPDATE ${qi(table)} SET ${qi(cols[i])} = ${qi(cols[i])} || '${part}' WHERE ${where};\n`);
    }
  }
  log(`  ${table}: 1 行を ${chunked.size} 列に分けて追記`);
}

/** 連番つきでファイルを切り替えながら書くライタ */
function makeWriter(outDir, maxBytes) {
  let seq = 0;
  let fd = null;
  let written = 0;
  let name = "";

  const open = (table) => {
    seq += 1;
    name = `${String(seq).padStart(4, "0")}_${table}.sql`;
    fd = fs.openSync(path.join(outDir, name), "w");
    written = 0;
    write(`-- 流域カルテ: ${table} (part ${seq})\nPRAGMA defer_foreign_keys=TRUE;\n`);
  };
  const write = (s) => {
    const buf = Buffer.from(s, "utf8");
    fs.writeSync(fd, buf);
    written += buf.length;
  };
  const close = () => {
    if (fd !== null) {
      fs.closeSync(fd);
      log(`  ${name} ${(written / 1e6).toFixed(1)}MB`);
      fd = null;
    }
  };
  return {
    startTable: (table) => {
      close();
      open(table);
    },
    /** 上限に達していたら同じテーブルの続きを次のファイルへ */
    rollIfNeeded: (table) => {
      if (written >= maxBytes) {
        close();
        open(table);
      }
    },
    write,
    close,
    get files() {
      return seq;
    },
  };
}

function main() {
  const outDir = path.resolve(WEB, arg("--out", "dist/d1"));
  // カンマ区切りで複数指定できる（water_* だけを足す、のような使い方）
  const onlyArg = arg("--table", null);
  const only = onlyArg ? onlyArg.split(",").map((t) => t.trim()).filter(Boolean) : null;
  const maxBytes = Number(arg("--max-mb", "20")) * 1e6;

  fs.rmSync(outDir, { recursive: true, force: true });
  fs.mkdirSync(outDir, { recursive: true });

  const dbArg = arg("--db", null);
  const dbPath = dbArg ? path.resolve(WEB, dbArg) : findLocalD1();
  log(`読み込み元: ${dbPath}`);
  const db = new Database(dbPath, { readonly: true, fileMustExist: true });

  const all = db
    .prepare("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    .all()
    .map((r) => r.name)
    .filter((n) => !isInternal(n));
  const tables = [...FIRST.filter((t) => all.includes(t)), ...all.filter((t) => !FIRST.includes(t))].filter(
    (t) => !only || only.includes(t),
  );
  if (only) {
    const missing = only.filter((t) => !all.includes(t));
    if (missing.length) throw new Error(`テーブルが無い: ${missing.join(", ")}`);
  }

  const w = makeWriter(outDir, maxBytes);
  let grandTotal = 0;

  for (const table of tables) {
    const info = db.prepare(`PRAGMA table_info(${qi(table)})`).all();
    const cols = info.map((c) => c.name);
    const pkCols = info.filter((c) => c.pk > 0).map((c) => c.name);
    const colList = cols.map(qi).join(",");
    const head = `INSERT INTO ${qi(table)} (${colList}) VALUES `;

    w.startTable(table);
    const sel = db.prepare(`SELECT ${colList} FROM ${qi(table)}`).raw(true);

    let batch = [];
    let batchBytes = 0;
    let n = 0;

    const flush = () => {
      if (!batch.length) return;
      w.write(head + batch.join(",") + ";\n");
      batch = [];
      batchBytes = 0;
      w.rollIfNeeded(table);
    };

    const headBytes = Buffer.byteLength(head, "utf8");
    for (const row of sel.iterate()) {
      const tuple = `(${row.map(lit).join(",")})`;
      const tupleBytes = Buffer.byteLength(tuple, "utf8");
      // 1 行で上限を超える場合はその 1 行だけで 1 文にする
      if (tupleBytes + headBytes > MAX_STATEMENT_BYTES) {
        flush(); // 途中のバッチを先に出してから、この 1 行だけを分割して書く
        writeBigRow(w, db, table, cols, pkCols, row, head);
        n++;
        w.rollIfNeeded(table);
        continue;
      }
      if (batchBytes + tupleBytes + headBytes > MAX_STATEMENT_BYTES) flush();
      batch.push(tuple);
      batchBytes += tupleBytes + 1;
      n++;
    }
    flush();
    grandTotal += n;
    log(`${table}: ${n.toLocaleString()} 行`);
  }

  w.close();
  db.close();
  log(`完了: ${tables.length} テーブル / ${grandTotal.toLocaleString()} 行 -> ${outDir} (${w.files} ファイル)`);
  console.log(
    `\n本番へ流す:\n  for f in ${path.relative(WEB, outDir)}/*.sql; do\n` +
      `    pnpm wrangler d1 execute ryuiki --remote --file="$f" || break\n  done`,
  );
}

main();
