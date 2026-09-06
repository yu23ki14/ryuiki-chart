#!/usr/bin/env node
/**
 * ローカル D1 と本番 D1 の行数を全テーブルで突き合わせる。
 *
 *   pnpm run db:verify:remote
 *
 * 投入は 80 本以上の .sql をネットワーク越しに流すので、途中で落ちた／二重に流した
 * ことに気付けるようにしておく。差があったテーブルだけを出す。
 */
import Database from "better-sqlite3";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.resolve(__dirname, "..");
const D1_STATE = path.join(WEB, ".wrangler", "state", "v3", "d1", "miniflare-D1DatabaseObject");
const DB_NAME = process.argv[2] ?? "ryuiki";

const isInternal = (n) =>
  n.startsWith("_cf_") || n.startsWith("sqlite_") || n === "d1_migrations" || n === "_seed_state";
const qi = (n) => `"${String(n).replace(/"/g, '""')}"`;

const file = fs
  .readdirSync(D1_STATE)
  .filter((f) => f.endsWith(".sqlite") && f !== "metadata.sqlite")
  .map((f) => path.join(D1_STATE, f))[0];
const db = new Database(file, { readonly: true, fileMustExist: true });

const tables = db
  .prepare("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
  .all()
  .map((r) => r.name)
  .filter((n) => !isInternal(n));

const local = Object.fromEntries(
  tables.map((t) => [t, db.prepare(`SELECT count(*) AS c FROM ${qi(t)}`).get().c]),
);
db.close();

/** D1 に一度に投げるサブクエリの数。SQL が長くなりすぎないように割る。 */
const BATCH = 15;
const remote = {};
for (let i = 0; i < tables.length; i += BATCH) {
  const chunk = tables.slice(i, i + BATCH);
  const sql = "SELECT " + chunk.map((t) => `(SELECT count(*) FROM ${qi(t)}) AS ${qi(t)}`).join(", ");
  const out = execFileSync(
    "wrangler",
    ["d1", "execute", DB_NAME, "--remote", "-y", "--json", "--command", sql],
    { encoding: "utf8", maxBuffer: 32 * 1024 * 1024, cwd: WEB },
  );
  Object.assign(remote, JSON.parse(out.slice(out.indexOf("[")))[0].results[0]);
  process.stderr.write(`  ${Math.min(i + BATCH, tables.length)}/${tables.length}\r`);
}

let bad = 0;
for (const t of tables) {
  if (local[t] !== remote[t]) {
    bad++;
    const diff = remote[t] - local[t];
    console.log(`✗ ${t}: ローカル ${local[t].toLocaleString()} / 本番 ${remote[t].toLocaleString()} (${diff > 0 ? "+" : ""}${diff.toLocaleString()})`);
  }
}
const rows = tables.reduce((a, t) => a + local[t], 0);
console.log(
  bad === 0
    ? `✔ ${tables.length} テーブル / ${rows.toLocaleString()} 行 すべて一致`
    : `✗ ${bad} テーブルで不一致`,
);
process.exit(bad === 0 ? 0 : 1);
