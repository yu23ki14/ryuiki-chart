/**
 * 記事をチャンクに分け、キャッシュに無いものだけ埋め込む。Cloudflare には何も書かない。
 *   node scripts/vector/embed.mjs --cells <cells.sqlite> [--model @cf/baai/bge-m3] [--limit N] [--dry-run]
 */
import { CONFIG, REPO, allChunks, ensureEmbeddings, modelConfig, openCache, parseArgs, readArticles } from "./lib.mjs";
import path from "node:path";

const args = parseArgs(process.argv.slice(2));
const cells = args.cells || path.join(REPO, "data/db/cells.sqlite");
const model = args.model || CONFIG.model;
modelConfig(model);
const articles = readArticles(cells);
let chunks = allChunks(articles, model);
if (args.limit) chunks = chunks.slice(0, Number(args.limit));
const targetArticles = new Set(chunks.map((c) => c.article_id)).size;
const chars = chunks.reduce((s, c) => s + c.text.length, 0);
console.log(`記事 ${articles.length} 件 → 対象 ${targetArticles} 件・チャンク ${chunks.length}（${chars} 字）model=${model}`);
if (args["dry-run"]) process.exit(0);
const cache = openCache();
const t0 = Date.now();
const r = await ensureEmbeddings(cache, chunks.map((c) => ({ key: c.chunk_sha, text: c.text })), model, { log: console.log });
console.log(`一意 ${r.unique}・キャッシュ済み ${r.cached}・今回埋め込み ${r.embedded}・${((Date.now() - t0) / 1000).toFixed(1)} 秒`);
