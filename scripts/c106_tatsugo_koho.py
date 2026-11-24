"""c106: 龍郷町「広報たつごう」の目録づくりと PDF 取得（Issue #131 手順 0・1）。

  catalog                          索引→年度ページ＋令和元年度以前ページを取り、PDF ごとの目録 catalog.json を作る
  fetch --sample | --only YYYYMM…  指定の号の PDF を取り、sha256・ページ数を fetch_log.json に記録する

取得は GET のみ（scripts/common.py の get。UA とレート制限つき）。号はリンク文から決め、ファイル名は使わない
（ファイル名は時期ごとに付け方が違う）。HTML 解析は標準ライブラリだけ（CI は PyYAML と pytest しか無い）。
PDF のページ数を数える pymupdf は fetch・extract の中で遅延 import する。

  extract [--only YYYYMM…]         取得済み PDF を記事に切り、issues/files/pages/articles.jsonl と reconcile.json を
                                   --raw-dir 直下に書く（--only なら、その号の行だけ入れ替える）
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import unicodedata
import urllib.parse
from collections import defaultdict
from html.parser import HTMLParser

import tatsugo_segment as seg

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_RAW = ROOT / "data/raw/tatsugo_koho"
BASE = "https://www.town.tatsugo.lg.jp/kikakukanko/chose/koho-kocho/"
INDEX_URL = BASE + "idx-kohoshi.html"
OLD_PAGE = "kohotatsugo.html"
YEAR_PAGE_RE = re.compile(r"(?:^|/)(koho20\d\d\.html)$")
SAMPLE = ("201212", "201810", "202611")  # 2012〜13年・2018年・2026年から1冊ずつ（分割号は避ける）

ERA_BASE = {"令和": 2018, "平成": 1988, "昭和": 1925}


# ---------------------------------------------------------------- リンク文の解釈
def parse_link_text(text: str, section_label: str | None = None) -> dict | None:
    """リンク文 → {year, month, months, fiscal, part, merged, annex, size_kb}。号を決められなければ None。

    「2026年11月号」（西暦）、「令和元年度広報たつごう4月号」「平成30年度…」（年度。1〜3月は翌暦年）、
    「平成25年広報たつごう8月号」（元号の暦年）、「4.5月合併号」、「前半/後半」「1.」「2.」（分割）、「別冊」。
    年が文中に無い（「4月号」だけ）ときは section_label（見出しの年度）で補う。
    """
    t = re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))
    size = None
    m = re.search(r"PDF[:：]([\d,]+)KB", t)
    if m:
        size = int(m.group(1).replace(",", ""))
    head = re.split(r"[（(]PDF", t)[0]

    m = re.search(r"(令和|平成|昭和)(元|\d+)年(度?)", head) or re.search(r"(?<!\d)((?:19|20)\d\d)年(度?)", head)
    if m is None:
        return parse_link_text(section_label + head, None) if section_label else None
    if m.group(1) in ERA_BASE:
        n = 1 if m.group(2) == "元" else int(m.group(2))
        year, fiscal = ERA_BASE[m.group(1)] + n, bool(m.group(3))
    else:
        year, fiscal = int(m.group(1)), bool(m.group(2))

    rest = head[m.end():]
    mm = re.search(r"(\d{1,2})[.・](\d{1,2})月", rest)
    if mm:
        months = [int(mm.group(1)), int(mm.group(2))]
    else:
        mm = re.search(r"(\d{1,2})月", rest)
        months = [int(mm.group(1))] if mm else []
    if not months or not all(1 <= x <= 12 for x in months):
        return None
    if fiscal and months[0] <= 3:
        year += 1  # 年度表記の 1〜3 月は翌暦年

    tail = rest[mm.end():]
    part = None
    if "前半" in tail:
        part = 1
    elif "後半" in tail:
        part = 2
    else:
        pm = re.fullmatch(r"(?:合併)?号(\d)\.?", tail)  # 「2023年7月号1.」「…号2.」
        if pm:
            part = int(pm.group(1))
    return {
        "year": year, "month": months[0], "months": months, "fiscal": fiscal,
        "part": part, "merged": len(months) > 1, "annex": "別冊" in tail,
        "size_kb": size,
    }


def parse_issue_date(h3: str, issue_year: int, issue_month: int) -> str | None:
    """見出し「11月号（10月28日発行）」「4月号　3月31日発行」→ ISO 日付。年は号の年月から決める
    （発行は号の月と同じか前月以前。発行月 > 号の月なら前年）。"""
    m = re.search(r"(\d{1,2})月(\d{1,2})日?\s*発行", unicodedata.normalize("NFKC", h3))
    if not m:
        return None
    mo, d = int(m.group(1)), int(m.group(2))
    y = issue_year - 1 if mo > issue_month else issue_year
    return f"{y:04d}-{mo:02d}-{d:02d}"


# ---------------------------------------------------------------- HTML 解析
class _Page(HTMLParser):
    """h2/h3 の見出し、PDF リンク、直後の ul>li（主な記事。年度ページだけ）を拾う。"""

    def __init__(self, capture_li: bool):
        super().__init__(convert_charrefs=True)
        self.capture_li = capture_li
        self.entries: list[dict] = []
        self.hrefs: list[str] = []
        self.heading = None
        self._buf = None  # (kind, [text])
        self._href = None
        self._last = None  # 直前の PDF エントリ（続く li を紐づける）

    def handle_starttag(self, tag, attrs):
        href = dict(attrs).get("href") or ""
        if tag in ("h2", "h3", "div"):
            self._last = None  # 見出し・ブロックの区切り（サイトのフッターの ul を主な記事に取り込まない）
        if tag in ("h2", "h3"):
            self._buf = (tag, [])
        elif tag == "a" and href:
            self.hrefs.append(href)
            if href.lower().endswith(".pdf"):
                self._buf, self._href = ("a", []), href
        elif tag == "li" and self.capture_li and self._last is not None and self._buf is None:
            self._buf = ("li", [])

    def handle_data(self, data):
        if self._buf is not None:
            self._buf[1].append(data)

    def handle_endtag(self, tag):
        if tag == "ul" and self._last is not None and self.capture_li:
            self._last = None  # 主な記事の ul は 1 つだけ（2 つ目以降のリストは別物）
        if self._buf is None or self._buf[0] != tag:
            return
        kind, parts = self._buf
        text = "".join(parts).strip()
        self._buf = None
        if kind in ("h2", "h3"):
            self.heading = text
        elif kind == "a":
            self._last = {"link_text": text, "href": self._href, "heading": self.heading, "headlines": []}
            self.entries.append(self._last)
        elif text and self._last is not None:  # li の中の div で _last が外れていることがある
            self._last["headlines"].append(text)


def parse_page(html: str, page_url: str) -> list[dict]:
    p = _Page(capture_li=bool(YEAR_PAGE_RE.search(page_url)))
    p.feed(html)
    out = []
    for e in p.entries:
        # 令和元年度以前のページは h3「令和元年度」「平成30年度」を、年の無いリンク文の補いに使う
        sec = e["heading"] if e["heading"] and re.search(r"(令和|平成)", e["heading"]) else None
        info = parse_link_text(e["link_text"], sec)
        row = {"link_text": e["link_text"], "url": urllib.parse.urljoin(page_url, e["href"]),
               "source_page": page_url, "heading": e["heading"], "headlines": e["headlines"]}
        if info:
            row.update(info)
            row["issue_date"] = parse_issue_date(e["heading"] or "", info["year"], info["month"])
            row["issue"] = f"{info['year']:04d}{info['month']:02d}"
        else:
            row.update(parse_error=True, issue=None)
        out.append(row)
    _fix_fiscal_april(out)
    return out


def _fix_fiscal_april(rows: list[dict]) -> None:
    """年度表記の「4月号」は、年度の最後（翌年4月号＝3月末発行）に載ることがある（令和元年度ページの先頭の
    「令和元年度広報たつごう4月号」は 2020年4月号）。ページは新しい順なので、直後の行より新しくならない行は
    1年進める。年度見出しの規則だけでは決まらないので並び順で確かめる。"""
    for r, nxt in zip(rows, rows[1:]):
        if r.get("fiscal") and r["months"][0] == 4 and nxt.get("year") and (r["year"], 4) <= (nxt["year"], nxt["month"]):
            r["year"] += 1
            r["issue"] = f"{r['year']:04d}{r['month']:02d}"


def year_page_urls(index_html: str) -> list[str]:
    p = _Page(capture_li=False)
    p.feed(index_html)
    seen, out = set(), []
    for h in p.hrefs:
        m = YEAR_PAGE_RE.search(h)
        if m and m.group(1) not in seen:
            seen.add(m.group(1))
            out.append(urllib.parse.urljoin(INDEX_URL, h))
    return sorted(out)


def summarize(rows: list[dict]) -> dict:
    """冊数＝(年, 月) の異なる数。合併号（4.5月）は1冊、分割は1冊、別冊は本冊に数えない。"""
    issues = {r["issue"] for r in rows if r.get("issue") and not r.get("annex")}
    return {"pdf": len(rows), "issues": len(issues),
            "split_pdfs": sum(1 for r in rows if r.get("part")),
            "annex_pdfs": sum(1 for r in rows if r.get("annex")),
            "merged_pdfs": sum(1 for r in rows if r.get("merged")),
            "parse_errors": sum(1 for r in rows if r.get("parse_error"))}


# ---------------------------------------------------------------- コマンド
def cmd_catalog(raw: pathlib.Path, offline: bool = False) -> None:
    """offline なら取得せず、保存済みの HTML（raw/html）から目録を作り直す。"""
    html_dir = raw / "html"
    html_dir.mkdir(parents=True, exist_ok=True)

    def fetch_page(url):
        if offline:
            return (html_dir / url.rsplit("/", 1)[-1]).read_text(encoding="utf-8")
        from common import get  # 遅延 import（requests を要する）
        r = get(url)
        r.encoding = "utf-8"
        (html_dir / url.rsplit("/", 1)[-1]).write_text(r.text, encoding="utf-8")
        return r.text

    pages = year_page_urls(fetch_page(INDEX_URL)) + [BASE + OLD_PAGE]
    rows = []
    for u in pages:
        rows += parse_page(fetch_page(u), u)
    s = summarize(rows)
    (raw / "catalog.json").write_text(json.dumps({"pages": pages, "summary": s, "pdfs": rows},
                                                 ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(s, ensure_ascii=False), f"pages={len(pages)}")


def _pages_of(path: pathlib.Path) -> int:
    """PDF のページ数（pymupdf）。開けなければ握りつぶさず例外で止める。"""
    import pymupdf  # 遅延 import
    with pymupdf.open(path) as d:
        return d.page_count


def cmd_fetch(raw: pathlib.Path, only: list[str]) -> None:
    import os
    from common import download, sha256
    cat = json.loads((raw / "catalog.json").read_text(encoding="utf-8"))
    log_path = raw / "fetch_log.json"
    log = json.loads(log_path.read_text(encoding="utf-8")) if log_path.exists() else {}
    pdf_dir = raw / "pdf"
    pdf_dir.mkdir(exist_ok=True)
    for r in cat["pdfs"]:
        if r.get("issue") not in only:
            continue
        name = r["url"].rsplit("/", 1)[-1]
        dest = pdf_dir / name
        if dest.exists() and log.get(name, {}).get("sha256") == sha256(dest):
            print("skip (same sha256)", name)
            continue
        part = dest.with_name(name + ".part")  # 取得の途中で止まった半端なファイルを PDF として残さない
        part.unlink(missing_ok=True)
        download(r["url"], part, timeout=180)
        pages = _pages_of(part)  # 開けなければここで止まる（.part は残るが次回消す）
        os.replace(part, dest)
        log[name] = {"url": r["url"], "issue": r["issue"], "bytes": dest.stat().st_size, "sha256": sha256(dest), "pages": pages}
        print("fetched", name, log[name]["bytes"], log[name]["pages"])
    log_path.write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------------------------------------------------------------- extract
SOURCE_ID = "tatsugo_koho"
REGION_ID = "jp-46"


def build_issue_tables(cat_rows: list[dict], fetch_log: dict) -> tuple[list[dict], list[dict]]:
    """catalog の PDF 行 → issues（号）と files（ファイル）。設計書 §2・§3.2・§3.3。"""
    by_issue: dict[str, list[tuple[int, dict]]] = {}
    annex_n: dict[str, int] = {}
    # 別冊は 1 ファイル＝1 号で、同じ月の別冊は URL の順に `_sp1`・`_sp2`…（m13 の assign_ids と同じ規則）
    for i, r in sorted(enumerate(cat_rows), key=lambda ir: ir[1]["url"]):
        if not r.get("issue"):
            continue
        key = r["issue"]
        if r.get("annex"):
            annex_n[key] = annex_n.get(key, 0) + 1
            key += f"_sp{annex_n[key]}"
        by_issue.setdefault(key, []).append((i, r))
    issues, files = [], []
    for key in sorted(by_issue):
        rows = sorted(by_issue[key], key=lambda ir: (ir[1].get("part") or 0, ir[0]))
        first = rows[0][1]
        ym = f"{first['year']:04d}-{first['month']:02d}"
        months = first["months"]
        issue_id = f"tatsugo_koho_{key}"
        offset, n_pages_total, any_unknown = 0, 0, False
        for n, (_, r) in enumerate(rows, 1):
            name = r["url"].rsplit("/", 1)[-1]
            fl = fetch_log.get(name, {})
            doc_id = issue_id if len(rows) == 1 else f"{issue_id}_p{n}"
            files.append({
                "doc_id": doc_id, "issue_id": issue_id, "part_no": n, "page_offset": offset,
                "link_text_raw": r["link_text"], "download_url": r["url"], "local_path": f"pdf/{name}",
                "sha256": fl.get("sha256"), "n_pages": fl.get("pages"), "size_kb_listed": r.get("size_kb"),
            })
            if fl.get("pages") is None:
                any_unknown = True
            else:
                offset += fl["pages"]
                n_pages_total += fl["pages"]
        heads = [h for _, r in rows for h in r["headlines"]]
        fy = first["year"] if first["month"] >= 4 else first["year"] - 1
        issues.append({
            "issue_id": issue_id, "kind": "supplement" if first.get("annex") else "monthly", "year_month": ym,
            "year_month_to": f"{first['year']:04d}-{months[1]:02d}" if len(months) > 1 else None,
            "fiscal_year": fy, "issued_on": first.get("issue_date"), "issued_on_raw": first.get("heading"),
            "label_raw": first["link_text"], "listing_url": first["source_page"], "headlines": heads or None,
            "n_files": len(rows), "n_pages": None if any_unknown else n_pages_total,
            "note": "合併号" if len(months) > 1 else ("別冊" if first.get("annex") else None),
        })
    return issues, files


def extract_file(pdf_path: pathlib.Path, issue: dict, f: dict) -> tuple[list[dict], list[dict]]:
    """1 ファイル → (pages 行, articles 行)。pymupdf を使う。"""
    import pymupdf  # 遅延 import
    y, m = int(issue["year_month"][:4]), int(issue["year_month"][5:])
    pages, pages_rows = [], []
    with pymupdf.open(pdf_path) as d:
        for i, p in enumerate(d, 1):
            raw = p.get_text("dict")
            blocks = seg.blocks_from_pymupdf(raw)
            area = p.rect.width * p.rect.height
            img = sum((pymupdf.Rect(im["bbox"]) & p.rect).get_area() for im in p.get_image_info()) / area
            pages.append({"page": i, "w": p.rect.width, "h": p.rect.height, "blocks": blocks, "image_cover": img})
            nchars = sum(len(b["text"].strip()) for b in blocks)
            vch = sum(len(b["text"].strip()) for b in blocks if b["vertical"])
            pages_rows.append({"doc_id": f["doc_id"], "page": i, "n_chars": nchars, "has_text_layer": nchars >= 20,
                               "vertical_ratio": round(vch / nchars, 2) if nchars else None,
                               "image_cover": round(img, 2)})
        version = pymupdf.__version__
    base = seg.body_size([p["blocks"] for p in pages])
    now = now_iso()
    arts = []
    for a in seg.segment_file(pages, base):
        kind = "cover_toc" if a["page_from"] == 1 and f["part_no"] == 1 else a["kind"]
        is_cover = kind == "cover_toc"
        a.update({
            "doc_id": f["doc_id"], "issue_id": f["issue_id"], "kind": kind,
            "event_dates": [] if is_cover else seg.extract_dates(a["body_text"], y, m),
            "topics": [] if is_cover else seg.classify(a["title"], a["body_text"]),
            "places": [] if is_cover else seg.extract_places(a["title"], a["body_text"]),
            "extractor": f"pymupdf:{version}+{seg.LAYOUT_VERSION}+{seg.RULE_VERSION}", "verified_by": None,
            "extracted_at": now,
        })
        arts.append(a)
    return pages_rows, arts


def now_iso() -> str:
    import datetime
    return datetime.datetime.now().isoformat(timespec="seconds")


def read_jsonl(p: pathlib.Path, *, missing_ok: bool = False) -> list[dict]:
    """JSON Lines を読む。無ければ FileNotFoundError（missing_ok なら空）。m13 もこれを使う。"""
    if missing_ok and not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def write_jsonl(p: pathlib.Path, rows: list[dict]) -> None:
    p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def cmd_extract(raw: pathlib.Path, only: list[str]) -> None:
    cat = json.loads((raw / "catalog.json").read_text(encoding="utf-8"))
    log = json.loads((raw / "fetch_log.json").read_text(encoding="utf-8")) if (raw / "fetch_log.json").exists() else {}
    issues, files = build_issue_tables(cat["pdfs"], log)
    write_jsonl(raw / "issues.jsonl", issues)
    write_jsonl(raw / "files.jsonl", files)
    iss_by_id = {i["issue_id"]: i for i in issues}
    todo = [f for f in files if (not only or f["issue_id"].removeprefix("tatsugo_koho_")[:6] in only)
            and f["sha256"] and (raw / f["local_path"]).exists()]
    pages_old, arts_old = read_jsonl(raw / "pages.jsonl", missing_ok=True), read_jsonl(raw / "articles.jsonl", missing_ok=True)
    done = {f["doc_id"] for f in todo}
    pages_all = [r for r in pages_old if r["doc_id"] not in done]
    arts_all = [r for r in arts_old if r["doc_id"] not in done]
    for f in todo:
        pr, ar = extract_file(raw / f["local_path"], iss_by_id[f["issue_id"]], f)
        for a in ar:
            a["doc_sha256"] = f["sha256"]
        pages_all += pr
        arts_all += ar
        print(f["doc_id"], f"pages={len(pr)} articles={len(ar)}")
    write_jsonl(raw / "pages.jsonl", pages_all)
    write_jsonl(raw / "articles.jsonl", arts_all)
    # 令和 2 年度以降の「主な記事」見出しとの照合（抽出済みの号だけ）
    by_issue: dict[str, list[dict]] = defaultdict(list)
    for a in arts_all:
        by_issue[a["issue_id"]].append(a)
    rec = {}
    for i in issues:
        if not i["headlines"]:
            continue
        arts = by_issue.get(i["issue_id"])
        if arts:
            unread = sum(1 for a in arts if a["unreadable_reason"] in seg.UNREADABLE_REASONS)
            rec[i["issue_id"]] = seg.reconcile_issue(i["headlines"], arts, unread)
    (raw / "reconcile.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    for k, v in rec.items():
        print("reconcile", k, f"headlines={v['headlines']} matched={len(v['matched'])} "
              f"in_text_only={len(v['in_text_only'])} paraphrase={len(v['paraphrase'])} "
              f"missed_unreadable={len(v['missed_unreadable'])} missed={len(v['missed'])} extra={v['extra_count']}")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--raw-dir", type=pathlib.Path, default=DEFAULT_RAW)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("catalog").add_argument("--offline", action="store_true", help="保存済みの HTML から作り直す（取得しない）")
    f = sub.add_parser("fetch")
    f.add_argument("--sample", action="store_true")
    f.add_argument("--only", nargs="+", default=[], metavar="YYYYMM")
    e = sub.add_parser("extract")
    e.add_argument("--only", nargs="+", default=[], metavar="YYYYMM")
    a = ap.parse_args(argv)
    a.raw_dir.mkdir(parents=True, exist_ok=True)
    if a.cmd == "catalog":
        cmd_catalog(a.raw_dir, a.offline)
    elif a.cmd == "extract":
        cmd_extract(a.raw_dir, a.only)
    else:
        only = list(a.only) + (list(SAMPLE) if a.sample else [])
        if not only:
            ap.error("--sample か --only が要る（全件取得はまだしない）")
        cmd_fetch(a.raw_dir, only)


if __name__ == "__main__":
    main()
