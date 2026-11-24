/**
 * 評価（設計 §9）。キャッシュ済みのベクトルに対して手元で全探索の cosine を取り、上位 5 件の再現率を出す。
 * Vectorize は要らない。質問の埋め込みだけ AI Gateway を呼ぶ（キャッシュされる）。Cloudflare には何も書かない。
 *   node scripts/vector/eval.mjs --cells <cells.sqlite> [--models a,b] [--questions path] [--detail]
 * 前提: embed.mjs をモデルごとに実行済み。
 */
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { CONFIG, REPO, WEB, allChunks, ensureEmbeddings, fromBlob, modelConfig, openCache, parseArgs, readArticles } from "./lib.mjs";
import { sha256 } from "./chunk.mjs";
import { keywordRank, queryTerms, rrf } from "./keyword.mjs";

const require = createRequire(path.join(WEB, "package.json"));
const yaml = require("js-yaml");
const args = parseArgs(process.argv.slice(2));
const cells = args.cells || path.join(REPO, "data/db/cells.sqlite");
const qfile = args.questions || path.join(REPO, "scripts/data/tatsugo_koho_eval.yaml");
const models = (args.models || Object.keys(CONFIG.candidates).join(",")).split(",");
const K = 5;

const questions = yaml.load(fs.readFileSync(qfile, "utf8")).questions;
const articles = readArticles(cells);
const byId = new Map(articles.map((a) => [a.article_id, a]));
const cache = openCache();

const qKey = (model, q) => sha256(`query\n${model}\n${modelConfig(model).query_prefix}${q}`);

function inYears(a, qu) {
  if (!qu.year_from && !qu.year_to) return true;
  return a.year >= (qu.year_from ?? -Infinity) && a.year <= (qu.year_to ?? Infinity);
}

/** 質問ごとのキーワード順位（LIKE と同じ: 生の title / body_text の部分一致）。 */
function keywordFor(qu) {
  const terms = queryTerms(qu.q);
  const pool = articles.filter((a) => a.kind !== "cover_toc" && inYears(a, qu));
  const hits = new Map();
  const df = new Map();
  for (const t of terms) {
    const s = new Set();
    for (const a of pool) if ((a.title ?? "").includes(t) || (a.body_text ?? "").includes(t)) s.add(a.article_id);
    hits.set(t, s);
    df.set(t, s.size);
  }
  return { terms, rank: keywordRank(terms, hits, df, pool.length).slice(0, 50) };
}

function score(ranked, gold) {
  const top = ranked.slice(0, K).map((r) => r.article_id);
  const g = new Set(gold.map((x) => x.article_id));
  const found = top.filter((id) => g.has(id));
  let rr = 0;
  const first = ranked.findIndex((r) => g.has(r.article_id));
  if (first >= 0) rr = 1 / (first + 1);
  return { hit: found.length > 0 ? 1 : 0, frac: g.size ? found.length / g.size : 0, rr, top };
}

const results = [];
for (const model of models) {
  const mc = modelConfig(model);
  const chunks = allChunks(articles, model);
  const getVec = cache.prepare("SELECT vec FROM embedding WHERE model = ? AND chunk_sha = ?");
  const vecs = chunks.map((c) => {
    const r = getVec.get(model, c.chunk_sha);
    if (!r) throw new Error(`キャッシュに無い: ${model} ${c.article_id}。先に embed.mjs --model ${model}`);
    return fromBlob(r.vec);
  });
  await ensureEmbeddings(cache, questions.map((q) => ({ key: qKey(model, q.q), text: mc.query_prefix + q.q })), model, {});
  const norm = (v) => Math.sqrt(v.reduce((s, x) => s + x * x, 0));
  const cn = vecs.map(norm);
  for (const qu of questions) {
    const qv = fromBlob(getVec.get(model, qKey(model, qu.q)).vec);
    const qn = norm(qv);
    const best = new Map();
    for (let i = 0; i < chunks.length; i++) {
      const a = byId.get(chunks[i].article_id);
      if (!inYears(a, qu)) continue;
      let d = 0;
      const v = vecs[i];
      for (let j = 0; j < v.length; j++) d += v[j] * qv[j];
      const cos = d / (cn[i] * qn);
      if (!best.has(a.article_id) || best.get(a.article_id) < cos) best.set(a.article_id, cos);
    }
    const sem = [...best.entries()].sort((a, b) => b[1] - a[1]).slice(0, 50).map(([article_id, s]) => ({ article_id, score: s }));
    const kw = keywordFor(qu);
    const hyb = rrf([sem.map((x) => x.article_id), kw.rank.map((x) => x.article_id)]);
    for (const [mode, ranked] of [["semantic", sem], ["keyword", kw.rank], ["hybrid", hyb]]) {
      results.push({ model, mode, qu, ranked, terms: kw.terms, ...score(ranked, qu.gold ?? []) });
    }
  }
}

// ---- 集計 ----
const pct = (x) => (100 * x).toFixed(0).padStart(3) + "%";
const groups = ["全体", "概念", "固有名詞", "時期"];
const header = ["model", "mode", ...groups.map((g) => `recall@5 ${g}`), "平均再現(複数正解)", "MRR"];
console.log("| " + header.join(" | ") + " |\n|" + header.map(() => "---").join("|") + "|");
const rows = [];
for (const model of models) {
  for (const mode of ["semantic", "keyword", "hybrid"]) {
    const rs = results.filter((r) => r.model === model && r.mode === mode && r.qu.type !== "否定");
    const cell = (g) => {
      const s = g === "全体" ? rs : rs.filter((r) => r.qu.type === g);
      return `${pct(s.reduce((a, r) => a + r.hit, 0) / s.length)} (${s.reduce((a, r) => a + r.hit, 0)}/${s.length})`;
    };
    const frac = rs.reduce((a, r) => a + r.frac, 0) / rs.length;
    const mrr = rs.reduce((a, r) => a + r.rr, 0) / rs.length;
    const line = `| ${mc(model)} | ${mode} | ${groups.map(cell).join(" | ")} | ${pct(frac)} | ${mrr.toFixed(3)} |`;
    console.log(line);
    rows.push(line);
  }
}
function mc(m) {
  return modelConfig(m).short;
}
// 否定の質問: semantic の最上位のスコア（正解のある質問の最上位との比較に使う）
for (const model of models) {
  const neg = results.filter((r) => r.model === model && r.mode === "semantic" && r.qu.type === "否定");
  const pos = results.filter((r) => r.model === model && r.mode === "semantic" && r.qu.type !== "否定");
  const avg = pos.reduce((a, r) => a + r.ranked[0].score, 0) / pos.length;
  console.log(`否定 ${mc(model)}: 最上位の cosine ${neg.map((r) => r.ranked[0].score.toFixed(3)).join(",")}（正解のある質問の最上位の平均 ${avg.toFixed(3)}）`);
}
if (args.detail) {
  for (const r of results.filter((x) => x.qu.type !== "否定" && !x.hit)) {
    console.log(`MISS ${mc(r.model)}/${r.mode} ${r.qu.id} ${r.qu.q} terms=${r.terms.join(",")}\n   top: ${r.top.map((id) => `${id}[${(byId.get(id)?.title ?? "").slice(0, 14)}]`).join(" ")}\n   gold: ${r.qu.gold.map((g) => g.article_id).join(" ")}`);
  }
}
