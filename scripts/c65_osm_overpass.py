"""
OpenStreetMap Overpass API — 神奈川県分の水系/森林/農地/保護区データ取得

収集エージェント契約に従い、カテゴリごとに個別クエリ・個別ファイル・個別source_idで取得する。
Overpass API は共有インフラのため、リクエスト間に明示的な time.sleep(30) を挟む。

出力:
  data/raw/osm_kanagawa/<category>.json        生のOverpass応答
  data/processed/osm_kanagawa_<category>.csv   代表点付き一覧
  data/processed/osm_kanagawa_<category>.jsonl

ライセンス: OSM/Overpassのデータは ODbL 1.0 (Open Database License)。
Share-Alike（同条件での再頒布義務）と帰属表示(attribution)の継承条件がある。
https://www.openstreetmap.org/copyright 参照。
"""
import collections, csv, json, sys, time, pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from common import get, register, write_jsonl, PROC, RAW, now
import regions as rc

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
# 地域別の設定。configure(rid) が1か所で組み立て、定義の後の呼び出しで既定の jp-14 にする
# （jp-14 のパス・source_id・クエリは据え置き）。
REGION = RAW_DIR = None

ODBL_LICENSE = (
    "ODbL 1.0（Share-Alike/帰属表示の継承条件あり、詳細: "
    "https://www.openstreetmap.org/copyright）"
)
ODBL_NOTE = (
    "OSM/Overpassの地物データはOpenDatabaseLicense(ODbL) 1.0に基づき提供される。"
    "要約: (1)帰属表示 - '© OpenStreetMap contributors' の表示が必要。"
    "(2)Share-Alike - このデータから作成した派生データベースを公開する場合は同じ"
    "ODbLまたは互換ライセンスで公開する必要がある。詳細は"
    "https://www.openstreetmap.org/copyright および https://opendatacommons.org/licenses/odbl/1-0/ 参照。"
)

CATEGORIES = {
    "water": {
        "source_id": "osm_kanagawa_water",
        "name": "OSM 神奈川県 水系（水域・河川）",
        "query": """
[out:json][timeout:120];
{AREA_DECL}(
  way["natural"="water"]({AREA});
  relation["natural"="water"]({AREA});
  way["waterway"="river"]({AREA});
  way["waterway"="stream"]({AREA});
);
out tags center;
""",
    },
    "forest": {
        "source_id": "osm_kanagawa_forest",
        "name": "OSM 神奈川県 森林（landuse=forest, natural=wood）",
        "query": """
[out:json][timeout:120];
{AREA_DECL}(
  way["landuse"="forest"]({AREA});
  relation["landuse"="forest"]({AREA});
  way["natural"="wood"]({AREA});
  relation["natural"="wood"]({AREA});
);
out tags center;
""",
    },
    "farmland": {
        "source_id": "osm_kanagawa_farmland",
        "name": "OSM 神奈川県 農地（landuse=farmland, meadow）",
        "query": """
[out:json][timeout:120];
{AREA_DECL}(
  way["landuse"="farmland"]({AREA});
  relation["landuse"="farmland"]({AREA});
  way["landuse"="meadow"]({AREA});
  relation["landuse"="meadow"]({AREA});
);
out tags center;
""",
    },
    "protected_area": {
        "source_id": "osm_kanagawa_protected_area",
        "name": "OSM 神奈川県 保護区（nature_reserve, protected_area）",
        "query": """
[out:json][timeout:120];
{AREA_DECL}(
  node["leisure"="nature_reserve"]({AREA});
  way["leisure"="nature_reserve"]({AREA});
  relation["leisure"="nature_reserve"]({AREA});
  way["boundary"="protected_area"]({AREA});
  relation["boundary"="protected_area"]({AREA});
);
out tags center;
""",
    },
}


def area_clause(rid):
    """(AREA_DECL, AREA)。県全域の地域は ISO3166-2 の area（神奈川はクエリを変えない）。
    県の一部の地域（clip_bbox がある）は bbox を Overpass の (S,W,N,E) で指定する。"""
    bbox = rc.clip_bbox(rid)
    if bbox is None:
        return f'area["ISO3166-2"="JP-{rc.get(rid)["pref_code"]}"]->.a;\n', "area.a"
    x0, y0, x1, y1 = bbox
    return "", f"{y0},{x0},{y1},{x1}"


def render_cfg(cat_key, rid):
    """カテゴリ設定を地域用に組み立てる（source_id・名前・クエリ）。"""
    cfg = CATEGORIES[cat_key]
    decl, area = area_clause(rid)
    return {
        "source_id": rc.name(cfg["source_id"], rid),
        "name": cfg["name"].replace("神奈川県", rc.get(rid)["name_ja"]),
        "query": cfg["query"].format(AREA_DECL=decl, AREA=area),
    }


def configure(rid):
    global REGION, RAW_DIR
    REGION = rid
    RAW_DIR = RAW / rc.name("osm_kanagawa", rid)
    RAW_DIR.mkdir(parents=True, exist_ok=True)


configure("jp-14")


def run_query(cat_key, cfg):
    query = cfg["query"]
    raw_path = RAW_DIR / f"{cat_key}.json"
    print(f"[{now()}] querying Overpass for category={cat_key} ...")
    try:
        r = get(OVERPASS_URL, params={"data": query}, timeout=180, retries=2)
    except Exception as e:
        register(
            source_id=cfg["source_id"], name=cfg["name"], publisher="OpenStreetMap contributors",
            url=OVERPASS_URL, category="osm", access_method="Overpass API",
            fmt="json/csv", license_=ODBL_LICENSE, redistributable=1, record_count=0,
            notes=f"Overpassクエリ失敗: {e!r}. {ODBL_NOTE}",
        )
        return None

    try:
        data = r.json()
    except Exception as e:
        register(
            source_id=cfg["source_id"], name=cfg["name"], publisher="OpenStreetMap contributors",
            url=OVERPASS_URL, category="osm", access_method="Overpass API",
            fmt="json/csv", license_=ODBL_LICENSE, redistributable=1, record_count=0,
            notes=f"Overpass応答のJSON解析失敗: {e!r}. {ODBL_NOTE}",
        )
        return None

    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)

    elements = data.get("elements", [])
    remark = data.get("remark")
    if not elements and remark:
        register(
            source_id=cfg["source_id"], name=cfg["name"], publisher="OpenStreetMap contributors",
            url=OVERPASS_URL, category="osm", access_method="Overpass API",
            fmt="json/csv", license_=ODBL_LICENSE, redistributable=1, record_count=0,
            notes=f"要素0件・Overpassからの注記: {remark}. {ODBL_NOTE}",
        )
        return None

    return elements, raw_path, data.get("osm3s", {}).get("timestamp_osm_base")


def build_rows(cat_key, cfg, elements):
    source_id = cfg["source_id"]
    rows = []
    for el in elements:
        osm_type = el.get("type")
        osm_id = el.get("id")
        tags = el.get("tags", {}) or {}
        name_ja = tags.get("name")
        if "lat" in el and "lon" in el:
            lat, lon = el["lat"], el["lon"]
        elif "center" in el:
            lat, lon = el["center"].get("lat"), el["center"].get("lon")
        else:
            lat, lon = None, None
        rows.append({
            "source_id": source_id,
            "source_ref": f"{osm_type}/{osm_id}",
            "osm_type": osm_type,
            "osm_id": osm_id,
            "name_ja": name_ja,
            "tags_json": json.dumps(tags, ensure_ascii=False),
            "lat": lat,
            "lon": lon,
        })
    return rows


def write_outputs(cat_key, rows):
    out_name = rc.name(f"osm_kanagawa_{cat_key}", REGION)
    csv_path = PROC / f"{out_name}.csv"
    cols = ["source_id", "source_ref", "osm_type", "osm_id", "name_ja", "tags_json", "lat", "lon"]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"  [write] {csv_path.relative_to(csv_path.parents[2])}  {len(rows)} rows")
    write_jsonl(out_name, rows)
    return csv_path


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser()
    rc.add_region_arg(ap)
    configure(ap.parse_args(argv).region)
    keys = list(CATEGORIES.keys())
    for i, cat_key in enumerate(keys):
        cfg = render_cfg(cat_key, REGION)
        result = run_query(cat_key, cfg)
        if result is not None:
            elements, raw_path, osm_ts = result
            rows = build_rows(cat_key, cfg, elements)
            write_outputs(cat_key, rows)
            types = collections.Counter(r["osm_type"] for r in rows)
            notes = (
                f"OSMデータ基準時刻(timestamp_osm_base)={osm_ts}。要素内訳: {dict(types)}。"
                f"代表点座標のみ保存（way/relationはOverpassの'out center'出力=境界ボックス中心であり、"
                f"ポリゴン重心でも面積でもない）。ジオメトリ全体（全頂点）は未保存。"
                f"生データ: data/raw/{RAW_DIR.name}/{raw_path.name}。"
                f"OSMはボランティア編集のため地物の網羅性・タグ付与は地域差があり、"
                f"取得時点のスナップショットであって時系列比較には使えない。"
                + (" " + rc.get(REGION)["osm_extra_notes"][cat_key] if cat_key in rc.get(REGION)["osm_extra_notes"] else "")
                + " " + ODBL_NOTE
            )
            register(
                source_id=cfg["source_id"], name=cfg["name"], publisher="OpenStreetMap contributors",
                url=OVERPASS_URL, category="osm", access_method="Overpass API",
                fmt="json/csv", license_=ODBL_LICENSE, redistributable=1,
                record_count=len(rows), notes=notes,
            )
        if i < len(keys) - 1:
            print(f"[{now()}] sleeping 30s before next category ...")
            time.sleep(30)


if __name__ == "__main__":
    main()
