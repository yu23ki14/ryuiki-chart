"""相模川ライブカメラ16地点 (京浜河川事務所) -> sites候補CSV
lat/lonは掲載されている「川の防災情報」リンクのclat/clonクエリパラメータから取得。
これはカメラ表示用地図の中心座標であり、カメラ設置点そのものの正確な測量値ではない
可能性がある点に注意 (notesに明記)。
"""
import sys, re, csv, urllib.parse
sys.path.insert(0, "scripts")
from common import get, register, write_jsonl, PROC

URL = "https://www.ktr.mlit.go.jp/keihin/keihin01459.html"
PUBLISHER = "国土交通省 関東地方整備局 京浜河川事務所"

def main():
    r = get(URL)
    r.encoding = r.apparent_encoding
    t = r.text
    idx = t.find("ライブカメラ(相模川)")
    block = t[idx: idx + 20000]
    # 各 <a href="https://www.river.go.jp/kawabou/pc/tm?...">N.地点名(所在地)</a>
    pattern = re.compile(
        r'<a href="(https://www\.river\.go\.jp/kawabou/pc/tm\?[^"]+)"[^>]*>(\d+)\.([^<(]+)\(([^)]*)\)'
    )
    rows = []
    for m in pattern.finditer(block):
        href, no, name, place = m.groups()
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
        lat = float(qs["clat"][0]) if "clat" in qs else None
        lon = float(qs["clon"][0]) if "clon" in qs else None
        rows.append({
            "site_id_candidate": f"sagami_livecam_{int(no):02d}",
            "seq_no": int(no),
            "name_ja": name.strip(),
            "location_ja": place.strip(),
            "watershed": "相模川水系",
            "lat": lat,
            "lon": lon,
            "kind": "河川ライブカメラ",
            "operator": PUBLISHER,
            "source_id": "sagami_livecams",
            "source_ref": href,
            "notes": "lat/lonは川の防災情報カメラ表示ページの地図中心座標(clat/clon)。カメラ設置点の実測位置とは限らない",
        })

    p = PROC / "sagami_livecams.csv"
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        for row in rows:
            w.writerow(row)
    write_jsonl("sagami_livecams", rows)
    print(f"  [write] {p} ({len(rows)} rows)")

    register(
        source_id="sagami_livecams",
        name="相模川ライブカメラ地点一覧",
        publisher=PUBLISHER,
        url=URL,
        category="観測地点(河川)",
        access_method="HTMLページ内リンクパラメータ解析",
        fmt="HTML",
        license_="政府標準利用規約(第2.0版)相当（要確認）",
        redistributable=1,
        record_count=len(rows),
        notes="観測地点マスタ(sites)の候補素材。lat/lonはカメラ表示用地図の中心座標(clat/clon)であり実測点ではない可能性がある。",
    )

if __name__ == "__main__":
    main()
