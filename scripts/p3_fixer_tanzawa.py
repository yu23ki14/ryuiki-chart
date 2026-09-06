#!/usr/bin/env python3
"""P3 Fixer — pdfplumber が失敗した表を、ページ画像を目視確認した人間(LLM)が
手作業で再構成する。対象は最優先PDFのうち、縦書きラベルの混入で
pdfplumber の grid 抽出が構造的に破綻した「個体数調整実績の概要」表:
  - tanzawa_shika_r6  page4 table p4_t1  (表I-1-1 令和6年度実績の概要)
  - tanzawa_shika_r4  page3 table p3_t1  (表I-1-1 令和4年度実績の概要)

このスクリプトは、対象テーブルの既存セル(pdfplumber由来, 構造崩壊)を削除し、
ページ画像の目視読み取りに基づく正しい row_key/col_key 階層で置き換える。
value_raw は必ず、pdfplumber で再抽出した生テキストに対する literal 検索で
検証してから採用する(見つからなければ null化: 推測しない)。
"""
import sys, json, sqlite3
sys.path.insert(0, "scripts")
import pdfplumber
from common import DB, ROOT, now, to_fiscal_year, to_number
from p1_maker import literal_search, make_source_text

EXTRACTOR = "human-verified-llm@1"
VERIFIED_BY = "llm:claude-sonnet-5-P3fixer"


def build_r6():
    doc_id = "tanzawa_shika_r6"
    page_no = 4
    table_id = "p4_t1"
    cols = [
        ("R6実績|オス", 2024, "R6", "頭", False),
        ("R6実績|メス", 2024, "R6", "頭", False),
        ("R6実績|不明", 2024, "R6", "頭", False),
        ("R6実績|計A", 2024, "R6", "頭", True),
        ("R6計画B", 2024, "R6", "頭", False),
        ("計画比率A/B(％)", None, None, "％", False),
        ("R5実績C", 2023, "R5", "頭", False),
        ("R5との比率A/C(％)", None, None, "％", False),
    ]
    # (row_path_list, is_total_row, [values in col order])
    rows = [
        (["管理捕獲", "保護管理区域", "自然植生回復・生息環境整備の基盤づくり（実施主体：県）", "民間事業者等委託"], False,
         ["93", "97", "9", "199", "255", "78%", "191", "104%"]),
        (["管理捕獲", "保護管理区域", "自然植生回復・生息環境整備の基盤づくり（実施主体：県）", "ワイルドライフレンジャー"], False,
         ["171", "261", "4", "436", "600", "73%", "428", "102%"]),
        (["管理捕獲", "保護管理区域", "自然植生回復・生息環境整備の基盤づくり（実施主体：県）", "計 (a)"], True,
         ["264", "358", "13", "635", "855", "74%", "619", "103%"]),
        (["管理捕獲", "保護管理区域", "被害軽減 (b)（実施主体：市町村）"], False,
         ["632", "911", "-", "1,543", "1,990", "78%", "1,450", "106%"]),
        (["管理捕獲", "保護管理区域", "有害捕獲（c）"], False,
         ["6", "10", "-", "16", "-", "-", "26", "62%"]),
        (["管理捕獲", "保護管理区域", "計 (a+b+c)"], True,
         ["902", "1,279", "13", "2,194", "2,845", "77%", "2,095", "105%"]),
        (["管理捕獲", "定着防止区域", "定着防止（実施主体：県）", "民間事業者等委託"], False,
         ["18", "16", "1", "35", "60", "58%", "47", "74%"]),
        (["管理捕獲", "定着防止区域", "定着防止（実施主体：県）", "ワイルドライフレンジャー"], False,
         ["17", "55", "1", "73", "30", "243%", "39", "187%"]),
        (["管理捕獲", "定着防止区域", "定着防止（実施主体：県）", "県森林担当部局"], False,
         ["9", "7", "-", "16", "-", "-", "-", "-"]),
        (["管理捕獲", "定着防止区域", "定着防止（実施主体：県）", "県自然公園担当部局"], False,
         ["13", "18", "-", "31", "-", "-", "-", "-"]),
        (["管理捕獲", "定着防止区域", "定着防止（実施主体：県）", "計 (d)"], True,
         ["57", "96", "2", "155", "90", "172%", "86", "180%"]),
        (["管理捕獲", "定着防止区域", "定着防止 (e)（実施主体：市町村）"], False,
         ["558", "405", "-", "963", "1,425", "68%", "1,030", "93%"]),
        (["管理捕獲", "定着防止区域", "国立公園管理者（f）"], False,
         ["15", "31", "-", "46", "-", "-", "-", "-"]),
        (["管理捕獲", "定着防止区域", "国有林管理者（g）"], False,
         ["5", "5", "-", "10", "-", "-", "-", "-"]),
        (["管理捕獲", "定着防止区域", "有害捕獲（h）"], False,
         ["8", "11", "-", "19", "-", "-", "12", "-"]),
        (["管理捕獲", "定着防止区域", "計 (d+e+f+g+h)"], True,
         ["643", "548", "2", "1,193", "1,515", "79%", "1,128", "106%"]),
        (["管理捕獲", "管理捕獲計 (a+b+c+d+e+f+g+h)"], True,
         ["1,545", "1,827", "15", "3,387", "4,360", "78%", "3,223", "105%"]),
        (["狩猟", "保護管理区域"], False,
         ["264", "282", "-", "546", "652", "84%", "464", "118%"]),
        (["狩猟", "定着防止区域"], False,
         ["87", "50", "-", "137", "96", "143%", "115", "119%"]),
        (["狩猟", "計 (i)"], True,
         ["351", "332", "0", "683", "748", "91%", "579", "118%"]),
        (["合計（a+b+c+d+e+f+g+h+i）"], True,
         ["1,896", "2,159", "15", "4,070", "5,108", "80%", "3,802", "107%"]),
    ]
    return doc_id, page_no, table_id, cols, rows


def build_r4():
    doc_id = "tanzawa_shika_r4"
    page_no = 3
    table_id = "p3_t1"
    cols = [
        ("R4捕獲実績|オス", 2022, "R4", "頭", False),
        ("R4捕獲実績|メス", 2022, "R4", "頭", False),
        ("R4捕獲実績|不明", 2022, "R4", "頭", False),
        ("R4捕獲実績|計A", 2022, "R4", "頭", True),
        ("R4計画B", 2022, "R4", "頭", False),
        ("計画比率A/B(％)", None, None, "％", False),
        ("R3実績C", 2021, "R3", "頭", False),
        ("R3比率A/C（％)", None, None, "％", False),
    ]
    rows = [
        (["管理捕獲", "保護管理区域", "自然植生回復・生息環境整備の基盤づくり（実施主体：県）", "民間事業者等委託"], False,
         ["80", "82", "6", "168", "180", "93%", "155", "108%"]),
        (["管理捕獲", "保護管理区域", "自然植生回復・生息環境整備の基盤づくり（実施主体：県）", "ワイルドライフレンジャー"], False,
         ["164", "217", "17", "398", "300", "133%", "369", "108%"]),
        (["管理捕獲", "保護管理区域", "自然植生回復・生息環境整備の基盤づくり（実施主体：県）", "計 (a)"], True,
         ["244", "299", "23", "566", "480", "118%", "524", "108%"]),
        (["管理捕獲", "保護管理区域", "被害軽減 (b)（実施主体：市町村）"], False,
         ["787", "1,028", "-", "1,815", "1,871", "97%", "1,605", "113%"]),
        (["管理捕獲", "保護管理区域", "有害捕獲（c）"], False,
         ["25", "22", "-", "47", "-", "-", "24", "196%"]),
        (["管理捕獲", "保護管理区域", "計 (a+b+c)"], True,
         ["1,056", "1,349", "23", "2,428", "2,351", "103%", "2,153", "113%"]),
        (["管理捕獲", "定着防止区域", "定着防止（実施主体：県）", "民間事業者等委託"], False,
         ["14", "18", "0", "32", "50", "64%", "28", "114%"]),
        (["管理捕獲", "定着防止区域", "定着防止（実施主体：県）", "ワイルドライフレンジャー"], False,
         ["7", "33", "3", "43", "-", "-", "31", "139%"]),
        (["管理捕獲", "定着防止区域", "定着防止（実施主体：県）", "計 (d)"], True,
         ["21", "51", "3", "75", "50", "-", "59", "127%"]),
        (["管理捕獲", "定着防止区域", "定着防止 (e)（実施主体：市町村）"], False,
         ["462", "313", "-", "775", "899", "86%", "616", "126%"]),
        (["管理捕獲", "定着防止区域", "有害捕獲（f）"], False,
         ["3", "3", "-", "6", "-", "-", "16", "-"]),
        (["管理捕獲", "定着防止区域", "計 (d+e+f)"], True,
         ["486", "367", "3", "856", "949", "90%", "691", "124%"]),
        (["管理捕獲", "管理捕獲計 (a+b+c+d+e+f)"], True,
         ["1,542", "1,716", "26", "3,284", "3,300", "100%", "2,844", "115%"]),
        (["狩猟", "保護管理区域"], False,
         ["336", "375", "-", "711", "635", "112%", "712", "100%"]),
        (["狩猟", "定着防止区域"], False,
         ["54", "50", "-", "104", "73", "142%", "130", "80%"]),
        (["狩猟", "計 (g)"], True,
         ["390", "425", "-", "815", "708", "115%", "842", "97%"]),
        (["県実施合計 （a保護管理区域＋d定着防止区域）"], True,
         ["265", "350", "26", "641", "530", "121%", "583", "110%"]),
        (["（）内：民間事業者等委託"], True,
         ["(94)", "(100)", "(6)", "(200)", "(230)", "(87%)", "(183)", "(109%)"]),
        (["合計（a+b+c+d+e+f+g）"], True,
         ["1,932", "2,141", "26", "4,099", "4,008", "102%", "3,686", "111%"]),
    ]
    return doc_id, page_no, table_id, cols, rows


def apply(builder):
    doc_id, page_no, table_id, cols, rows = builder()
    con = sqlite3.connect(DB / "cells.sqlite")
    cur = con.cursor()
    doc_sha256, local_path = cur.execute(
        "SELECT doc_sha256, local_path FROM documents WHERE doc_id=?", (doc_id,)
    ).fetchone()

    with pdfplumber.open(str(ROOT / local_path)) as pdf:
        raw_text = pdf.pages[page_no - 1].extract_text() or ""

    # 既存の(pdfplumber由来の)当該テーブルのセルを削除
    deleted = cur.execute(
        "DELETE FROM cells WHERE doc_id=? AND page_no=? AND table_id=?",
        (doc_id, page_no, table_id),
    ).rowcount

    n_inserted = 0
    n_unreadable = 0
    for row_path, row_is_total, values in rows:
        row_key = "|".join(row_path)
        for (col_key, fy, era_raw, unit, col_is_total), value_raw in zip(cols, values):
            is_total = 1 if (row_is_total or col_is_total) else 0
            span = literal_search(raw_text, value_raw)
            rec_value_raw = None
            source_text = None
            unreadable_reason = None
            value = None
            value_type = None
            rec_fy = None
            rec_era = None
            if span is None:
                unreadable_reason = f"cell_text_not_found_in_page_rawtext: {value_raw!r}"
                n_unreadable += 1
            else:
                rec_value_raw = value_raw
                source_text = make_source_text(raw_text, span)
                v, vt = to_number(value_raw)
                value, value_type = v, vt
                if value_type in ("int", "float"):
                    rec_fy, rec_era = fy, era_raw
            cur.execute(
                """INSERT INTO cells
                (doc_id, doc_sha256, page_no, table_id, row_key, col_key,
                 value_raw, value, value_type, unit, fiscal_year, era_raw,
                 source_text, source_bbox, notes_ref, is_total, merged,
                 unreadable_reason, confidence, extractor, verified_by, extracted_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (doc_id, doc_sha256, page_no, table_id, row_key, col_key,
                 rec_value_raw, value, value_type, unit, rec_fy, rec_era,
                 source_text, None, None, is_total, 0,
                 unreadable_reason, 0.95, EXTRACTOR, VERIFIED_BY, now()),
            )
            n_inserted += 1
    con.commit()
    con.close()
    print(f"[{doc_id}] p{page_no} {table_id}: deleted {deleted} pdfplumber cells, "
          f"inserted {n_inserted} human-verified cells (unreadable={n_unreadable})")


if __name__ == "__main__":
    apply(build_r6)
    apply(build_r4)
