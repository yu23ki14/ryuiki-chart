#!/usr/bin/env node
/**
 * ローカル D1 と本番 D1 を表ごとに指紋で比べる。
 *   node diff-tables.mjs            # 自己テスト（ローカルを2回読んで比べる。差は0のはず）
 *   node diff-tables.mjs --remote   # 本番と比べる（CLOUDFLARE_ACCOUNT_ID があればそのまま wrangler に渡る）
 * 指紋: n=件数 / l*=real 以外の列の total(length(quote(col))) / s_<col>=数値列の total(col)
 * real 列の quote は書式がローカルと D1 で違うので長さに入れず、合計だけ（相対 1e-9 で比較）。
 */
import { Database, findLocalD1, qi, isInternal, wranglerRemote } from "./common.mjs";

const REMOTE = process.argv.includes("--remote");
const LEN_TERMS = 20; // 1式あたりの quote 項数（式の深さ 100 に余裕）
const ITEMS_PER_STMT = 40; // 1 SELECT の出力列数
const BATCH_BYTES = 50_000; // 1回の wrangler 呼び出しの SQL 長

const db = new Database(findLocalD1(), { readonly: true, fileMustExist: true });
const localTables = db.prepare("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").all()
  .map((r) => r.name).filter((n) => !isInternal(n));

const isReal = (t) => /REAL|FLOA|DOUB/i.test(t);
const isNum = (t) => /INT|REAL|FLOA|DOUB|NUMERIC|DECIMAL/i.test(t);

function statementsFor(table) {
  const cols = db.prepare(`PRAGMA table_info(${qi(table)})`).all();
  const items = [["n", "count(*)"]];
  const lenCols = cols.filter((c) => !isReal(c.type ?? ""));
  for (let i = 0, k = 0; i < lenCols.length; i += LEN_TERMS, k++) {
    items.push([`l${k}`, "total(" + lenCols.slice(i, i + LEN_TERMS).map((c) => `length(quote(${qi(c.name)}))`).join("+") + ")"]);
  }
  for (const c of cols) if (isNum(c.type ?? "")) items.push([`s_${c.name}`, `total(${qi(c.name)})`]);
  const stmts = [];
  for (let i = 0; i < items.length; i += ITEMS_PER_STMT) {
    const part = items.slice(i, i + ITEMS_PER_STMT);
    stmts.push(`SELECT ${part.map(([a, e]) => `${e} AS ${qi(a)}`).join(", ")} FROM ${qi(table)}`);
  }
  return stmts;
}

const runLocal = (stmts) => stmts.map((s) => db.prepare(s).get());
function runRemote(stmts) {
  const res = [];
  let i = 0;
  while (i < stmts.length) {
    let j = i, size = 0;
    while (j < stmts.length && (j === i || size + stmts[j].length < BATCH_BYTES)) size += stmts[j++].length + 2;
    const out = wranglerRemote(stmts.slice(i, j).join(";\n"));
    if (out.length !== j - i) throw new Error(`結果数が合わない: ${out.length} != ${j - i}`);
    for (const o of out) res.push(o.results[0]);
    i = j;
  }
  return res;
}

let otherTables;
let runOther;
if (REMOTE) {
  const out = wranglerRemote("SELECT name FROM sqlite_master WHERE type='table'");
  otherTables = out[0].results.map((r) => r.name).filter((n) => !isInternal(n)).sort();
  runOther = runRemote;
} else {
  otherTables = [...localTables];
  runOther = runLocal;
}
const common = localTables.filter((t) => otherTables.includes(t));
const diffs = [];
const near = (a, b) => Math.abs(a - b) <= 1e-9 * Math.max(1, Math.abs(a), Math.abs(b));

for (const [idx, t] of common.entries()) {
  const stmts = statementsFor(t);
  const a = Object.assign({}, ...runLocal(stmts));
  let b;
  try { b = Object.assign({}, ...runOther(stmts)); }
  catch (e) { diffs.push([t, [`エラー: ${String(e.message).split("\n")[0]}`]]); continue; }
  const bad = [];
  for (const k of Object.keys(a)) {
    const ok = k.startsWith("s_") ? near(Number(a[k]), Number(b[k])) : a[k] === b[k];
    if (!ok) bad.push(`${k}: ローカル ${a[k]} / 相手 ${b[k]}`);
  }
  if (bad.length) diffs.push([t, bad]);
  process.stderr.write(`  ${idx + 1}/${common.length}\r`);
}

console.log(`## 違う表 (${diffs.length} / ${common.length})`);
for (const [t, bad] of diffs) console.log(`- ${t}\n    ${bad.join("\n    ")}`);
console.log("## ローカルにだけある表");
console.log(localTables.filter((t) => !otherTables.includes(t)).join(" ") || "(なし)");
console.log("## 本番にだけある表");
console.log(otherTables.filter((t) => !localTables.includes(t)).join(" ") || "(なし)");
console.log("## 違う表名");
console.log(diffs.map(([t]) => t).join(" "));
