"""環境省「いきもの地図」(ArcGIS Experience Builder / arc-gis.biodic.go.jp) — 匿名で叩ける
裏側REST APIから、神奈川県相当のbboxで以下2件を取得する。

  1. biodic_veg2024_kanagawa        現存植生図2024(vg2024/MapServer/2, 関東ブロック) のポリゴン
  2. biodic_mammal_mesh_kanagawa    中大型哺乳類分布調査(タヌキ/キツネ/アナグマ, 各FeatureServer/0)
                                    の3次メッシュ分布(ワイド→ロング変換)

旧 gis.biodic.go.jp は廃止済み。後継アプリ(いきもの地図, item 8ba29c091ba04870a8c7e5265fb9fb6c)の
構成JSON (`.../sharing/rest/content/items/<id>/data?f=json`) から実データのREST URL群を辿る。
アプリ自体は access:public / licenseInfo 空欄で、ログイン・APIキー・フォーム同意は一切不要。

673MBのGeoPackage(veg2024bk3.gpkg)はダウンロードしない — 同じ vg2024 データがこのRESTで
取れるうえ、本環境に geopandas が無い(shapelyのみ)ため。

CSVの行108(自然環境調査Web-GIS)・110(1/25,000植生図GISデータ)・111(自然環境保全基礎調査 植生調査)・
113(自然環境保全基礎調査 動物分布調査)・115(生物多様性センター基盤情報データリスト) をまとめてカバーする。

=====================================================================================
【重要: 実行保留中 (2026-08-30)】
本スクリプトは書いた時点では実行していない。理由:

`scripts/common.py` の get/get_json/download が全リクエストに付与する User-Agent には
個人の氏名・私用と思われるメールアドレス (contact: yuki.kawabe@code4japan.org) が含まれている。
`docs/COLLECTOR_CONTRACT.md` の「【2026-08-29 追記】既に発生した違反と、その帰結」2. および
`docs/nextstep.md` (同日付) はこれを「未対応・要確認」とし、明記している:

    次に収集スクリプトを実行する前に、当該個人の承諾を確認すること。承諾が無い場合は
    UAから個人名・個人アドレスを外し、組織の代表連絡先に差し替えてから実行する。

この承諾確認は今回のタスク範囲外で完了できず、`scripts/common.py` の改変も別途の作業分担
(このスクリプト1ファイルの範囲外)。よって、本スクリプトの実データ収集(get/get_json経由の
本番リクエスト)は意図的に実行していない。フィールド定義・件数・座標系などの下調べのみ、
このスクリプトの外で、個人を特定しない汎用UAでの少数の読み取り専用リクエストによって別途
確認済み(下記の値は実測に基づく)。

→ 上記の承諾確認 or UA差し替えが完了し次第、
   `cd /home/yu23ki14/cfj/ryuiki-demo && .venv/bin/python scripts/c80_biodic_ikimonomap.py`
   を実行すればよい(冪等: 既存のraw JSONは再利用される)。
=====================================================================================
"""
import csv
import json
import math
import re
import sys
import time
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from common import get_json, register, write_jsonl, to_fiscal_year, PROC, RAW, now

from shapely.geometry import shape, mapping
from shapely.ops import transform as shp_transform

# ---------------------------------------------------------------------------
# 定数
# ---------------------------------------------------------------------------

RAW_DIR = RAW / "biodic_ikimonomap"
RAW_DIR.mkdir(parents=True, exist_ok=True)

APP_ITEM_ID = "8ba29c091ba04870a8c7e5265fb9fb6c"
APP_CONFIG_URL = (
    f"https://pl-moej.gisservice.jp/arcgis/sharing/rest/content/items/{APP_ITEM_ID}/data"
)
APP_ITEM_URL = f"https://pl-moej.gisservice.jp/arcgis/sharing/rest/content/items/{APP_ITEM_ID}"
APP_PUBLIC_URL = (
    f"https://pl-moej.gisservice.jp/arcgis/apps/experiencebuilder/experience?id={APP_ITEM_ID}"
)

SERVICES_BASE = "https://arc-gis.biodic.go.jp/arcgis/rest/services/webgis"
VG2024_LAYER_URL = f"{SERVICES_BASE}/vg2024/MapServer/2"  # 関東ブロック(実測で確認)

MAMMAL_LAYERS = {
    "tanuki": f"{SERVICES_BASE}/tanuki/FeatureServer/0",
    "kitune": f"{SERVICES_BASE}/kitune/FeatureServer/0",
    "anaguma": f"{SERVICES_BASE}/anaguma/FeatureServer/0",
}
MAMMAL_JA = {"tanuki": "タヌキ", "kitune": "キツネ", "anaguma": "アナグマ"}

# 神奈川県を覆うbbox(県境を含むよう余裕をもたせた)。lon_min, lat_min, lon_max, lat_max
KANAGAWA_BBOX = (138.9, 35.1, 139.8, 35.7)

PAGE_SIZE = 1000  # 各レイヤの maxRecordCount=2000 より小さくして安全側に

LICENSE_TEXT = (
    "生物多様性センターウェブサイト利用規約"
    "（www.biodic.go.jp と同一の環境省生物多様性センターが公開するWebGISであり、"
    "既存収集分(biodic_vegmesh_4th_kanagawa 等)と同じ利用規約が適用されると判断)。"
    "ただし『いきもの地図』のWebMapアイテム自体は ArcGIS Online 上で "
    "access: public / licenseInfo: 空欄 だったことを実測で確認しており(2026-08-30)、"
    "明示的な二次利用許諾条項がアプリ側に記載されているわけではない点に注意。"
)

# 現存植生図の凡例フィールドで実測確認できたフィールド名(vg2024/MapServer/2 ?f=json)
VG_EXPECTED_FIELDS = {
    "凡例コード", "凡例名", "植生自然度", "植生自然度区分", "植生区分", "作成年度", "地域ブロック",
}

# 哺乳類メッシュ層で「年別確認フラグではない」既知フィールド(実測: 130フィールド中10個)
MAMMAL_NONFLAG_FIELDS = {
    "objectid", "name", "descriptio", "pref1", "pref2", "pref3",
    "hikaku", "hikaku_txt", "Shape__Area", "Shape__Length",
}

YEAR_SUFFIX_RE = re.compile(r"(20\d{2})$")


# ---------------------------------------------------------------------------
# 共通ヘルパ
# ---------------------------------------------------------------------------

def _cached_json(cache_path: pathlib.Path, fetch_fn):
    """cache_path に既存ファイルがあれば読み込んで返す(冪等)。無ければ fetch_fn() を呼んで保存。"""
    if cache_path.exists() and cache_path.stat().st_size > 0:
        return json.loads(cache_path.read_text(encoding="utf-8"))
    data = fetch_fn()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


def fetch_all_features(layer_url, bbox, out_fields="*", page_size=PAGE_SIZE, page_cache_dir=None):
    """resultOffset によるページング取得。exceededTransferLimit は打ち切り判定に使わず、
    返却件数が page_size 未満になるまでページを回し続ける。各ページはキャッシュして冪等にする。
    """
    lon_min, lat_min, lon_max, lat_max = bbox
    offset = 0
    all_features = []
    page_no = 0
    while True:
        params = {
            "where": "1=1",
            "outFields": out_fields,
            "geometry": f"{lon_min},{lat_min},{lon_max},{lat_max}",
            "geometryType": "esriGeometryEnvelope",
            "inSR": 4326,
            "spatialRel": "esriSpatialRelIntersects",
            "resultOffset": offset,
            "resultRecordCount": page_size,
            "f": "geojson",
        }

        def _do_fetch(url=layer_url, p=dict(params)):
            return get_json(f"{url}/query", params=p)

        if page_cache_dir is not None:
            cache_path = page_cache_dir / f"page_{page_no:04d}.json"
            data = _cached_json(cache_path, _do_fetch)
        else:
            data = _do_fetch()

        feats = data.get("features", [])
        all_features.extend(feats)
        print(f"    [page {page_no}] offset={offset} -> {len(feats)}件 (累計 {len(all_features)})")
        page_no += 1
        if len(feats) < page_size:
            break
        offset += page_size
    return all_features


def get_count(layer_url, bbox):
    lon_min, lat_min, lon_max, lat_max = bbox
    params = {
        "where": "1=1",
        "geometry": f"{lon_min},{lat_min},{lon_max},{lat_max}",
        "geometryType": "esriGeometryEnvelope",
        "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
        "returnCountOnly": "true",
        "f": "json",
    }
    data = get_json(f"{layer_url}/query", params=params)
    return data.get("count")


def project_to_meters(geom):
    """緯度経度(度)のshapely geometryを、簡易メートル換算で近似投影する。
    緯度1度≒111,320m、経度1度≒111,320*cos(緯度) という定数近似(日本付近専用、簡易)。
    参照緯度はポリゴン自身の重心緯度を使う(県全体で1つの参照緯度を使うよりは誤差が小さい)。
    厳密な測地計算(測地線面積など)ではないので、面積の桁・大小比較用と割り切ること。
    """
    ref_lat = geom.centroid.y

    def _fn(x, y, z=None):
        return (x * 111_320.0 * math.cos(math.radians(ref_lat)), y * 111_320.0)

    return shp_transform(_fn, geom), ref_lat


def simplify_to_budget(geoms, budget_bytes, start_tol=0.0001, max_tol=0.02):
    """出力CSV全体がおおむね budget_bytes 以内に収まるまで、shapely simplify の
    toleranceを倍々に上げながら間引く。preserve_topology=Trueでポリゴンの自己交差を避ける。
    返り値: (採用したtolerance, 各geomのgeojson文字列リスト, 推定合計バイト数)
    """
    tol = start_tol
    last = None
    while True:
        gj_list = []
        total = 0
        for g in geoms:
            sg = g.simplify(tol, preserve_topology=True)
            gj = json.dumps(mapping(sg), ensure_ascii=False, separators=(",", ":"))
            gj_list.append(gj)
            total += len(gj)
        last = (tol, gj_list, total)
        if total <= budget_bytes or tol >= max_tol:
            return last
        tol *= 2


# ---------------------------------------------------------------------------
# Step 1: アプリ構成JSON → services.json
# ---------------------------------------------------------------------------

def step1_services():
    print("[1] アプリ構成JSON取得")
    app_config_path = RAW_DIR / "app_config.json"
    app_config = _cached_json(app_config_path, lambda: get_json(APP_CONFIG_URL, params={"f": "json"}))

    app_item_path = RAW_DIR / "app_item.json"
    app_item = _cached_json(app_item_path, lambda: get_json(APP_ITEM_URL, params={"f": "json"}))

    entries = []

    def walk(node, path):
        for key, v in node.items():
            label = v.get("sourceLabel")
            entries.append({
                "key": key,
                "type": v.get("type"),
                "label": label,
                "url": v.get("url"),
                "item_id": v.get("itemId"),
                "path_ja": " > ".join([p for p in path + [label] if p]),
            })
            child = v.get("childDataSourceJsons")
            if child:
                walk(child, path + [label])

    web_map_ds = None
    for ds in app_config.get("dataSources", {}).values():
        if ds.get("type") == "WEB_MAP" and ds.get("childDataSourceJsons"):
            web_map_ds = ds
            break
    if web_map_ds:
        walk(web_map_ds.get("childDataSourceJsons", {}), [])

    root_services = sorted({
        m.group(1) for e in entries if e["url"]
        for m in [re.match(r"(.*/(MapServer|FeatureServer))", e["url"])]
        if m
    })

    services_out = {
        "app_item_id": APP_ITEM_ID,
        "app_title": app_item.get("title"),
        "app_access": app_item.get("access"),
        "app_license_info": app_item.get("licenseInfo"),
        "app_public_url": APP_PUBLIC_URL,
        "fetched_at": now(),
        "n_layer_tree_entries": len(entries),
        "n_root_services": len(root_services),
        "root_services": root_services,
        "layer_tree": entries,
    }
    services_path = RAW_DIR / "services.json"
    services_path.write_text(json.dumps(services_out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  [write] {services_path.relative_to(RAW.parent.parent)}  "
          f"{len(entries)} tree entries / {len(root_services)} root services")
    return services_out


# ---------------------------------------------------------------------------
# Step 2-4: 現存植生図2024 (biodic_veg2024_kanagawa)
# ---------------------------------------------------------------------------

VEG_CSV_FIELDS = [
    "feature_id", "legend_code", "legend_name_ja", "veg_division_ja", "naturalness",
    "naturalness_class_ja", "survey_year", "survey_year_raw", "block_ja", "area_m2",
    "centroid_lat", "centroid_lon", "geometry_geojson", "source_id", "source_ref",
]


def step_veg2024():
    print("[2] 現存植生図2024 (vg2024/MapServer/2, 関東ブロック)")
    source_id = "biodic_veg2024_kanagawa"

    layer_def_path = RAW_DIR / "vg2024_layer2_def.json"
    layer_def = _cached_json(layer_def_path, lambda: get_json(VG2024_LAYER_URL, params={"f": "json"}))
    field_names = {f["name"] for f in layer_def.get("fields", [])}
    missing = VG_EXPECTED_FIELDS - field_names
    if missing:
        raise RuntimeError(
            f"vg2024 layer2: 期待していたフィールドが実レスポンスに無い: {missing}. "
            f"実際のフィールド: {sorted(field_names)}"
        )
    print(f"  レイヤ名={layer_def.get('name')!r} geometryType={layer_def.get('geometryType')} "
          f"maxRecordCount={layer_def.get('maxRecordCount')}")

    expected_count = get_count(VG2024_LAYER_URL, KANAGAWA_BBOX)
    print(f"  bbox内件数(returnCountOnly)= {expected_count}")

    page_cache_dir = RAW_DIR / "vg2024_pages"
    features = fetch_all_features(VG2024_LAYER_URL, KANAGAWA_BBOX, out_fields="*",
                                   page_cache_dir=page_cache_dir)
    print(f"  取得 {len(features)}件 (期待値 {expected_count})")
    if expected_count is not None and len(features) != expected_count:
        print(f"  [WARN] 取得件数が returnCountOnly と一致しない: {len(features)} vs {expected_count}")

    # 面積・重心はオリジナル(簡略化前)ジオメトリで計算する
    shapely_geoms = []
    attrs_list = []
    skipped_no_geom = 0
    for feat in features:
        geom_json = feat.get("geometry")
        if not geom_json:
            skipped_no_geom += 1
            continue
        g = shape(geom_json)
        shapely_geoms.append(g)
        attrs_list.append(feat.get("properties", {}))
    if skipped_no_geom:
        print(f"  [WARN] geometry が無いフィーチャを {skipped_no_geom} 件スキップ")

    centroids = [(g.centroid.y, g.centroid.x) for g in shapely_geoms]
    areas_m2 = []
    for g in shapely_geoms:
        proj, ref_lat = project_to_meters(g)
        areas_m2.append(proj.area)

    budget_bytes = 55 * 1024 * 1024  # 60MB目標に対して余裕を見て55MB
    tol, geojson_strs, total_geom_bytes = simplify_to_budget(shapely_geoms, budget_bytes)
    print(f"  simplify tolerance = {tol} 度で geometry_geojson 合計 ≈ {total_geom_bytes/1e6:.1f}MB")

    rows = []
    for attrs, (clat, clon), area_m2, geom_str in zip(attrs_list, centroids, areas_m2, geojson_strs):
        survey_year_raw = attrs.get("作成年度")
        rows.append({
            "feature_id": attrs.get("objectid"),
            "legend_code": attrs.get("凡例コード"),
            "legend_name_ja": attrs.get("凡例名"),
            "veg_division_ja": attrs.get("植生区分"),
            "naturalness": attrs.get("植生自然度"),
            "naturalness_class_ja": attrs.get("植生自然度区分"),
            "survey_year": to_fiscal_year(survey_year_raw),
            "survey_year_raw": survey_year_raw,
            "block_ja": attrs.get("地域ブロック"),
            "area_m2": round(area_m2, 1) if area_m2 is not None else None,
            "centroid_lat": round(clat, 6),
            "centroid_lon": round(clon, 6),
            "geometry_geojson": geom_str,
            "source_id": source_id,
            "source_ref": f"{VG2024_LAYER_URL} objectid={attrs.get('objectid')}",
        })

    csv_path = PROC / f"{source_id}.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=VEG_CSV_FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    csv_size_mb = csv_path.stat().st_size / 1e6
    print(f"  [write] {csv_path}  {len(rows)} rows  ({csv_size_mb:.1f}MB)")
    write_jsonl(source_id, rows)

    register(
        source_id=source_id,
        name="現存植生図2024(いきもの地図/vg2024, 関東ブロック・神奈川県相当bbox抽出)",
        publisher="環境省生物多様性センター",
        url=APP_PUBLIC_URL,
        category="自然環境保全基礎調査(植生)",
        access_method=(
            f"ArcGIS REST API 匿名アクセス({VG2024_LAYER_URL}/query, f=geojson)。"
            f"lon/lat bbox({KANAGAWA_BBOX}) と esriSpatialRelIntersects でページング取得"
            f"(resultOffset, page_size={PAGE_SIZE})。exceededTransferLimitはページ打ち切り判定に使わず、"
            "返却件数がpage_size未満になるまで継続。"
        ),
        fmt="ArcGIS REST(GeoJSON) -> CSV/JSONL(UTF-8)",
        license_=LICENSE_TEXT,
        redistributable=1,
        record_count=len(rows),
        notes=(
            f"bbox {KANAGAWA_BBOX}(lon_min,lat_min,lon_max,lat_max)で vg2024/MapServer/2"
            f"(関東ブロック)を検索。returnCountOnly={expected_count}件に対し実取得{len(features)}件"
            f"(geometry欠損スキップ{skipped_no_geom}件)。"
            "『地域ブロック』フィールドの値(例:'3')はアプリの8分割レイヤID(0=北海道..7=九州沖縄)とは"
            "対応していない可能性がある(layer2=関東で取得したのに地域ブロック='3'の行が多数を占めた実測結果あり)。"
            "値をそのまま保持しレイヤIDとの対応付けはしていない。"
            "作成年度(survey_year/survey_year_raw)は個々のポリゴンの実測年で、"
            "サービス名の『2024』は最新統合版のリリース名であり全ポリゴンの作成年ではない"
            "(実測で2007〜2009年などが混在するのを確認)。"
            f"area_m2 と centroid_lat/lon は shapely で計算した近似値: "
            "緯度1度≒111,320m・経度1度≒111,320*cos(緯度)の簡易メートル換算(測地線計算ではない)。"
            "参照緯度は各ポリゴン自身の重心緯度を使用。県全体一律の参照緯度より誤差は小さいはずだが、"
            "正確な面積が必要な用途にはこの値を使わないこと。"
            f"geometry_geojsonはD1格納サイズの都合でshapely.simplify(tolerance={tol}, "
            "preserve_topology=True)により間引いている(頂点数を削減、面積/重心は簡略化前の元ジオメトリで計算済み"
            "なのでarea_m2/centroidとgeometry_geojsonの形状は完全には整合しない場合がある)。"
            "673MBのGeoPackage(veg2024bk3.gpkg)は未取得(このRESTで代替、geopandas未導入のため)。"
        ),
    )
    return len(rows)


# ---------------------------------------------------------------------------
# Step 3-4: 中大型哺乳類メッシュ分布 (biodic_mammal_mesh_kanagawa)
# ---------------------------------------------------------------------------

MAMMAL_CSV_FIELDS = [
    "mesh_code", "species", "species_ja", "survey_label", "survey_year", "confirmed",
    "lat", "lon", "source_id", "source_ref",
]


def parse_flag_value(v):
    if v is None:
        return None
    s = str(v).strip()
    if s == "0":
        return 0
    if s == "1":
        return 1
    return None


def step_mammals():
    print("[3] 中大型哺乳類分布調査(タヌキ/キツネ/アナグマ)")
    source_id = "biodic_mammal_mesh_kanagawa"

    all_rows = []
    per_species_counts = {}
    anomalous_values = set()
    truncated_field_note = None

    for species, layer_url in MAMMAL_LAYERS.items():
        species_ja = MAMMAL_JA[species]
        print(f"  --- {species} ({species_ja}) ---")

        layer_def_path = RAW_DIR / f"{species}_layer0_def.json"
        layer_def = _cached_json(layer_def_path, lambda url=layer_url: get_json(url, params={"f": "json"}))
        fields = layer_def.get("fields", [])
        print(f"  レイヤ名={layer_def.get('name')!r} フィールド数={len(fields)}")

        flag_fields = [
            f["name"] for f in fields
            if f.get("type") == "esriFieldTypeString" and f["name"] not in MAMMAL_NONFLAG_FIELDS
        ]
        if not flag_fields:
            raise RuntimeError(f"{species}: 年別確認フラグ列を検出できなかった。フィールド定義を確認すること: {fields}")

        # <species>2022 相当の単年フラグ列は、anaguma だけ Esriの10文字フィールド名制限で
        # "anaguma202" に切り詰められている(tanuki2022/kitune2022と同じ位置・同じ意味と推測されるが、
        # メタデータ上は確認できないため year は自動抽出せず null のままにする。下記notesに残す)。
        if species == "anaguma" and "anaguma202" in flag_fields:
            truncated_field_note = (
                "anaguma層の単年確認フラグ列は 'anaguma202' という名前で、tanuki2022/kitune2022と"
                "同じ構造上の位置にある(10文字フィールド名制限で 'anaguma2022' が切り詰められたと推測)。"
                "ただし確証がないため survey_year は自動推定せず null のままにしてある"
                "(survey_labelには生の列名'anaguma202'をそのまま残した)。"
            )

        expected_count = get_count(layer_url, KANAGAWA_BBOX)
        page_cache_dir = RAW_DIR / f"{species}_pages"
        features = fetch_all_features(layer_url, KANAGAWA_BBOX, out_fields="*",
                                       page_cache_dir=page_cache_dir)
        print(f"  取得 {len(features)}件 (returnCountOnly={expected_count})")
        if expected_count is not None and len(features) != expected_count:
            print(f"  [WARN] 取得件数不一致: {len(features)} vs {expected_count}")

        n_rows_this_species = 0
        for feat in features:
            attrs = feat.get("properties", {})
            geom_json = feat.get("geometry")
            mesh_code = attrs.get("name")
            objectid = attrs.get("objectid")
            if geom_json:
                g = shape(geom_json)
                lat, lon = round(g.centroid.y, 6), round(g.centroid.x, 6)
            else:
                lat = lon = None
            for field_name in flag_fields:
                m = YEAR_SUFFIX_RE.search(field_name)
                survey_year = int(m.group(1)) if m else None
                raw_v = attrs.get(field_name)
                confirmed = parse_flag_value(raw_v)
                if confirmed is None and raw_v not in (None, "", " "):
                    anomalous_values.add(str(raw_v))
                all_rows.append({
                    "mesh_code": mesh_code,
                    "species": species,
                    "species_ja": species_ja,
                    "survey_label": field_name,
                    "survey_year": survey_year,
                    "confirmed": confirmed,
                    "lat": lat,
                    "lon": lon,
                    "source_id": source_id,
                    "source_ref": f"{layer_url} objectid={objectid}",
                })
                n_rows_this_species += 1
        per_species_counts[species] = {"n_mesh": len(features), "n_rows": n_rows_this_species,
                                        "n_flag_fields": len(flag_fields)}

    csv_path = PROC / f"{source_id}.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=MAMMAL_CSV_FIELDS)
        w.writeheader()
        for r in all_rows:
            w.writerow(r)
    csv_size_mb = csv_path.stat().st_size / 1e6
    print(f"  [write] {csv_path}  {len(all_rows)} rows  ({csv_size_mb:.1f}MB)")
    write_jsonl(source_id, all_rows)

    notes = (
        f"bbox {KANAGAWA_BBOX} でタヌキ/キツネ/アナグマ各FeatureServer/0を検索し、"
        f"メッシュ単位×年別・情報源別の確認フラグ列(1メッシュあたり実測120列)をワイド→ロング変換した。"
        f"種別内訳: " + ", ".join(
            f"{sp}: メッシュ{c['n_mesh']}件×フラグ列{c['n_flag_fields']}列={c['n_rows']}行"
            for sp, c in per_species_counts.items()
        ) + "。"
        "フラグ列は実測で2系統ある: "
        "(a) 年が無いもの(dai2kai=第2回調査, dai6kai=第6回調査, および無年次の wis/mizu/kuni/city/pro/"
        "pref/douro/bunken/sonota) — survey_yearはnull。"
        "(b) 各カテゴリ(wis/mizu/kuni/city/pro/pref/douro/bunken/sonota)×2010〜2021年度、"
        "および種別単年フラグ(tanuki2022/kitune2022) — survey_labelの末尾4桁(20xx)から抽出。"
        "wis/mizu/kuni/city/pro/pref/douro/bunken/sonota という列名の正確な意味"
        "(情報源の種別と推測されるが、目撃/水系/国道/市道/都道府県道/道路/文献/その他 等の対応関係は"
        "レイヤ定義のalias・domainに説明が無く未確認)は原文の列名(survey_label)をそのまま残すことで"
        "担保し、このスクリプトでは意味の翻訳・要約はしていない。"
        + (f" {truncated_field_note}" if truncated_field_note else "")
        + (f" confirmedへの変換で '0'/'1' 以外の値が見つかった: {sorted(anomalous_values)} (nullにした)。"
           if anomalous_values else " confirmedは全件 '0'/'1' の二値で、それ以外の値は無かった。")
        + " descriptio/pref1/pref2/pref3/hikaku/hikaku_txt/Shape__Area/Shape__Length の各列は"
          "本CSVのスキーマに含めていないが、生レスポンス(data/raw/biodic_ikimonomap/<species>_pages/)"
          "には残っている。特にhikaku_txt(比較結果の説明文, 例:'第6回調査と2018〜2021年度報告調査で"
          "生息あり')は経年比較の文脈として有用なので、必要なら生JSONを直接参照すること。"
    )

    register(
        source_id=source_id,
        name="中大型哺乳類分布調査(タヌキ・キツネ・アナグマ, いきもの地図/神奈川県相当bbox・3次メッシュ)",
        publisher="環境省生物多様性センター",
        url=APP_PUBLIC_URL,
        category="自然環境保全基礎調査(動物分布)",
        access_method=(
            "ArcGIS REST API 匿名アクセス(tanuki/kitune/anaguma 各 FeatureServer/0, f=geojson)。"
            f"lon/lat bbox({KANAGAWA_BBOX})でページング取得(resultOffset, page_size={PAGE_SIZE})。"
            "ワイド(1メッシュ1行×約120フラグ列)→ロング(1行=1メッシュ×1survey_label)に変換。"
        ),
        fmt="ArcGIS REST(GeoJSON) -> CSV/JSONL(UTF-8)",
        license_=LICENSE_TEXT,
        redistributable=1,
        record_count=len(all_rows),
        notes=notes,
    )
    return len(all_rows)


# ---------------------------------------------------------------------------
def main():
    t0 = time.time()
    step1_services()
    n_veg = step_veg2024()
    n_mammal = step_mammals()
    print(f"完了: biodic_veg2024_kanagawa={n_veg}行, biodic_mammal_mesh_kanagawa={n_mammal}行 "
          f"({time.time()-t0:.1f}s)")


if __name__ == "__main__":
    main()
