/**
 * 望ましい状態（キャッシュ済みの埋め込み）と前回のマニフェストの差を、Vectorize へ入れる／消す。
 * 既定は dry-run（件数を出すだけ）。--execute を付けたときだけ wrangler（OAuth ログイン済み）を呼ぶ。
 * 実行するのは本番反映のときの人。手順は DEPLOYMENT.md「広報たつごうのベクトル検索」。
 *
 *   node scripts/vector/sync.mjs --cells <cells.sqlite> [--execute]          差分を upsert / delete
 *   node scripts/vector/sync.mjs --init [--execute]                          メタデータインデックスの作成（初回の投入の前）
 *   node scripts/vector/sync.mjs --withdraw --doc-prefix <doc_id> | --article-ids-file <file> [--execute]   取り下げ
 *
 * 取り下げの article_id は、D1 の行を消す前に控えておく（D1 を消した後はマニフェストの article_id から引く）。
 * Vectorize の upsert は wrangler の vectorize upsert（ndjson）、削除は delete-vectors --ids。REST のトークンは使わない。
 */
import fs from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { CONFIG, REPO, VECTOR_DIR, WEB, allChunks, getVec, modelConfig, openCache, parseArgs, readArticles } from "./lib.mjs";
import { applyWithdraw, desiredState, diffState, idsToWithdraw, toNdjson, vectorRow } from "./sync-lib.mjs";

const args = parseArgs(process.argv.slice(2));
const execute = Boolean(args.execute);
const index = CONFIG.index_name;
const dir = path.join(VECTOR_DIR, index);
const manifestPath = path.join(dir, "manifest.jsonl");
const UPSERT_BATCH = 1000;
const DELETE_BATCH = 100;

const wrangler = (...a) => {
  console.log(`$ wrangler ${a.join(" ").slice(0, 160)}`);
  return execFileSync("pnpm", ["wrangler", ...a], { cwd: WEB, encoding: "utf8", stdio: ["ignore", "pipe", "inherit"] });
};

function loadManifest() {
  const m = new Map();
  if (fs.existsSync(manifestPath)) for (const l of fs.readFileSync(manifestPath, "utf8").split("\n")) if (l) { const e = JSON.parse(l); m.set(e.id, e); }
  return m;
}
function saveManifest(m) {
  fs.mkdirSync(dir, { recursive: true });
  const tmp = `${manifestPath}.tmp`;
  fs.writeFileSync(tmp, [...m.values()].map((e) => JSON.stringify(e)).join("\n") + (m.size ? "\n" : ""));
  fs.renameSync(tmp, manifestPath);
}
const note = (s) => console.log(execute ? s : `[dry-run] ${s}`);

if (args.init) {
  // フィルタに使う 4 つ。初回の投入の前に作る（作る前に入れたベクトルには効かない）。
  const props = [["region_id", "string"], ["source_id", "string"], ["year", "number"], ["kind", "string"]];
  for (const [p, t] of props) {
    note(`メタデータインデックス ${index}: ${p} (${t})`);
    if (execute) wrangler("vectorize", "create-metadata-index", index, "--propertyName", p, "--type", t);
  }
  note(`インデックスの作成は本番反映のときに人が行う: wrangler vectorize create ${index} --dimensions=${CONFIG.dimensions} --metric=${CONFIG.metric}`);
  process.exit(0);
}

const manifest = loadManifest();
const cache = openCache();

if (args.withdraw) {
  const articleIds = args["article-ids-file"] ? fs.readFileSync(args["article-ids-file"], "utf8").split("\n").map((s) => s.trim()).filter(Boolean) : [];
  const docPrefixes = args["doc-prefix"] ? String(args["doc-prefix"]).split(",") : [];
  if (!articleIds.length && !docPrefixes.length) throw new Error("--doc-prefix か --article-ids-file が要る");
  const ids = idsToWithdraw(manifest, { articleIds, docPrefixes });
  note(`取り下げ: ${ids.length} ベクトル（マニフェストの ${manifest.size} 件中）`);
  if (execute && ids.length) {
    for (let i = 0; i < ids.length; i += DELETE_BATCH) wrangler("vectorize", "delete-vectors", index, "--ids", ...ids.slice(i, i + DELETE_BATCH));
    const shas = applyWithdraw(manifest, ids);
    saveManifest(manifest);
    const del = cache.prepare("DELETE FROM embedding WHERE chunk_sha = ?");
    cache.transaction(() => { for (const s of shas) del.run(s); })();
    note(`マニフェストとキャッシュから ${ids.length} 件を消した。status.mjs --remote で件数を確かめる`);
  }
  process.exit(0);
}

const cells = args.cells || path.join(REPO, "data/db/cells.sqlite");
const model = CONFIG.model;
modelConfig(model);
const chunks = allChunks(readArticles(cells), model);
const byId = new Map(chunks.map((c) => [c.id, c]));
const d = diffState(desiredState(chunks), manifest);
const missing = d.upsert.filter((id) => !getVec(cache, model, byId.get(id).chunk_sha));
if (missing.length) throw new Error(`埋め込みが無いチャンクが ${missing.length} 件。先に embed.mjs を実行する`);
note(`index=${index} 望ましい ${byId.size}・マニフェスト ${manifest.size} → upsert ${d.upsert.length}・delete ${d.delete.length}・変わらない ${d.unchanged}`);
note(`変わる記事 ${d.changedArticles.length} 件${d.changedArticles.length <= 20 ? ": " + d.changedArticles.join(", ") : "（先頭 20）: " + d.changedArticles.slice(0, 20).join(", ")}`);
if (!execute) process.exit(0);

fs.mkdirSync(dir, { recursive: true });
for (let i = 0, n = 1; i < d.upsert.length; i += UPSERT_BATCH, n++) {
  const part = d.upsert.slice(i, i + UPSERT_BATCH);
  const file = path.join(dir, `upsert-${String(n).padStart(3, "0")}.ndjson`);
  fs.writeFileSync(file, toNdjson(part.map((id) => vectorRow(byId.get(id), getVec(cache, model, byId.get(id).chunk_sha), model))));
  wrangler("vectorize", "upsert", index, "--file", file);
  for (const id of part) manifest.set(id, { id, article_id: byId.get(id).article_id, chunk_sha: byId.get(id).chunk_sha });
  saveManifest(manifest);
}
for (let i = 0; i < d.delete.length; i += DELETE_BATCH) {
  const part = d.delete.slice(i, i + DELETE_BATCH);
  wrangler("vectorize", "delete-vectors", index, "--ids", ...part);
  for (const id of part) manifest.delete(id);
  saveManifest(manifest);
}
note(`完了。マニフェスト ${manifest.size} 件。反映は非同期なので status.mjs --remote で件数が一致するまで待つ`);
