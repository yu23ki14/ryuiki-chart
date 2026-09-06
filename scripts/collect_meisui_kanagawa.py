"""名水百選(環境省)のうち神奈川県分(秦野盆地湧水群 info=25, 洒水の滝/滝沢川 info=26)を収集。
data/processed/moe_meisui_kanagawa.csv / .jsonl
緯度経度は本文中に記載がないため lat/lon は null(アクセスマップ画像のみ)。
"""
import sys, re, csv
sys.path.insert(0, "scripts")
from common import get, register, write_jsonl, PROC
from bs4 import BeautifulSoup

BASE = "https://water-pub.env.go.jp/water-pub/mizu-site/meisui/"
TARGETS = [25, 26]


def fetch(url):
    r = get(url)
    return r.content.decode("cp932", errors="replace")


def parse_detail(html, info_no, url):
    soup = BeautifulSoup(html, "html.parser")
    # ラベル(img alt)とその直後のspan.fmhのペアを取得
    fields = {}
    for img in soup.find_all("img"):
        alt = img.get("alt", "").strip()
        if not alt or alt in ("位置情報", "アクセスマップ図", "写真", ""):
            continue
        # 直後の兄弟要素からspan.fmhを探す
        sib = img.find_next_sibling("span", class_="fmh")
        if sib:
            fields[alt] = sib.get_text(" ", strip=True)

    # 種別/所在地/名称は先頭の表から
    text_all = soup.get_text("\n", strip=True)
    lines = [l for l in text_all.split("\n") if l.strip()]
    # 「湧水」等の種別、所在地、名称(ふりがな付き)は3,4,5行目付近
    type_ja = lines[1] if len(lines) > 1 else None
    location_ja = lines[2] if len(lines) > 2 else None
    name_ja = lines[3] if len(lines) > 3 else None

    return {
        "source_id": "moe_meisui_kanagawa",
        "info_no": info_no,
        "name_ja": name_ja,
        "type_ja": type_ja,
        "location_ja": location_ja,
        "lat": None, "lon": None, "latlon_note": "本文に緯度経度記載なし(アクセスマップ画像のみ)",
        "season_ja": fields.get("おすすめの時期"),
        "surrounding_nature_ja": fields.get("周辺の自然環境"),
        "usage_ja": fields.get("利用状況"),
        "event_ja": fields.get("イベント情報"),
        "water_quality_quantity_ja": fields.get("水質・水量"),
        "history_ja": fields.get("由来・歴史"),
        "conservation_activity_ja": fields.get("水質保全活動"),
        "access_ja": fields.get("アクセス"),
        "contact_ja": fields.get("お問い合わせ"),
        "source_ref": url,
    }


def main():
    out = []
    for n in TARGETS:
        url = f"{BASE}data/index.asp?info={n}"
        html = fetch(url)
        rec = parse_detail(html, n, url)
        out.append(rec)
        print(f"  info={n}: {rec['name_ja']}")

    fieldnames = list(out[0].keys())
    csv_path = PROC / "moe_meisui_kanagawa.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for row in out:
            w.writerow(row)
    write_jsonl("moe_meisui_kanagawa", out)
    print(f"[write] {csv_path} {len(out)} rows")

    register(
        source_id="moe_meisui_kanagawa",
        name="名水百選（神奈川県分: 秦野盆地湧水群・洒水の滝/滝沢川）",
        publisher="環境省",
        url="https://water-pub.env.go.jp/water-pub/mizu-site/meisui/",
        category="水環境",
        access_method="一覧HTML(Shift_JIS)から神奈川県分を特定し、詳細ページ(info=25,26)をパース",
        fmt="HTML->CSV/JSONL",
        license_="環境省ウェブサイト著作権・リンクについてに準拠(要確認)",
        redistributable=1,
        record_count=len(out),
        notes="緯度経度はページ本文に数値記載がなく、アクセスマップ画像のみのため lat/lon は null。",
    )


if __name__ == "__main__":
    main()
