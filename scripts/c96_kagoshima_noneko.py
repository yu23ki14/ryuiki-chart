#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""奄美大島のノネコ捕獲状況（環境省 奄美野生生物保護センター、2023年3月末現在）→ cells.sqlite（AMAMI_STEP2C §3b）。

PDF（wildcat230417.pdf、2ページ）の1ページ目に、月次の表（2022年度）と年度別の表
（2018年度〔7〜3月〕・2019〜2022年度・合計）がある。行は 捕獲頭数・うち譲渡・うち安楽死・その他。
- 月次（p1_t1）は fiscal_year=NULL（系列にしない）。年度別（p1_t2）の年度の列は fiscal_year=年度。
- 「合計」の列は is_total=1。
- 検算: 行の和＝合計、捕獲＝譲渡＋安楽死＋その他、月次の合計＝年度別の2022年度。
  原本の食い違い（捕獲が内訳の和より2頭多い）は EXPECTED_SPLIT_EXCEPTIONS に宣言した列だけ許す。
環境省の資料（政府標準利用規約 第2.0版、PDL1.0 互換）。PDF は data/raw に置く。
"""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import doccells as dc  # noqa: E402

DOC_ID = "kagoshima_noneko_r4"
SOURCE_ID = "kagoshima_noneko_amami"
PAGE_URL = "https://kyushu.env.go.jp/okinawa/awcc/Wild-dog-Wild-cat.html"
PDF_URL = "https://kyushu.env.go.jp/okinawa/awcc/pdf/wildcat230417.pdf"
PDF_FILE = "kagoshima_doc/wildcat230417.pdf"
PUBLISHER = "環境省 九州地方環境事務所 沖縄奄美自然環境事務所 奄美野生生物保護センター"
LICENSE = "政府標準利用規約（第2.0版）・公共データ利用規約（PDL1.0）互換。出典を明記"
UNIT = "頭"
EXTRACTOR = "pdfplumber"
VERIFIED_BY = "auto:arith"
ROW_NAMES = {"捕獲頭数（合計）": "捕獲頭数", "うち譲渡頭数（合計）": "うち譲渡頭数",
             "うち安楽死頭数（合計）": "うち安楽死頭数", "その他（合計）": "その他"}

# 宣言する例外（原本の食い違い）: 列 → (捕獲頭数, 譲渡＋安楽死＋その他)
EXPECTED_SPLIT_EXCEPTIONS = {
    "p1_t1": {"3月": (13, 11), "合計": (101, 99)},
    "p1_t2": {"2022年度": (101, 99), "合計": (420, 418)},
}


def _clean(c):
    return "".join((c or "").split())


def parse_table(rows):
    """表 → {"cols": [...], "rows": {行名: [文字列...]}}（先頭の見出し行・空セルを整える）。"""
    rows = [r for r in rows if any((c or "").strip() for c in r)]
    cols = [_clean(c) for c in rows[0][1:]]
    body = {}
    for r in rows[1:]:
        name = ROW_NAMES[_clean(r[0])]
        vals = [(c or "").strip() for c in r[1:]]
        assert len(vals) == len(cols)
        body[name] = vals
    assert list(body) == list(ROW_NAMES.values()), list(body)
    return {"cols": cols, "rows": body}


def _n(s):
    v, _ = dc.parse_count(s)
    return v


def verify(monthly, annual):
    """検算。返り値は宣言どおりの食い違い（表ごと）。"""
    out = {}
    for tid, t in (("p1_t1", monthly), ("p1_t2", annual)):
        cols = t["cols"]
        assert cols[-1] == "合計"
        # 行の和＝合計
        row_sums = {name: (_n(v[-1]), sum(_n(x) or 0 for x in v[:-1])) for name, v in t["rows"].items()}
        dc.check_identity(f"{tid} 行の和＝合計", row_sums)
        # 捕獲＝譲渡＋安楽死＋その他
        split = {}
        for i, c in enumerate(cols):
            parts = sum(_n(t["rows"][k][i]) or 0 for k in ("うち譲渡頭数", "うち安楽死頭数", "その他"))
            split[c] = (_n(t["rows"]["捕獲頭数"][i]), parts)
        out[tid] = dc.check_identity(f"{tid} 捕獲＝内訳の和", split, EXPECTED_SPLIT_EXCEPTIONS[tid])
    # 月次の合計＝年度別の2022年度
    j = annual["cols"].index("2022年度")
    link = {name: (_n(monthly["rows"][name][-1]), _n(annual["rows"][name][j])) for name in ROW_NAMES.values()}
    dc.check_identity("月次の合計＝年度別の2022年度", link)
    return out


def build_cells(monthly, annual, sha, page_no=1):
    out = []

    def add(tid, name, col, raw, fy, is_total, era):
        v = _n(raw)
        out.append({"doc_sha256": sha, "page_no": page_no, "table_id": tid, "row_key": name, "col_key": col,
                    "value_raw": raw, "value": None if v is None else str(v),
                    "value_type": "int" if v is not None else "string", "unit": UNIT,
                    "fiscal_year": fy, "era_raw": era, "is_total": int(is_total), "confidence": 1.0,
                    "extractor": EXTRACTOR, "verified_by": VERIFIED_BY})

    for name, vals in monthly["rows"].items():
        for col, raw in zip(monthly["cols"], vals):
            add("p1_t1", name, col, raw, None, col == "合計", f"2022年度 {col}")
    for name, vals in annual["rows"].items():
        for col, raw in zip(annual["cols"], vals):
            tot = col == "合計"
            add("p1_t2", name, col, raw, None if tot else dc.era_to_year(col), tot, col)
    return out


def build_notes():
    return [
        {"kind": "survey_scope", "page": 1, "table_ids": ["p1_t1", "p1_t2"], "blocks_timeseries": 0,
         "text": "希少種が多い森林域において捕獲した頭数。作業地域の詳細は希少種保全の観点から非公表。"
                 "このほか飼い猫とみられるネコが20頭（2018年度1頭、2019年度3頭、2020年度3頭、2021年度5頭、2022年度8頭）"
                 "捕獲されており、9頭は飼い主に返還済み、11頭は公示後保健所に引き渡している（表には含まれない）。",
         "reason": "森林域のノネコ捕獲に限った数で、飼い猫とみられる個体は別"},
        {"kind": "comparability", "page": 1, "table_ids": ["p1_t2"], "blocks_timeseries": 1,
         "text": "2018年度は捕獲を始めた7月から3月までの9か月分で、ほかの年度（12か月）と期間が違う。",
         "reason": "2018年度は9か月分のため、年度間の単純比較はできない"},
        {"kind": "footnote", "page": 1, "table_ids": ["p1_t1", "p1_t2"], "blocks_timeseries": 0,
         "text": "「その他」の内訳は収容中の死亡2頭（2019年度）。",
         "reason": "原本の脚注"},
        {"kind": "footnote", "page": 1, "table_ids": ["p1_t1", "p1_t2"], "blocks_timeseries": 0,
         "text": "2022年度（月次表の3月と合計、年度別表の2022年度と合計）では、捕獲頭数が「譲渡＋安楽死＋その他」より2頭多い"
                 "（3月: 13頭に対し11頭、2022年度: 101頭に対し99頭、年度別の合計: 420頭に対し418頭）。"
                 "原本の印字のまま入れた。",
         "reason": "捕獲と内訳の和が一致しない原本の食い違い（宣言した例外）"},
    ]


def read_tables(pdf_path):
    import pdfplumber
    with pdfplumber.open(str(pdf_path)) as pdf:
        n_pages = len(pdf.pages)
        tables = pdf.pages[0].extract_tables()
    return n_pages, parse_table(tables[0]), parse_table(tables[1])


def main():
    from common import RAW, sha256, cellsdb, register, download
    pdf = RAW / PDF_FILE
    if not pdf.exists():
        download(PDF_URL, pdf)
    sha = sha256(pdf)
    n_pages, monthly, annual = read_tables(pdf)
    exc = verify(monthly, annual)
    cells = build_cells(monthly, annual, sha)
    log = [{"verdict": "pass", "page_no": 1, "table_id": tid, "role": "checker",
            "failures": {"declared_split_exceptions": {k: list(v) for k, v in e.items()}},
            "note": "行の和＝合計・月次合計＝2022年度（全列一致）・捕獲＝内訳の和（宣言した例外を除き一致）"}
           for tid, e in exc.items()]
    con = cellsdb()
    document = dict(title="奄美大島のノネコ捕獲状況（2023年3月末現在）", publisher=PUBLISHER, url=PDF_URL,
                    local_path=PDF_FILE, doc_sha256=sha, n_pages=n_pages, fiscal_year=2022, license=LICENSE)
    n = dc.write_doc(con, DOC_ID, document, cells, build_notes(), log)
    con.close()
    register(SOURCE_ID, "奄美大島のノネコ捕獲状況（2018〜2022年度、2023年3月末現在）", PUBLISHER, PAGE_URL,
             "生態系モニタリング", "PDF（pdfplumber）→ cells.sqlite", "PDF", LICENSE, 1, n,
             f"doc_id={DOC_ID}。月次（2022年度）と年度別（2018〜2022年度）。検算済み（捕獲と内訳の2頭差は注記）。")
    print(f"done. cells={n}")


if __name__ == "__main__":
    main()
