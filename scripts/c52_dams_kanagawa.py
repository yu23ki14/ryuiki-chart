"""相模川水系・酒匂川水系 主要ダム諸元 -> data/processed/dams_kanagawa.csv
出典:
- 城山ダム: 神奈川県公式ページが404のため Wayback Machine 保存版(2026-02-14取得, 更新日2025-07-25)を使用
- 相模ダム・三保ダム: 神奈川県公式ページ(諸元表)
- 宮ヶ瀬ダム: 国交省京浜(相模川水系広域ダム管理事務所)公式ページ(Q&A/ランキング表)
  総貯水容量・型式・竣工年は「日本のダム・総貯水容量順ランキング」(出典:日本ダム協会「ダム便覧2022」)より。
  竣工年(2000年, ダム便覧)と「本格運用開始」(平成13年=2001年, 宮ヶ瀬ダムQ&A)は別概念であり、
  単純に同一視できない点に注意(comparability note)。
lat/lon: 各ダムの日本語Wikipediaのgeohack座標(度分秒->10進)を使用。行政サイトに座標記載なしのため。
"""
import sys, csv
sys.path.insert(0, "scripts")
from common import register, write_jsonl, PROC

ROWS = [
    {
        "name_ja": "宮ヶ瀬ダム", "river_ja": "中津川(相模川水系)",
        "dam_type_ja": "重力式コンクリートダム",
        "height_m": 156.0, "crest_length_m": 375.0,
        "total_capacity_m3": 193_000_000,
        "purpose_ja": "洪水調節、河川流量の調整、水道用水の貯水、発電",
        "completed_year": 2000,
        "lat": 35.542222, "lon": 139.249333,
        "source_id": "dams_kanagawa",
        "source_ref": (
            "https://www.ktr.mlit.go.jp/sagami/sagami00006.html (総貯水容量・型式・竣工年); "
            "https://www.ktr.mlit.go.jp/sagami/sagami00109.html (堤高・堤頂長・型式・本格運用開始年)"
        ),
        "notes_ja": (
            "「日本のダム・総貯水容量順ランキング」ページ(出典:日本ダム協会「ダム便覧2022」)の竣工年は2000年。"
            "一方、宮ヶ瀬ダムQ&Aページは『平成13年より本格運用を開始』(=2001年)と記載。"
            "竣工年と本格運用開始年は別概念であり単純比較できないため両方を残す。"
        ),
    },
    {
        "name_ja": "城山ダム", "river_ja": "相模川",
        "dam_type_ja": "重力式コンクリートダム",
        "height_m": 75.0, "crest_length_m": 260.0,
        "total_capacity_m3": 62_300_000,
        "purpose_ja": "洪水調節、水道用水、工業用水、発電",
        "completed_year": 1965,
        "lat": 35.585833, "lon": 139.283333,
        "source_id": "dams_kanagawa",
        "source_ref": (
            "https://web.archive.org/web/20260214083401/"
            "https://www.pref.kanagawa.jp/docs/vh6/cnt/f8018/shiroyamadam.html "
            "(現行URLは2026-08-29時点で404。神奈川県公式ページのWayback Machine保存版、"
            "同ページの更新日表記は2025年7月25日)"
        ),
        "notes_ja": "総貯水容量62,300,000m3は「※サーチャージ容量(3,500,000m3)含む」の注記あり(原文まま)。",
    },
    {
        "name_ja": "相模ダム", "river_ja": "相模川",
        "dam_type_ja": "重力式コンクリートダム",
        "height_m": 58.4, "crest_length_m": 196.0,
        "total_capacity_m3": 63_200_000,
        "purpose_ja": "水道用水、工業用水、発電",
        "completed_year": 1947,
        "lat": 35.615278, "lon": 139.195556,
        "source_id": "dams_kanagawa",
        "source_ref": "https://www.pref.kanagawa.jp/docs/vh6/cnt/f8018/sagamidam.html",
        "notes_ja": "",
    },
    {
        "name_ja": "三保ダム", "river_ja": "河内川(酒匂川水系)",
        "dam_type_ja": "ロックフィルダム",
        "height_m": 95.0, "crest_length_m": 587.7,
        "total_capacity_m3": 64_900_000,
        "purpose_ja": "洪水調節、水道用水、発電",
        "completed_year": 1979,
        "lat": 35.410278, "lon": 139.041667,
        "source_id": "dams_kanagawa",
        "source_ref": "https://www.pref.kanagawa.jp/docs/vh6/cnt/f8018/mihodam.html",
        "notes_ja": "",
    },
]


def main():
    fields = ["name_ja", "river_ja", "dam_type_ja", "height_m", "crest_length_m",
              "total_capacity_m3", "purpose_ja", "completed_year", "lat", "lon",
              "source_id", "source_ref", "notes_ja"]
    p = PROC / "dams_kanagawa.csv"
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for row in ROWS:
            w.writerow(row)
    write_jsonl("dams_kanagawa", ROWS)
    print(f"  [write] {p} ({len(ROWS)} rows)")

    register(
        source_id="dams_kanagawa",
        name="神奈川県内主要ダム諸元(宮ヶ瀬・城山・相模・三保)",
        publisher="国土交通省 関東地方整備局 / 神奈川県企業局",
        url="https://www.pref.kanagawa.jp/docs/vh6/cnt/f8018/ ; https://www.ktr.mlit.go.jp/sagami/",
        category="観測地点(ダム諸元)",
        access_method="各ダム公式ページのHTML表(城山ダムのみWayback Machine保存版、現行URLは404)",
        fmt="HTML",
        license_="政府標準利用規約(第2.0版)相当（要確認）",
        redistributable=1,
        record_count=len(ROWS),
        notes=(
            "城山ダム公式ページ https://www.pref.kanagawa.jp/docs/vh6/cnt/f8018/shiroyamadam.html は"
            "2026-08-29時点でHTTP 404(サイト内リンクは現存するがリンク切れ)。Wayback Machine保存版"
            "(2026-02-14クロール、ページ更新日2025-07-25)から諸元を取得。lat/lonは行政サイトに"
            "記載がないため日本語WikipediaのGeohack座標(度分秒)を10進変換して使用した。"
        ),
    )


if __name__ == "__main__":
    main()
