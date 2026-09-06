#!/usr/bin/env python3
"""
c64: e-Stat (政府統計の総合窓口) 神奈川県分の機械判読可能データ収集
- 農林業センサス 市区町村別 (経営体数・経営耕地面積・耕作放棄地面積) 2015/2020
- 国勢調査 市区町村別人口 (神奈川県)
- RESAS API / 神奈川県統計ページ の確認・断念記録

appId登録が必要な api.e-stat.go.jp は一切使わない。
e-Statサイトの /stat-search/file-download?statInfId=... はログイン・appId不要で
直接ファイルを取得できることを確認したため、これを利用する。
"""
import sys, re, urllib.parse
sys.path.insert(0, "scripts")
from common import get, download, register, write_jsonl, to_fiscal_year, to_number, PROC, RAW, appdb, now

import xlrd
import csv

ESTAT_RAW = RAW / "estat"
ESTAT_RAW.mkdir(parents=True, exist_ok=True)

CENSUS_LICENSE = "政府標準利用規約2.0 (e-Stat)"
CENSUS_PUBLISHER = "総務省統計局 / 農林水産省 (e-Stat経由)"


# ---------------------------------------------------------------------------
# 1. e-Stat CSV/Excel直接ダウンロード経路の確認
#    https://www.e-stat.go.jp/stat-search/files?... の検索結果HTMLから
#    /stat-search/file-download?statInfId=...&fileKind=0 リンクを抽出して取得する。
#    これはログイン・appId登録なしで200が返る（本スクリプト実行時に確認済み）。
# ---------------------------------------------------------------------------

def estat_search(query, page=1):
    url = ("https://www.e-stat.go.jp/stat-search/files?page=%d&layout=dataset&query=%s"
           % (page, urllib.parse.quote(query)))
    r = get(url)
    return r.text


def extract_articles(html):
    return re.findall(
        r'<article class="stat-resource_list-item stat-resource_list-item-dataset">(.*?)</article>',
        html, re.S)


def article_info(a):
    detail = re.findall(r'<li class="stat-resource_list-detail-item">(.*?)</li>', a, re.S)
    detail = [re.sub(r"\s+", " ", re.sub("<[^>]+>", "", d)).strip() for d in detail]
    links = re.findall(r'href="([^"]*file-download[^"]*)"', a)
    return detail, links


# ---------------------------------------------------------------------------
# 2a. 農林業センサス 市区町村別（神奈川県）
# ---------------------------------------------------------------------------
# 検索で特定した統計表 (2026-08-29時点でe-Stat検索結果から確認):
#   2015年農林業センサス 確報 第1巻 都道府県別統計書 14 神奈川県
#     - II 農業経営体 1 農業経営体数                      statInfId=000031511885
#     - V  総農家等   2 経営耕地のある農家数と経営耕地面積  statInfId=000031512239
#     - V  総農家等   3 耕作放棄地 (2) 耕作放棄地面積       statInfId=000031512244
#   2020年農林業センサス 確報 第1巻 都道府県別統計書（神奈川県）
#     - II 農業経営体（総数） 1 農業経営体数                statInfId=000032153273
#     - VI 総農家等 2 経営耕地のある農家数と経営耕地面積     statInfId=000032153325
#   -> 2020年調査では「耕作放棄地」項目自体が調査から廃止されており、
#      2020年分の耕作放棄地面積表は存在しない（e-Stat検索でヒット0件を確認）。
AGRI_FILES = [
    dict(name="2015_noukeieitai_su", stat_inf_id="000031511885", fiscal_year=2015,
         table_ja="農林業センサス 2015年 第1巻都道府県別統計書(神奈川県) II農業経営体 1農業経営体数",
         indicator_table="agri_management_bodies", ncols=9),
    dict(name="2015_keiei_kouchi_menseki", stat_inf_id="000031512239", fiscal_year=2015,
         table_ja="農林業センサス 2015年 第1巻都道府県別統計書(神奈川県) V総農家等 2経営耕地のある農家数と経営耕地面積",
         indicator_table="managed_farmland_area", ncols=10),
    dict(name="2015_kousakuhoukichi_menseki", stat_inf_id="000031512244", fiscal_year=2015,
         table_ja="農林業センサス 2015年 第1巻都道府県別統計書(神奈川県) V総農家等 3耕作放棄地(2)耕作放棄地面積",
         indicator_table="abandoned_farmland_area", ncols=9),
    dict(name="2020_noukeieitai_su", stat_inf_id="000032153273", fiscal_year=2020,
         table_ja="農林業センサス 2020年 第1巻都道府県別統計書(神奈川県) II農業経営体(総数) 1農業経営体数",
         indicator_table="agri_management_bodies", ncols=12),
    dict(name="2020_keiei_kouchi_menseki", stat_inf_id="000032153325", fiscal_year=2020,
         table_ja="農林業センサス 2020年 第1巻都道府県別統計書(神奈川県) VI総農家等 2経営耕地のある農家数と経営耕地面積",
         indicator_table="managed_farmland_area", ncols=14),
]

# 列定義: 4カラム(名前/コード)より後のデータ列の意味 (indicator_key, indicator_ja, unit_ja)
COLDEFS = {
    "agri_management_bodies_2015": [
        (4, "total", "計", "経営体"),
        (5, "family_management", "家族経営体", "経営体"),
        (6, "family_management_incorporated", "家族経営体のうち法人経営", "経営体"),
        (7, "organizational_management", "組織経営体", "経営体"),
        (8, "organizational_management_incorporated", "組織経営体のうち法人経営", "経営体"),
    ],
    "agri_management_bodies_2020": [
        (8, "total", "計", "経営体"),
        (9, "individual_management", "個人経営体", "経営体"),
        (10, "juridical_or_group_management", "団体経営体", "経営体"),
        (11, "juridical_or_group_management_incorporated", "団体経営体のうち法人経営", "経営体"),
    ],
    "managed_farmland_area_2015": [
        (4, "total_farm_households_farm_count", "総農家_計_農家数", "戸"),
        (5, "total_farm_households_area", "総農家_計_面積", "ha"),
        (6, "commercial_farm_households_farm_count", "総農家_販売農家_農家数", "戸"),
        (7, "commercial_farm_households_area", "総農家_販売農家_面積", "ha"),
        (8, "subsistence_farm_households_farm_count", "総農家_自給的農家_農家数", "戸"),
        (9, "subsistence_farm_households_area", "総農家_自給的農家_面積", "ha"),
    ],
    "managed_farmland_area_2020": [
        (8, "total_farm_households_farm_count", "総農家_計_農家数", "戸"),
        (9, "total_farm_households_area", "総農家_計_面積", "ha"),
        (10, "commercial_farm_households_farm_count", "総農家_販売農家_農家数", "戸"),
        (11, "commercial_farm_households_area", "総農家_販売農家_面積", "ha"),
        (12, "subsistence_farm_households_farm_count", "総農家_自給的農家_農家数", "戸"),
        (13, "subsistence_farm_households_area", "総農家_自給的農家_面積", "ha"),
    ],
    "abandoned_farmland_area_2015": [
        (4, "total", "計", "ha"),
        (5, "total_farm_households_subtotal", "総農家_小計", "ha"),
        (6, "commercial_farm_households", "総農家_販売農家", "ha"),
        (7, "subsistence_farm_households", "総農家_自給的農家", "ha"),
        (8, "non_farming_landowner_households", "土地持ち非農家", "ha"),
    ],
}

CENSUS_NOTE_SYMBOLS = (
    '統計表の記号 (2020年農林業センサス 確報 利用上の注意, 都道府県統計主管課が公開する説明文より原文引用): '
    '「0」＝単位に満たないもの。（例：0.4ha→0ha） / '
    '「－」＝調査は行ったが事実のないもの。 / '
    '「△」＝負数又は減少したもの。 / '
    '「Ｘ」＝調査票情報を集計した結果、3未満の調査対象者の集計結果を表示する場合に、'
    '各統計表の集計対象数計を除き、秘匿したもの。'
)


def fetch_agri_files():
    for f in AGRI_FILES:
        url = f"https://www.e-stat.go.jp/stat-search/file-download?statInfId={f['stat_inf_id']}&fileKind=0"
        dest = ESTAT_RAW / f"{f['name']}_{f['stat_inf_id']}.xls"
        download(url, dest)
        f["path"] = dest
        f["url"] = url


def parse_2015_sheet(sh, ncols):
    """2015年統計書形式: col0=県/郡見出し, col1=市区町村(現行), col2=旧市区町村, col3=コード"""
    rows = []
    county_ja = None
    current_city = None
    for r in range(sh.nrows):
        vals = [sh.cell_value(r, c) for c in range(ncols)]
        c0, c1, c2, c3 = (str(v).strip() if not isinstance(v, str) else v.strip() for v in vals[:4])
        data = vals[4:]
        if not any([c0, c1, c2, c3]):
            continue
        if c0 and not c1 and not c2 and not c3:
            if c0 == "神奈川県":
                rows.append(dict(level="prefecture_total", pref_ja=c0, county_ja=None,
                                  city_ja=None, sub_area_ja=None, area_code=None, data=data))
                county_ja = None
            else:
                # 郡見出し行 (データなし)
                county_ja = c0
            continue
        if c1:
            current_city = c1
            rows.append(dict(level="municipality", pref_ja="神奈川県", county_ja=county_ja,
                              city_ja=c1, sub_area_ja=None, area_code=c3, data=data))
            continue
        if c2:
            rows.append(dict(level="former_municipality", pref_ja="神奈川県", county_ja=county_ja,
                              city_ja=current_city, sub_area_ja=c2, area_code=c3, data=data))
            continue
    return rows


def parse_2020_sheet(sh, ncols):
    """2020年統計書形式: col0-3=コード(都道府県/振興局/市区町村/旧市区町村), col4-7=名称"""
    rows = []
    for r in range(sh.nrows):
        vals = [sh.cell_value(r, c) for c in range(ncols)]
        pref_code, shinko_code, shichoson_code, kyu_code = (str(v).strip() for v in vals[0:4])
        pref_ja, shinko_ja, shichoson_ja, kyu_ja = (str(v).strip() for v in vals[4:8])
        data = vals[8:]
        if not re.match(r"^\d+$", pref_code):
            continue  # ヘッダ/見出し行をスキップ
        area_code = f"{shichoson_code}-{kyu_code}" if shichoson_code else None
        if shichoson_code == "000":
            rows.append(dict(level="prefecture_total", pref_ja=pref_ja, county_ja=None,
                              city_ja=None, sub_area_ja=None, area_code=None, data=data))
        elif kyu_code == "00":
            rows.append(dict(level="municipality", pref_ja=pref_ja, county_ja=None,
                              city_ja=shichoson_ja, sub_area_ja=None, area_code=area_code, data=data))
        else:
            rows.append(dict(level="former_municipality", pref_ja=pref_ja, county_ja=None,
                              city_ja=shichoson_ja, sub_area_ja=kyu_ja, area_code=area_code, data=data))
    return rows


def build_agri_census_rows():
    out = []
    for f in AGRI_FILES:
        wb = xlrd.open_workbook(str(f["path"]))
        sh = wb.sheet_by_index(0)
        if f["fiscal_year"] == 2015:
            arearows = parse_2015_sheet(sh, f["ncols"])
        else:
            arearows = parse_2020_sheet(sh, f["ncols"])
        coldef_key = f"{f['indicator_table']}_{f['fiscal_year']}"
        coldefs = COLDEFS[coldef_key]
        data_offset = 4 if f["fiscal_year"] == 2015 else 8  # data list starts at this original col index
        for ar in arearows:
            for col_idx, ind_key, ind_ja, unit_ja in coldefs:
                data_idx = col_idx - data_offset
                raw = ar["data"][data_idx] if data_idx < len(ar["data"]) else None
                if isinstance(raw, float) and raw.is_integer():
                    raw_disp = str(int(raw))
                else:
                    raw_disp = "" if raw is None else str(raw).strip()
                value, value_type = to_number(raw_disp)
                if raw_disp.upper() == "X":
                    # 秘匿値: 3未満の調査対象者の集計結果のため数値非公開。推測で埋めない。
                    value, value_type = None, "suppressed"
                out.append(dict(
                    source_id="estat_agri_census_kanagawa",
                    fiscal_year=f["fiscal_year"],
                    indicator_table=f["indicator_table"],
                    table_ja=f["table_ja"],
                    pref_ja=ar["pref_ja"],
                    county_ja=ar["county_ja"],
                    city_ja=ar["city_ja"],
                    sub_area_ja=ar["sub_area_ja"],
                    area_level=ar["level"],
                    area_code=ar["area_code"],
                    indicator_key=ind_key,
                    indicator_ja=ind_ja,
                    unit_ja=unit_ja,
                    value=value,
                    value_type=value_type,
                    value_raw=raw_disp,
                    source_ref=f"{f['url']} (statInfId={f['stat_inf_id']})",
                    notes=CENSUS_NOTE_SYMBOLS if raw_disp in ("-", "X", "x", "0") else "",
                ))
    return out


def write_agri_census(rows):
    cols = ["source_id", "fiscal_year", "indicator_table", "table_ja", "pref_ja", "county_ja",
            "city_ja", "sub_area_ja", "area_level", "area_code", "indicator_key", "indicator_ja",
            "unit_ja", "value", "value_type", "value_raw", "source_ref", "notes"]
    p = PROC / "estat_agri_census_kanagawa.csv"
    with open(p, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"  [write] {p} {len(rows)} rows")
    write_jsonl("estat_agri_census_kanagawa", rows)
    return p


# ---------------------------------------------------------------------------
# 2b. 国勢調査 市区町村別人口 (神奈川県)
# ---------------------------------------------------------------------------
# 検索で特定した統計表:
#   令和7年国勢調査 速報集計 人口速報集計（男女別人口及び世帯総数）
#   第1表 男女別人口、2020年（令和2年）の人口（組替）、世帯数、2020年（令和2年）の世帯数（組替）、
#   5年間の人口増減数、5年間の人口増減率、5年間の世帯増減数、5年間の世帯増減率、人口性比、
#   面積（参考）及び人口密度－全国、都道府県、市区町村
#   statInfId=000040454825 (全国×市区町村の一括表。神奈川県分のみ抽出して使用)
#   -> 2020年との比較値が「組替」(市区町村合併等を現在の境域に組み替え直した値)として
#      同じ表に同梱されているため、2025年と2020年を別表で取得する必要がない。
CENSUS_POP_STAT_INF_ID = "000040454825"
CENSUS_POP_URL = f"https://www.e-stat.go.jp/stat-search/file-download?statInfId={CENSUS_POP_STAT_INF_ID}&fileKind=0"

CENSUS_POP_COLDEFS = [
    (3, "population_total", "人口（総数）", "人"),
    (4, "population_male", "人口（男）", "人"),
    (5, "population_female", "人口（女）", "人"),
    (6, "population_2020_rebased", "2020年（令和2年）の人口（組替）", "人"),
    (7, "population_change_5yr", "5年間の人口増減数", "人"),
    (8, "population_change_rate_5yr", "5年間の人口増減率", "％"),
    (9, "sex_ratio", "人口性比（女性100人に対する男性の数）", ""),
    (10, "area_km2", "面積（参考）", "km2"),
    (11, "population_density", "人口密度", "1km2当たり"),
    (12, "households_total", "世帯数", "世帯"),
    (13, "households_2020_rebased", "2020年（令和2年）の世帯数（組替）", "世帯"),
    (14, "households_change_5yr", "5年間の世帯増減数", "世帯"),
    (15, "households_change_rate_5yr", "5年間の世帯増減率", "％"),
]

AREA_LEVEL_MAP = {
    "a": "prefecture_total",
    "1": "designated_city_total",
    "0": "ward",
    "2": "city",
    "3": "town_village",
}


def fetch_census_population():
    import pandas as pd
    dest = ESTAT_RAW / f"2025_sokuhou_jinko_setai_{CENSUS_POP_STAT_INF_ID}.xls"
    download(CENSUS_POP_URL, dest)
    df = pd.read_excel(dest, sheet_name=0, header=None)
    kn = df[df[1].astype(str).str.contains("14_神奈川県", na=False)]
    rows = []
    for _, r in kn.iterrows():
        area_level = AREA_LEVEL_MAP.get(str(r[0]).strip(), str(r[0]).strip())
        code_name = str(r[2])
        area_code, _, area_name_ja = code_name.partition("_")
        for col_idx, ind_key, ind_ja, unit_ja in CENSUS_POP_COLDEFS:
            raw = r[col_idx]
            if pd.isna(raw):
                raw_disp = ""
            elif isinstance(raw, float) and raw.is_integer():
                raw_disp = str(int(raw))
            else:
                raw_disp = str(raw)
            value, value_type = to_number(raw_disp)
            rows.append(dict(
                source_id="estat_census_population_kanagawa",
                fiscal_year=2025,
                comparison_fiscal_year=2020,
                pref_ja="神奈川県",
                area_ja=area_name_ja,
                area_level=area_level,
                area_code=area_code,
                indicator_key=ind_key,
                indicator_ja=ind_ja,
                unit_ja=unit_ja,
                value=value,
                value_type=value_type,
                value_raw=raw_disp,
                source_ref=f"{CENSUS_POP_URL} (statInfId={CENSUS_POP_STAT_INF_ID})",
                notes=("2020年（令和2年）比較値は市区町村合併等を反映して現在の境域に組み替えた「組替」値。"
                       "速報集計のため確定数と異なる場合がある(原表注記1・2参照)。"),
            ))
    return rows


def write_census_population(rows):
    cols = ["source_id", "fiscal_year", "comparison_fiscal_year", "pref_ja", "area_ja", "area_level",
            "area_code", "indicator_key", "indicator_ja", "unit_ja", "value", "value_type",
            "value_raw", "source_ref", "notes"]
    p = PROC / "estat_census_population_kanagawa.csv"
    with open(p, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"  [write] {p} {len(rows)} rows")
    write_jsonl("estat_census_population_kanagawa", rows)
    return p


# ---------------------------------------------------------------------------
# 3. RESAS API 確認 (登録はしない)
# ---------------------------------------------------------------------------
def check_resas():
    r = get("https://opendata.resas-portal.go.jp/")
    txt = r.text
    return txt


# ---------------------------------------------------------------------------
# 4. 神奈川県統計ページの確認 (代替経路)
# ---------------------------------------------------------------------------
def check_pref_kanagawa_page():
    r = get("https://www.pref.kanagawa.jp/docs/x8n/")
    return r.text


if __name__ == "__main__":
    print("== step1: 農林業センサス ダウンロード ==")
    fetch_agri_files()
    rows = build_agri_census_rows()
    write_agri_census(rows)
    print(f"total agri census rows: {len(rows)}")

    print("== step2: 国勢調査 市区町村別人口 ==")
    pop_rows = fetch_census_population()
    write_census_population(pop_rows)
    print(f"total census population rows: {len(pop_rows)}")
