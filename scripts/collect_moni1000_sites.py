"""モニタリングサイト1000: 全国サイト一覧を都道府県別ページから収集し、
data/processed/moni1000_sites_all.csv / .jsonl と
data/processed/moni1000_sites_kanagawa.csv / .jsonl を出力する。
"""
import sys, re
sys.path.insert(0, "scripts")
from common import get, register, write_jsonl, PROC
from bs4 import BeautifulSoup

BASE = "https://www.biodic.go.jp/moni1000/"
TOP = "https://www.biodic.go.jp/moni1000/site_list.html"

PREF_MAP = {
    "hokkaido": "北海道", "aomori": "青森県", "iwate": "岩手県", "miyagi": "宮城県",
    "akita": "秋田県", "yamagata": "山形県", "fukushima": "福島県",
    "ibaraki": "茨城県", "tochigi": "栃木県", "gunma": "群馬県", "saitama": "埼玉県",
    "chiba": "千葉県", "tokyo": "東京都", "kanagawa": "神奈川県",
    "niigata": "新潟県", "toyama": "富山県", "ishikawa": "石川県", "fukui": "福井県",
    "yamanashi": "山梨県", "nagano": "長野県", "gifu": "岐阜県", "shizuoka": "静岡県",
    "aichi": "愛知県", "mie": "三重県",
    "shiga": "滋賀県", "kyoto": "京都府", "osaka": "大阪府", "hyogo": "兵庫県",
    "nara": "奈良県", "wakayama": "和歌山県",
    "tottori": "鳥取県", "shimane": "島根県", "okayama": "岡山県", "hiroshima": "広島県",
    "yamaguchi": "山口県",
    "tokushima": "徳島県", "kagawa": "香川県", "ehime": "愛媛県", "kochi": "高知県",
    "fukuoka": "福岡県", "saga": "佐賀県", "nagasaki": "長崎県", "kumamoto": "熊本県",
    "oita": "大分県", "miyazaki": "宮崎県", "kagoshima": "鹿児島県", "okinawa": "沖縄県",
}


def fetch_html(url):
    r = get(url)
    return r.content.decode("utf-8", errors="replace")


def parse_pref_page(html, pref_slug, pref_ja, url):
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", class_="site-list-table")
    rows = []
    if not table:
        return rows
    tbody = table.find("tbody")
    if not tbody:
        return rows
    for tr in tbody.find_all("tr"):
        tds = [td.get_text(strip=True) for td in tr.find_all("td")]
        if len(tds) != 6:
            continue
        ecosystem_ja, survey_name_ja, site_name_ja, lat_raw, lon_raw, municipality_ja = tds
        try:
            lat = float(lat_raw)
        except ValueError:
            lat = None
        try:
            lon = float(lon_raw)
        except ValueError:
            lon = None
        site_class = tr.get("class", [""])[0]
        rows.append({
            "source_id": "moni1000_sites",
            "site_code": site_class,
            "prefecture": pref_ja,
            "prefecture_slug": pref_slug,
            "ecosystem_ja": ecosystem_ja,
            "survey_name_ja": survey_name_ja,
            "site_name_ja": site_name_ja,
            "lat": lat,
            "lon": lon,
            "lat_raw": lat_raw,
            "lon_raw": lon_raw,
            "municipality_ja": municipality_ja,
            "source_ref": url,
        })
    return rows


def main():
    all_rows = []
    failed = []
    for slug, pref_ja in PREF_MAP.items():
        url = f"{BASE}site_list_{slug}_map.html"
        try:
            html = fetch_html(url)
        except Exception as e:
            failed.append((slug, str(e)))
            print(f"  [fail] {slug}: {e}")
            continue
        rows = parse_pref_page(html, slug, pref_ja, url)
        print(f"  {slug}: {len(rows)} sites")
        all_rows.extend(rows)

    # write all
    import csv
    p_all_csv = PROC / "moni1000_sites_all.csv"
    fieldnames = ["source_id", "site_code", "prefecture", "prefecture_slug",
                  "ecosystem_ja", "survey_name_ja", "site_name_ja",
                  "lat", "lon", "lat_raw", "lon_raw", "municipality_ja", "source_ref"]
    with open(p_all_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in all_rows:
            w.writerow(r)
    write_jsonl("moni1000_sites_all", all_rows)
    print(f"[write] {p_all_csv} {len(all_rows)} rows")

    kanagawa_rows = [r for r in all_rows if r["prefecture"] == "神奈川県"]
    p_kn_csv = PROC / "moni1000_sites_kanagawa.csv"
    with open(p_kn_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in kanagawa_rows:
            w.writerow(r)
    write_jsonl("moni1000_sites_kanagawa", kanagawa_rows)
    print(f"[write] {p_kn_csv} {len(kanagawa_rows)} rows")

    notes = ""
    if failed:
        notes = "取得失敗都道府県: " + ", ".join(f"{s}({e})" for s, e in failed)
    register(
        source_id="moni1000_sites",
        name="モニタリングサイト1000 サイト一覧（全国・神奈川抽出）",
        publisher="環境省生物多様性センター",
        url=TOP,
        category="生態系モニタリング",
        access_method="HTML(都道府県別ページ)を収集・パース",
        fmt="HTML->CSV/JSONL",
        license_="政府標準利用規約(準拠を想定、要確認)",
        redistributable=1,
        record_count=len(all_rows),
        notes=(f"全国{len(all_rows)}サイト中、神奈川県{len(kanagawa_rows)}サイト。"
               f"緯度経度は各都道府県別ページの表に十進度で記載済み(変換不要)。" + notes),
    )


if __name__ == "__main__":
    main()
