"""モニタリングサイト1000: 森林・草原(陸生鳥類 SIN04) と 沿岸域(シギ・チドリ SIG02)
を神奈川県分に絞り込んで出力。あわせて陸水域(湖沼底生動物KOS04/淡水魚KOS06/水生植物KOS07/
湿原植生SIT01)とガンカモ類(GAN01)は神奈川県内サイトが存在しないことを確認し記録用に register。
"""
import sys, glob
sys.path.insert(0, "scripts")
import pandas as pd
from common import PROC, RAW, register, write_jsonl

EXT = RAW / "moni1000" / "extracted"


def read_any(path):
    try:
        return pd.read_csv(path, encoding="utf-8-sig")
    except UnicodeDecodeError:
        return pd.read_csv(path, encoding="cp932")


def process_sin04():
    files = sorted(glob.glob(str(EXT / "SIN04/BirdData*.csv")))
    frames = []
    for f in files:
        df = read_any(f)
        kn = df[df["都道府県"].astype(str).str.contains("神奈川", na=False)]
        if len(kn):
            frames.append(kn)
    allkn = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    colmap = {
        "サイトID": "site_id", "サイトタイプ": "site_type_ja", "環境": "habitat_ja",
        "緯度": "lat", "経度": "lon", "都道府県": "prefecture_ja", "市町村": "municipality_ja",
        "サイクル": "cycle_ja", "調査年度・時期": "survey_period_ja", "地点": "point_ja",
        "回": "rep_no", "年": "survey_year", "月": "survey_month", "日": "survey_day",
        "開始時": "start_hour", "開始分": "start_min", "終了時": "end_hour", "終了分": "end_min",
        "天候": "weather_ja", "種名": "species_ja", "亜種名": "subspecies_ja",
        "学名": "scientific_name", "個体数": "count", "確認区分": "id_type_ja",
        "調査方法": "survey_method_ja",
    }
    allkn = allkn.rename(columns=colmap)
    allkn["source_id"] = "moni1000_forest_bird"
    allkn["source_ref"] = "https://www.biodic.go.jp/moni1000/question/question.html (SIN04)"
    csv_path = PROC / "moni1000_forest_bird_kanagawa.csv"
    allkn.to_csv(csv_path, index=False, encoding="utf-8")
    write_jsonl("moni1000_forest_bird_kanagawa", allkn.to_dict(orient="records"))
    print(f"[write] {csv_path} {len(allkn)} rows")
    register(
        source_id="moni1000_forest_bird",
        name="モニタリングサイト1000 森林・草原調査 陸生鳥類調査（神奈川県サイトのみ抽出）",
        publisher="環境省生物多様性センター",
        url="https://www.biodic.go.jp/moni1000/forest.html",
        category="生態系モニタリング(森林・草原)",
        access_method="利用アンケートフォーム経由でzip取得(SIN04)、年度別CSVを都道府県列で神奈川抽出",
        fmt="CSV(UTF-8-sig/Shift_JIS混在)->CSV/JSONL(UTF-8)",
        license_="生物多様性センターウェブサイト利用規約(要事前アンケート回答)",
        redistributable=1,
        record_count=len(allkn),
        notes=("年度別ファイル(2004~2025年、繁殖期B/越冬期W)を都道府県列'神奈川県'で抽出・結合。"
               "サイトID 100246(横浜市),100084(相模原市/緑区),100317(足柄上郡山北町),"
               "100319(秦野市),100316(足柄下郡箱根町),100318(横浜市/磯子区),200035(山北町)。"),
    )


def process_sig02():
    df = read_any(EXT / "SIG02/一斉調査日個体数リスト表(2004-05以降).csv")
    mask = df["Latitude"].between(35.0, 35.75) & df["Longitude"].between(138.9, 139.85)
    cand = df[mask]
    # 東京都(江東区・大田区)側のみのサイトは除外し、神奈川県内(川崎市・海老名市・小田原市)サイトのみ残す
    exclude = {"中央防波堤内・外側埋立地", "東京港野鳥公園", "東京港野鳥公園　前浜干潟"}
    kn = cand[~cand["Japanese Site Name"].isin(exclude)].copy()
    colmap = {
        "Survey Year": "survey_year_raw", "Season": "season_ja", "Site Code": "site_code",
        "Japanese Site Name": "site_name_ja", "Alphabetical Site Name": "site_name_romaji",
        "Latitude": "lat", "Longitude": "lon", "Year": "year", "Month": "month", "Day": "day",
        "Start Time": "start_time", "End Time": "end_time",
        "Japanese Name": "species_ja", "English Name": "species_en",
        "Scientific Name": "scientific_name", "Count": "count",
    }
    kn = kn.rename(columns=colmap)
    kn["source_id"] = "moni1000_coast_shorebird"
    kn["source_ref"] = "https://www.biodic.go.jp/moni1000/question/question.html (SIG02)"
    csv_path = PROC / "moni1000_coast_shorebird_kanagawa.csv"
    kn.to_csv(csv_path, index=False, encoding="utf-8")
    write_jsonl("moni1000_coast_shorebird_kanagawa", kn.to_dict(orient="records"))
    print(f"[write] {csv_path} {len(kn)} rows")
    register(
        source_id="moni1000_coast_shorebird",
        name="モニタリングサイト1000 沿岸域(シギ・チドリ類)調査（神奈川県サイトのみ抽出）",
        publisher="環境省生物多様性センター",
        url="https://www.biodic.go.jp/moni1000/coast.html",
        category="生態系モニタリング(沿岸域)",
        access_method="利用アンケートフォーム経由でzip取得(SIG02)、緯度経度で神奈川圏内を抽出後、東京都側サイトを除外",
        fmt="CSV(Shift_JIS)->CSV/JSONL(UTF-8)",
        license_="生物多様性センターウェブサイト利用規約(要事前アンケート回答)",
        redistributable=1,
        record_count=len(kn),
        notes=("緯度経度が神奈川圏内(北緯35.0-35.75,東経138.9-139.85)の地点のうち、"
               "行政区分が東京都に属する'中央防波堤内・外側埋立地''東京港野鳥公園'(大田区)を除外。"
               "'多摩川下流域(六郷橋～大師橋)'は多摩川両岸(大田区/川崎市)にまたがる調査区間のため、"
               "行政区画の同一視を避け注記付きでそのまま残した(境界域)。"),
    )


def register_empty():
    empties = [
        ("moni1000_lake_benthos", "陸水域(湖沼)底生動物調査(KOS04)",
         "https://www.biodic.go.jp/moni1000/wetlands.html",
         "全国7湖沼(宍道湖・秋田・琵琶湖・池田湖・印旛沼・神西湖・摩周湖等)のいずれも神奈川県内ではない。"),
        ("moni1000_lake_fish", "陸水域(湖沼)淡水魚調査(KOS06)",
         "https://www.biodic.go.jp/moni1000/wetlands.html",
         "ダウンロードフォーム送信時にサーバエラー('エラーが発生しました。管理者にお問い合わせください。')が発生し取得不可。"
         "KOS04(同一湖沼群、底生動物)の結果から神奈川県内サイトは存在しないと推定。"),
        ("moni1000_lake_aquaticplants", "陸水域(湖沼)水生植物調査(KOS07)",
         "https://www.biodic.go.jp/moni1000/wetlands.html",
         "ダウンロードフォーム送信時にサーバエラー('エラーが発生しました。管理者にお問い合わせください。')が発生し取得不可。"
         "KOS04(同一湖沼群、底生動物)の結果から神奈川県内サイトは存在しないと推定。"),
        ("moni1000_wetland_vegetation", "陸水域(湿原)湿原植生調査(SIT01)",
         "https://www.biodic.go.jp/moni1000/wetlands.html",
         "対象10湿原(尾瀬・釧路湿原等)はいずれも神奈川県内ではない。"),
        ("moni1000_waterfowl", "ガンカモ類調査(GAN01)",
         "https://www.biodic.go.jp/moni1000/wetlands.html",
         "全国94地点の調査地点名・緯度経度を確認したが神奈川県内(北緯35.0-35.75,東経138.9-139.85)の地点なし。"),
    ]
    for sid, name, url, note in empties:
        register(
            source_id=sid,
            name=f"モニタリングサイト1000 {name}",
            publisher="環境省生物多様性センター",
            url=url,
            category="生態系モニタリング",
            access_method="利用アンケートフォーム経由でzip取得を試行",
            fmt="CSV/XLSX",
            license_="生物多様性センターウェブサイト利用規約(要事前アンケート回答)",
            redistributable=1,
            record_count=0,
            notes=note,
        )


if __name__ == "__main__":
    process_sin04()
    process_sig02()
    register_empty()
