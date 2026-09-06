"""環境省 重要里地里山 選定地(神奈川県28か所)を一覧+詳細ページから収集。
data/processed/moe_satoyama_kanagawa.csv / .jsonl
列: no, name_ja, municipality_ja, area_ha, features_ja, source_ref
"""
import sys, re, csv
sys.path.insert(0, "scripts")
from common import get, register, write_jsonl, PROC
from bs4 import BeautifulSoup

LIST_URL = "https://www.env.go.jp/nature/satoyama/14_kanagawa/kanagawa.html"
BASE = "https://www.env.go.jp/nature/satoyama/14_kanagawa/"


def fetch(url):
    r = get(url)
    return r.content.decode("utf-8", errors="replace")


def main():
    html = fetch(LIST_URL)
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", class_="table01")
    rows = []
    for tr in table.find_all("tr")[1:]:
        tds = tr.find_all("td")
        if len(tds) != 3:
            continue
        no = tds[0].get_text(strip=True)
        municipality_ja = tds[1].get_text(strip=True)
        a = tds[2].find("a")
        name_ja = a.get_text(strip=True)
        href = a["href"]
        detail_url = BASE + href
        rows.append({"no": no, "municipality_ja": municipality_ja,
                     "name_ja": name_ja, "detail_url": detail_url})

    out = []
    for r in rows:
        dhtml = fetch(r["detail_url"])
        dsoup = BeautifulSoup(dhtml, "html.parser")
        features_ja = None
        area_ha = None
        for th in dsoup.find_all("th"):
            label = th.get_text(strip=True)
            td = th.find_next_sibling("td")
            if td is None:
                continue
            if label == "選定理由":
                features_ja = td.get_text(" ", strip=True)
            if "面積" in label:
                area_ha = td.get_text(strip=True)
        out.append({
            "source_id": "moe_satoyama_kanagawa",
            "no": r["no"],
            "name_ja": r["name_ja"],
            "municipality_ja": r["municipality_ja"],
            "area_ha": area_ha,  # 詳細ページに面積記載なし -> None
            "features_ja": features_ja,
            "source_ref": r["detail_url"],
        })
        print(f"  {r['no']} {r['name_ja']} area_ha={area_ha}")

    fieldnames = ["source_id", "no", "name_ja", "municipality_ja", "area_ha", "features_ja", "source_ref"]
    csv_path = PROC / "moe_satoyama_kanagawa.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for row in out:
            w.writerow(row)
    write_jsonl("moe_satoyama_kanagawa", out)
    print(f"[write] {csv_path} {len(out)} rows")

    register(
        source_id="moe_satoyama_kanagawa",
        name="重要里地里山 選定地一覧（神奈川県）",
        publisher="環境省",
        url=LIST_URL,
        category="里地里山",
        access_method="一覧HTML+詳細HTML(28件)をBeautifulSoupでパース",
        fmt="HTML->CSV/JSONL",
        license_="環境省ウェブサイト著作権・リンクについてに準拠(要確認)",
        redistributable=1,
        record_count=len(out),
        notes=("詳細ページに面積(ha)の記載がないため area_ha は全件 null。"
               "features_ja は各詳細ページの「選定理由」欄の原文をそのまま格納(要約していない)。"),
    )


if __name__ == "__main__":
    main()
