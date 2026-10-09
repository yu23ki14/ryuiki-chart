"""国土数値情報 C23 海岸線（平成18/2006年版 C23-06）→ GeoJSON/CSV/JSONL

神奈川県（14）と鹿児島県（46）の zip を取り、`data/processed/nlni_c23_coastline.geojson` にまとめる。
zone（Ridge to Reef）の「海岸までの距離」の基準になる線で、c68（標高・起伏量・海岸距離）が読む。
設計: docs/plans/AMAMI_STEP0.md §3・§6-A。

- 神奈川（14）は全線（597 本）。
- 鹿児島（46）は奄美大島とその周辺の 5 市町村の線だけ（行政区域コード C23_001 で絞る）。
  県全体は 7,227 本あり、大半は本土側で zone に要らない。
- 許諾は「非商用」（W05 等と同じ扱い。nlni_lib.LICENSE_NONCOM）。

使い方: `.venv/bin/python3 scripts/c36_nlni_c23_coastline.py [--no-register]`
  --no-register: 原本 ryuiki.sqlite の source_registry に登録しない（手元の確認用）。
zip は data/raw/nlni_c23_coastline/ にキャッシュし、あれば取り直さない。
"""
import argparse
import pathlib
import sys
import zipfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from regions import REGIONS
from common import RAW, register, write_jsonl, download
from nlni_lib import read_shp, geod_length_km, write_geojson, write_csv, LICENSE_NONCOM
from shapely.geometry import shape as shp_shape

SID = "nlni_c23_coastline"
PAGE = "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-C23.html"
ZIP_URL = "https://nlftp.mlit.go.jp/ksj/gml/data/C23/C23-06/C23-06_{pref}_GML.zip"
BASE = RAW / SID
PREF_NAME = {"14": "神奈川県", "46": "鹿児島県"}

# 鹿児島県のうち奄美大島とその周辺の市町村（C23_001 行政区域コード。2006 年時点）。
KAGOSHIMA_AMAMI_CODES = REGIONS["jp-46"]["muni_codes"]
# 県 → 取る行政区域コード（None は全線）
PREF_CODES = {"14": None, "46": KAGOSHIMA_AMAMI_CODES}


def select(admin_code, codes):
    """行政区域コードが対象か（codes が None なら全線）。"""
    return codes is None or str(admin_code) in codes


def fetch_pref(pref):
    zp = BASE / f"C23-06_{pref}_GML.zip"
    download(ZIP_URL.format(pref=pref), zp)
    out = BASE / f"C23-06_{pref}"
    shp = out / f"C23-06_{pref}-g_Coastline.shp"
    if not shp.exists():
        out.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zp) as z:
            for n in z.namelist():
                # zip 内のパス区切りを取り除いて out 直下に置く（zip-slip 防止）
                name = pathlib.PurePosixPath(n).name
                if name:
                    (out / name).write_bytes(z.read(n))
    return shp


def features_of(pref, shp, codes):
    r, fields, recs, enc = read_shp(shp)
    print(f"C23 {pref}: {len(recs)} features {fields} enc={enc}")
    feats, rows = [], []
    for i, (sh, rc) in enumerate(zip(r.shapes(), recs)):
        d = dict(zip(fields, rc))
        if not select(d["C23_001"], codes):
            continue
        gj = sh.__geo_interface__
        g = shp_shape(gj)
        props = {
            "source_id": SID,
            "source_ref": f"{ZIP_URL.format(pref=pref)}#C23-06_{pref}-g_Coastline:{i}",
            "admin_code": str(d["C23_001"]),
            "c23_002": d["C23_002"], "c23_003": d["C23_003"], "c23_004": d["C23_004"],
            "c23_005": d["C23_005"], "c23_006": d["C23_006"], "c23_007": str(d["C23_007"]),
            "length_km": geod_length_km(g),
            "data_year": 2006,
            "prefecture_code": pref,
            "prefecture_name_ja": PREF_NAME[pref],
        }
        feats.append({"type": "Feature", "geometry": gj, "properties": props})
        rows.append(props)
    print(f"  -> 取り込み {len(rows)} 本（pref={pref}, codes={'全線' if codes is None else ','.join(codes)}）")
    return feats, rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-register", action="store_true", help="source_registry に登録しない")
    args = ap.parse_args()

    feats, rows = [], []
    for pref, codes in PREF_CODES.items():
        f, r = features_of(pref, fetch_pref(pref), codes)
        feats += f
        rows += r
    write_geojson(SID, feats, crs_note="原データ座標系 JGD2000/(B,L)。WGS84(EPSG:4326)として出力。")
    write_csv(SID, rows)
    write_jsonl(SID, rows)
    if args.no_register:
        return
    register(SID, "国土数値情報 海岸線（神奈川県・鹿児島県奄美周辺）",
             "国土交通省 国土数値情報ダウンロードサイト", PAGE, "gis_coast",
             "http_zip_shapefile", "geojson+csv+jsonl", LICENSE_NONCOM, 1, len(rows),
             "C23-06（平成18/2006年）神奈川県(14)の全線と、鹿児島県(46)のうち奄美大島周辺の5市町村"
             f"（行政区域コード {','.join(KAGOSHIMA_AMAMI_CODES)}）の線。zone の海岸距離の基準（c68）。"
             "ダウンロードページの使用許諾条件は「非商用」。")


if __name__ == "__main__":
    main()
