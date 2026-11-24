/**
 * ベクトル検索スクリプトの共通部分（設計: docs/plans/TATSUGO_KOHO_VECTOR.md §5）。
 * - 設定: src/lib/vector/config.json
 * - 入力: cells.sqlite の document_articles（読み取り専用）。D1 に載るのと同じ記事（m13 が article_id を決める）
 * - 埋め込み: AI Gateway の OpenAI 互換 /compat/embeddings（新しい API トークンは作らない。web/.env.local の AI_GATEWAY_*）
 * - キャッシュ: data/vector/cache.sqlite（gitignore 済み。再作成できる生成物）
 */
import fs from "node:fs";
import path from "node:path";
import { parseArgs as nodeParseArgs } from "node:util";
import { Database, WEB, loadEnvFile } from "../d1/common.mjs";
import { chunksForArticle } from "../../src/lib/vector/chunk.mjs";

export { WEB, wrangler } from "../d1/common.mjs";
export { Database };
export const REPO = path.resolve(WEB, "..");

export const CONFIG = JSON.parse(fs.readFileSync(path.join(WEB, "src/lib/vector/config.json"), "utf8"));
/** 作業ディレクトリ。worktree から本体のキャッシュを使うときは RYUIKI_VECTOR_DIR で上書き。 */
export const VECTOR_DIR = process.env.RYUIKI_VECTOR_DIR || path.join(REPO, "data", "vector");

const OPTIONS = {
  cells: { type: "string" }, model: { type: "string" }, models: { type: "string" }, limit: { type: "string" }, questions: { type: "string" },
  wait: { type: "string" }, "doc-prefix": { type: "string" }, "article-ids-file": { type: "string" },
  execute: { type: "boolean" }, init: { type: "boolean" }, withdraw: { type: "boolean" }, remote: { type: "boolean" },
  detail: { type: "boolean" }, "dry-run": { type: "boolean" },
};
export const parseArgs = (argv) => nodeParseArgs({ args: argv, options: OPTIONS, strict: true }).values;

/** モデルごとの設定（config.json の candidates。無ければ最上位の値）。 */
export function modelConfig(model = CONFIG.model) {
  const c = CONFIG.candidates?.[model];
  if (c) return { model, dimensions: c.dimensions, query_prefix: c.query_prefix ?? "", short: c.short };
  if (model === CONFIG.model) return { model, dimensions: CONFIG.dimensions, query_prefix: CONFIG.query_prefix ?? "", short: "main" };
  throw new Error(`未知のモデル: ${model}`);
}

export const loadEnv = () => loadEnvFile();

export function openCache(file = path.join(VECTOR_DIR, "cache.sqlite")) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const db = new Database(file);
  db.pragma("journal_mode = WAL");
  db.exec(`CREATE TABLE IF NOT EXISTS embedding(
    model TEXT NOT NULL, chunk_sha TEXT NOT NULL, dims INTEGER NOT NULL, vec BLOB NOT NULL, created_at TEXT NOT NULL,
    PRIMARY KEY (model, chunk_sha))`);
  return db;
}

export const toBlob = (arr) => Buffer.from(new Float32Array(arr).buffer);
export const fromBlob = (b) => new Float32Array(b.buffer, b.byteOffset, b.byteLength / 4);

/** cells.sqlite（読み取り専用）から記事を読む。year は発行年（periodical_issues.year_month）。 */
export function readArticles(cellsPath) {
  const db = new Database(cellsPath, { readonly: true, fileMustExist: true });
  try {
    return db
      .prepare(
        `SELECT a.article_id, a.issue_id, a.doc_id, a.source_id, a.region_id, a.kind, a.title, a.section, a.body_text,
                a.body_sha256, a.issue_page_from, CAST(substr(i.year_month, 1, 4) AS INTEGER) AS year
           FROM document_articles a LEFT JOIN periodical_issues i ON i.issue_id = a.issue_id
          ORDER BY a.doc_id, a.page_from, a.article_id`,
      )
      .all();
  } finally {
    db.close();
  }
}

export function allChunks(articles, model = CONFIG.model) {
  const out = [];
  for (const a of articles) out.push(...chunksForArticle(a, { model, chunkerVersion: CONFIG.chunker_version }));
  return out;
}

/** 入力が大きすぎる・件数が合わないときだけ二分割して再試行する（認証・形式の誤りは分けても直らないので即 throw）。 */
class SplitBatch extends Error {}
const TOO_BIG = /token|too (long|large|big)|exceed|length|limit/i;

/** AI Gateway 経由の埋め込み。429/5xx は待って再試行、413・入力上限・件数不一致だけ半分にして再試行、他の 4xx は即 throw。 */
export async function embedTexts(texts, model, env = loadEnv()) {
  const acct = env.AI_GATEWAY_ACCOUNT_ID;
  const token = env.AI_GATEWAY_TOKEN;
  if (!acct || !token) throw new Error("AI_GATEWAY_ACCOUNT_ID / AI_GATEWAY_TOKEN が未設定（web/.env.local）");
  const url = `https://gateway.ai.cloudflare.com/v1/${acct}/${env.AI_GATEWAY_NAME || "default"}/compat/embeddings`;
  const call = async (batch) => {
    for (let attempt = 0; attempt < 4; attempt++) {
      const r = await fetch(url, {
        method: "POST",
        headers: { "cf-aig-authorization": `Bearer ${token}`, authorization: `Bearer ${token}`, "content-type": "application/json" },
        body: JSON.stringify({ model: `workers-ai/${model}`, input: batch }),
      });
      if (r.ok) {
        const d = await r.json();
        if (!d.data || d.data.length !== batch.length) throw new SplitBatch(`件数が合わない: ${batch.length} → ${d.data?.length}`);
        return d.data.sort((a, b) => a.index - b.index).map((x) => x.embedding);
      }
      if (r.status === 429 || r.status >= 500) {
        await new Promise((res) => setTimeout(res, 1500 * (attempt + 1)));
        continue;
      }
      const body = (await r.text()).slice(0, 200);
      const msg = `埋め込み ${r.status}: ${body}`;
      if (r.status === 413 || ((r.status === 400 || r.status === 422) && TOO_BIG.test(body))) throw new SplitBatch(msg);
      throw new Error(msg);
    }
    throw new Error("埋め込みのリトライ上限（429/5xx）");
  };
  const run = async (batch) => {
    try {
      return await call(batch);
    } catch (e) {
      if (!(e instanceof SplitBatch) || batch.length === 1) throw e;
      const h = batch.length >> 1;
      return [...(await run(batch.slice(0, h))), ...(await run(batch.slice(h)))];
    }
  };
  return run(texts);
}

/** キャッシュに無いものだけ埋め込み、バッチごとにコミットする。items: [{key, text}] → 件数の内訳。 */
export async function ensureEmbeddings(cache, items, model, { batch = 32, concurrency = 4, log = () => {} } = {}) {
  const have = new Set(cache.prepare("SELECT chunk_sha FROM embedding WHERE model = ?").pluck().all(model));
  const seen = new Set();
  const todo = items.filter((it) => {
    if (seen.has(it.key)) return false;
    seen.add(it.key);
    return !have.has(it.key);
  });
  const ins = cache.prepare("INSERT OR REPLACE INTO embedding(model, chunk_sha, dims, vec, created_at) VALUES (?,?,?,?,?)");
  const batches = [];
  for (let i = 0; i < todo.length; i += batch) batches.push(todo.slice(i, i + batch));
  let done = 0;
  let next = 0;
  const worker = async () => {
    while (next < batches.length) {
      const b = batches[next++];
      const vecs = await embedTexts(b.map((x) => x.text), model);
      cache.transaction(() => b.forEach((x, i) => ins.run(model, x.key, vecs[i].length, toBlob(vecs[i]), new Date().toISOString())))();
      done += b.length;
      if (done % 320 < batch) log(`  ${done}/${todo.length}`);
    }
  };
  await Promise.all(Array.from({ length: concurrency }, worker));
  return { unique: seen.size, embedded: todo.length, cached: seen.size - todo.length };
}

/** そのモデルの埋め込みを全部読む（chunk_sha → Float32Array）。 */
export function loadVectors(cache, model) {
  const m = new Map();
  for (const r of cache.prepare("SELECT chunk_sha, vec FROM embedding WHERE model = ?").iterate(model)) m.set(r.chunk_sha, fromBlob(r.vec));
  return m;
}
