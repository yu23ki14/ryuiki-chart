/**
 * `searchDocuments`（広報たつごうのベクトル検索）の配管のテスト（設計 §8）。
 * 実モデルの品質は見ない。埋め込みは「文字 2-gram のハッシュを 64 次元に畳む」決定的な偽物、インデックスはメモリ上の cosine。
 */
import Database from "better-sqlite3";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { applyMigrations } from "@/lib/cube/__fixtures__/cube-fixture";

vi.mock("server-only", () => ({}));

import { rrf } from "@/lib/vector/keyword.mjs";
import { chunksForArticle, normalizeBody } from "@/lib/vector/chunk.mjs";
import {
  DEFAULT_SEARCH_MODE,
  VectorUnavailableError,
  searchDocuments,
  vectorFilter,
  type SearchDeps,
} from "./document-search";
import type { VectorIndexLike, VectorMatch } from "@/lib/vector/bindings";

const DIM = 64;
export function fakeEmbed(text: string): number[] {
  const v = new Array<number>(DIM).fill(0);
  const s = text.normalize("NFKC");
  for (let i = 0; i < s.length - 1; i++) {
    let h = 0;
    for (const ch of s.slice(i, i + 2)) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
    v[h % DIM] += 1;
  }
  return v;
}
const cos = (a: number[], b: number[]) => {
  const d = a.reduce((s, x, i) => s + x * b[i], 0);
  return d / (Math.hypot(...a) * Math.hypot(...b) || 1);
};

type Stored = { id: string; values: number[]; metadata: Record<string, string | number | boolean | null> };
/** メタデータの $eq / $gte / $lte だけ実装した偽の Vectorize。 */
class FakeIndex implements VectorIndexLike {
  rows: Stored[] = [];
  lastOptions: unknown;
  async query(vector: number[], options: { topK: number; returnMetadata: string; filter?: Record<string, unknown> }) {
    this.lastOptions = options;
    const ok = (md: Stored["metadata"]) =>
      Object.entries(options.filter ?? {}).every(([k, c]) => {
        const cond = c as Record<string, number | string>;
        const x = md[k];
        return (
          (cond.$eq === undefined || x === cond.$eq) &&
          (cond.$gte === undefined || (x as number) >= (cond.$gte as number)) &&
          (cond.$lte === undefined || (x as number) <= (cond.$lte as number))
        );
      });
    const matches: VectorMatch[] = this.rows
      .filter((r) => ok(r.metadata))
      .map((r) => ({ id: r.id, score: cos(vector, r.values), metadata: r.metadata }))
      .sort((a, b) => b.score - a.score)
      .slice(0, options.topK);
    return { matches };
  }
}

let raw: Database.Database;
let index: FakeIndex;
let calls: number;
const deps = (): SearchDeps => ({
  embed: async (t) => fakeEmbed(t),
  index,
  all: async (sql, params) => raw.prepare(sql).all(...(params as unknown[])) as Record<string, unknown>[],
  chunked: async (values, make, size = 80) => {
    const out: Record<string, unknown>[] = [];
    for (let i = 0; i < values.length; i += size) {
      const { sql, params } = make(values.slice(i, i + size));
      expect(params.length).toBeLessThanOrEqual(100); // D1 のバインドパラメータの上限
      out.push(...(raw.prepare(sql).all(...(params as unknown[])) as Record<string, unknown>[]));
    }
    return out;
  },
});

interface Art {
  id: string;
  title: string;
  body: string | null;
  issue?: string; // 'YYYY-MM'
  region?: string;
  page?: number;
  docUrl?: string | null;
  topics?: string[];
}

function addArticle(a: Art, opts: { indexed?: boolean; bodyShaInIndex?: string } = {}) {
  const ym = a.issue ?? "2014-08";
  const issueId = `iss_${ym}`;
  const docId = `doc_${ym}`;
  raw.prepare("INSERT OR IGNORE INTO periodical_series (series_id, source_id, title, publisher, license) VALUES ('s','tatsugo_koho_amami','広報たつごう','龍郷町','著作権は龍郷町に帰属')").run();
  raw.prepare("INSERT OR IGNORE INTO periodical_issues (issue_id, series_id, source_id, region_id, kind, year_month) VALUES (?,?,?,?,?,?)").run(issueId, "s", "tatsugo_koho_amami", "jp-46", "monthly", ym);
  raw.prepare("INSERT OR IGNORE INTO documents (doc_id, url) VALUES (?,?)").run(docId, a.docUrl === undefined ? `https://example.test/${docId}.pdf` : a.docUrl);
  raw
    .prepare(
      `INSERT INTO document_articles (article_id, issue_id, doc_id, source_id, region_id, kind, page_from, page_to, issue_page_from, issue_page_to, title, body_text, body_sha256)
       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)`,
    )
    .run(a.id, issueId, docId, "tatsugo_koho_amami", a.region ?? "jp-46", "article", a.page ?? 3, a.page ?? 3, a.page ?? 3, a.page ?? 3, a.title, a.body, `sha_${a.id}`);
  for (const t of a.topics ?? []) raw.prepare("INSERT INTO document_article_topics (article_id, topic_id) VALUES (?,?)").run(a.id, t);
  if (opts.indexed !== false && a.body) {
    const row = { article_id: a.id, title: a.title, section: null, body_text: a.body, body_sha256: `sha_${a.id}`, region_id: a.region ?? "jp-46", source_id: "tatsugo_koho_amami", kind: "article", year: Number(ym.slice(0, 4)) };
    for (const c of chunksForArticle(row, { model: "m", chunkerVersion: 1 })) {
      index.rows.push({
        id: c.id,
        values: fakeEmbed(c.text),
        metadata: { article_id: c.article_id, seq: c.seq, c0: c.c0, c1: c.c1, body_sha: opts.bodyShaInIndex ?? c.body_sha ?? "", region_id: row.region_id, source_id: row.source_id, year: row.year, kind: "article" },
      });
    }
  }
}

beforeEach(() => {
  raw = new Database(":memory:");
  applyMigrations(raw);
  index = new FakeIndex();
  calls = 0;
});
afterEach(() => raw.close());

const BOUSAI = "豪雨や台風のときは早めに避難所へ避難してください。防災ガイドに避難の仕方がまとめてあります。";
const GOMI = "充電式の電池はクリーンセンターに搬入できません。回収箱へお持ちください。ごみの分別にご協力ください。";

describe("searchDocuments", () => {
  it("近い記事が上位に出て、citation・pdf_url・snippet が付く", async () => {
    addArticle({ id: "a1", title: "防災ガイド", body: BOUSAI, page: 4 });
    addArticle({ id: "a2", title: "電池の回収", body: GOMI });
    const r = await searchDocuments(deps(), { query: "台風のときの避難の仕方", limit: 5 });
    expect(r.rows[0].article_id).toBe("a1");
    expect(r.rows[0].citation).toBe("龍郷町「広報たつごう」2014年8月号 p.4");
    expect(r.rows[0].pdf_url).toBe("https://example.test/doc_2014-08.pdf#page=4");
    expect(r.rows[0].snippet).toContain("避難所");
    expect(r.rows[0].source_license).toContain("龍郷町");
    expect(r.mode).toBe(DEFAULT_SEARCH_MODE);
  });

  it("D1 に無い article_id（取り下げ済み・未反映）は返らない", async () => {
    addArticle({ id: "a1", title: "防災ガイド", body: BOUSAI });
    addArticle({ id: "a2", title: "電池の回収", body: GOMI });
    raw.prepare("DELETE FROM document_article_topics WHERE article_id = 'a1'").run();
    raw.prepare("DELETE FROM document_articles WHERE article_id = 'a1'").run(); // 取り下げ。Vectorize には残っている
    const r = await searchDocuments(deps(), { query: "台風のときの避難の仕方", limit: 5 });
    expect(r.rows.map((x) => x.article_id)).not.toContain("a1");
    expect(r.rows.map((x) => x.article_id)).toEqual(["a2"]);
  });

  it("同じ記事の複数チャンクは 1 件にまとまる", async () => {
    const long = Array.from({ length: 30 }, (_, i) => `第${i}節。避難所の開設について、${"防災の備えを確認しましょう。".repeat(4)}`).join("");
    addArticle({ id: "a1", title: "防災", body: long });
    expect(index.rows.filter((r) => r.metadata.article_id === "a1").length).toBeGreaterThan(1);
    const r = await searchDocuments(deps(), { query: "避難所の開設", limit: 10 });
    expect(r.rows.filter((x) => x.article_id === "a1")).toHaveLength(1);
  });

  it("citation か pdf_url が組み立てられない行は返さない", async () => {
    addArticle({ id: "a1", title: "防災ガイド", body: BOUSAI, docUrl: null });
    addArticle({ id: "a2", title: "防災の備え", body: BOUSAI + "備蓄品を用意しましょう。", issue: "2014-09" });
    const r = await searchDocuments(deps(), { query: "避難所", limit: 5 });
    expect(r.rows.map((x) => x.article_id)).toEqual(["a2"]);
    expect(r.notes.join("")).toContain("1 件は返していない");
  });

  it("body_sha が D1 と違えば stale_index にして記事の冒頭を snippet にする", async () => {
    addArticle({ id: "a1", title: "防災ガイド", body: BOUSAI }, { bodyShaInIndex: "old" });
    const r = await searchDocuments(deps(), { query: "避難所", limit: 5 });
    expect(r.rows[0].stale_index).toBe(true);
    expect(r.rows[0].snippet).toBe(normalizeBody(BOUSAI).slice(0, 300));
  });

  it("D1 の body_sha256 が NULL なら文字位置を信じて stale にしない（m13 は本文があれば body_sha256 を必ず付ける）", async () => {
    addArticle({ id: "a1", title: "防災ガイド", body: BOUSAI });
    raw.prepare("UPDATE document_articles SET body_sha256 = NULL WHERE article_id = 'a1'").run();
    const r = await searchDocuments(deps(), { query: "避難所", limit: 5 });
    expect(r.rows[0].stale_index).toBeUndefined();
    expect(r.rows[0].snippet).toBe(normalizeBody(BOUSAI).slice(0, 300));
  });

  it("year・region の絞り込みを Vectorize の filter に渡し、topic は D1 で絞る", async () => {
    addArticle({ id: "a1", title: "防災ガイド", body: BOUSAI, issue: "2014-08", topics: ["disaster"] });
    addArticle({ id: "a2", title: "防災の備え", body: BOUSAI, issue: "2019-05", topics: ["other"] });
    const r = await searchDocuments(deps(), { query: "避難所", year_from: 2015, region_id: "jp-46" });
    expect(index.lastOptions).toMatchObject({ topK: 50, returnMetadata: "all", filter: { region_id: { $eq: "jp-46" }, year: { $gte: 2015 } } });
    expect(r.rows.map((x) => x.article_id)).toEqual(["a2"]);
    const t = await searchDocuments(deps(), { query: "避難所", topic: "disaster" });
    expect(t.rows.map((x) => x.article_id)).toEqual(["a1"]);
    expect(vectorFilter({ query: "x" })).toBeUndefined();
  });

  it("hybrid: 質問の語を含む記事が押し上げられ、similarity も返る", async () => {
    addArticle({ id: "a1", title: "防災ガイド", body: BOUSAI });
    addArticle({ id: "a2", title: "電池の回収", body: GOMI });
    const r = await searchDocuments(deps(), { query: "クリーンセンターの電池", mode: "hybrid", limit: 5 });
    expect(r.mode).toBe("hybrid");
    expect(r.rows[0].article_id).toBe("a2");
    expect(r.rows[0].similarity).toBeGreaterThan(0);
  });

  it("本文が無い記事は snippet が空で unreadable_reason を返す", async () => {
    addArticle({ id: "a1", title: "読めない記事", body: null });
    raw.prepare("UPDATE document_articles SET unreadable_reason = 'image_only' WHERE article_id = 'a1'").run();
    // 本文が無いのでチャンクは作られない。キーワードでも当たらないが、索引に残っていた場合の挙動を見る
    index.rows.push({ id: "x", values: fakeEmbed("読めない記事"), metadata: { article_id: "a1", seq: 0, c0: 0, c1: 0, body_sha: "", region_id: "jp-46", source_id: "tatsugo_koho_amami", year: 2014, kind: "article" } });
    const r = await searchDocuments(deps(), { query: "読めない記事" });
    expect(r.rows[0]).toMatchObject({ article_id: "a1", snippet: "", unreadable_reason: "image_only" });
  });

  it("hybrid のキーワード側は語ごとに並列で LIKE を発行し、総数は実数（COUNT）", async () => {
    addArticle({ id: "a1", title: "防災ガイド", body: BOUSAI });
    const sqls: string[] = [];
    const d = deps();
    const all = d.all;
    await searchDocuments({ ...d, all: async (sql, p) => (sqls.push(sql), all(sql, p)) }, { query: "避難所の開設と防災ガイド", mode: "hybrid" });
    expect(sqls.some((q) => q.includes("COUNT(*)"))).toBe(true);
    expect(sqls.filter((q) => q.includes("LIKE")).every((q) => /LIMIT \d+/.test(q))).toBe(true);
  });

  it("埋め込みや Vectorize が失敗したら VectorUnavailableError", async () => {
    await expect(searchDocuments({ ...deps(), embed: async () => { throw new Error("down"); } }, { query: "x" })).rejects.toBeInstanceOf(VectorUnavailableError);
    const bad = { query: async () => { calls++; throw new Error("503"); } } as unknown as VectorIndexLike;
    await expect(searchDocuments({ ...deps(), index: bad }, { query: "x" })).rejects.toBeInstanceOf(VectorUnavailableError);
    expect(calls).toBe(1);
  });
});

describe("rrf", () => {
  it("2 つの順位から期待の順位になる", () => {
    const r = rrf([["a", "b", "c"], ["c", "b", "d"]]);
    expect(r.map((x) => x.article_id)).toEqual(["c", "b", "a", "d"]);
    expect(r[0].score).toBeCloseTo(1 / 61 + 1 / 63);
  });
});
