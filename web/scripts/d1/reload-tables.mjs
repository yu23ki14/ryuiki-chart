#!/usr/bin/env node
/**
 * 指定した表を本番で空にし、dist/d1/ の該当ファイルを流す。
 *   node reload-tables.mjs <table...>             # dry-run（流すコマンドとファイルを表示するだけ）
 *   node reload-tables.mjs <table...> --execute   # 本番で実行
 * 外部キー: notes -> documents。消すときは notes が先、入れるときは documents が先。
 * 最後に表ごとの件数をローカルと突き合わせる。
 */
import { Database, WEB, findLocalD1, qi, wranglerRemote, DB_NAME } from "./common.mjs";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

const args = process.argv.slice(2);
const EXECUTE = args.includes("--execute");
const requested = args.filter((a) => !a.startsWith("--"));
if (!requested.length) { console.error("使い方: reload-tables.mjs <table...> [--execute]"); process.exit(2); }

const DIST = path.join(WEB, "dist", "d1");
const CHUNK = 100_000;
// 入れる順（先に入れる）。消す順はこの逆。
const rank = (t) => (t === "documents" ? 0 : t === "notes" ? 2 : 1);
const insertOrder = [...new Set(requested)].sort((a, b) => rank(a) - rank(b));
const deleteOrder = [...insertOrder].reverse();

const files = fs.existsSync(DIST) ? fs.readdirSync(DIST).filter((f) => /^\d{4}_.+\.sql$/.test(f)).sort() : [];
const filesOf = (t) => files.filter((f) => f.replace(/^\d{4}_/, "").replace(/\.sql$/, "") === t);
const missing = insertOrder.filter((t) => !filesOf(t).length);
if (missing.length) {
  console.error(`dist/d1 にファイルが無い: ${missing.join(" ")}（${DIST}）。先に db:export --table で出す。`);
  process.exit(1);
}

const wr = (extra) => ["pnpm", "wrangler", "d1", "execute", DB_NAME, "--remote", "-y", ...extra];
const show = (a) => console.log("  $ " + a.join(" "));

console.log(`# ${EXECUTE ? "実行" : "dry-run"}: 削除順 ${deleteOrder.join(" ")} / 投入順 ${insertOrder.join(" ")}`);
for (const t of deleteOrder) {
  console.log(`- 空にする ${t}（${CHUNK} 行ずつ繰り返す）`);
  show(wr(["--json", "--command", `DELETE FROM ${qi(t)} WHERE rowid IN (SELECT rowid FROM ${qi(t)} LIMIT ${CHUNK})`]));
}
for (const t of insertOrder) for (const f of filesOf(t)) {
  console.log(`- 流す ${f}`);
  show(wr([`--file=${path.join("dist/d1", f)}`]));
}
if (!EXECUTE) { console.log("\n(dry-run。--execute を付けると本番で実行する)"); process.exit(0); }

const run = (a, opts = {}) =>
  execFileSync(a[0], a.slice(1), { encoding: "utf8", cwd: WEB, env: process.env, maxBuffer: 256 * 1024 * 1024, ...opts });

for (const t of deleteOrder) {
  let total = 0;
  for (;;) {
    const out = wranglerRemote(`DELETE FROM ${qi(t)} WHERE rowid IN (SELECT rowid FROM ${qi(t)} LIMIT ${CHUNK})`);
    const n = out[0].meta?.changes ?? 0;
    total += n;
    console.log(`  ${t}: ${total.toLocaleString()} 行削除`);
    if (n < CHUNK) break;
  }
}
for (const t of insertOrder) for (const f of filesOf(t)) {
  for (let attempt = 1; ; attempt++) {
    try { run(wr([`--file=${path.join("dist/d1", f)}`]), { stdio: ["ignore", "pipe", "inherit"] }); console.log(`  OK ${f}`); break; }
    catch (e) {
      console.error(`  失敗 ${f} (${attempt}/3)`);
      if (attempt >= 3) { console.error("3回失敗。中断する（この表は空か中途半端）。"); process.exit(1); }
    }
  }
}

const db = new Database(findLocalD1(), { readonly: true, fileMustExist: true });
let bad = 0;
const rows = wranglerRemote(insertOrder.map((t) => `SELECT count(*) AS c FROM ${qi(t)}`).join(";\n"));
insertOrder.forEach((t, i) => {
  const l = db.prepare(`SELECT count(*) AS c FROM ${qi(t)}`).get().c;
  const r = rows[i].results[0].c;
  if (l !== r) bad++;
  console.log(`${l === r ? "✔" : "✗"} ${t}: ローカル ${l.toLocaleString()} / 本番 ${r.toLocaleString()}`);
});
process.exit(bad ? 1 : 0);
