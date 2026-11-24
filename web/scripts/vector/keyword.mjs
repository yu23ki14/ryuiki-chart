/**
 * キーワード側（hybrid の片側）。質問文を語に分け、title・body_text の LIKE で当たる語の数（IDF 重み）で順位をつける。
 * 評価（eval.mjs）と Worker（src/lib/document-search.ts）が同じ関数を通す。
 * 分かち書きは Intl.Segmenter（Node・Workers の V8 に入っている）。ひらがなだけの語（助詞・活用語尾）は捨てる。
 */
const HIRAGANA_ONLY = /^[ぁ-ゟー]+$/;
const STOP = new Set(["こと", "もの", "ため", "どこ", "いつ", "どう", "どんな", "ください"]);

export function queryTerms(q, max = 6) {
  const seg = new Intl.Segmenter("ja", { granularity: "word" });
  const out = [];
  for (const s of seg.segment(String(q).normalize("NFKC"))) {
    const w = s.segment.trim();
    if (!s.isWordLike || w.length < 2 || HIRAGANA_ONLY.test(w) || STOP.has(w)) continue;
    if (!out.includes(w)) out.push(w);
  }
  // 長い語ほど手がかりが多い。max 個までに絞る（D1 の LIKE の本数の上限）。
  return out.sort((a, b) => b.length - a.length).slice(0, max);
}

/** df: 語 → その語を含む記事の数、N: 記事総数。hits: 語 → 当たった article_id の集合。 */
export function keywordRank(terms, hits, df, N) {
  const score = new Map();
  for (const t of terms) {
    const idf = Math.log(1 + N / Math.max(1, df.get(t) ?? 1));
    for (const id of hits.get(t) ?? []) score.set(id, (score.get(id) ?? 0) + idf);
  }
  return [...score.entries()].sort((a, b) => b[1] - a[1] || (a[0] < b[0] ? -1 : 1)).map(([id, s]) => ({ article_id: id, score: s }));
}

/** 順位融合（Reciprocal Rank Fusion）。rankings: 記事 ID の配列の配列（先頭が1位）。 */
export function rrf(rankings, k = 60) {
  const m = new Map();
  for (const r of rankings) r.forEach((id, i) => m.set(id, (m.get(id) ?? 0) + 1 / (k + i + 1)));
  return [...m.entries()].sort((a, b) => b[1] - a[1] || (a[0] < b[0] ? -1 : 1)).map(([id, s]) => ({ article_id: id, score: s }));
}
