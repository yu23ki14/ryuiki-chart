#!/usr/bin/env python3
"""産総研 20万分の1日本シームレス地質図V2 Web API (ver 1.3.1) から
   (1) 凡例（地質記号→岩相・年代等）全件
   (2) 相模川流域内グリッド地点の地質判定結果
   を取得して data/processed に出力する。

API仕様は https://gbank.gsj.jp/seamless/v2/api/1.3.1/ (実際に取得して確認済み。
推測でURL/パラメータを組み立てていない)。

利用規約: 政府標準利用規約（第2.0版）に準拠。
  https://www.gsj.jp/license/index.html
  https://www.gsj.jp/license/license.html
  同ページに「本利用ルールは、クリエイティブ・コモンズ・ライセンスの表示4.0国際
  （CC BY 4.0）と互換性があり、本利用ルールが適用されるコンテンツはCC BYに従う
  ことでも利用することができます」と明記されている（2026-08-29 取得時点で確認）。
  → license列には原文の規約名を記載し、CC BY 4.0互換である旨を併記する。
"""
import csv
import io
import json
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from common import get, get_json, register, write_jsonl, PROC, RAW, now

API_BASE = "https://gbank.gsj.jp/seamless/v2/api/1.3.1"
LICENSE = ("政府標準利用規約（第2.0版）準拠。出典明示で改変含む自由利用・商用利用可"
           "（利用申請不要）。CC BY 4.0（表示4.0国際）と互換性があり、CC BYに従うこと"
           "でも利用可能（https://www.gsj.jp/license/license.html に明記）。")


def fetch_legend():
    """全凡例をcsv(タブ区切り, utf-8)で取得してパースする。"""
    dest = RAW / "gsj_seamless" / "legend_all.tsv"
    dest.parent.mkdir(parents=True, exist_ok=True)
    url = f"{API_BASE}/legend.csv"
    r = get(url)
    # ドキュメントに「csvと表現しているがタブ区切り、文字コードはutf-8」と明記
    text = r.content.decode("utf-8")
    dest.write_text(text, encoding="utf-8")
    reader = csv.DictReader(io.StringIO(text), delimiter="\t")
    rows = []
    for rec in reader:
        r_, g_, b_ = rec.get("r"), rec.get("g"), rec.get("b")
        try:
            color_hex = "%02x%02x%02x" % (int(r_), int(g_), int(b_))
        except (TypeError, ValueError):
            color_hex = None
        rows.append({
            "source_id": "gsj_seamless_legend",
            "source_ref": url,
            "geology_symbol": rec.get("symbol"),
            "color_r": r_, "color_g": g_, "color_b": b_,
            "color_hex": color_hex,
            "formation_age_ja": rec.get("formationAge_ja"),
            "formation_age_en": rec.get("formationAge_en"),
            "rock_group_ja": rec.get("group_ja"),
            "rock_group_en": rec.get("group_en"),
            "lithology_ja": rec.get("lithology_ja"),
            "lithology_en": rec.get("lithology_en"),
        })
    return rows, url


def build_sagami_grid(step=0.02):
    """既存の nlni_w12_watersheds.geojson (水系名=相模川) の和集合ポリゴン内に
    step度間隔のグリッド点を生成する。このgeojsonは並行エージェント担当の
    国土数値情報W12収集成果物であり、ここでは地点選定のためのポリゴン参照のみに
    read-onlyで利用する（再取得・再登録はしない）。
    """
    from shapely.geometry import shape, Point
    from shapely.ops import unary_union
    import numpy as np

    gj_path = PROC / "nlni_w12_watersheds.geojson"
    d = json.loads(gj_path.read_text(encoding="utf-8"))
    feats = [f for f in d["features"]
             if f["properties"].get("water_system_name_ja_estimated") == "相模川"]
    geoms = [shape(f["geometry"]) for f in feats]
    union = unary_union(geoms)
    minx, miny, maxx, maxy = union.bounds
    xs = np.arange(minx, maxx + step, step)
    ys = np.arange(miny, maxy + step, step)
    pts = []
    for x in xs:
        for y in ys:
            p = Point(x, y)
            if union.contains(p):
                pts.append((round(float(x), 5), round(float(y), 5)))
    return pts, len(feats)


def fetch_points(points):
    rows = []
    raw_path = RAW / "gsj_seamless" / "points_raw.jsonl"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_f = open(raw_path, "w", encoding="utf-8")
    for idx, (lon, lat) in enumerate(points):
        url = f"{API_BASE}/legend.json"
        params = {"point": f"{lat},{lon}"}
        try:
            data = get_json(url, params=params)
        except Exception as e:
            rows.append({
                "source_id": "gsj_geology_points",
                "source_ref": f"{url}?point={lat},{lon}",
                "point_id": idx,
                "lon": lon, "lat": lat,
                "geology_symbol": None, "geology_title_ja": None,
                "formation_age_ja": None, "formation_age_en": None,
                "rock_group_ja": None, "rock_group_en": None,
                "rock_type_ja": None, "rock_type_en": None,
                "color_hex": None, "has_data": 0,
                "notes": f"取得失敗: {e!r}",
            })
            continue
        raw_f.write(json.dumps({"point_id": idx, "lon": lon, "lat": lat,
                                "response": data}, ensure_ascii=False) + "\n")
        # APIは凡例が無い場合でも空オブジェクトではなく全フィールドが空文字の
        # オブジェクト(title=",", value="000000")を返すことがある。
        # symbolが空のものは凡例なしとして扱う（値を推測で埋めない）。
        has_data = bool(data.get("symbol"))
        rows.append({
            "source_id": "gsj_geology_points",
            "source_ref": f"{url}?point={lat},{lon}",
            "point_id": idx,
            "lon": lon, "lat": lat,
            "geology_symbol": data.get("symbol"),
            "geology_title_ja": data.get("title"),
            "formation_age_ja": data.get("formationAge_ja"),
            "formation_age_en": data.get("formationAge_en"),
            "rock_group_ja": data.get("group_ja"),
            "rock_group_en": data.get("group_en"),
            "rock_type_ja": data.get("lithology_ja"),
            "rock_type_en": data.get("lithology_en"),
            "color_hex": data.get("value"),
            "has_data": 1 if has_data else 0,
            "notes": "" if has_data else
                     "凡例なし: APIが空の凡例（symbol等すべて空文字, value=000000）を返却",
        })
        if idx % 20 == 0:
            print(f"  ... {idx+1}/{len(points)} points done")
    raw_f.close()
    return rows


def write_csv_jsonl(name, rows, fieldnames):
    csv_path = PROC / f"{name}.csv"
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for row in rows:
            w.writerow(row)
    print(f"  [write] {csv_path.relative_to(PROC.parent.parent)}  {len(rows)} rows")
    write_jsonl(name, rows)


def main():
    print("=== legend ===")
    legend_rows, legend_url = fetch_legend()
    write_csv_jsonl("gsj_seamless_legend", legend_rows, [
        "source_id", "source_ref", "geology_symbol",
        "color_r", "color_g", "color_b", "color_hex",
        "formation_age_ja", "formation_age_en",
        "rock_group_ja", "rock_group_en",
        "lithology_ja", "lithology_en",
    ])
    register(
        source_id="gsj_seamless_legend",
        name="20万分の1日本シームレス地質図V2 凡例（全凡例）",
        publisher="産業技術総合研究所 地質調査総合センター(GSJ)",
        url=legend_url,
        category="地質",
        access_method="Web API (legend.csv, 全凡例)",
        fmt="csv+jsonl",
        license_=LICENSE,
        redistributable=1,
        record_count=len(legend_rows),
        notes=(f"全凡例{len(legend_rows)}件を取得。地質記号(symbol)がgsj_geology_points."
               "geology_symbolとのJOINキー。csvはタブ区切り(仕様書に明記)。"),
    )

    print("=== points ===")
    points, n_feats = build_sagami_grid(step=0.02)
    print(f"  grid points in Sagami-river watershed polygon: {len(points)}")
    point_rows = fetch_points(points)
    write_csv_jsonl("gsj_geology_points", point_rows, [
        "source_id", "source_ref", "point_id", "lon", "lat",
        "geology_symbol", "geology_title_ja",
        "formation_age_ja", "formation_age_en",
        "rock_group_ja", "rock_group_en",
        "rock_type_ja", "rock_type_en",
        "color_hex", "has_data", "notes",
    ])
    n_with_data = sum(1 for r in point_rows if r["has_data"])
    register(
        source_id="gsj_geology_points",
        name="20万分の1日本シームレス地質図V2 地点別地質判定（相模川流域グリッド）",
        publisher="産業技術総合研究所 地質調査総合センター(GSJ)",
        url=f"{API_BASE}/legend.json?point=<lat>,<lon>",
        category="地質",
        access_method="Web API (legend.json, point指定)",
        fmt="csv+jsonl",
        license_=LICENSE,
        redistributable=1,
        record_count=len(point_rows),
        notes=(
            f"data/processed/nlni_w12_watersheds.geojson"
            f"（他エージェント収集の国土数値情報W12、water_system_name_ja_estimated='相模川'"
            f"に該当する{n_feats}ポリゴンの和集合、read-only参照のみで再取得はしていない）"
            f"の内側に0.02度間隔（約2km)のグリッド点を生成し{len(points)}地点とした。"
            f"多すぎる全国一様グリッドではなく流域ポリゴン内に絞ることで妥当な密度"
            f"（目安50〜300件の指示内で流域形状をカバーできる150件程度）とした。"
            f"うち凡例が存在した(has_data=1)地点は{n_with_data}件、"
            f"残り{len(point_rows)-n_with_data}件はAPIが空の凡例"
            f"（symbol等すべて空文字, value=000000）を返した地点で、"
            f"値は推測で埋めずnullのままとした。"
            "geology_symbolでgsj_seamless_legendとJOIN可能。"
        ),
    )
    print("done.")


if __name__ == "__main__":
    main()
