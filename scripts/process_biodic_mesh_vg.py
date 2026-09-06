"""自然環境保全基礎調査 植生調査 3次メッシュデータ(第4回1988-1992, 第5回1992-1996)を
神奈川県に該当する3次メッシュ(緯度35.0-35.75, 経度138.9-139.85のバウンディングボックス)で抽出。
凡例コード表(veg_c02)もあわせて処理。
"""
import sys, csv
sys.path.insert(0, "scripts")
from common import PROC, RAW, register, write_jsonl

MESH_DIR = RAW / "biodic_mesh_vg"

# 神奈川県がまたがりうる緯度経度範囲(WGS84相当、日本測地系との差は数十m程度で許容)
LAT_MIN, LAT_MAX = 35.0, 35.85
LON_MIN, LON_MAX = 138.9, 139.85


def mesh_to_latlon_sw(mesh_code):
    """3次メッシュコード(8桁)から南西端の緯度経度(度)を返す"""
    s = str(mesh_code)
    if len(s) != 8:
        return None, None
    p, u, q, v, a, b = int(s[0:2]), int(s[2:4]), int(s[4]), int(s[5]), int(s[6]), int(s[7])
    lat = p / 1.5 + q / 12 + a / 120
    lon = 100 + u + v / 8 + b / 80
    return lat, lon


def load_mesh_csv(path):
    rows = []
    with open(path, encoding="cp932", newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        for row in reader:
            if len(row) < 2:
                continue
            mesh_code, veg_code = row[0].strip('"'), row[1].strip('"')
            rows.append((mesh_code, veg_code))
    return rows


def load_legend(path):
    rows = []
    with open(path, encoding="cp932", newline="") as f:
        reader = csv.reader(f)
        header = [h.strip('"') for h in next(reader)]
        for row in reader:
            rows.append(dict(zip(header, [c.strip('"') for c in row])))
    return header, rows


def process_survey(csv_path, survey_label, survey_years, source_id):
    all_rows = load_mesh_csv(csv_path)
    out = []
    for mesh_code, veg_code in all_rows:
        lat, lon = mesh_to_latlon_sw(mesh_code)
        if lat is None:
            continue
        # メッシュ中心座標(南西端+半メッシュ分, 3次メッシュ=約1km=緯度1/120度・経度1/80度)
        lat_c = lat + (1 / 120) / 2
        lon_c = lon + (1 / 80) / 2
        if LAT_MIN <= lat_c <= LAT_MAX and LON_MIN <= lon_c <= LON_MAX:
            out.append({
                "source_id": source_id,
                "mesh_code": mesh_code,
                "vegetation_code_raw": veg_code,
                "survey": survey_label,
                "survey_years": survey_years,
                "lat": round(lat_c, 6),
                "lon": round(lon_c, 6),
                "source_ref": "https://www.biodic.go.jp/dload/mesh_vg.html",
            })
    csv_out = PROC / f"{source_id}.csv"
    fieldnames = ["source_id", "mesh_code", "vegetation_code_raw", "survey", "survey_years", "lat", "lon", "source_ref"]
    with open(csv_out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in out:
            w.writerow(r)
    write_jsonl(source_id, out)
    print(f"[write] {csv_out} {len(out)} rows (全国{len(all_rows)}メッシュ中)")
    return len(out), len(all_rows)


def process_legend():
    import glob
    files = sorted(glob.glob(str(MESH_DIR / "extract_c02/veg_c02/*.csv")))
    out_all = {}
    for f in files:
        header, rows = load_legend(f)
        name = f.split("/")[-1].replace(".csv", "")
        csv_out = PROC / f"biodic_vegcode_{name}.csv"
        with open(csv_out, "w", newline="", encoding="utf-8") as fo:
            w = csv.DictWriter(fo, fieldnames=header)
            w.writeheader()
            for r in rows:
                w.writerow(r)
        write_jsonl(f"biodic_vegcode_{name}", rows)
        print(f"[write] {csv_out} {len(rows)} rows")
        out_all[name] = len(rows)
    return out_all


def main():
    n4, total4 = process_survey(MESH_DIR / "extract_04/veg04m01/veg04mesh.csv",
                                 "第4回自然環境保全基礎調査", "1988-1992",
                                 "biodic_vegmesh_4th_kanagawa")
    n5, total5 = process_survey(MESH_DIR / "extract_05/veg05m01/veg05mesh.csv",
                                 "第5回自然環境保全基礎調査", "1992-1996",
                                 "biodic_vegmesh_5th_kanagawa")
    legend_counts = process_legend()

    register(
        source_id="biodic_vegmesh_4th_kanagawa",
        name="植生調査 3次メッシュデータ 第4回自然環境保全基礎調査(1988-1992)（神奈川県相当メッシュ抽出）",
        publisher="環境省生物多様性センター",
        url="https://www.biodic.go.jp/dload/mesh_vg.html",
        category="自然環境保全基礎調査(植生)",
        access_method="lzh圧縮ファイルを直接ダウンロード(7zで解凍)、メッシュコードから緯度経度を計算しバウンディングボックスで抽出",
        fmt="CSV(Shift_JIS,lzh圧縮)->CSV/JSONL(UTF-8)",
        license_="生物多様性センターウェブサイト利用規約",
        redistributable=1,
        record_count=n4,
        notes=(f"全国{total4}メッシュから緯度35.0-35.85,経度138.9-139.85のバウンディングボックスで抽出({n4}件)。"
               "3次メッシュは約1km×1km。メッシュコードは南西端を基準に中心点座標を算出(JIS X0410方式)。"
               "バウンディングボックスのため一部東京都・山梨県・静岡県境界付近のメッシュを含む可能性がある(市区町村単位の厳密な行政界フィルタは未実施)。"
               "植生コードの凡例(判読)は biodic_vegcode_veg_kubun 等を参照。"),
    )
    register(
        source_id="biodic_vegmesh_5th_kanagawa",
        name="植生調査 3次メッシュデータ 第5回自然環境保全基礎調査(1992-1996)（神奈川県相当メッシュ抽出）",
        publisher="環境省生物多様性センター",
        url="https://www.biodic.go.jp/dload/mesh_vg.html",
        category="自然環境保全基礎調査(植生)",
        access_method="lzh圧縮ファイルを直接ダウンロード(7zで解凍)、メッシュコードから緯度経度を計算しバウンディングボックスで抽出",
        fmt="CSV(Shift_JIS,lzh圧縮)->CSV/JSONL(UTF-8)",
        license_="生物多様性センターウェブサイト利用規約",
        redistributable=1,
        record_count=n5,
        notes=(f"全国{total5}メッシュから同バウンディングボックスで抽出({n5}件)。"
               "第4回(1988-1992)と第5回(1992-1996)は調査年・凡例コード体系が同一のため経年比較が可能だが、"
               "行政界ではなく緯度経度バウンディングボックスでの抽出である点に注意。"),
    )
    register(
        source_id="biodic_vegcode_legend",
        name="植生調査共通凡例コード表(第2版, 2001-10-31~)",
        publisher="環境省生物多様性センター",
        url="https://www.biodic.go.jp/dload/mesh_vg.html",
        category="自然環境保全基礎調査(植生)",
        access_method="lzh圧縮ファイルを直接ダウンロード(7zで解凍)、全国共通コード表のためそのまま格納(地域抽出なし)",
        fmt="CSV(Shift_JIS,lzh圧縮)->CSV/JSONL(UTF-8)",
        license_="生物多様性センターウェブサイト利用規約",
        redistributable=1,
        record_count=sum(legend_counts.values()),
        notes=f"内訳: {legend_counts}。植生コード(vegetation_code_raw)の意味を引く凡例表(全国共通、地域限定なし)。",
    )


if __name__ == "__main__":
    main()
