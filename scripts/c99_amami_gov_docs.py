#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""奄美の行政文書（計画・戦略・評価シート）を cells.sqlite の documents / notes に載せる（AMAMI_STEP2D §0〜§3）。

- 表は作らない（cells は 0 件）。載せるのは題名・発行者・URL・ページ数・sha256・ライセンスと、事実だけの注記。
- PDF は data/raw/amami_doc/ に保存する（gitignore 済み。再配布しない）。取得は1件ごとに間隔を空ける（BODIK は5秒以上）。
  落とした PDF が壊れていたら（先頭が %PDF でない・開けない）、ファイルを消して止める。
- 書き込みは doc_id 単位（doccells.write_doc）。ほかの doc_id には触れない。documents.fetched_at は PDF の取得日時（mtime）。
- ライセンス表記の無い3件（地域戦略・エコツーリズム推進全体構想・持続的観光マスタープラン）は
  メタデータだけで、本文は転載しない（redistributable=0。license が NO_LICENSE なら自動）。
- fiscal_year は**4月始まりの年度**で、策定・改訂・登録の日付から換算した版の年度（暦年ではない）。
  doc_id の年は文書の通称（作成年・計画期間・登録年など）なので、fiscal_year と食い違うことがある。
  根拠の日付は DOCS の各行のコメントに書いた。
- notes の page は、PDF のそのページにある事実なら実ページ、PDF の外の事実（案内ページ・登録日・ライセンス表記が無いこと）は
  NULL にして、取得元の URL を本文に書く。kind は、調査・対象範囲の注記だけ survey_scope、ほかは footnote。
- 使い方: python3 scripts/c99_amami_gov_docs.py [--cells PATH] [--no-register]
  --cells で書き込み先の cells.sqlite を差し替えられる（試すときはコピーに向ける。このときは source_registry に登録しない）。
"""
import argparse
import datetime
import pathlib
import sqlite3
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import doccells as dc  # noqa: E402

RAW_SUBDIR = "amami_doc"
SLEEP_S = 3.0
SLEEP_BODIK_S = 6.0
SRC_BODIK = "bodik_kagoshima_ryuiki_chisui_amami"

PDL = dc.LICENSE_MOE_PDL
PDL_MLIT = "公共データ利用規約（第1.0版）PDL1.0（国土交通省ホームページの利用について）: https://www.mlit.go.jp/link.html"
CC_BY = "CC BY 4.0"
NO_LICENSE = "ライセンス表記なし（題名・URL・ページ数・sha256 のみ掲載。本文は転載しない）"

KYUSHU = "https://kyushu.env.go.jp/okinawa/amami-okinawa"
PUB_MOE = "環境省 九州地方環境事務所 沖縄奄美自然環境事務所"
PUB_MOE_PLAN = "環境省 九州地方環境事務所 ほか（奄美大島世界自然遺産地域連絡会議）"
PUB_ECO = "奄美群島エコツーリズム推進協議会"
PUB_ECO_PREF = "奄美群島エコツーリズム推進協議会・鹿児島県"

# 注記: (kind, page, 本文, 理由)。page が None のものは PDF の外の事実で、本文に取得元の URL を書く。
SC, FN = "survey_scope", "footnote"
YAMATO = "https://www.vill.yamato.lg.jp/kikaku/kurashi/kankyo/shizenkankyo/shizenhogo/jore/documents/00_full.pdf"
BODIK_PKG = "https://data.bodik.jp/dataset/460001_1_01_ryuuikichisuipurojekuto"

# (doc_id, source_id, 題名, 発行者, URL, 保存名, fiscal_year, ライセンス, 注記の列)
# fiscal_year の根拠（4月始まりの年度）を各行のコメントに書く。
DOCS = [
    # 「2025 年●月●日改定」の改定案（日付は空欄）。2025年と読み、年度は 2025
    ("amami_wh_comprehensive_plan_2025draft", "moe_amami_wh_plans_amami",
     "世界自然遺産 奄美大島、徳之島、沖縄島北部及び西表島 包括的管理計画（改定案）", PUB_MOE_PLAN,
     f"{KYUSHU}/world-natural-heritage/plan/pdf/d-2-j.pdf", "d-2-j.pdf", 2025, PDL,
     [(FN, 1, "表紙は「2025年●月●日改定」で、改定案。改定日は空欄のまま（策定版ではない）。", "改定案であること")]),
    # 作成年は 2016 年（月は不明のまま。通称どおり年度 2016 とする）
    ("mlit_amami_action_plan_2016", "mlit_amami_action_plan_amami",
     "奄美大島 行動計画", "国土交通省",
     "https://www.mlit.go.jp/common/001294716.pdf", "001294716.pdf", 2016, PDL_MLIT, []),
    # 期間は 2021-04-01〜2026-03-31（令和3年度〜令和7年度）。年度は期間の開始 2021（doc_id r3_r7 は和暦の年度）
    ("moe_amami_mongoose_plan_r3_r7", "moe_amami_wh_plans_amami",
     "根絶確認及び防除完了に向けた奄美大島におけるマングース防除実施計画", PUB_MOE,
     f"{KYUSHU}/plans/alien/pdf/z-1-j.pdf", "z-1-j.pdf", 2021, PDL,
     [(SC, 1, "計画期間は2021年4月1日から2026年3月31日まで（5年間）。", "計画期間")]),
    # 2020年3月改訂 → 年度 2019（doc_id の 2015_2024 は計画期間 2015〜2024年度）
    ("amami_biodiversity_strategy_2015_2024", "amami_biodiversity_strategy_amami",
     "奄美大島生物多様性地域戦略（2020年3月改訂）", "奄美大島自然保護協議会",
     YAMATO, "00_full.pdf", 2019, NO_LICENSE,
     [(FN, 2, "2015年3月策定、2020年3月改訂・発行の版。", "版"),
      (SC, 3, "計画期間は2015年度から2024年度までの10年間。", "計画期間")]),
    # BODIK 登録 2023-03 → 年度 2022（doc_id の 2022）
    ("bodik_460001_amami_ryuiki_chisui_2022", "bodik_kagoshima_ryuiki_chisui_amami",
     "奄美大島地域流域治水プロジェクト", "鹿児島県",
     "https://data.bodik.jp/dataset/767684a7-e3e3-4e1a-bf9c-b6c728eb9f68/resource/"
     "cb54d179-a3d6-44ce-b862-470193dd771f/download/7_1_amamiooshimatiiki.pdf",
     "7_1_amamiooshimatiiki.pdf", 2022, CC_BY,
     [(SC, 1, "鹿児島県流域治水プロジェクトのうち、奄美大島地域だけの文書。", "対象地域"),
      (FN, None, f"BODIK への登録（リソース作成）は2023年3月13日（{BODIK_PKG} の CKAN package_show）。", "登録日")]),
    # 計画期間 2018年度〜2027年度 → 年度 2018
    ("moe_amami_noneko_plan_2018_2027", "moe_amami_wh_plans_amami",
     "奄美大島における生態系保全のためのノネコ管理計画", PUB_MOE_PLAN,
     "https://kyushu.env.go.jp/naha/0328amami.pdf", "0328amami.pdf", 2018, PDL,
     [(SC, 1, "表紙の計画期間は2018年度から2027年度。", "計画期間"),
      (FN, None, "環境省の案内ページ（https://www.env.go.jp/nature/kisho/noneko.html）は同じ計画を「2018年～2028年」と書いており、表紙と食い違う。",
       "期間の表記の食い違い")]),
    # 「2023年度改訂」 → 年度 2023
    ("moe_amami_noneko_goal_2023rev", "moe_amami_wh_plans_amami",
     "奄美大島ノネコ管理計画 最終目標達成に向けた取組（2023年度改訂）", PUB_MOE,
     "https://kyushu.env.go.jp/okinawa/content/000165719.pdf", "000165719.pdf", 2023, PDL,
     [(FN, 1, "題名は「最終目標達成に向けた取組（2023年度改訂）」で、改訂版。", "改訂版であること")]),
    # 2017年2月 → 年度 2016
    ("amami_ecotourism_zentai_2017", "amami_tourism_plans_amami",
     "奄美群島エコツーリズム推進全体構想", PUB_ECO,
     f"{KYUSHU}/plans/ecotourism/pdf/z-4-j.pdf", "eco_z-4-j.pdf", 2016, NO_LICENSE, []),
    # 2016年3月 → 年度 2015
    ("amami_sustainable_tourism_mp_2016", "amami_tourism_plans_amami",
     "奄美大島における持続的観光マスタープラン", "鹿児島県",
     f"{KYUSHU}/plans/ecotourism/pdf/z-2-j.pdf", "eco_z-2-j.pdf", 2015, NO_LICENSE, []),
]

# モニタリング評価シート: (番号, 年度, 和暦の年度)。年度は評価対象の年度（4月始まり）で、doc_id の rN は令和N年度（元年=1）
MONITORING_EVAL = ((1, 2019, "令和元"), (2, 2020, "令和2"), (3, 2021, "令和3"), (4, 2022, "令和4"), (5, 2023, "令和5"))
for _n, _fy, _era in MONITORING_EVAL:
    DOCS.append((
        f"moe_wh_monitoring_eval_r{_n}", "moe_amami_wh_plans_amami",
        f"奄美大島、徳之島、沖縄島北部及び西表島 世界自然遺産 モニタリング評価シート（{_era}年度）", PUB_MOE,
        f"{KYUSHU}/plans/monitoring/pdf/a-{_n}-j.pdf", f"mon_a-{_n}-j.pdf", _fy, PDL,
        [(SC, 1, f"{_era}（{_fy}）年度のモニタリングの評価結果一覧。", "対象年度")]))

# 出典: source_id -> (名前, 発行者, URL)。ライセンスと redistributable は文書の license から導く。
SOURCES = {
    "moe_amami_wh_plans_amami": ("環境省 奄美の世界自然遺産関連の計画・評価シート（包括的管理計画・マングース・ノネコ・モニタリング評価）",
                                 PUB_MOE, f"{KYUSHU}/plans/index.html"),
    "mlit_amami_action_plan_amami": ("国土交通省 奄美大島 行動計画（2016年）", "国土交通省",
                                     "https://www.mlit.go.jp/common/001294716.pdf"),
    "amami_biodiversity_strategy_amami": ("奄美大島生物多様性地域戦略（2020年3月改訂、計画期間2015〜2024年度）",
                                          "奄美大島自然保護協議会", YAMATO),
    SRC_BODIK: ("鹿児島県 奄美大島地域流域治水プロジェクト（BODIK）", "鹿児島県", BODIK_PKG),
    "amami_tourism_plans_amami": ("奄美群島エコツーリズム推進全体構想・奄美大島持続的観光マスタープラン", PUB_ECO_PREF,
                                  f"{KYUSHU}/plans/ecotourism/index.html"),
}


def doc_notes(doc):
    """文書の注記の列(dict)。ライセンス表記なしの文書には、その旨の注記を license から自動で足す。"""
    doc_id, _sid, _t, _p, url, _f, _fy, lic, notes = doc
    out = [{"kind": k, "page": pg, "text": tx, "reason": rs, "table_ids": [], "blocks_timeseries": 0}
           for k, pg, tx, rs in notes]
    if lic == NO_LICENSE:
        out.append({"kind": FN, "page": None, "table_ids": [], "blocks_timeseries": 0,
                    "text": f"この文書（{url}）にはライセンスの表記が見当たらないため、題名・URL・ページ数・sha256 だけを載せ、本文は転載しない。",
                    "reason": "ライセンス表記なし"})
    return out


def source_license(source_id):
    """出典のライセンス原文（その出典の文書のライセンスは1種類）と redistributable。"""
    lics = {d[7] for d in DOCS if d[1] == source_id}
    assert len(lics) == 1, (source_id, lics)
    lic = lics.pop()
    return lic, int(lic != NO_LICENSE)


def fetch_all(raw_dir):
    """PDF を取得して {doc_id: (path, sha256, n_pages, fetched_at)} を返す。既にあれば取得しない。壊れた PDF は消して止める。"""
    out = {}
    for d in DOCS:
        doc_id, sid, url, name = d[0], d[1], d[4], d[5]
        path = raw_dir / name
        fresh = not path.exists()
        _, sha = dc.fetch_pdf(url, path)
        try:
            n_pages = dc.pdf_page_count(path)
        except ValueError:
            path.unlink()
            raise
        fetched_at = datetime.datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")
        out[doc_id] = (path, sha, n_pages, fetched_at)
        print(f"  {doc_id}: {n_pages}p {path.stat().st_size} bytes sha={sha[:12]}")
        if fresh:
            time.sleep(SLEEP_BODIK_S if sid == SRC_BODIK else SLEEP_S)
    return out


def document_row(d, sha, n_pages, fetched_at):
    return dict(title=d[2], publisher=d[3], url=d[4], local_path=f"{RAW_SUBDIR}/{d[5]}", doc_sha256=sha,
                n_pages=n_pages, fiscal_year=d[6], license=d[7], fetched_at=fetched_at)


def write_all(con, fetched):
    for d in DOCS:
        _, sha, n_pages, fetched_at = fetched[d[0]]
        dc.write_doc(con, d[0], document_row(d, sha, n_pages, fetched_at), [], doc_notes(d))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cells", help="書き込み先の cells.sqlite（既定は data/db/cells.sqlite）。指定時は source_registry に登録しない")
    ap.add_argument("--no-register", action="store_true", help="source_registry に登録しない")
    a = ap.parse_args()
    import common
    fetched = fetch_all(common.RAW / RAW_SUBDIR)
    con = sqlite3.connect(a.cells, timeout=30) if a.cells else common.cellsdb()
    try:
        write_all(con, fetched)
    finally:
        con.close()
    if not (a.no_register or a.cells):
        for sid, (name, pub, url) in SOURCES.items():
            lic, redis = source_license(sid)
            ids = [d[0] for d in DOCS if d[1] == sid]
            common.register(
                source_id=sid, name=name, publisher=pub, url=url, category="行政計画・文書",
                access_method="PDF 個別ダウンロード（documents / notes のみ。cells なし）", fmt="PDF",
                license_=lic, redistributable=redis, record_count=len(ids),
                notes=("doc_id=" + "・".join(ids) + "。文書のまま載せ、表は取り出していない。"
                       + ("" if redis else "ライセンス表記が無いため題名・URL・ページ数・sha256 のみ（本文は転載しない）。")))
    print(f"done. documents={len(DOCS)} notes={sum(len(doc_notes(d)) for d in DOCS)}")


if __name__ == "__main__":
    main()
