/**
 * 広報誌の記事の正規化とチャンク分割（docs/plans/TATSUGO_KOHO_VECTOR.md §4）。純関数。
 * web（スニペットを切るとき）とスクリプト（埋め込み）の両方がこの1ファイルを通す。
 * 規則を変えたら config.json の chunker_version を上げ、全件を作り直す。
 */
import { createHash } from "node:crypto";

export const MIN_CHARS = 30;
export const SINGLE_MAX = 1000;
export const TARGET = 800;
export const HARD_MAX = 1000;
export const OVERLAP = 100;

const NON_ASCII = /[^\x00-\x7f]/;

/** NFKC・空白の連なりを 1 つに。日本語どうしの間の改行（PDF の折り返し）は詰める。 */
export function normalizeBody(text) {
  if (!text) return "";
  let s = String(text).normalize("NFKC").replace(/\r/g, "");
  s = s.replace(/([^\n])[ \t　]*\n[ \t　]*(?=[^\n])/g, (m, a, off, whole) => {
    const next = whole[off + m.length];
    return NON_ASCII.test(a) && NON_ASCII.test(next) ? a : `${a} `;
  });
  return s.replace(/\s+/g, " ").trim();
}

/** 文末（。！？）で区切った [start,end) の列。1,000 字を超える文は 、→文字数 の順で割る。 */
function sentenceSpans(s) {
  const spans = [];
  let start = 0;
  const push = (a, b) => {
    while (b - a > HARD_MAX) {
      let cut = s.lastIndexOf("、", a + HARD_MAX - 1);
      if (cut <= a) cut = a + HARD_MAX - 1;
      spans.push([a, cut + 1]);
      a = cut + 1;
    }
    if (b > a) spans.push([a, b]);
  };
  const re = /[。！？]+ ?/g;
  let m;
  while ((m = re.exec(s))) {
    push(start, m.index + m[0].length);
    start = m.index + m[0].length;
  }
  push(start, s.length);
  return spans;
}

/** 1 記事の本文 → チャンク（{seq, c0, c1, text}）。c0/c1 は正規化後の本文の文字位置。対象外は []。 */
export function chunkBody(body) {
  const s = normalizeBody(body);
  if (s.length < MIN_CHARS) return [];
  if (s.length <= SINGLE_MAX) return [{ seq: 0, c0: 0, c1: s.length, text: s }];
  const sp = sentenceSpans(s);
  const out = [];
  let i = 0;
  while (i < sp.length) {
    let j = i;
    let len = 0;
    while (j < sp.length && (len === 0 || (len + (sp[j][1] - sp[j][0]) <= HARD_MAX && len < TARGET))) {
      len += sp[j][1] - sp[j][0];
      j++;
    }
    const c0 = sp[i][0];
    const c1 = sp[j - 1][1];
    out.push({ seq: out.length, c0, c1, text: s.slice(c0, c1) });
    if (j >= sp.length) break;
    // 重なり: 直前の最後の 1〜2 文（合計 OVERLAP 字前後まで）から次を始める。必ず前進する。
    let k = j;
    let ov = 0;
    while (k - 1 > i && j - (k - 1) <= 2 && ov + (sp[k - 1][1] - sp[k - 1][0]) <= OVERLAP + 20) {
      ov += sp[k - 1][1] - sp[k - 1][0];
      k--;
    }
    i = k;
  }
  return out;
}

export const sha256 = (s) => createHash("sha256").update(s).digest("hex");

/** 埋め込む文字列: 見出し\n区分\nチャンク本文（見出し・区分が無ければ省く）。 */
export function embedText(article, chunk) {
  const head = [article.title, article.section]
    .map((x) => (x ? String(x).normalize("NFKC").replace(/\s+/g, " ").trim() : ""))
    .filter(Boolean);
  return [...head, chunk.text].join("\n");
}

/** ベクトル ID。article_id は 64 バイトを超えうるのでハッシュの先頭 24 字にする。 */
export function vectorId(articleId, seq) {
  return `${sha256(articleId).slice(0, 24)}:${String(seq).padStart(3, "0")}`;
}

export function chunkShaOf(model, chunkerVersion, text) {
  return sha256(`${model}\n${chunkerVersion}\n${text}`);
}

/**
 * 記事（document_articles の行 + year）→ 埋め込み対象のチャンク列。
 * 表紙・目次（cover_toc）と 30 字未満は対象外。
 */
export function chunksForArticle(a, { model, chunkerVersion }) {
  if (a.kind === "cover_toc") return [];
  return chunkBody(a.body_text).map((c) => {
    const text = embedText(a, c);
    return {
      id: vectorId(a.article_id, c.seq),
      article_id: a.article_id,
      seq: c.seq,
      c0: c.c0,
      c1: c.c1,
      text,
      chunk_sha: chunkShaOf(model, chunkerVersion, text),
      body_sha: a.body_sha256 ?? null,
      metadata: { region_id: a.region_id, source_id: a.source_id, year: a.year ?? null, kind: a.kind },
    };
  });
}
