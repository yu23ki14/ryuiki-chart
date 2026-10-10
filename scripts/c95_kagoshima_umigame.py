#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""鹿児島県 ウミガメ上陸・産卵確認状況（R7年度版）→ cells.sqlite（AMAMI_STEP2C §3a）。

県の PDF（2ページ）。p1 は上陸（H23〜R7 の15年）、p2 は産卵（H22〜R7 の16年）で、
どちらも39市町村の行に「市町村数」と「合計」の行が付く。pdfplumber の罫線で読む。
- 「-」と「－」は value=NULL（原本に意味の説明が無い。0 とは区別する）。
- 「市町村数」「合計」の行は is_total=1。
- 検算: 全列で39行の和＝合計、値が正の行数＝市町村数。原本の誤りは EXPECTED_* に宣言した例外だけ許す
  （H27 の合計が H26 と同じ値の印字になっている。誤りの値は印字のまま入れ、注記に事実を書く）。
事実（数値）だけを抜き出して出典を明記する。PDF は data/raw に置き再配布しない。
"""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import doccells as dc  # noqa: E402

DOC_ID = "kagoshima_umigame_r7"
SOURCE_ID = "kagoshima_umigame_amami"
PAGE_URL = "https://www.pref.kagoshima.jp/ad04/kurashi-kankyo/kankyo/yasei/umigame/umigame.html"
PDF_URL = ("https://www.pref.kagoshima.jp/ad04/kurashi-kankyo/kankyo/yasei/umigame/documents/"
           "2666_20260213091539-1.pdf")
PDF_FILE = "kagoshima_doc/umigame_r7.pdf"
N_MUNICIPALITIES = 39
UNIT = "回"
EXTRACTOR = "pdfplumber"
VERIFIED_BY = "auto:arith"
LICENSE = dc.LICENSE_PREF_KAGOSHIMA

# (page_no, table_id, 行ラベルの「市町村数」行, 見出し)
TABLES = [
    (1, "p1_t1", "上陸市町村数", "上陸確認"),
    (2, "p2_t1", "産卵市町村数", "産卵確認"),
]
# 宣言する例外（原本の誤り）: 列ラベル → (表の合計の印字, 39行の和)
EXPECTED_SUM_EXCEPTIONS = {
    "p1_t1": {"H27": (7179, 3511)},
    "p2_t1": {"H27": (4313, 2151)},
}
EXPECTED_COUNT_EXCEPTIONS = {"p1_t1": {}, "p2_t1": {}}


def parse_table(rows, count_label):
    """pdfplumber の表（行のリスト）→ dict。空行を捨て、見出し・市町村行・市町村数・合計に分ける。"""
    rows = [r for r in rows if any((c or "").strip() for c in r)]
    header = [(c or "").strip() for c in rows[0]]
    assert header[0] == "区分", header
    cols = header[1:]
    munis, count_row, total_row = [], None, None
    for r in rows[1:]:
        label = (r[0] or "").replace(" ", "").strip()
        vals = [(c or "").strip() for c in r[1:]]
        assert len(vals) == len(cols), (label, len(vals), len(cols))
        if label == count_label:
            count_row = vals
        elif label == "合計":
            total_row = vals
        else:
            munis.append((label, vals))
    assert count_row is not None and total_row is not None
    assert len(munis) == N_MUNICIPALITIES, len(munis)
    return {"cols": cols, "years": [dc.era_to_year(c) for c in cols],
            "munis": munis, "count": count_row, "total": total_row}


def verify(table_id, t):
    """検算。宣言した例外と過不足なく一致しなければ止める。返り値は宣言どおりの食い違い。"""
    sums, counts = {}, {}
    for i, col in enumerate(t["cols"]):
        vals = [dc.parse_count(v[i])[0] for _, v in t["munis"]]
        total = dc.parse_count(t["total"][i])[0]
        n = dc.parse_count(t["count"][i])[0]
        sums[col] = (total, sum(v or 0 for v in vals))
        counts[col] = (n, sum(1 for v in vals if v))
    a = dc.check_identity(f"{table_id} 39行の和＝合計", sums, EXPECTED_SUM_EXCEPTIONS[table_id])
    b = dc.check_identity(f"{table_id} 値が正の行数＝市町村数", counts, EXPECTED_COUNT_EXCEPTIONS[table_id])
    return a, b


def build_cells(page_no, table_id, t, count_label, sha):
    out = []

    def add(row_key, i, raw, is_total, unit):
        out.append(dc.count_cell(
            raw, doc_sha256=sha, page_no=page_no, table_id=table_id, row_key=row_key, col_key=t["cols"][i],
            unit=unit, fiscal_year=t["years"][i], era_raw=t["cols"][i], is_total=int(is_total), confidence=1.0,
            extractor=EXTRACTOR, verified_by=VERIFIED_BY))

    for label, vals in t["munis"]:
        for i, raw in enumerate(vals):
            add(label, i, raw, False, UNIT)
    for i, raw in enumerate(t["count"]):
        add(count_label, i, raw, True, "市町村")
    for i, raw in enumerate(t["total"]):
        add("合計", i, raw, True, UNIT)
    return out


def build_notes():
    return [
        {"kind": "survey_scope", "page": 1, "table_ids": ["p1_t1", "p2_t1"], "blocks_timeseries": 0,
         "text": "本表は，環境省による調査結果並びに，各市町村が委嘱したウミガメ保護監視員及びボランティアによる"
                 "監視活動等を通じて把握した確認数を基に集計したものであり，本県における上陸・産卵の総数を表すものではない。"
                 "県内における海岸を有する市町村は39市町村。",
         "reason": "監視活動で把握できた分の集計で総数ではない（原本の脚注）"},
        {"kind": "footnote", "page": 1, "table_ids": ["p1_t1", "p2_t1"], "blocks_timeseries": 0,
         "text": "表中の「-」と「－」は原本に意味の説明が無い（0 とは区別されている）。値は空（NULL）として入れた。",
         "reason": "欠測か未調査かが原本から分からない"},
        {"kind": "footnote", "page": 1, "table_ids": ["p1_t1"], "blocks_timeseries": 0,
         "text": "H27 の合計は 7,179 と印字されているが、39市町村の値の和は 3,511 で、H26 の合計（7,179）と同じ値になっている。"
                 "原本の印字のまま入れた。",
         "reason": "表の合計と各行の和が一致しない原本の誤り（宣言した例外）"},
        {"kind": "footnote", "page": 2, "table_ids": ["p2_t1"], "blocks_timeseries": 0,
         "text": "H27 の合計は 4,313 と印字されているが、39市町村の値の和は 2,151 で、H26 の合計（4,313）と同じ値になっている。"
                 "原本の印字のまま入れた。",
         "reason": "表の合計と各行の和が一致しない原本の誤り（宣言した例外）"},
        {"kind": "definition_change", "page": 1, "table_ids": ["p1_t1", "p2_t1"], "blocks_timeseries": 0,
         "text": "列の見出しは元号（H23〜R7）で、年度か暦年かは原本に明記が無い。fiscal_year には元号を西暦に直した値を入れた。",
         "reason": "年区分が不明"},
    ]


def read_tables(pdf_path):
    n_pages, by_page = dc.pdf_tables(pdf_path, [p for p, *_ in TABLES])
    return n_pages, [(page_no, table_id, count_label, parse_table(by_page[page_no][0], count_label))
                     for page_no, table_id, count_label, _ in TABLES]


def main():
    from common import RAW
    pdf, sha = dc.fetch_pdf(PDF_URL, RAW / PDF_FILE)
    n_pages, tables = read_tables(pdf)
    cells, log = [], []
    for page_no, table_id, count_label, t in tables:
        a, b = verify(table_id, t)
        cells += build_cells(page_no, table_id, t, count_label, sha)
        log.append({"verdict": "pass", "page_no": page_no, "table_id": table_id, "role": "checker",
                    "failures": {"declared_sum_exceptions": {k: list(v) for k, v in a.items()},
                                 "declared_count_exceptions": {k: list(v) for k, v in b.items()}},
                    "note": "39行の和＝合計・正の行数＝市町村数（宣言した例外を除き全列で一致）"})
    document = dict(title="鹿児島県のウミガメ上陸・産卵確認状況（過去15年間、R7年度版）",
                    publisher="鹿児島県 環境林務部 自然保護課", url=PDF_URL, local_path=str(PDF_FILE),
                    doc_sha256=sha, n_pages=n_pages, fiscal_year=2025, license=LICENSE)
    n = dc.commit_doc(DOC_ID, document, cells, build_notes(), log, source=dict(
        source_id=SOURCE_ID, name="鹿児島県 ウミガメ上陸・産卵確認状況（市町村別、R7年度版）",
        publisher="鹿児島県 環境林務部 自然保護課", url=PAGE_URL, category="生態系モニタリング",
        access_method="PDF（pdfplumber）→ cells.sqlite", fmt="PDF", license_=LICENSE, redistributable=0,
        notes=f"doc_id={DOC_ID}。39市町村×上陸15年・産卵16年。検算済み（H27 の合計の原本誤りは注記）。"
              "PDF は data/raw に置き再配布しない。"))
    print(f"done. cells={n}")


if __name__ == "__main__":
    main()
