"""m13: 龍郷町「広報たつごう」の号・ファイル・記事を cells.sqlite に作る（Issue #130、docs/plans/TATSUGO_KOHO.md §2・§3・§7.2・§8.1・§9）。

入力（`data/raw/tatsugo_koho/`。収集担当 c106 の `extract` の出力。契約は設計書 §7.1。gitignore 済みの生成物）:

- `issues.jsonl`・`files.jsonl`: 号とファイル（`periodical_issues`・`periodical_issue_files` の列に `local_path`・`sha256`・`n_pages` を足した形）。
  doc_id・page_offset・n_files・n_pages は §2・§3 の規則と照合する（食い違えば止まる）。未取得のファイル（sha256・n_pages が無い）がある号は、
  `--allow-partial` なら号ごと除き、無ければ止まる。
- `articles.jsonl`: 記事ごとに 1 行。`doc_id`・`page_from`・`page_to`（ファイル内ページ）・
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
ページ範囲・全ページの被覆・話題の語彙・`kind='article'` の話題 1 件以上・article_id の衝突（同一記事の重複は通し番号 `x2` で区別）・本文 64KB 以下・
令和 2 年度以降の「主な記事」見出しとの突合（読めないページの無い号で、本文のどこかに見つかる割合が 95% 以上）。
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
import tatsugo_segment as seg  # noqa: E402
from c106_tatsugo_koho import read_jsonl  # noqa: E402  jsonl の読み書きは c106 と共通
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
HEADLINE_THRESHOLD = 0.95  # 見出しが本文のどこかに見つかる割合（題の一致率ではない。読めないページのある号で見つからないものは分母から除く）
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
DEFAULT_RAW = ROOT / "data" / "raw" / "tatsugo_koho"
DEFAULT_WITHDRAWN = ROOT / "scripts" / "data" / "tatsugo_koho_withdrawn.yaml"

TABLES_CHILD_FIRST = (
    "document_article_places", "document_article_topics", "document_articles",
    "periodical_issue_files", "periodical_issues", "periodical_series",
)


class M13Error(ValueError):
    pass


def norm_id(s: str | None) -> str:
    """NFKC・空白除去（見出しの突合・article_id・body_sha256 の正規化）。"""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", s or ""))


def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# 号・ファイル（§2.1・§2.2・§3.2〜3.4）
# ---------------------------------------------------------------------------

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
    t = norm_id(a.get("title"))
    if t:
        return sha256_text(t)[:8]
    b = norm_id(a.get("body_text"))[:40]
    return sha256_text(b)[:8] if b else None


def build_articles(arts: list[dict], files: list[dict], topic_ids: set[str], place_ids: set[str] | None = None
                   ) -> tuple[list[dict], list[dict], list[dict]]:
    """(document_articles, document_article_topics, document_article_places) の行。検査は §8.1。"""
    by_doc = {f["doc_id"]: f for f in files}
    articles, topics, places = [], [], []
    seen: set[str] = set()
    untitled: dict[tuple[str, int], int] = {}
    # 同じ (doc_id, page_from, 見出しの h8) が複数ある記事（同じページに同じ見出し。例「主な活動」「▼連絡先」）は、
    # 見出し＋本文の先頭 80 字で h8 を作り直して区別する（入力の並びに依存しない）。それでも重なれば止まる。
    first_keys: dict[tuple, int] = {}
    for a in arts:
        k = (a.get("doc_id"), a.get("page_from"), _h8(a))
        first_keys[k] = first_keys.get(k, 0) + 1
    for a in arts:
        doc_id = a.get("doc_id")
        f = by_doc.get(doc_id)
        if f is None:
            raise M13Error(f"articles.jsonl: doc_id {doc_id!r} が files.jsonl に無い")
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
        if h8 is not None and first_keys[(doc_id, p0, h8)] > 1:
            h8 = sha256_text(norm_id(a.get("title")) + "\0" + norm_id(body)[:80])[:8]
        if h8 is None:
            k = untitled[(doc_id, p0)] = untitled.get((doc_id, p0), 0) + 1
            h8 = f"untitled{k}"
        article_id = f"{doc_id}:{p0:03d}:{h8}"
        if article_id in seen:
            # 見出しも本文の先頭も同じ記事が同じページに 2 つ以上ある（見出しだけの重複。c106 の実データに 6 組）。
            # 入力の並び順の通し番号 `x2`・`x3` で区別する（ほかに区別の手がかりが無い）。
            k = 2
            while f"{article_id}x{k}" in seen:
                k += 1
            article_id = f"{article_id}x{k}"
        seen.add(article_id)
        ev = a.get("event_dates")
        if ev is not None and not (isinstance(ev, list) and all(isinstance(e, dict) and "raw" in e for e in ev)):
            raise M13Error(f"{article_id}: event_dates は {{raw, iso}} の配列")
        off = f["page_offset"]
        articles.append(dict(
            article_id=article_id, issue_id=f["issue_id"], doc_id=doc_id, source_id=SOURCE_ID, region_id=REGION_ID, kind=kind,
            page_from=p0, page_to=p1, issue_page_from=p0 + off, issue_page_to=p1 + off,
            title=a.get("title"), section=a.get("section"), body_text=body,
            body_sha256=sha256_text(norm_id(body)) if body else None,
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


def headline_check(issues: list[dict], articles: list[dict]) -> dict:
    """令和 2 年度以降の「主な記事」見出し（HTML）と、抽出した記事の突合（`tatsugo_segment.reconcile_issue` と同じ分類）。

    見出しが本文のどこかに見つかった数（題の一致＋本文中にある＋言い換え）を、全見出しから「読めないページ
    （スキャン・文字化け）のある号で見つからなかったもの（missed_unreadable。OCR で読める可能性）」を除いた数で割る
    （`found`/`total`）。題の一致率（`title_matched`）は報告するだけ。
    -> {"found", "total", "title_matched", "classes"（分類ごとの数）, "missing"（(号, 見出し, 分類)。読めない理由の無い取りこぼし）}"""
    by_issue: dict[str, list[dict]] = {}
    for a in articles:
        by_issue.setdefault(a["issue_id"], []).append(a)
    classes = {"matched": 0, "in_text_only": 0, "paraphrase": 0, "missed_unreadable": 0, "missed": 0}
    n_headlines = 0
    missing: list[tuple[str, str, str]] = []
    for i in issues:
        hl = json.loads(i["headlines"]) if i["headlines"] else []
        if not hl:
            continue
        arts = by_issue.get(i["issue_id"], [])
        unread = sum(1 for a in arts if a["unreadable_reason"] in seg.UNREADABLE_REASONS)
        r = seg.reconcile_issue(hl, arts, unread)
        n_headlines += r["headlines"]
        for k in classes:
            classes[k] += len(r[k])
        missing += [(i["issue_id"], h, "missed") for h in r["missed"]]
    found = classes["matched"] + classes["in_text_only"] + classes["paraphrase"]
    return {"found": found, "total": n_headlines - classes["missed_unreadable"], "title_matched": classes["matched"],
            "classes": classes, "missing": missing}


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

def _mtime_iso(path: pathlib.Path) -> str | None:
    """PDF の取得日時（ファイルの更新時刻。c99 と同じ）。ファイルが無ければ None。"""
    import datetime
    return datetime.datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds") if path.exists() else None


def from_extract(issues: list[dict], files: list[dict], raw_dir: pathlib.Path | None = None, *, allow_partial: bool = False) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    """c106 `extract` の issues.jsonl / files.jsonl（`periodical_issues`・`periodical_issue_files` の列で出てくる）を受ける。
    doc_id・page_offset・n_files・n_pages が §2・§3 の規則と食い違えば止まる（c106 側の誤りをここで見つける）。
    -> (documents の行, periodical_issues の行, periodical_issue_files の行, 記事の検査に使うファイル行)。"""
    by_issue: dict[str, list[dict]] = {}
    for f in files:
        by_issue.setdefault(f["issue_id"], []).append(f)
    iss = {i["issue_id"]: i for i in issues}
    if len(iss) != len(issues) or set(by_issue) != set(iss):
        raise M13Error("issues.jsonl と files.jsonl の号が一致しない")
    docs, out_issues, links, flist = [], [], [], []
    skipped: list[str] = []
    for issue_id in sorted(iss):
        i = iss[issue_id]
        fs = sorted(by_issue[issue_id], key=lambda f: f["part_no"])
        n = len(fs)
        if any(f.get("n_pages") is None or not f.get("sha256") for f in fs):  # 未取得のファイルがある号
            if not allow_partial:
                raise M13Error(f"{issue_id}: 未取得のファイル（sha256・n_pages が無い）がある。取得してから extract を回す（一部だけなら --allow-partial）")
            skipped.append(issue_id)
            continue
        if [f["part_no"] for f in fs] != list(range(1, n + 1)):
            raise M13Error(f"{issue_id}: part_no が 1..{n} でない")
        offset = 0
        for f in fs:
            want = issue_id if (i["kind"] == "supplement" or n == 1) else f"{issue_id}_p{f['part_no']}"
            if f["doc_id"] != want:
                raise M13Error(f"{f['doc_id']}: doc_id が規則（{want}）と違う")
            if f["page_offset"] != offset:
                raise M13Error(f"{f['doc_id']}: page_offset が {f['page_offset']}（期待 {offset}）")
            if not f.get("sha256") or int(f["n_pages"]) < 1:
                raise M13Error(f"{f['doc_id']}: sha256 か n_pages が無い")
            offset += int(f["n_pages"])
            saved = f["local_path"].rsplit("/", 1)[-1]
            ym = i["year_month"]
            y, mo = int(ym[:4]), int(ym[5:7])
            if i["kind"] == "supplement":
                title = f"広報たつごう {y}年{mo}月 別冊"
            elif i["year_month_to"]:
                title = f"広報たつごう {y}年{mo}・{int(i['year_month_to'][5:7])}月合併号"
            else:
                title = f"広報たつごう {y}年{mo}月号"
            if n > 1:
                title += f"（その{f['part_no']}）"
            docs.append(dict(doc_id=f["doc_id"], title=title, publisher=PUBLISHER, url=f["download_url"], local_path=f"{RAW_SUBDIR}/{saved}",
                             doc_sha256=f["sha256"], n_pages=int(f["n_pages"]), fiscal_year=i["fiscal_year"], license=LICENSE_TEXT,
                             fetched_at=_mtime_iso(raw_dir / f["local_path"]) if raw_dir else None))
            links.append({k: f[k] for k in ("doc_id", "issue_id", "part_no", "page_offset", "link_text_raw", "download_url")})
            flist.append(dict(doc_id=f["doc_id"], issue_id=issue_id, n_pages=int(f["n_pages"]), page_offset=offset - int(f["n_pages"]),
                              sha256=f["sha256"]))
        if (i["n_files"], i["n_pages"]) != (n, offset):
            raise M13Error(f"{issue_id}: n_files/n_pages が files.jsonl と合わない（{i['n_files']}/{i['n_pages']} と {n}/{offset}）")
        h = i.get("headlines")
        out_issues.append(dict(
            issue_id=issue_id, series_id=SERIES_ID, source_id=SOURCE_ID, region_id=REGION_ID, kind=i["kind"],
            year_month=i["year_month"], year_month_to=i.get("year_month_to"), fiscal_year=i["fiscal_year"],
            issued_on=i.get("issued_on"), issued_on_raw=i.get("issued_on_raw"), label_raw=i.get("label_raw"),
            listing_url=i.get("listing_url"), headlines=json.dumps(h, ensure_ascii=False) if h else None,
            n_files=n, n_pages=offset, note=i.get("note")))
    if skipped:
        print(f"未取得の号を除いた（--allow-partial）: {skipped}", file=sys.stderr)
    return docs, out_issues, links, flist


def finish_model(docs, issues, links, files, articles_in, topic_ids, withdrawals, *, allow_partial=False, place_ids=None,
                 headline_threshold=HEADLINE_THRESHOLD, expect_issues=EXPECTED_ISSUES, expect_files=EXPECTED_FILES) -> dict:
    if not allow_partial:
        if len(issues) != expect_issues or len(files) != expect_files:
            raise M13Error(f"件数が宣言と違う: 号 {len(issues)}（期待 {expect_issues}）・ファイル {len(files)}（期待 {expect_files}）。"
                           "取りこぼしか、号が増えた（EXPECTED_* を直す）。一部だけ入れるときは --allow-partial")
        check_issue_continuity(issues)
    articles, topics, places = build_articles(articles_in, files, topic_ids, place_ids)
    check_coverage(files, articles)
    hc = headline_check(issues, articles)
    if hc["total"] and hc["found"] / hc["total"] < headline_threshold:
        raise M13Error(f"主な記事の見出しの突合が閾値未満: {hc['found']}/{hc['total']}（閾値 {headline_threshold}）。見つからない例: {hc['missing'][:5]}")
    model = dict(docs=docs, issues=issues, links=links, articles=articles, topics=topics, places=places,
                 headline_check=hc)
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
        mine = DOC_PREFIX + "*"
        article_ids = "article_id IN (SELECT article_id FROM document_articles WHERE source_id = ?)"
        for table, where, arg in (
            ("document_article_places", article_ids, SOURCE_ID), ("document_article_topics", article_ids, SOURCE_ID),
            ("document_articles", "source_id = ?", SOURCE_ID), ("periodical_issue_files", "doc_id GLOB ?", mine),
            ("periodical_issues", "series_id = ?", SERIES_ID), ("periodical_series", "series_id = ?", SERIES_ID),
            ("notes", "doc_id GLOB ?", mine), ("documents", "doc_id GLOB ?", mine),
        ):
            con.execute(f"DELETE FROM {table} WHERE {where}", (arg,))

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


def read_input(path: pathlib.Path) -> list[dict]:
    try:
        return read_jsonl(path)
    except FileNotFoundError:
        raise M13Error(f"{path} が無い（c106 の extract の出力。設計書 §7.1）") from None


def report(model: dict, diff: dict | None) -> None:
    hc = model["headline_check"]
    print(f"号 {len(model['issues'])}（月刊 {sum(i['kind'] == 'monthly' for i in model['issues'])}・別冊 "
          f"{sum(i['kind'] == 'supplement' for i in model['issues'])}）・ファイル {len(model['links'])}・"
          f"記事 {len(model['articles'])}・話題 {len(model['topics'])}・地名 {len(model['places'])}")
    if hc["total"]:
        print(f"主な記事の見出し（読めないために見つからないものを除く）: 本文に見つかった {hc['found']}/{hc['total']}"
              f"（{hc['found'] / hc['total']:.1%}。題の一致 {hc['title_matched']}）。分類（全号）: {hc['classes']}")
        for issue, h, _c in hc["missing"][:10]:
            print(f"  - {issue}: {h}")
    if model.get("withdrawn") and (model["withdrawn"]["issues"] or model["withdrawn"]["articles"]):
        print(f"取り下げ: 号 {model['withdrawn']['issues']}・記事 {len(model['withdrawn']['articles'])} 件を外した")
        print("  手元の PDF も消すこと:", model["withdrawn"]["docs"])
    if diff is not None:
        print(f"旧原本との差分: 消えた {len(diff['removed'])}・増えた {len(diff['added'])}・本文が変わった {len(diff['changed'])}")


def register_source(common, model: dict) -> None:
    """source_registry（ryuiki.sqlite）に出典の行を足す（c99 と同じ）。"""
    common.register(
        source_id=SOURCE_ID, name="龍郷町 広報たつごう", publisher=PUBLISHER, url=INDEX_URL, category="行政広報誌",
        access_method="PDF 個別ダウンロード（documents・periodical_*・document_articles。本文あり）", fmt="PDF",
        license_=LICENSE_TEXT, redistributable=1, record_count=len(model["articles"]),
        notes="号と記事は get_records の record_set=periodical_issues / document_articles。設計は docs/plans/TATSUGO_KOHO.md。"
              "redistributable=1 の根拠: 2026-11-24 オーナーが龍郷町の広報担当と確認し、公開分の再配布（本文の掲載）が可。自由な再利用ライセンスではない。")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--raw-dir", type=pathlib.Path, default=DEFAULT_RAW, help="c106 extract の出力先（issues/files/articles.jsonl と PDF）")
    ap.add_argument("--cells", help="書き込み先の cells.sqlite（既定は data/db/cells.sqlite）。指定時は source_registry に登録しない")
    ap.add_argument("--withdrawn", type=pathlib.Path, default=DEFAULT_WITHDRAWN)
    ap.add_argument("--registry-db", help="place_id の実在を検査する registry.sqlite（省略時は検査しない）")
    ap.add_argument("--allow-partial", action="store_true", help="件数（176 号・180 ファイル）と月の欠けを検査しない（サンプル・テスト用）")
    ap.add_argument("--no-register", action="store_true", help="source_registry に登録しない")
    ap.add_argument("--dry-run", action="store_true", help="検査と件数だけ。何も書かない")
    a = ap.parse_args(argv)

    place_ids = None
    if a.registry_db:
        rc = sqlite3.connect(f"file:{a.registry_db}?mode=ro", uri=True)
        place_ids = {r[0] for r in rc.execute("SELECT place_id FROM place")}
        rc.close()
    kw = dict(allow_partial=a.allow_partial, place_ids=place_ids, headline_threshold=HEADLINE_THRESHOLD)
    docs, issues, links, files = from_extract(read_input(a.raw_dir / "issues.jsonl"), read_input(a.raw_dir / "files.jsonl"),
                                              a.raw_dir, allow_partial=a.allow_partial)
    model = finish_model(docs, issues, links, files, read_input(a.raw_dir / "articles.jsonl"), set(load_topics()),
                         load_withdrawn(a.withdrawn), **kw)
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
        register_source(common, model)


if __name__ == "__main__":
    try:
        main()
    except M13Error as e:
        raise SystemExit(f"m13: {e}")
