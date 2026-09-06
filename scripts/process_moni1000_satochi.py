"""モニタリングサイト1000 里地調査(鳥類・中大型哺乳類・チョウ類)データを
神奈川県のサイトIDで絞り込み、data/processed/moni1000_satochi_*.csv/.jsonl に出力する。
"""
import sys, csv
sys.path.insert(0, "scripts")
import pandas as pd
from common import PROC, RAW, register, write_jsonl

EXT = RAW / "moni1000" / "extracted"

SITE_FILES = {
    "bird": (EXT / "SAT02/DataSite_bird.xlsx", 3),
    "mammal": (EXT / "SAT03/DataSite_ver.2_20140312.xls", 3),
    "butterfly": (EXT / "SAT07/DataSite_Butterfly.xlsx", 3),
}


def kanagawa_site_ids(path, header_row):
    df = pd.read_excel(path, header=header_row)
    df.columns = [str(c).strip() for c in df.columns]
    kn = df[df["都道府県"] == "神奈川"].copy()
    # サイト名 appears twice (site_label combined, and plain name) -> take last occurrence as plain name
    cols = list(df.columns)
    name_col = cols[2] if cols[0] == cols[2] else cols[2]
    kn = kn.rename(columns={cols[1]: "site_id", name_col: "site_name_ja",
                             "都道府県": "prefecture", "緯度": "lat", "経度": "lon"})
    return kn


def write_out(name, df, source_id, source_ref, colmap):
    df = df.rename(columns=colmap)
    df["source_id"] = source_id
    df["source_ref"] = source_ref
    csv_path = PROC / f"{name}.csv"
    df.to_csv(csv_path, index=False, encoding="utf-8")
    print(f"[write] {csv_path} {len(df)} rows")
    write_jsonl(name, df.to_dict(orient="records"))
    return len(df)


def main():
    results = {}

    # --- 鳥類調査 ---
    bird_sites = kanagawa_site_ids(*SITE_FILES["bird"])
    bird_site_ids = set(bird_sites["site_id"])
    print("bird kanagawa sites:", bird_site_ids)
    census = pd.read_csv(EXT / "SAT02/DataCensus202207.csv", encoding="cp932")
    census_kn = census[census["サイトID"].isin(bird_site_ids)]
    n = write_out("moni1000_satochi_bird_census_kanagawa", census_kn,
                   "moni1000_satochi_bird",
                   "https://www.biodic.go.jp/moni1000/question/question.html (SAT02)",
                   {"データID": "data_id", "調査ID": "survey_id", "サイトID": "site_id",
                    "調査年": "survey_year", "調査月": "survey_month", "季節": "season_ja",
                    "反復No.": "rep_no", "区間名": "section_name_ja", "種名": "species_ja",
                    "同定の確度": "id_confidence_ja", "個体数": "count", "±": "plusminus",
                    "同定_視認": "id_visual", "同定_さえずり": "id_song", "同定_地鳴き": "id_call",
                    "成鳥／幼鳥": "age_class_ja", "繁殖行動": "breeding_behavior_ja",
                    "範囲外": "out_of_range", "時間外": "out_of_time"})
    results["moni1000_satochi_bird"] = n

    site_out_csv = PROC / "moni1000_satochi_bird_sites_kanagawa.csv"
    bird_sites.to_csv(site_out_csv, index=False, encoding="utf-8")
    print(f"[write] {site_out_csv} {len(bird_sites)} rows")

    # --- 中大型哺乳類調査 ---
    mammal_sites = kanagawa_site_ids(*SITE_FILES["mammal"])
    mammal_site_ids = set(mammal_sites["site_id"])
    print("mammal kanagawa sites:", mammal_site_ids)
    photo = pd.read_csv(EXT / "SAT03/DataPhoto_ver.2_20140312.csv", encoding="cp932")
    photo_kn = photo[photo["サイトID"].isin(mammal_site_ids)]
    n = write_out("moni1000_satochi_mammal_photo_kanagawa", photo_kn,
                   "moni1000_satochi_mammal",
                   "https://www.biodic.go.jp/moni1000/question/question.html (SAT03)",
                   {"データID": "data_id", "調査ID": "survey_id", "サイトID": "site_id",
                    "撮影年": "photo_year", "撮影月": "photo_month", "撮影日": "photo_day",
                    "撮影時刻": "photo_time", "最終同定種名": "species_ja", "個体数": "count"})
    results["moni1000_satochi_mammal"] = n
    site_out_csv = PROC / "moni1000_satochi_mammal_sites_kanagawa.csv"
    mammal_sites.to_csv(site_out_csv, index=False, encoding="utf-8")
    print(f"[write] {site_out_csv} {len(mammal_sites)} rows")

    # --- チョウ類調査 ---
    butterfly_sites = kanagawa_site_ids(*SITE_FILES["butterfly"])
    butterfly_site_ids = set(butterfly_sites["site_id"])
    print("butterfly kanagawa sites:", butterfly_site_ids)
    bcensus = pd.read_csv(EXT / "SAT07/data_census202207.csv", encoding="cp932")
    bcensus_kn = bcensus[bcensus["サイトID"].isin(butterfly_site_ids)]
    n = write_out("moni1000_satochi_butterfly_census_kanagawa", bcensus_kn,
                   "moni1000_satochi_butterfly",
                   "https://www.biodic.go.jp/moni1000/question/question.html (SAT07)",
                   {"データID": "data_id", "調査ID": "survey_id", "サイトID": "site_id",
                    "調査年": "survey_year", "調査月": "survey_month", "調査日": "survey_day",
                    "区間名": "section_name_ja", "種名": "species_ja", "個体数": "count",
                    "範囲外": "out_of_range", "時間外": "out_of_time"})
    results["moni1000_satochi_butterfly"] = n
    site_out_csv = PROC / "moni1000_satochi_butterfly_sites_kanagawa.csv"
    butterfly_sites.to_csv(site_out_csv, index=False, encoding="utf-8")
    print(f"[write] {site_out_csv} {len(butterfly_sites)} rows")

    for sid, cnt, label, codes in [
        ("moni1000_satochi_bird", results["moni1000_satochi_bird"], "里地鳥類調査", "SAT02"),
        ("moni1000_satochi_mammal", results["moni1000_satochi_mammal"], "里地中・大型哺乳類調査(自動撮影)", "SAT03"),
        ("moni1000_satochi_butterfly", results["moni1000_satochi_butterfly"], "里地チョウ類調査", "SAT07"),
    ]:
        register(
            source_id=sid,
            name=f"モニタリングサイト1000 {label}（神奈川県サイトのみ抽出）",
            publisher="環境省生物多様性センター",
            url="https://www.biodic.go.jp/moni1000/village.html",
            category="生態系モニタリング(里地里山)",
            access_method=f"利用アンケートフォーム経由でzip取得({codes})、サイトIDで神奈川抽出",
            fmt="CSV(Shift_JIS)->CSV/JSONL(UTF-8)",
            license_="生物多様性センターウェブサイト利用規約(要事前アンケート回答)",
            redistributable=1,
            record_count=cnt,
            notes="全国データを都道府県別サイト一覧(DataSite_*.xlsx)のサイトIDで神奈川県分に絞り込み。",
        )


if __name__ == "__main__":
    main()
