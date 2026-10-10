#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""奄美の行政文書（計画・戦略・評価シート）を cells.sqlite の documents / notes に載せる（AMAMI_STEP2D §0〜§3）。

- 表は作らない（cells は 0 件）。載せるのは題名・発行者・URL・ページ数・sha256・ライセンスと、事実だけの注記。
- PDF は data/raw/amami_doc/ に保存する（gitignore 済み。再配布しない）。取得は1件ごとに間隔を空ける（BODIK は5秒以上）。
- 書き込みは doc_id 単位（doccells.write_doc）。ほかの doc_id には触れない。
- ライセンス表記の無い3件（地域戦略・エコツーリズム推進全体構想・持続的観光マスタープラン）は
  メタデータだけで、本文は転載しない（redistributable=0）。
- 使い方: python3 scripts/c99_amami_gov_docs.py [--cells PATH] [--no-register]
  --cells で書き込み先の cells.sqlite を差し替えられる（試すときはコピーに向ける）。
"""
import argparse
import pathlib
import sqlite3
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import doccells as dc  # noqa: E402

RAW_SUBDIR = "amami_doc"

PDL = "公共データ利用規約（第1.0版）PDL1.0（環境省ホームページコンテンツの利用について）: https://www.env.go.jp/mail.html"
PDL_MLIT = "公共データ利用規約（第1.0版）PDL1.0（国土交通省ホームページの利用について）: https://www.mlit.go.jp/link.html"
CC_BY = "CC BY 4.0"
NO_LICENSE = "ライセンス表記なし（題名・URL・ページ数・sha256 のみ掲載。本文は転載しない）"

KYUSHU = "https://kyushu.env.go.jp/okinawa/amami-okinawa"
PUB_MOE = "環境省 九州地方環境事務所 沖縄奄美自然環境事務所"
PUB_MOE_PLAN = "環境省 九州地方環境事務所 ほか（奄美大島世界自然遺産地域連絡会議）"
PUB_MLIT = "国土交通省"
PUB_KAGOSHIMA = "鹿児島県"
PUB_STRATEGY = "奄美大島自然保護協議会"
PUB_ECO = "奄美群島エコツーリズム推進協議会"

SRC_MOE = "moe_amami_wh_plans_amami"
SRC_MLIT = "mlit_amami_action_plan_amami"
SRC_STRATEGY = "amami_biodiversity_strategy_amami"
SRC_BODIK = "bodik_kagoshima_ryuiki_chisui_amami"
SRC_TOURISM = "amami_tourism_plans_amami"


def _doc(doc_id, source_id, title, publisher, url, file, fiscal_year, license_):
    return dict(doc_id=doc_id, source_id=source_id, title=title, publisher=publisher, url=url,
                local_path=f"{RAW_SUBDIR}/{file}", fiscal_year=fiscal_year, license=license_)


DOCS = [
    _doc("amami_wh_comprehensive_plan_2025draft", SRC_MOE,
         "世界自然遺産 奄美大島、徳之島、沖縄島北部及び西表島 包括的管理計画（改定案）", PUB_MOE_PLAN,
         f"{KYUSHU}/world-natural-heritage/plan/pdf/d-2-j.pdf", "d-2-j.pdf", 2025, PDL),
    _doc("mlit_amami_action_plan_2016", SRC_MLIT,
         "奄美大島 行動計画", PUB_MLIT,
         "https://www.mlit.go.jp/common/001294716.pdf", "001294716.pdf", 2016, PDL_MLIT),
    _doc("moe_amami_mongoose_plan_r3_r7", SRC_MOE,
         "根絶確認及び防除完了に向けた奄美大島におけるマングース防除実施計画", PUB_MOE,
         f"{KYUSHU}/plans/alien/pdf/z-1-j.pdf", "z-1-j.pdf", 2021, PDL),
    _doc("amami_biodiversity_strategy_2015_2024", SRC_STRATEGY,
         "奄美大島生物多様性地域戦略（2020年3月改訂）", PUB_STRATEGY,
         "https://www.vill.yamato.lg.jp/kikaku/kurashi/kankyo/shizenkankyo/shizenhogo/jore/documents/00_full.pdf",
         "00_full.pdf", 2019, NO_LICENSE),
    _doc("bodik_460001_amami_ryuiki_chisui_2022", SRC_BODIK,
         "奄美大島地域流域治水プロジェクト", PUB_KAGOSHIMA,
         "https://data.bodik.jp/dataset/767684a7-e3e3-4e1a-bf9c-b6c728eb9f68/resource/"
         "cb54d179-a3d6-44ce-b862-470193dd771f/download/7_1_amamiooshimatiiki.pdf",
         "7_1_amamiooshimatiiki.pdf", 2022, CC_BY),
    _doc("moe_amami_noneko_plan_2018_2027", SRC_MOE,
         "奄美大島における生態系保全のためのノネコ管理計画", PUB_MOE_PLAN,
         "https://kyushu.env.go.jp/naha/0328amami.pdf", "0328amami.pdf", 2018, PDL),
    _doc("moe_amami_noneko_goal_2023rev", SRC_MOE,
         "奄美大島におけるノネコ管理計画 最終目標達成に向けた取組（2023年度改訂）", PUB_MOE,
         "https://kyushu.env.go.jp/okinawa/content/000165719.pdf", "000165719.pdf", 2023, PDL),
    _doc("amami_ecotourism_zentai_2017", SRC_TOURISM,
         "奄美群島エコツーリズム推進全体構想", PUB_ECO,
         f"{KYUSHU}/plans/ecotourism/pdf/z-4-j.pdf", "eco_z-4-j.pdf", 2016, NO_LICENSE),
    _doc("amami_sustainable_tourism_mp_2016", SRC_TOURISM,
         "奄美大島における持続的観光マスタープラン", PUB_KAGOSHIMA,
         f"{KYUSHU}/plans/ecotourism/pdf/z-2-j.pdf", "eco_z-2-j.pdf", 2015, NO_LICENSE),
]
# モニタリング評価シート（令和元〜5年度。年度は西暦に直して fiscal_year に入れる）
for _n, _fy, _label in ((1, 2019, "令和元年度"), (2, 2020, "令和2年度"), (3, 2021, "令和3年度"),
                        (4, 2022, "令和4年度"), (5, 2023, "令和5年度")):
    DOCS.append(_doc(f"moe_wh_monitoring_eval_r{_n}", SRC_MOE,
                     f"奄美大島、徳之島、沖縄島北部及び西表島 世界自然遺産 モニタリング評価シート（{_label}）", PUB_MOE,
                     f"{KYUSHU}/plans/monitoring/pdf/a-{_n}-j.pdf", f"mon_a-{_n}-j.pdf", _fy, PDL))

# 出典（source_registry）。(source_id, 名前, 発行者, URL, ライセンス, redistributable, 備考)
SOURCES = [
    (SRC_MOE, "環境省 奄美の世界自然遺産関連の計画・評価シート（包括的管理計画・マングース・ノネコ・モニタリング評価）", PUB_MOE,
     f"{KYUSHU}/plans/index.html", PDL, 1),
    (SRC_MLIT, "国土交通省 奄美大島 行動計画（2016年）", PUB_MLIT,
     "https://www.mlit.go.jp/common/001294716.pdf", PDL_MLIT, 1),
    (SRC_STRATEGY, "奄美大島生物多様性地域戦略（2020年3月改訂、計画期間2015〜2024年度）", PUB_STRATEGY,
     "https://www.vill.yamato.lg.jp/kikaku/kurashi/kankyo/shizenkankyo/shizenhogo/jore/documents/00_full.pdf",
     NO_LICENSE, 0),
    (SRC_BODIK, "鹿児島県 奄美大島地域流域治水プロジェクト（BODIK）", PUB_KAGOSHIMA,
     "https://data.bodik.jp/dataset/460001_1_01_ryuuikichisuipurojekuto", CC_BY, 1),
    (SRC_TOURISM, "奄美群島エコツーリズム推進全体構想・奄美大島持続的観光マスタープラン", PUB_ECO,
     f"{KYUSHU}/plans/ecotourism/index.html", NO_LICENSE, 0),
]


def _note(text, reason):
    return {"kind": "survey_scope", "page": 1, "table_ids": [], "blocks_timeseries": 0, "text": text, "reason": reason}


# 注記は事実だけ（期間の終了・改定案であること・版の別）。本文の要約や数値の転記はしない。
NOTES = {
    "amami_wh_comprehensive_plan_2025draft": [
        _note("2025年の改定案。改定日は空欄（●月●日）のまま。策定版ではない。", "改定案であること"),
    ],
    "mlit_amami_action_plan_2016": [
        _note("2016年に作成された行動計画。", "作成年"),
    ],
    "moe_amami_mongoose_plan_r3_r7": [
        _note("計画期間は2021年4月から2026年3月まで（期間は終了）。2024年9月に根絶を達成したとされ、後継の計画があるが未確認。",
           "計画期間の終了と後継計画が未確認であること"),
    ],
    "amami_biodiversity_strategy_2015_2024": [
        _note("2020年3月の改訂版。計画期間は2015〜2024年度（期間は終了）。後継版は見つかっていない。",
           "計画期間の終了と後継版が未確認であること"),
        _note("ライセンスの表記が無いため、題名・URL・ページ数・sha256 だけを載せ、本文は転載しない。", "ライセンス表記なし"),
    ],
    "bodik_460001_amami_ryuiki_chisui_2022": [
        _note("BODIK に2023年に登録された資料（4ページ）。", "登録年"),
    ],
    "moe_amami_noneko_plan_2018_2027": [
        _note("表紙の計画期間は2018〜2027年度。環境省の案内ページには2018〜2028年と書かれており、食い違う。",
           "表紙と案内ページで期間の表記が違うこと"),
    ],
    "moe_amami_noneko_goal_2023rev": [
        _note("ノネコ管理計画の最終目標達成に向けた取組を2023年度に改訂した版。", "改訂版であること"),
    ],
    "amami_ecotourism_zentai_2017": [
        _note("2017年2月の構想。ライセンスの表記が無いため、題名・URL・ページ数・sha256 だけを載せ、本文は転載しない。",
           "ライセンス表記なし"),
    ],
    "amami_sustainable_tourism_mp_2016": [
        _note("2016年3月のマスタープラン（奄美大島版。沖縄島北部版は別の文書）。ライセンスの表記が無いため、"
           "題名・URL・ページ数・sha256 だけを載せ、本文は転載しない。", "ライセンス表記なし"),
    ],
}
for _n_, _label in ((1, "令和元年度（2019年度）"), (2, "令和2年度（2020年度）"), (3, "令和3年度（2021年度）"),
                    (4, "令和4年度（2022年度）"), (5, "令和5年度（2023年度）")):
    NOTES[f"moe_wh_monitoring_eval_r{_n_}"] = [
        _note(f"{_label}のモニタリング評価シート。PDF のまま載せており、表としては取り出していない。", "文書の版と扱い")]


def fetch_all(raw_dir, sleep_s=3.0):
    """PDF を取得して {doc_id: (path, sha256, n_pages)} を返す。既にあれば取得しない。BODIK は5秒以上空ける。"""
    import pdfplumber
    out = {}
    for d in DOCS:
        path = raw_dir / pathlib.Path(d["local_path"]).name
        fresh = not path.exists()
        _, sha = dc.fetch_pdf(d["url"], path)
        with pdfplumber.open(str(path)) as pdf:
            n_pages = len(pdf.pages)
        out[d["doc_id"]] = (path, sha, n_pages)
        print(f"  {d['doc_id']}: {n_pages}p {path.stat().st_size} bytes sha={sha[:12]}")
        if fresh:
            time.sleep(6.0 if "bodik" in d["url"] else sleep_s)
    return out


def document_row(d, sha, n_pages):
    return dict(title=d["title"], publisher=d["publisher"], url=d["url"], local_path=d["local_path"],
                doc_sha256=sha, n_pages=n_pages, fiscal_year=d["fiscal_year"], license=d["license"])


def write_all(con, fetched):
    for d in DOCS:
        _, sha, n_pages = fetched[d["doc_id"]]
        dc.write_doc(con, d["doc_id"], document_row(d, sha, n_pages), [], NOTES[d["doc_id"]])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cells", help="書き込み先の cells.sqlite（既定は data/db/cells.sqlite）")
    ap.add_argument("--no-register", action="store_true", help="source_registry に登録しない")
    a = ap.parse_args()
    import common
    fetched = fetch_all(common.RAW / RAW_SUBDIR)
    con = sqlite3.connect(a.cells, timeout=30) if a.cells else common.cellsdb()
    try:
        write_all(con, fetched)
    finally:
        con.close()
    if not a.no_register:
        for sid, name, pub, url, lic, redis in SOURCES:
            n = sum(1 for d in DOCS if d["source_id"] == sid)
            common.register(
                source_id=sid, name=name, publisher=pub, url=url, category="行政計画・文書",
                access_method="PDF 個別ダウンロード（documents / notes のみ。cells なし）", fmt="PDF",
                license_=lic, redistributable=redis, record_count=n,
                notes=("doc_id=" + "・".join(d["doc_id"] for d in DOCS if d["source_id"] == sid)
                       + "。文書のまま載せ、表は取り出していない。"
                       + ("" if redis else "ライセンス表記が無いため題名・URL・ページ数・sha256 のみ（本文は転載しない）。")))
    print(f"done. documents={len(DOCS)} notes={sum(len(v) for v in NOTES.values())}")


if __name__ == "__main__":
    main()
