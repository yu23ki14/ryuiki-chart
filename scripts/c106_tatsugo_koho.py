"""c106: 龍郷町「広報たつごう」の目録づくりと PDF 取得（Issue #131 手順 0・1）。

  catalog                          索引→年度ページ＋令和元年度以前ページを取り、PDF ごとの目録 catalog.json を作る
  fetch --sample | --only YYYYMM…  指定の号の PDF を取り、sha256・ページ数を fetch_log.json に記録する

取得は GET のみ（scripts/common.py の get。UA とレート制限つき）。号はリンク文から決め、ファイル名は使わない
（ファイル名は時期ごとに付け方が違う）。HTML 解析は標準ライブラリだけ（CI は PyYAML と pytest しか無い）。
PDF のページ数を数える pymupdf は fetch の中で遅延 import する。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import unicodedata
import urllib.parse
from html.parser import HTMLParser

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
        if tag in ("h2", "h3"):
            self._buf, self._last = (tag, []), None
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
        elif text:
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
def cmd_catalog(raw: pathlib.Path) -> None:
    from common import get  # 遅延 import（requests を要する）
    html_dir = raw / "html"
    html_dir.mkdir(parents=True, exist_ok=True)

    def fetch_page(url):
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


def _pages_of(path: pathlib.Path) -> int | None:
    try:
        import pymupdf  # 遅延 import
        with pymupdf.open(path) as d:
            return d.page_count
    except Exception as e:  # noqa: BLE001
        print("page count failed:", path.name, e, file=sys.stderr)
        return None


def cmd_fetch(raw: pathlib.Path, only: list[str]) -> None:
    from common import get, sha256
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
        dest.write_bytes(get(r["url"], timeout=180).content)
        log[name] = {"url": r["url"], "issue": r["issue"], "bytes": dest.stat().st_size,
                     "sha256": sha256(dest), "pages": _pages_of(dest)}
        print("fetched", name, log[name]["bytes"], log[name]["pages"])
    log_path.write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--raw-dir", type=pathlib.Path, default=DEFAULT_RAW)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("catalog")
    f = sub.add_parser("fetch")
    f.add_argument("--sample", action="store_true")
    f.add_argument("--only", nargs="+", default=[], metavar="YYYYMM")
    a = ap.parse_args(argv)
    a.raw_dir.mkdir(parents=True, exist_ok=True)
    if a.cmd == "catalog":
        cmd_catalog(a.raw_dir)
    else:
        only = list(a.only) + (list(SAMPLE) if a.sample else [])
        if not only:
            ap.error("--sample か --only が要る（全件取得はまだしない）")
        cmd_fetch(a.raw_dir, only)


if __name__ == "__main__":
    main()
