#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""鹿児島県希少野生動植物の保護に関する条例の指定希少野生動植物（59種）

県サイトの「指定希少野生動植物について」ページ（zyorei/03007006.html）にある一覧表 PDF
（「鹿児島県指定希少野生動植物一覧表」）を読む。URL はページの HTML のリンクから確かめる（推測しない）。
列は「分類・和名・学名・科名・県カテゴリー」の 5 つ。PDF の見出し（動物 20 種・植物 39 種・計 59 種）で検算する。
カテゴリーが「－」の種（ドウクツベンケイガニ）は category_code・category_ja を空にする。
指定日の列は PDF に無いので作らない。

赤リスト該当には含めない（評価の台帳では kind=designated）。
出力: data/processed/kagoshima_ordinance_species.csv
"""
import sys, pathlib, re, csv, collections
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from c29_kagoshima_redlist_2014 import (
    COLS, LIC, CATEGORY_CODE, SRC, norm_category, parse_scientific, clean_latin, load_moe_names, make_row,
    assert_list_matches_registry)

SID = "kagoshima_ordinance_species"
PAGE = "https://www.pref.kagoshima.jp/ad04/kurashi-kankyo/kankyo/yasei/zyorei/03007006.html"
LINK_LABEL = "鹿児島県指定希少野生動植物一覧表"
EDITION = "鹿児島県指定希少野生動植物（令和8年9月現在 59種）"
LIST_YEAR = 2026
EXPECTED = {"animals": 20, "plants": 39}


def find_pdf_url(html_text):
    """ページの <a> のうち、ラベルが「指定希少野生動植物一覧表」の PDF のリンク。"""
    import html as _h
    from urllib.parse import urljoin
    for m in re.finditer(r'<a[^>]+href="([^"]+\.pdf)"[^>]*>(.*?)</a>', html_text, re.S | re.I):
        label = _h.unescape(re.sub(r"<[^>]+>", "", m.group(2)))
        if LINK_LABEL in label:
            return urljoin(PAGE, m.group(1))
    raise RuntimeError("一覧表 PDF のリンクが見つからない")


def row_from_cells(cells, rank_required):
    """表の 1 行 [分類, 和名, 学名, 科名, 県カテゴリー] → dict。ヘッダ行は None。
    rank_required は c29 と同じ規則（植物 True・動物 False。SRC[kind]["rank_required"]）。"""
    cells = [re.sub(r"\s+", " ", (c or "")).strip() for c in cells]
    if len(cells) < 5 or cells[0] == "分類":
        return None
    group = cells[0].replace(" ", "")
    cat = norm_category(cells[4])
    if cat in ("－", "-", "―", ""):
        cat = ""
    assert cat == "" or cat in CATEGORY_CODE, f"想定外のカテゴリー {cells[4]!r}"
    latin = cells[2]
    return {"group": group, "verna": cells[1], "latin": latin, "family": cells[3], "cat": cat,
            "sci": parse_scientific(latin, rank_required=rank_required)}


def main():
    import pdfplumber
    assert_list_matches_registry("kgord", LIST_YEAR)
    from common import get, download, register, PROC, RAW
    page = get(PAGE)
    page.encoding = page.apparent_encoding
    url = find_pdf_url(page.text)
    p = download(url, RAW / "kagoshima_redlist_2014" / "ordinance.pdf")
    rows, kinds = [], collections.Counter()
    with pdfplumber.open(str(p)) as pdf:
        text = "\n".join((pg.extract_text() or "") for pg in pdf.pages)
        tables = [t for pg in pdf.pages for t in pg.extract_tables()]
    stated = {"animals": int(re.search(r"■動物（(\d+)種）", text).group(1)),
              "plants": int(re.search(r"■植物（(\d+)種）", text).group(1)),
              "total": int(re.search(r"(\d+)種）\n■動物", text).group(1))}
    for kind, t in zip(("animals", "plants"), tables):
        n = 0
        for cells in t:
            r = row_from_cells(cells, SRC[kind]["rank_required"])
            if r:
                rows.append(r); n += 1
        kinds[kind] = n
    assert dict(kinds) == {"animals": stated["animals"], "plants": stated["plants"]} == EXPECTED, (kinds, stated)
    assert len(rows) == stated["total"] == 59, (len(rows), stated)
    moe = load_moe_names(PROC / "moe_redlist.csv")
    out = [make_row(group=r["group"], family=r["family"], verna=r["verna"], sci=r["sci"],
                    raw=clean_latin(r["latin"]), cat=r["cat"], ref=url, year=LIST_YEAR, sid=SID, moe=moe)
           for r in rows]
    with open(PROC / "kagoshima_ordinance_species.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader(); w.writerows(out)
    register(SID, EDITION, "鹿児島県 環境林務部 自然保護課", PAGE, "希少種・保全ランク", "HTMLからリンク抽出→PDF表（pdfplumber）",
             "PDF", LIC, 0, len(out),
             "県条例の指定希少野生動植物。動物20・植物39。赤リスト該当には含めない（designated）。指定日の列は無い。")
    print(f"  [rows] {len(out)}（動物 {kinds['animals']}／植物 {kinds['plants']}）")


if __name__ == "__main__":
    main()
