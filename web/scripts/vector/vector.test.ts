/**
 * チャンク規則・ID・同期の差分・取り下げの単体テスト（設計 §8 の 9・10）。
 */
import { describe, expect, it } from "vitest";
import { MIN_CHARS, chunkBody, chunksForArticle, normalizeBody, vectorId } from "../../src/lib/vector/chunk.mjs";
import { applyWithdraw, desiredState, diffState, idsToWithdraw, vectorRow } from "./sync-lib.mjs";
import { keywordRank, queryTerms, rrf } from "../../src/lib/vector/keyword.mjs";

const sentence = (i: number) => `これは${i}番目の文で、避難所の開設や防災の備えについて説明しています。`;
const longBody = (n: number) => Array.from({ length: n }, (_, i) => sentence(i)).join("");
const art = (over: Record<string, unknown> = {}) => ({
  article_id: "tatsugo_koho_201408:009:abcd1234",
  title: "見出し",
  section: null,
  kind: "article",
  body_text: longBody(5),
  body_sha256: "h",
  region_id: "jp-46",
  source_id: "s",
  year: 2014,
  ...over,
});
const opts = { model: "m", chunkerVersion: 1 };

describe("normalizeBody", () => {
  it("日本語の途中の折り返しは詰め、英数字の間は空白 1 つにする", () => {
    expect(normalizeBody("龍郷\n町は\n  奄美\n\n大島")).toBe("龍郷町は奄美 大島"); // 空行（段落）は空白 1 つ
    expect(normalizeBody("TEL\n0997")).toBe("TEL 0997");
    expect(normalizeBody("ＡＢＣ　１２３")).toBe("ABC 123");
  });
});

describe("chunkBody", () => {
  it("1,000 字以下は 1 チャンク（全文）", () => {
    const b = longBody(10);
    expect(b.length).toBeLessThanOrEqual(1000);
    const c = chunkBody(b);
    expect(c).toHaveLength(1);
    expect(c[0]).toMatchObject({ seq: 0, c0: 0, c1: normalizeBody(b).length });
  });
  it("30 字未満は対象外", () => {
    expect(chunkBody("あ".repeat(MIN_CHARS - 1))).toEqual([]);
    expect(chunkBody(null)).toEqual([]);
    expect(chunkBody("あ".repeat(MIN_CHARS))).toHaveLength(1);
  });
  it("長い記事は上限 1,000 字以内に分け、前のチャンクと重なり、全文を覆う", () => {
    const b = normalizeBody(longBody(80));
    const c = chunkBody(b);
    expect(c.length).toBeGreaterThan(2);
    for (const x of c) {
      expect(x.text.length).toBeLessThanOrEqual(1000);
      expect(x.text).toBe(b.slice(x.c0, x.c1));
    }
    for (let i = 1; i < c.length; i++) {
      expect(c[i].c0).toBeLessThan(c[i - 1].c1); // 重なり
      expect(c[i].c0).toBeGreaterThan(c[i - 1].c0); // 前進する
    }
    expect(c[0].c0).toBe(0);
    expect(c.at(-1)!.c1).toBe(b.length);
    expect(c.map((x) => x.seq)).toEqual(c.map((_, i) => i));
  });
  it("NFKC 後の ! ? も文末として区切る（全角の！？は ASCII になる）", () => {
    const b = Array.from({ length: 60 }, (_, i) => `避難してください${i}！本当ですか？`).join("");
    const c = chunkBody(b);
    expect(c.length).toBeGreaterThan(1);
    for (const x of c.slice(0, -1)) expect(/[!?]$/.test(x.text)).toBe(true);
  });
  it("句点のない長い文でも止まらず、1,000 字以内に割る", () => {
    const c = chunkBody("あ".repeat(2500));
    expect(c.length).toBeGreaterThanOrEqual(3);
    for (const x of c) expect(x.text.length).toBeLessThanOrEqual(1000);
  });
});

describe("chunksForArticle", () => {
  it("表紙・目次（cover_toc）は対象外", () => {
    expect(chunksForArticle(art({ kind: "cover_toc" }), opts)).toEqual([]);
  });
  it("埋め込む文字列は 見出し + 本文。本文・モデルが変わると chunk_sha が変わる", () => {
    const [a] = chunksForArticle(art(), opts);
    expect(a.text.startsWith("見出し\n")).toBe(true);
    const [b] = chunksForArticle(art({ body_text: longBody(6) }), opts);
    expect(b.chunk_sha).not.toBe(a.chunk_sha);
    expect(chunksForArticle(art(), { model: "m2", chunkerVersion: 1 })[0].chunk_sha).not.toBe(a.chunk_sha);
    // 規則の版だけが違っても、埋め込む文字列が同じなら鍵は同じ（再埋め込みしない）
    expect(chunksForArticle(art(), { model: "m", chunkerVersion: 2 })[0].chunk_sha).toBe(a.chunk_sha);
  });
  it("ベクトル ID は 64 バイト以下で、同じ入力なら同じ", () => {
    const long = `tatsugo_koho_201408_part2:${"9".repeat(80)}`;
    expect(Buffer.byteLength(vectorId(long, 12))).toBeLessThanOrEqual(64);
    expect(vectorId("a", 0)).toBe(vectorId("a", 0));
    expect(vectorId("a", 0)).not.toBe(vectorId("a", 1));
  });
});

describe("同期の差分", () => {
  const state = (a = art()) => desiredState(chunksForArticle(a, opts));

  it("初回は全部 upsert、同じなら何もしない", () => {
    const d = state();
    expect(diffState(d, new Map()).upsert).toHaveLength(d.size);
    expect(diffState(d, new Map(d))).toMatchObject({ upsert: [], delete: [], unchanged: d.size });
  });
  it("チャンクが減ったら余りの seq を delete、記事が消えたら全 delete", () => {
    const before = state(art({ body_text: longBody(80) }));
    const manifest = new Map(before);
    expect(before.size).toBeGreaterThan(2);
    const d = diffState(state(art({ body_text: longBody(5) })), manifest);
    expect(d.upsert).toHaveLength(1);
    expect(d.delete).toHaveLength(before.size - 1);
    expect(d.changedArticles).toEqual(["tatsugo_koho_201408:009:abcd1234"]);
    expect(diffState(new Map(), manifest).delete).toHaveLength(before.size);
  });
});

describe("取り下げ", () => {
  it("doc 接頭辞と article_id でマニフェストから引き、マニフェストとキャッシュ用の sha から消える", () => {
    const m = new Map<string, { id: string; article_id: string; chunk_sha: string }>();
    for (const a of [art({ article_id: "d1:001:aaaaaaaa" }), art({ article_id: "d1:002:bbbbbbbb" }), art({ article_id: "d2:001:cccccccc" })]) {
      for (const [k, v] of desiredState(chunksForArticle(a, opts))) m.set(k, v);
    }
    const byDoc = idsToWithdraw(m, { docPrefixes: ["d1"] });
    expect(byDoc).toHaveLength(2);
    const one = idsToWithdraw(m, { articleIds: ["d2:001:cccccccc"] });
    expect(one).toHaveLength(1);
    const shas = applyWithdraw(m, [...byDoc, ...one]);
    expect(m.size).toBe(0);
    expect(shas.size).toBeGreaterThan(0);
  });
  it("他の記事が同じ chunk_sha を使っていれば、キャッシュから消す対象にしない", () => {
    const same = { body_text: "同じ文面の記事です。".repeat(5), title: null };
    const m = new Map<string, { id: string; article_id: string; chunk_sha: string }>();
    for (const a of [art({ article_id: "d1:001:aaaaaaaa", ...same }), art({ article_id: "d2:001:bbbbbbbb", ...same })]) {
      for (const [k, v] of desiredState(chunksForArticle(a, opts))) m.set(k, v);
    }
    expect(m.size).toBe(2);
    const ids = idsToWithdraw(m, { articleIds: ["d1:001:aaaaaaaa"] });
    expect(applyWithdraw(m, ids).size).toBe(0); // d2 がまだ使う
    const ids2 = idsToWithdraw(m, { articleIds: ["d2:001:bbbbbbbb"] });
    expect(applyWithdraw(m, ids2).size).toBe(1);
  });
  it("接頭辞は doc_id の途中で当たらない（d1 が d10 を巻き込まない）", () => {
    const m = new Map([["i", { id: "i", article_id: "d10:001:x", chunk_sha: "s" }]]);
    expect(idsToWithdraw(m, { docPrefixes: ["d1"] })).toEqual([]);
  });
});

describe("vectorRow", () => {
  it("メタデータは null を入れず、フィルタ用の 4 つと位置・sha を持つ", () => {
    const [c] = chunksForArticle(art({ year: null }), opts);
    const row = vectorRow(c, new Float32Array([0.5, 0.25]), "m");
    expect(row.values).toEqual([0.5, 0.25]);
    expect(row.metadata).toMatchObject({ article_id: c.article_id, seq: 0, region_id: "jp-46", source_id: "s", kind: "article", model: "m" });
    expect("year" in row.metadata).toBe(false);
  });
});

describe("keyword", () => {
  it("質問から語を取り出し、ひらがなだけの語は捨てる", () => {
    const t = queryTerms("ウミガメの卵を勝手に採ってもいいのですか");
    expect(t).toContain("ウミガメ");
    expect(t.every((x: string) => !/^[ぁ-ん]+$/.test(x))).toBe(true);
  });
  it("語の IDF で順位をつけ、RRF で混ぜる", () => {
    const hits = new Map([
      ["a", new Set(["x", "y"])],
      ["b", new Set(["y"])],
    ]);
    const df = new Map([
      ["a", 2],
      ["b", 1],
    ]);
    expect(keywordRank(["a", "b"], hits, df, 100).map((r) => r.article_id)).toEqual(["y", "x"]);
    expect(rrf([["x", "y"], ["y"]])[0].article_id).toBe("y");
  });
});
