/**
 * 「広報たつごう」の記事を内容で探す（ベクトル検索。MCP と AI の `search_documents` が共有する 1 関数。ADR-0014）。
 * 設計: docs/plans/TATSUGO_KOHO_VECTOR.md §6。
 *
 * 流れ: 質問を埋め込む → Vectorize（topK 50）→ 記事ごとに最良のチャンクにまとめる → D1 の document_articles と突き合わせる。
 * **D1 に無い article_id（取り下げ済み・未反映）は返さない。citation・pdf_url が組み立てられない行も返さない。**
 * hybrid は、質問の語の LIKE（D1）の順位と RRF で混ぜる。
 *
 * 外部（Workers AI・Vectorize・D1）は `SearchDeps` で受け取る。既定は本番のバインディング、テストは偽物に差し替える。
 */
import { z } from "zod";
import { decorateArticle, issueLabel } from "@/lib/periodical";
import { keywordRank, queryTerms, rrf } from "@/lib/vector/keyword.mjs";
import { normalizeBody } from "@/lib/vector/chunk.mjs";
import { embedQuery, getVectorBindings, type VectorIndexLike, type AiLike } from "@/lib/vector/bindings";

/** 検索の既定のモード。評価（docs/plans/TATSUGO_KOHO_VECTOR.md §9.5）の結果で決めた。 */
export const DEFAULT_SEARCH_MODE: "semantic" | "hybrid" = "semantic";
export const DEFAULT_LIMIT = 5;
export const MAX_LIMIT = 10;
/** Vectorize の topK の上限（メタデータを返すとき）。 */
export const TOP_K = 50;
const SNIPPET_MAX = 300;
const KEYWORD_TERMS = 6;
/** hybrid の語ごとの LIKE の取得行数の上限（読み取り量の上限ではなく、返す行の上限）。 */
const KEYWORD_LIMIT = 200;

export const searchDocumentsInputSchema = z.object({
  query: z.string().min(1).max(200).describe("探したい内容を日本語の文で（例: 「大雨のときの避難の仕方」）。キーワードの羅列でなく、知りたいことを文で書く"),
  region_id: z.string().max(40).optional().describe("地域の絞り込み（既定は全域）"),
  year_from: z.number().int().min(1900).max(2200).optional().describe("発行年（西暦）の下限"),
  year_to: z.number().int().min(1900).max(2200).optional().describe("発行年（西暦）の上限"),
  topic: z.string().max(60).optional().describe("話題の topic_id の完全一致（describe_catalog what='sources' の出典の topics）。検索結果をこの話題の記事に絞る"),
  mode: z.enum(["semantic", "hybrid"]).optional().describe(`semantic=意味の近さだけ、hybrid=意味の近さ＋質問の語を含むか（固有名詞に強い）。既定 ${DEFAULT_SEARCH_MODE}`),
  limit: z.number().int().min(1).max(MAX_LIMIT).optional().describe(`返す記事数（既定 ${DEFAULT_LIMIT}、最大 ${MAX_LIMIT}）`),
});
export type SearchDocumentsInput = z.infer<typeof searchDocumentsInputSchema>;

export const SEARCH_DOCUMENTS_DESCRIPTION =
  "「広報たつごう」（龍郷町の広報誌。出典 tatsugo_koho_amami）の記事を、内容の近さで探す（ベクトル検索）。" +
  "「大雨のときの避難」のように知りたいことを文で書くと、見出しや本文に同じ語が無くても関連する記事が出る。" +
  "各行に citation（出典の表記）・pdf_url（元の PDF の該当ページ）・snippet（該当部分の本文）・score（類似度）を付けて返す。" +
  "score は mode が semantic のとき cosine（0〜1）、hybrid のときは順位融合（RRF）の値（約 0.03 以下。大小は同じ質問の中の順位にだけ使える）で、hybrid の各行の similarity がベクトル側の cosine（キーワードだけで当たった行は null）。" +
  "回答では citation を出典として示し、pdf_url を添える。snippet は PDF から機械が読み取った文字で、段組みの読み取りに失敗して文が崩れている記事がある" +
  "（崩れた本文から事実を断定しない。pdf_url で原文を確かめるよう案内する）。見出しや語の完全一致で引くときは get_records（record_set=document_articles の q）を使う。" +
  "意味で探すので、該当する記事が無くても近い記事を返す。score（cosine）は該当の有無を分けない（評価では、記事に無い話題の質問の最上位が該当ありの質問の平均より高かった）。" +
  "snippet を読んで質問に答えているかを確かめ、答えていなければ「見つからなかった」と答える。";

export interface SearchDeps {
  embed: (text: string) => Promise<number[]>;
  index: VectorIndexLike;
  /** D1 の SELECT。 */
  all: (sql: string, params: readonly unknown[]) => Promise<Record<string, unknown>[]>;
  /** `IN (...)` の問い合わせ用（db.ts の queryChunked と同じ形。D1 のバインドパラメータ 100 個の上限を超えない）。 */
  chunked: (
    values: readonly unknown[],
    make: (chunk: readonly unknown[]) => { sql: string; params: readonly unknown[] },
    chunkSize?: number,
  ) => Promise<Record<string, unknown>[]>;
}

export class VectorUnavailableError extends Error {}

export interface SearchHit {
  article_id: string;
  doc_id: string;
  title: string | null;
  section: string | null;
  issue: string | null;
  page: number | null;
  snippet: string;
  /** semantic: cosine。hybrid: 順位融合の値（0〜約 0.033）。 */
  score: number;
  /** hybrid のとき、ベクトル側の cosine（キーワードだけで当たった記事は null）。 */
  similarity?: number | null;
  citation: string;
  pdf_url: string;
  source_id: string;
  source_license: string | null;
  stale_index?: true;
  unreadable_reason?: string;
}

export interface SearchOutcome {
  mode: "semantic" | "hybrid";
  rows: SearchHit[];
  /** 絞り込みの結果 limit に足りなかった等、答えに添える注記。 */
  notes: string[];
  source_ids: string[];
}

interface ArticleRow {
  article_id: string;
  doc_id: string;
  source_id: string;
  region_id: string;
  kind: string;
  title: string | null;
  section: string | null;
  body_text: string | null;
  body_sha256: string | null;
  unreadable_reason: string | null;
  issue_page_from: number | null;
  issue_page_to: number | null;
  page_from: number | null;
  year_month: string | null;
  year_month_to: string | null;
  issue_kind: string | null;
  series_title: string | null;
  series_publisher: string | null;
  doc_url: string | null;
  series_license: string | null;
}

const ARTICLE_COLS =
  "a.article_id, a.doc_id, a.source_id, a.region_id, a.kind, a.title, a.section, a.body_text, a.body_sha256, a.unreadable_reason, " +
  "a.issue_page_from, a.issue_page_to, a.page_from, pi.year_month, pi.year_month_to, pi.kind AS issue_kind, ps.title AS series_title, " +
  "ps.publisher AS series_publisher, dd.url AS doc_url, ps.license AS series_license";
const ARTICLE_JOIN =
  "FROM document_articles a LEFT JOIN periodical_issues pi ON pi.issue_id = a.issue_id " +
  "LEFT JOIN periodical_series ps ON ps.series_id = pi.series_id LEFT JOIN documents dd ON dd.doc_id = a.doc_id";

/** 絞り込みの SQL 断片（D1 側。Vectorize 側の filter と同じ意味）。 */
function filterSql(input: SearchDocumentsInput): { where: string[]; params: unknown[] } {
  const where = ["a.kind != 'cover_toc'"];
  const params: unknown[] = [];
  const add = (cond: string, v: unknown) => {
    where.push(cond);
    params.push(v);
  };
  if (input.region_id) add("a.region_id = ?", input.region_id);
  if (input.year_from !== undefined) add("CAST(substr(pi.year_month, 1, 4) AS INTEGER) >= ?", input.year_from);
  if (input.year_to !== undefined) add("CAST(substr(pi.year_month, 1, 4) AS INTEGER) <= ?", input.year_to);
  if (input.topic) add("EXISTS (SELECT 1 FROM document_article_topics t WHERE t.article_id = a.article_id AND t.topic_id = ?)", input.topic);
  return { where, params };
}

/** Vectorize の filter（region_id・year だけ。話題は配列なので D1 で絞る）。 */
export function vectorFilter(input: SearchDocumentsInput): Record<string, unknown> | undefined {
  const f: Record<string, unknown> = {};
  if (input.region_id) f.region_id = { $eq: input.region_id };
  if (input.year_from !== undefined || input.year_to !== undefined) {
    f.year = {
      ...(input.year_from !== undefined ? { $gte: input.year_from } : {}),
      ...(input.year_to !== undefined ? { $lte: input.year_to } : {}),
    };
  }
  return Object.keys(f).length ? f : undefined;
}

const likeEscape = (t: string) => t.replace(/[\\%_]/g, (c) => `\\${c}`);

async function keywordCandidates(deps: SearchDeps, input: SearchDocumentsInput): Promise<{ terms: string[]; rank: { article_id: string; score: number }[] }> {
  const terms = queryTerms(input.query, KEYWORD_TERMS);
  const { where, params } = filterSql(input);
  const from = `${ARTICLE_JOIN} WHERE ${where.join(" AND ")}`;
  // 総数（IDF の分母）と各語の当たりを並列に引く
  const [total, ...perTerm] = await Promise.all([
    deps.all(`SELECT COUNT(*) AS n ${from}`, params),
    ...terms.map((t) => {
      const like = `%${likeEscape(t)}%`;
      return deps.all(`SELECT a.article_id AS article_id ${from} AND (a.title LIKE ? ESCAPE '\\' OR a.body_text LIKE ? ESCAPE '\\') LIMIT ${KEYWORD_LIMIT}`, [...params, like, like]);
    }),
  ]);
  const N = Math.max(1, Number(total[0]?.n ?? 1));
  const hits = new Map<string, Set<string>>();
  const df = new Map<string, number>();
  terms.forEach((t, i) => {
    const ids = new Set(perTerm[i].map((r) => String(r.article_id)));
    hits.set(t, ids);
    df.set(t, ids.size);
  });
  return { terms, rank: keywordRank(terms, hits, df, N).slice(0, TOP_K) };
}

async function fetchArticles(deps: SearchDeps, ids: string[], input: SearchDocumentsInput): Promise<Map<string, ArticleRow>> {
  const { where, params } = filterSql(input);
  const rows = await deps.chunked(
    ids,
    (chunk) => ({
      sql: `SELECT ${ARTICLE_COLS} ${ARTICLE_JOIN} WHERE ${where.join(" AND ")} AND a.article_id IN (${chunk.map(() => "?").join(",")})`,
      params: [...params, ...chunk],
    }),
    Math.max(1, 90 - params.length),
  );
  return new Map(rows.map((r) => [String(r.article_id), r as unknown as ArticleRow]));
}

function snippetFor(row: ArticleRow, chunk: { c0: number; c1: number; bodySha: string | null } | null, terms: string[]): { snippet: string; stale: boolean } {
  const body = normalizeBody(row.body_text);
  if (!body) return { snippet: "", stale: false };
  // 索引の body_sha と D1 の body_sha256 が両方あって違うときだけ stale（どちらかが無ければ文字位置を信じる。m13 は本文があれば必ず body_sha256 を付ける）
  if (chunk && (chunk.bodySha === null || row.body_sha256 === null || chunk.bodySha === row.body_sha256)) {
    return { snippet: body.slice(chunk.c0, chunk.c1).slice(0, SNIPPET_MAX), stale: false };
  }
  if (chunk) return { snippet: body.slice(0, SNIPPET_MAX), stale: true }; // 入れた後に本文が変わった。文字位置は信用しない
  const t = terms.find((x) => body.includes(x));
  const at = t ? Math.max(0, body.indexOf(t) - 40) : 0;
  return { snippet: body.slice(at, at + SNIPPET_MAX), stale: false };
}

export async function searchDocuments(deps: SearchDeps, rawInput: SearchDocumentsInput): Promise<SearchOutcome> {
  const input = searchDocumentsInputSchema.parse(rawInput);
  const mode = input.mode ?? DEFAULT_SEARCH_MODE;
  const limit = input.limit ?? DEFAULT_LIMIT;

  let matches: Awaited<ReturnType<VectorIndexLike["query"]>>["matches"];
  try {
    const vec = await deps.embed(input.query);
    matches = (await deps.index.query(vec, { topK: TOP_K, returnMetadata: "all", filter: vectorFilter(input) })).matches;
  } catch (e) {
    throw new VectorUnavailableError(e instanceof Error ? e.message : String(e));
  }

  // 記事ごとに最良のチャンク
  const best = new Map<string, { score: number; c0: number; c1: number; bodySha: string | null }>();
  for (const m of matches) {
    const md = m.metadata ?? {};
    const id = typeof md.article_id === "string" ? md.article_id : null;
    if (!id) continue;
    const cur = best.get(id);
    if (!cur || m.score > cur.score) {
      best.set(id, {
        score: m.score,
        c0: Number(md.c0 ?? 0),
        c1: Number(md.c1 ?? 0),
        bodySha: typeof md.body_sha === "string" ? md.body_sha : null,
      });
    }
  }
  const semRank = [...best.entries()].sort((a, b) => b[1].score - a[1].score).map(([id]) => id);

  let ordered: { article_id: string; score: number }[];
  let terms: string[] = [];
  if (mode === "hybrid") {
    const kw = await keywordCandidates(deps, input);
    terms = kw.terms;
    ordered = rrf([semRank, kw.rank.map((r) => r.article_id)]);
  } else {
    ordered = semRank.map((id) => ({ article_id: id, score: best.get(id)!.score }));
  }

  // D1 と突き合わせる。D1 に無い（取り下げ済み・未反映）・絞り込みに合わない記事はここで落ちる。
  const rows = await fetchArticles(deps, ordered.map((o) => o.article_id), input);
  const notes: string[] = [];
  const out: SearchHit[] = [];
  let droppedNoCitation = 0;
  for (const o of ordered) {
    const row = rows.get(o.article_id);
    if (!row) continue;
    // citation・pdf_url・source_license は get_records と同じ関数（lib/periodical.ts）で付ける
    const dec = decorateArticle(row as unknown as Parameters<typeof decorateArticle>[0]);
    const citation = dec.citation;
    const pdf = dec.pdf_url;
    if (typeof citation !== "string" || typeof pdf !== "string") {
      droppedNoCitation++;
      continue;
    }
    const chunk = best.get(o.article_id) ?? null;
    const { snippet, stale } = snippetFor(row, chunk, terms);
    const hit: SearchHit = {
      article_id: row.article_id,
      doc_id: row.doc_id,
      title: row.title,
      section: row.section,
      issue: issueLabel({ kind: row.issue_kind, year_month: row.year_month, year_month_to: row.year_month_to }),
      page: row.issue_page_from,
      snippet,
      score: Math.round(o.score * 10000) / 10000,
      citation,
      pdf_url: pdf,
      source_id: row.source_id,
      source_license: typeof dec.source_license === "string" ? dec.source_license : null,
    };
    if (mode === "hybrid") hit.similarity = chunk ? Math.round(chunk.score * 10000) / 10000 : null;
    if (stale) hit.stale_index = true;
    if (row.body_text === null && row.unreadable_reason) hit.unreadable_reason = row.unreadable_reason;
    out.push(hit);
    if (out.length >= limit) break;
  }
  if (droppedNoCitation) notes.push(`出典の表記か PDF の URL を組み立てられない記事 ${droppedNoCitation} 件は返していない。`);
  if (out.length < limit) {
    notes.push(
      `結果は ${out.length} 件（要求 ${limit} 件）。近い記事の候補は上位 ${TOP_K} 件までで、話題・年・地域の絞り込みや、D1 に無い記事（取り下げ・未反映）を除くと足りなくなることがある。`,
    );
  }
  if (out.some((r) => r.stale_index)) notes.push("stale_index の行は、索引を作ったあとに本文が更新されている。snippet は記事の冒頭で、索引の入れ直しが要る。");
  return { mode, rows: out, notes, source_ids: [...new Set(out.map((r) => r.source_id))] };
}

/** ベクトル検索が使えないとき（または一時的に接続できないとき）の文言。MCP・AI 共通。 */
export const VECTOR_UNAVAILABLE_MESSAGE = "ベクトル検索に一時的に接続できない。get_records（record_set=document_articles の q）で探す";

/** 検索して、MCP・AI が返す data を作る。接続できないときは error（例外にしない）。 */
export async function runSearchDocuments(
  deps: SearchDeps,
  input: SearchDocumentsInput,
): Promise<{ ok: true; outcome: SearchOutcome; data: { mode: SearchOutcome["mode"]; rows: SearchHit[]; notes?: string[] } } | { ok: false; error: string }> {
  try {
    const outcome = await searchDocuments(deps, input);
    return { ok: true, outcome, data: { mode: outcome.mode, rows: outcome.rows, ...(outcome.notes.length ? { notes: outcome.notes } : {}) } };
  } catch (e) {
    if (e instanceof VectorUnavailableError) return { ok: false, error: VECTOR_UNAVAILABLE_MESSAGE };
    throw e;
  }
}

/** 本番の依存（バインディングと D1）。使えない・取得に失敗したら null（呼び出し側で握らない）。 */
export async function defaultSearchDeps(): Promise<SearchDeps | null> {
  try {
    const b = await getVectorBindings();
    if (!b) return null;
    const { query, queryChunked } = await import("@/lib/db");
    return {
      embed: (text) => embedQuery(b.ai as AiLike, text),
      index: b.index,
      all: (sql, params) => query<Record<string, unknown>>(sql, params),
      chunked: (values, make, size) => queryChunked<Record<string, unknown>>(values, make, size),
    };
  } catch {
    return null;
  }
}
