"""m13: 龍郷町「広報たつごう」の号・ファイル・記事を cells.sqlite に作る（Issue #130、docs/plans/TATSUGO_KOHO.md §2・§3・§7.2・§8.1・§9）。

入力（`data/processed/tatsugo_koho/`。収集担当 c106 の出力。契約は設計書 §7.1。gitignore 済みの生成物）:

- `catalog.jsonl`: PDF ファイルごとに 1 行。c106 の catalog.json の行（`url`・`link_text`・`source_page`・`heading`・`headlines`・
  `year`・`month`・`months`・`part`・`merged`・`annex`・`issue_date`）に、取得結果 `sha256`・`n_pages`・`fetched_at`・`saved_name`
  （無ければ url の末尾）を足したもの。号はリンク文から決まったものだけを使い、ファイル名は ID に使わない。
- `articles.jsonl`: 記事ごとに 1 行。`doc_id`（§2.1 の規則。`doc_id_of()` と同じ）・`page_from`・`page_to`（ファイル内ページ）・
  `kind`・`title`・`section`・`body_text`・`event_dates`・`extractor`・`confidence`・`unreadable_reason`・`extracted_at`・`verified_by`、
  入れ子の `topics`（`{topic_id, extractor, confidence}`）・`places`（`{place_raw, place_type, place_id, match_method, confidence}`）。
  `article_id`・`issue_id`・`source_id`・`region_id`・`issue_page_*`・`body_sha256`・`doc_sha256` は m13 が決める。
- `scripts/data/tatsugo_koho_withdrawn.yaml`: 取り下げの除外リスト（§9）。コミットする。ID と日付だけ。

出力（`cells.sqlite`）: `documents`（広報誌のファイルぶん）・`notes`（ライセンスの注記）・`periodical_series`・`periodical_issues`・
`periodical_issue_files`・`document_articles`・`document_article_topics`・`document_article_places`。DDL は `scripts/schema_tatsugo_koho.sql`。
`source_registry`（`ryuiki.sqlite`）には、`--cells` を指定しないときだけ `common.register` で出典の行を足す（c99 と同じ）。

何度回しても同じ結果。消して入れ直すのは広報誌の行（`doc_id GLOB 'tatsugo_koho_*'`、`series_id='tatsugo_koho'`）だけで、
ほかの文書の行・`cells` には触れない（広報誌の doc_id に cells が 1 行でもあれば止まる）。**実行する前に cells.sqlite を `.backup` すること。**
使い方はこの docstring と `--help`（argparse。本処理は走らない）。

    .venv/bin/python3 scripts/m13_tatsugo_koho.py --cells /tmp/cells_copy.sqlite      # 作業用コピーに書く（source_registry は触らない）
    .venv/bin/python3 scripts/m13_tatsugo_koho.py --dry-run                           # 検査と件数だけ（何も書かない）

検査（失敗したら止まる。設計書 §8.1）: 件数（176 号・180 ファイル。`--allow-partial` で外す）・月の欠け・分割の part 番号・
ページ範囲・全ページの被覆・話題の語彙・`kind='article'` の話題 1 件以上・article_id の衝突・本文 64KB 以下・
令和 2 年度以降の「主な記事」見出しとの突合（8 割以上。閾値は仮置き）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import sqlite3
import sys
import unicodedata

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import doccells as dc  # noqa: E402
from registry.build_article_topic import load_topics  # noqa: E402

SERIES_ID = "tatsugo_koho"
SOURCE_ID = "tatsugo_koho_amami"
REGION_ID = "jp-46"
DOC_PREFIX = "tatsugo_koho_"
PUBLISHER = "龍郷町"
SERIES_TITLE = "広報たつごう"
INDEX_URL = "https://www.town.tatsugo.lg.jp/kikakukanko/chose/koho-kocho/idx-kohoshi.html"
RAW_SUBDIR = "data/raw/tatsugo_koho/pdf"

# 2026-11 時点の件数（2012-04〜2026-11。月刊 175＋別冊 1、PDF 180）。号が増えたらこの 2 つを直す。
EXPECTED_ISSUES = 176
EXPECTED_FILES = 180
HEADLINE_THRESHOLD = 0.8
MAX_BODY_BYTES = 64 * 1024  # D1 の 1 文の SQL サイズ（100KB）に収める

LICENSE_TEXT = (
    "掲載内容の著作権は原則として龍郷町に帰属する（町「著作権・リンク」ページ）。私的利用と著作権法上の引用を超える"
    "複製・転用には事前の相談が要る旨の記載がある。2026-11-24、オーナーが龍郷町の広報担当と話し、ネットで公開されている"
    "ものを試験的に利用することを確認した（公開分のみ。取り下げの依頼があれば号・記事を外す）。"
)
AGREEMENT_NOTE = "2026-11-24 オーナーが広報担当と確認。テストとして公開分を利用。取り下げの依頼があれば号・記事を外す。"

KINDS = ("article", "unsegmented", "cover_toc")
PLACE_TYPES = ("settlement", "river", "coast", "other")

DDL_PATH = ROOT / "scripts" / "schema_tatsugo_koho.sql"
DEFAULT_PROCESSED = ROOT / "data" / "processed" / "tatsugo_koho"
DEFAULT_WITHDRAWN = ROOT / "scripts" / "data" / "tatsugo_koho_withdrawn.yaml"

TABLES_CHILD_FIRST = (
    "document_article_places", "document_article_topics", "document_articles",
    "periodical_issue_files", "periodical_issues", "periodical_series",
)


class M13Error(ValueError):
    pass


def norm(s: str | None) -> str:
    """NFKC・空白除去（見出しの突合・article_id・body_sha256 の正規化）。"""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", s or ""))


def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# 号・ファイル（§2.1・§2.2・§3.2〜3.4）
# ---------------------------------------------------------------------------

def _fiscal_year(year: int, month: int) -> int:
    return year if month >= 4 else year - 1


def _sorted_catalog(rows: list[dict]) -> list[dict]:
    for r in rows:
        for k in ("url", "link_text", "year", "month", "issue", "sha256", "n_pages"):
            if r.get(k) in (None, ""):
                raise M13Error(f"catalog.jsonl: {k} の無い行がある: {r.get('url') or r.get('link_text')!r}")
    return sorted(rows, key=lambda r: (r["issue"], bool(r.get("annex")), r.get("part") or 0, r["url"]))


def assign_ids(rows: list[dict]) -> list[dict]:
    """カタログの各行に `issue_id`・`doc_id`・`part_no` を付けて返す（入力は変えない）。

    - 月刊・合併号: issue_id=`tatsugo_koho_YYYYMM`（合併号は若い月）。ファイルが 1 つなら doc_id=issue_id。
      2 つ以上なら part（1 始まり・重複なし・連続）が必須で、doc_id=`…_p<part>`。
    - 別冊: 1 ファイル＝1 号。issue_id＝doc_id＝`tatsugo_koho_YYYYMM_sp<n>`（n は同月の別冊の通し番号）。
    """
    out: list[dict] = []
    monthly: dict[str, list[dict]] = {}
    annex_n: dict[str, int] = {}
    for r in _sorted_catalog(rows):
        r = dict(r)
        if r.get("annex"):
            annex_n[r["issue"]] = annex_n.get(r["issue"], 0) + 1
            r["issue_id"] = r["doc_id"] = f"{DOC_PREFIX}{r['issue']}_sp{annex_n[r['issue']]}"
            r["part_no"] = 1
            out.append(r)
        else:
            monthly.setdefault(r["issue"], []).append(r)
    for issue, files in monthly.items():
        base = f"{DOC_PREFIX}{issue}"
        if len(files) == 1:
            files[0].update(issue_id=base, doc_id=base, part_no=1)
        else:
            parts = sorted(f.get("part") or 0 for f in files)
            if parts != list(range(1, len(files) + 1)):
                raise M13Error(f"{issue}: ファイルが {len(files)} 個あるのに part が 1..{len(files)} になっていない: {parts}")
            for f in files:
                f.update(issue_id=base, doc_id=f"{base}_p{f['part']}", part_no=f["part"])
        out += files
    ids = [r["doc_id"] for r in out]
    if len(ids) != len(set(ids)):
        raise M13Error("doc_id が重複している")
    return sorted(out, key=lambda r: (r["issue_id"], r["part_no"]))


def doc_id_of(row: dict, siblings: list[dict]) -> str:
    """収集担当が doc_id を決めるときの入口（`assign_ids` と同じ規則）。`siblings` は同じカタログの全行。"""
    key = (row["url"],)
    for r in assign_ids(siblings):
        if (r["url"],) == key:
            return r["doc_id"]
    raise M13Error(f"カタログに無い行: {row['url']}")


def _title(r: dict) -> str:
    y, m = r["year"], r["month"]
    if r.get("annex"):
        t = f"広報たつごう {y}年{m}月 別冊"
    elif r.get("merged"):
        t = f"広報たつごう {y}年{r['months'][0]}・{r['months'][1]}月合併号"
    else:
        t = f"広報たつごう {y}年{m}月号"
    n_parts = r.get("_n_parts", 1)
    return f"{t}（その{r['part_no']}）" if n_parts > 1 else t


def build_issues(files: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """(documents の行, periodical_issues の行, periodical_issue_files の行)。files は `assign_ids` の結果。"""
    by_issue: dict[str, list[dict]] = {}
    for f in files:
        by_issue.setdefault(f["issue_id"], []).append(f)
    docs, issues, links = [], [], []
    for issue_id in sorted(by_issue):
        fs = sorted(by_issue[issue_id], key=lambda f: f["part_no"])
        offset = 0
        head = fs[0]
        for f in fs:
            f["_n_parts"] = len(fs)
            n_pages = int(f["n_pages"])
            if n_pages < 1:
                raise M13Error(f"{f['doc_id']}: n_pages が 1 未満")
            f["page_offset"] = offset
            f["n_pages"] = n_pages
            offset += n_pages
            saved = f.get("saved_name") or f["url"].rsplit("/", 1)[-1]
            docs.append(dict(
                doc_id=f["doc_id"], title=_title(f), publisher=PUBLISHER, url=f["url"], local_path=f"{RAW_SUBDIR}/{saved}",
                doc_sha256=f["sha256"], n_pages=n_pages, fiscal_year=_fiscal_year(f["year"], f["month"]),
                license=LICENSE_TEXT, fetched_at=f.get("fetched_at")))
            links.append(dict(doc_id=f["doc_id"], issue_id=issue_id, part_no=f["part_no"], page_offset=f["page_offset"],
                              link_text_raw=f["link_text"], download_url=f["url"]))
        headlines: list[str] = []
        for f in fs:
            for h in f.get("headlines") or []:
                if h not in headlines:
                    headlines.append(h)
        dated = next((f for f in fs if f.get("issue_date")), None)
        merged = bool(head.get("merged"))
        issues.append(dict(
            issue_id=issue_id, series_id=SERIES_ID, source_id=SOURCE_ID, region_id=REGION_ID,
            kind="supplement" if head.get("annex") else "monthly",
            year_month=f"{head['year']:04d}-{head['month']:02d}",
            year_month_to=f"{head['year']:04d}-{head['months'][1]:02d}" if merged else None,
            fiscal_year=_fiscal_year(head["year"], head["month"]),
            issued_on=dated["issue_date"] if dated else None,
            issued_on_raw=dated.get("heading") if dated else None,
            label_raw=head["link_text"], listing_url=head.get("source_page"),
            headlines=json.dumps(headlines, ensure_ascii=False) if headlines else None,
            n_files=len(fs), n_pages=offset,
            note=("合併号（%d月号は単独の号が無い）" % head["months"][1]) if merged else ("別冊" if head.get("annex") else None)))
    return docs, issues, links


def check_issue_continuity(issues: list[dict]) -> None:
    """月刊は最初の月から最後の月まで欠けがない（合併号の 2 か月目は埋まっているものとして数える）。"""
    have: set[str] = set()
    for i in issues:
        if i["kind"] != "monthly":
            continue
        have.add(i["year_month"])
        if i["year_month_to"]:
            have.add(i["year_month_to"])
    months = sorted(have)
    y, m = map(int, months[0].split("-"))
    ye, me = map(int, months[-1].split("-"))
    missing = []
    while (y, m) <= (ye, me):
        key = f"{y:04d}-{m:02d}"
        if key not in have:
            missing.append(key)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    if missing:
        raise M13Error(f"月刊の号が欠けている月がある: {missing}")


# ---------------------------------------------------------------------------
# 記事（§2.3・§3.5〜3.7）
# ---------------------------------------------------------------------------

def _h8(a: dict) -> str | None:
    t = norm(a.get("title"))
    if t:
        return sha256_text(t)[:8]
    b = norm(a.get("body_text"))[:40]
    return sha256_text(b)[:8] if b else None


def build_articles(arts: list[dict], files: list[dict], topic_ids: set[str], place_ids: set[str] | None = None
                   ) -> tuple[list[dict], list[dict], list[dict]]:
    """(document_articles, document_article_topics, document_article_places) の行。検査は §8.1。"""
    by_doc = {f["doc_id"]: f for f in files}
    articles, topics, places = [], [], []
    seen: set[str] = set()
    untitled: dict[tuple[str, int], int] = {}
    for a in arts:
        doc_id = a.get("doc_id")
        f = by_doc.get(doc_id)
        if f is None:
            raise M13Error(f"articles.jsonl: doc_id {doc_id!r} が catalog.jsonl に無い")
        p0, p1 = a.get("page_from"), a.get("page_to")
        if not (isinstance(p0, int) and isinstance(p1, int) and 1 <= p0 <= p1 <= f["n_pages"]):
            raise M13Error(f"{doc_id}: ページ範囲が不正 {p0}-{p1}（1..{f['n_pages']}）")
        kind = a.get("kind", "article")
        if kind not in KINDS:
            raise M13Error(f"{doc_id} p{p0}: kind が不正 {kind!r}")
        body = a.get("body_text")
        if body is not None and len(body.encode("utf-8")) > MAX_BODY_BYTES:
            raise M13Error(f"{doc_id} p{p0}: body_text が {MAX_BODY_BYTES} バイトを超える（D1 の 1 文の SQL の上限。設計書 §7.2）")
        if body is None and not a.get("unreadable_reason") and kind == "article":
            raise M13Error(f"{doc_id} p{p0}: 本文が無いのに unreadable_reason が無い（推測で埋めない。理由を書く）")
        conf = a.get("confidence")
        if conf is not None and not (0 <= conf <= 1):
            raise M13Error(f"{doc_id} p{p0}: confidence が 0..1 でない")
        h8 = _h8(a)
        if h8 is None:
            k = untitled[(doc_id, p0)] = untitled.get((doc_id, p0), 0) + 1
            h8 = f"untitled{k}"
        article_id = f"{doc_id}:{p0:03d}:{h8}"
        if article_id in seen:
            raise M13Error(f"article_id が衝突した: {article_id}（同じページに同じ見出しの記事が 2 つある）")
        seen.add(article_id)
        ev = a.get("event_dates")
        if ev is not None and not (isinstance(ev, list) and all(isinstance(e, dict) and "raw" in e for e in ev)):
            raise M13Error(f"{article_id}: event_dates は {{raw, iso}} の配列")
        off = f["page_offset"]
        articles.append(dict(
            article_id=article_id, issue_id=f["issue_id"], doc_id=doc_id, source_id=SOURCE_ID, region_id=REGION_ID, kind=kind,
            page_from=p0, page_to=p1, issue_page_from=p0 + off, issue_page_to=p1 + off,
            title=a.get("title"), section=a.get("section"), body_text=body,
            body_sha256=sha256_text(norm(body)) if body else None,
            event_dates=json.dumps(ev, ensure_ascii=False) if ev is not None else None,
            doc_sha256=f["sha256"], extractor=a.get("extractor"), confidence=conf, verified_by=a.get("verified_by"),
            unreadable_reason=a.get("unreadable_reason"), extracted_at=a.get("extracted_at")))
        ts = a.get("topics") or []
        if kind == "article" and not ts:
            raise M13Error(f"{article_id}: 話題が 0 件（どれにも当たらなければ other を付ける）")
        for t in ts:
            if t.get("topic_id") not in topic_ids:
                raise M13Error(f"{article_id}: topic_id {t.get('topic_id')!r} が語彙（registry/article_topic.yaml）に無い")
            topics.append(dict(article_id=article_id, topic_id=t["topic_id"], extractor=t.get("extractor"), confidence=t.get("confidence")))
        if len({t["topic_id"] for t in ts}) != len(ts):
            raise M13Error(f"{article_id}: 話題が重複している")
        raws: set[str] = set()
        for p in a.get("places") or []:
            raw = p.get("place_raw")
            if not raw or raw in raws:
                raise M13Error(f"{article_id}: place_raw が空か重複: {raw!r}")
            raws.add(raw)
            if p.get("place_type") not in (None, *PLACE_TYPES):
                raise M13Error(f"{article_id}: place_type が不正 {p.get('place_type')!r}")
            if p.get("place_id") and place_ids is not None and p["place_id"] not in place_ids:
                raise M13Error(f"{article_id}: place_id {p['place_id']!r} が place 表に無い")
            if p.get("place_id") and p.get("match_method") != "exact_name":
                raise M13Error(f"{article_id}: place_id を結ぶのは名称の完全一致（match_method=exact_name）だけ")
            places.append(dict(article_id=article_id, place_raw=raw, place_type=p.get("place_type"), place_id=p.get("place_id"),
                               match_method=p.get("match_method"), confidence=p.get("confidence")))
    return articles, topics, places


def check_coverage(files: list[dict], articles: list[dict]) -> None:
    """各ファイルの全ページが少なくとも 1 つの記事（unsegmented を含む）に入っている。"""
    covered: dict[str, set[int]] = {}
    for a in articles:
        covered.setdefault(a["doc_id"], set()).update(range(a["page_from"], a["page_to"] + 1))
    bad = {}
    for f in files:
        gap = sorted(set(range(1, f["n_pages"] + 1)) - covered.get(f["doc_id"], set()))
        if gap:
            bad[f["doc_id"]] = gap
    if bad:
        raise M13Error("どの記事にも入っていないページがある（切れないページは kind='unsegmented' で理由つきに残す）: "
                       + "; ".join(f"{d} {g[:10]}{'…' if len(g) > 10 else ''}" for d, g in sorted(bad.items())[:10]))


def headline_check(issues: list[dict], articles: list[dict]) -> tuple[int, int, list[tuple[str, str]]]:
    """令和 2 年度以降の「主な記事」見出しが、その号の記事の title/body に見つかるか。-> (見つかった数, 全数, 見つからない(号, 見出し))。"""
    hay: dict[str, str] = {}
    for a in articles:
        hay[a["issue_id"]] = hay.get(a["issue_id"], "") + norm(a["title"]) + "\n" + norm(a["body_text"]) + "\n"
    found = total = 0
    missing: list[tuple[str, str]] = []
    for i in issues:
        for h in json.loads(i["headlines"]) if i["headlines"] else []:
            total += 1
            if norm(h) and norm(h) in hay.get(i["issue_id"], ""):
                found += 1
            else:
                missing.append((i["issue_id"], h))
    return found, total, missing


# ---------------------------------------------------------------------------
# 取り下げ（§9）
# ---------------------------------------------------------------------------

def load_withdrawn(path: pathlib.Path) -> list[dict]:
    if not path.exists():
        return []
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    items = doc.get("withdrawals") or []
    for e in items:
        if not isinstance(e, dict) or e.get("scope") not in ("issue", "article") or not e.get("id") or not e.get("withdrawn_on"):
            raise M13Error(f"{path.name}: 取り下げの行は {{scope: issue|article, id, withdrawn_on}} が要る: {e!r}")
    return items


def apply_withdrawals(model: dict, items: list[dict]) -> dict:
    """除外リストに載る号（と、その号のファイル・記事）・記事を model から外す。知らない ID は止まる（打ち間違い・ID の変化に気づくため）。"""
    issue_ids = {i["issue_id"] for i in model["issues"]}
    article_ids = {a["article_id"] for a in model["articles"]}
    w_issues = {e["id"] for e in items if e["scope"] == "issue"}
    w_articles = {e["id"] for e in items if e["scope"] == "article"}
    unknown = sorted((w_issues - issue_ids) | (w_articles - article_ids))
    if unknown:
        raise M13Error(f"除外リストの ID が入力に無い（打ち間違いか、再抽出で article_id が変わった）: {unknown}")
    drop_docs = {f["doc_id"] for f in model["links"] if f["issue_id"] in w_issues}
    out = dict(model)
    out["issues"] = [i for i in model["issues"] if i["issue_id"] not in w_issues]
    out["links"] = [f for f in model["links"] if f["issue_id"] not in w_issues]
    out["docs"] = [d for d in model["docs"] if d["doc_id"] not in drop_docs]
    out["articles"] = [a for a in model["articles"] if a["issue_id"] not in w_issues and a["article_id"] not in w_articles]
    keep = {a["article_id"] for a in out["articles"]}
    out["topics"] = [t for t in model["topics"] if t["article_id"] in keep]
    out["places"] = [p for p in model["places"] if p["article_id"] in keep]
    out["withdrawn"] = {"issues": sorted(w_issues), "articles": sorted(w_articles), "docs": sorted(drop_docs)}
    return out


# ---------------------------------------------------------------------------
# 組み立て全体（DB に触らない）と書き込み
# ---------------------------------------------------------------------------

def build_model(catalog: list[dict], articles_in: list[dict], topic_ids: set[str], withdrawals: list[dict], *,
                allow_partial: bool = False, place_ids: set[str] | None = None, headline_threshold: float = HEADLINE_THRESHOLD,
                expect_issues: int = EXPECTED_ISSUES, expect_files: int = EXPECTED_FILES) -> dict:
    files = assign_ids(catalog)
    docs, issues, links = build_issues(files)
    if not allow_partial:
        if len(issues) != expect_issues or len(files) != expect_files:
            raise M13Error(f"件数が宣言と違う: 号 {len(issues)}（期待 {expect_issues}）・ファイル {len(files)}（期待 {expect_files}）。"
                           "取りこぼしか、号が増えた（EXPECTED_* を直す）。一部だけ入れるときは --allow-partial")
        check_issue_continuity(issues)
    for f in files:
        f.setdefault("sha256", None)
    articles, topics, places = build_articles(articles_in, files, topic_ids, place_ids)
    check_coverage(files, articles)
    found, total, missing = headline_check(issues, articles)
    if total and found / total < headline_threshold:
        raise M13Error(f"主な記事の見出しの突合が閾値未満: {found}/{total}（閾値 {headline_threshold}）。見つからない例: {missing[:5]}")
    model = dict(docs=docs, issues=issues, links=links, articles=articles, topics=topics, places=places,
                 headline_check={"found": found, "total": total, "missing": missing})
    return apply_withdrawals(model, withdrawals)


def _doc_notes() -> list[dict]:
    return [{"kind": "footnote", "page": None, "table_ids": [], "blocks_timeseries": 0,
             "text": LICENSE_TEXT + "自由な再利用ライセンス（CC 等）ではない。",
             "reason": "著作権は町に帰属。公開分の試験利用の合意"}]


def previous_articles(con: sqlite3.Connection) -> dict[str, str | None]:
    if not con.execute("SELECT 1 FROM sqlite_master WHERE name='document_articles'").fetchone():
        return {}
    return dict(con.execute("SELECT article_id, body_sha256 FROM document_articles WHERE source_id = ?", (SOURCE_ID,)))


def write(con: sqlite3.Connection, model: dict) -> dict:
    """広報誌の行を消して入れ直す（1 トランザクション）。返り値は旧原本との article_id の差分。"""
    con.execute("PRAGMA foreign_keys=ON")
    if not con.execute("SELECT 1 FROM sqlite_master WHERE name='documents'").fetchone():
        raise M13Error("cells.sqlite に documents 表が無い（原本のコピーを --cells に渡す）")
    con.executescript(DDL_PATH.read_text(encoding="utf-8"))
    n_cells = con.execute("SELECT count(*) FROM cells WHERE doc_id GLOB ?", (DOC_PREFIX + "*",)).fetchone()[0]
    if n_cells:
        raise M13Error(f"広報誌の doc_id に cells が {n_cells} 行ある（m13 は documents/notes だけを作る。表にしたものがあるなら設計を見直す）")
    old = previous_articles(con)
    con.execute("BEGIN IMMEDIATE")
    try:
        con.execute("DELETE FROM document_article_places WHERE article_id IN (SELECT article_id FROM document_articles WHERE source_id = ?)", (SOURCE_ID,))
        con.execute("DELETE FROM document_article_topics WHERE article_id IN (SELECT article_id FROM document_articles WHERE source_id = ?)", (SOURCE_ID,))
        con.execute("DELETE FROM document_articles WHERE source_id = ?", (SOURCE_ID,))
        con.execute("DELETE FROM periodical_issue_files WHERE doc_id GLOB ?", (DOC_PREFIX + "*",))
        con.execute("DELETE FROM periodical_issues WHERE series_id = ?", (SERIES_ID,))
        con.execute("DELETE FROM periodical_series WHERE series_id = ?", (SERIES_ID,))
        con.execute("DELETE FROM notes WHERE doc_id GLOB ?", (DOC_PREFIX + "*",))
        con.execute("DELETE FROM documents WHERE doc_id GLOB ?", (DOC_PREFIX + "*",))

        listing = [INDEX_URL] + sorted({i["listing_url"] for i in model["issues"] if i["listing_url"]})
        con.execute("INSERT INTO periodical_series VALUES (?,?,?,?,?,?,?,?)",
                    (SERIES_ID, SOURCE_ID, SERIES_TITLE, PUBLISHER, REGION_ID, json.dumps(listing, ensure_ascii=False),
                     LICENSE_TEXT, AGREEMENT_NOTE))
        for d in model["docs"]:
            fields = {k: v for k, v in d.items() if k != "doc_id"}
            dc.put_document(con, d["doc_id"], **fields)
            dc.put_notes(con, d["doc_id"], _doc_notes())
        for table, rows in (("periodical_issues", model["issues"]), ("periodical_issue_files", model["links"]),
                            ("document_articles", model["articles"]), ("document_article_topics", model["topics"]),
                            ("document_article_places", model["places"])):
            _insert(con, table, rows)
        bad = con.execute("PRAGMA foreign_key_check").fetchall()
        bad = [b for b in bad if b[0] in TABLES_CHILD_FIRST]
        if bad:
            raise M13Error(f"外部キーの孤児がある: {bad[:5]}")
        con.commit()
    except BaseException:
        con.rollback()
        raise
    new = {a["article_id"]: a["body_sha256"] for a in model["articles"]}
    return {"removed": sorted(set(old) - set(new)), "added": sorted(set(new) - set(old)),
            "changed": sorted(k for k in set(old) & set(new) if old[k] != new[k])}


def _insert(con: sqlite3.Connection, table: str, rows: list[dict]) -> None:
    if not rows:
        return
    cols = list(rows[0])
    con.executemany(f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                    [[r[c] for c in cols] for r in rows])


def read_jsonl(path: pathlib.Path) -> list[dict]:
    if not path.exists():
        raise M13Error(f"{path} が無い（収集担当の出力。設計書 §7.1）")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def report(model: dict, diff: dict | None) -> None:
    hc = model["headline_check"]
    print(f"号 {len(model['issues'])}（月刊 {sum(i['kind'] == 'monthly' for i in model['issues'])}・別冊 "
          f"{sum(i['kind'] == 'supplement' for i in model['issues'])}）・ファイル {len(model['links'])}・"
          f"記事 {len(model['articles'])}・話題 {len(model['topics'])}・地名 {len(model['places'])}")
    if hc["total"]:
        print(f"主な記事の見出し: {hc['found']}/{hc['total']} が記事に見つかった（見つからない {len(hc['missing'])} 件）")
        for issue, h in hc["missing"][:10]:
            print(f"  - {issue}: {h}")
    if model.get("withdrawn") and (model["withdrawn"]["issues"] or model["withdrawn"]["articles"]):
        print(f"取り下げ: 号 {model['withdrawn']['issues']}・記事 {len(model['withdrawn']['articles'])} 件を外した")
        print("  手元の PDF も消すこと:", model["withdrawn"]["docs"])
    if diff is not None:
        print(f"旧原本との差分: 消えた {len(diff['removed'])}・増えた {len(diff['added'])}・本文が変わった {len(diff['changed'])}")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--processed-dir", type=pathlib.Path, default=DEFAULT_PROCESSED)
    ap.add_argument("--cells", help="書き込み先の cells.sqlite（既定は data/db/cells.sqlite）。指定時は source_registry に登録しない")
    ap.add_argument("--withdrawn", type=pathlib.Path, default=DEFAULT_WITHDRAWN)
    ap.add_argument("--registry-db", help="place_id の実在を検査する registry.sqlite（省略時は検査しない）")
    ap.add_argument("--allow-partial", action="store_true", help="件数（176 号・180 ファイル）と月の欠けを検査しない（サンプル・テスト用）")
    ap.add_argument("--headline-threshold", type=float, default=HEADLINE_THRESHOLD)
    ap.add_argument("--no-register", action="store_true", help="source_registry に登録しない")
    ap.add_argument("--dry-run", action="store_true", help="検査と件数だけ。何も書かない")
    a = ap.parse_args(argv)

    place_ids = None
    if a.registry_db:
        rc = sqlite3.connect(f"file:{a.registry_db}?mode=ro", uri=True)
        place_ids = {r[0] for r in rc.execute("SELECT place_id FROM place")}
        rc.close()
    model = build_model(read_jsonl(a.processed_dir / "catalog.jsonl"), read_jsonl(a.processed_dir / "articles.jsonl"),
                        set(load_topics()), load_withdrawn(a.withdrawn), allow_partial=a.allow_partial, place_ids=place_ids,
                        headline_threshold=a.headline_threshold)
    if a.dry_run:
        report(model, None)
        return
    import common
    con = sqlite3.connect(a.cells, timeout=30) if a.cells else common.cellsdb()
    try:
        diff = write(con, model)
    finally:
        con.close()
    report(model, diff)
    if not (a.no_register or a.cells):
        common.register(
            source_id=SOURCE_ID, name="龍郷町 広報たつごう", publisher=PUBLISHER, url=INDEX_URL, category="行政広報誌",
            access_method="PDF 個別ダウンロード（documents・periodical_*・document_articles。本文あり）", fmt="PDF",
            license_=LICENSE_TEXT, redistributable=1, record_count=len(model["articles"]),
            notes="号と記事は get_records の record_set=periodical_issues / document_articles。設計は docs/plans/TATSUGO_KOHO.md。")


if __name__ == "__main__":
    try:
        main()
    except M13Error as e:
        raise SystemExit(f"m13: {e}")
