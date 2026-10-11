#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""奄美大島のマングース根絶宣言の報道発表（2024-09-03、2026-08-07 修正版）→ cells.sqlite の documents・notes（cells なし）。

設計: docs/plans/AMAMI_STEP3A.md §4（notes 7・8）・§6 担当2-3。Step 2d（c99）と同じ形。
出典の登録は c100b がまとめて行う（source_id=moe_mongoose_amami。doc_id は 2 つ）。事業費・延べ人年など、
ページにある表以外の数字は notes に広げない。

使い方: python3 scripts/c101_mongoose_declaration.py [--cells PATH] [--dry-run]
"""
import argparse
import datetime
import pathlib
import sqlite3
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import common
import doccells as dc

DOC_ID = "moe_mongoose_eradication_declaration_2024"
URL = "https://kyushu.env.go.jp/okinawa/press_00099.html"
LOCAL = "moe_mongoose/press_00099_declaration.html"
TITLE = "奄美大島からのフイリマングースの根絶宣言（報道発表）"
PUBLISHER = "環境省 沖縄奄美自然環境事務所"
FISCAL_YEAR = 2024
NOTES = [
    dict(kind="survey_scope", page=None, table_ids=[], blocks_timeseries=0, text=(
        "2024年9月3日、奄美大島フイリマングース防除事業検討会が根絶に達したと評価し、環境省が奄美大島からの"
        "根絶を宣言した。評価は2023年度末までの防除作業の確定値による。")),
    dict(kind="footnote", page=None, table_ids=[], blocks_timeseries=0, text=(
        "宣言時の根絶確率は HBM 99.7%・REA 98.9%（報道発表の本文）。2026年8月7日に、環境省が公表ページの図2を"
        "再計算結果（Fukasawa et al., 2026, プレプリント）に差し替えた。本文の数値は修正されておらず、修正後の確率は"
        "図からは数値として読み取れない。"),
        reason="2026年8月の修正"),
]


def build():
    path = common.RAW / LOCAL
    if not path.exists():
        raise SystemExit(f"{path} が無い。先に scripts/c100a_mongoose_fetch.py")
    fetched_at = datetime.datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")
    doc = dict(title=TITLE, publisher=PUBLISHER, url=URL, local_path=LOCAL, doc_sha256=common.sha256(path),
               n_pages=None, fiscal_year=FISCAL_YEAR, license=dc.LICENSE_MOE_PDL, fetched_at=fetched_at)
    return doc, [dict(n, reason=n.get("reason")) for n in NOTES]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cells", help="書き込み先の cells.sqlite（既定は data/db/cells.sqlite）")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    doc, notes = build()
    print(f"{DOC_ID}: sha256={doc['doc_sha256'][:12]} notes={len(notes)}")
    if a.dry_run:
        return
    con = sqlite3.connect(a.cells, timeout=30) if a.cells else common.cellsdb()
    try:
        dc.write_doc(con, DOC_ID, doc, [], notes,
                     log=[dict(verdict="pass", note="c101_mongoose_declaration: documents と notes だけ（cells なし）")])
    finally:
        con.close()


if __name__ == "__main__":
    main()
