"""相模川水系(水系コード830307) 河川GeoJSON — geoshape.ex.nii.ac.jp (NII再パッケージ版)
https://geoshape.ex.nii.ac.jp/river/resource/830307/stream.json

国土数値情報(MLIT) W05「河川」を、国立情報学研究所(NII)が水系単位に再パッケージしたGeoJSON。
1547 features (LineString)。既存の `nlni_w05_rivers`(source_registry) は神奈川県(都道府県コード14)
単位でKSJから直接取得したもので、相模川水系分(water_system_code=830307)は712行に限られる。
本データは水系単位のため、相模川の水源である山梨県側の桂川上流部を含む流域全体が入る。

properties の実キー(レスポンスを実際に取得して確認)は W05_001〜W05_010 のみで、
既存 nlni_w05_rivers の元シェープファイル属性(W05_001〜W05_010)と一致する
(先頭2件のnode_ref・river_name等がnlni_w05_riversの処理結果と完全一致することを確認済み)。
祖先データの都道府県コードを直接持つ属性は無いが、河川端点参照(W05_007〜010, 例:"#gb03_1400010")の
7桁数値の先頭2桁が都道府県コード(14=神奈川県 / 19=山梨県)になっており、これは
既存nlni_w05_riversのnode_ref出力（同じ"#gb03_14xxxxx"形式）と突き合わせて確認した規則性。
ジオコーディング等の推測ではなく、原データ内に埋め込まれたコードを読み取っているだけの点に注意。

このスクリプトでは既存nlni_w05_riversとの重複除去は行わない(ローダー側の仕事)。
"""
import sys, csv, json, math, re, pathlib
sys.path.insert(0, "scripts")
from common import download, register, write_jsonl, PROC, RAW

from shapely.geometry import shape as shp_shape, mapping as shp_mapping

URL = "https://geoshape.ex.nii.ac.jp/river/resource/830307/stream.json"
SID = "geoshape_sagami_river"
WATER_SYSTEM_CODE = "830307"
WATER_SYSTEM_NAME_JA = "相模川"

# 国土数値情報 W05 属性コード表 (c31_nlni_w05.py の SECTION 定義と同一。既存スクリプトは変更せずコピーして使う)
SECTION = {"1": "1級直轄区間", "2": "1級指定区間", "3": "2級河川区間", "4": "指定区間外",
           "5": "1級直轄区間でかつ湖沼区間を兼ねる", "6": "1級指定区間でかつ湖沼区間を兼ねる",
           "7": "2級河川区間でかつ湖沼区間を兼ねる", "8": "指定区間外でかつ湖沼区間を兼ねる",
           "0": "不明"}

PREF_CODE_JA = {"14": "神奈川県", "19": "山梨県"}

SIMPLIFY_TOLERANCE_DEG = 0.00001  # 約1.1m (緯度35度付近)。shapely.simplify(preserve_topology=True)。

# コードリスト(既存c31_nlni_w05.py実行時にキャッシュ済みのHTML。読み取り専用で流用)
CODELIST_DIR = RAW / "nlni_codelists"


def parse_codelist_html(path, code_re=r"\d+"):
    """既存 nlni_lib.parse_codelist_html と同じロジック(コードリスト表 -> {code: 名称})。
    既存ファイルを import して使うと `scripts/nlni_lib.py` への暗黙依存が増えるため、
    ここでは同じロジックを独立実装する(既存スクリプト/ライブラリは変更しない)。
    """
    import html
    if not path.exists():
        return {}
    h = path.read_text(encoding="utf-8")
    out = {}
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", h, re.S):
        c = [html.unescape(re.sub(r"\s+", "", re.sub(r"<[^>]+>", "", x)))
             for x in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)]
        if len(c) >= 2 and re.fullmatch(code_re, c[0]):
            out[c[0]] = c[1]
    return out


def approx_length_m(coords):
    """shapelyのLineString座標列から概算長を求める(測地線計算はしない近似)。
    緯度1度 ≒ 111,320m、経度1度 ≒ 111,320 * cos(緯度) で各区間を平面近似し積算する。
    """
    total = 0.0
    for (lon1, lat1), (lon2, lat2) in zip(coords, coords[1:]):
        dlat_m = (lat2 - lat1) * 111_320.0
        mean_lat = math.radians((lat1 + lat2) / 2.0)
        dlon_m = (lon2 - lon1) * 111_320.0 * math.cos(mean_lat)
        total += math.hypot(dlat_m, dlon_m)
    return total


NODE_RE = re.compile(r"^#gb\d+_(\d{2})\d+$")


def node_pref_code(ref):
    if not ref:
        return None
    m = NODE_RE.match(str(ref))
    return m.group(1) if m else None


def derive_prefecture(props):
    """W05_007〜010 (河川端点参照) の先頭2桁(都道府県コード)を集めて判定する。
    1種類のみなら単一県、複数なら県境をまたぐ区間として "/" 区切りで両方残す。
    """
    codes = set()
    for k in ("W05_007", "W05_008", "W05_009", "W05_010"):
        c = node_pref_code(props.get(k))
        if c:
            codes.add(c)
    if not codes:
        return None, None
    codes_sorted = sorted(codes)
    code_raw = "/".join(codes_sorted)
    names = [PREF_CODE_JA.get(c, c) for c in codes_sorted]
    return code_raw, "/".join(names)


def main():
    raw_path = RAW / "geoshape_sagami_river" / "stream.json"
    print(f"[fetch] {URL} -> {raw_path}")
    download(URL, raw_path)
    fc = json.loads(raw_path.read_text(encoding="utf-8"))
    feats_in = fc["features"]
    print(f"  {len(feats_in)} features, type={fc.get('type')}")

    ws_names = parse_codelist_html(CODELIST_DIR / "WaterSystemCodeCd.html", r"\d{6}")
    river_names = parse_codelist_html(CODELIST_DIR / "RiverCodeCd.html", r"\d{10}")
    src_names = parse_codelist_html(CODELIST_DIR / "OriginalDataCodeCd.html", r"\d+")
    print(f"  codelists: watersystem={len(ws_names)} river={len(river_names)} origsrc={len(src_names)}")

    rows, prop_rows = [], []
    pref_counter = {}
    n_multi_pref = 0
    total_vtx_raw = total_vtx_simplified = 0

    for i, feat in enumerate(feats_in):
        if feat.get("geometry", {}).get("type") != "LineString":
            print(f"  [skip] feature {i}: geometry type != LineString ({feat.get('geometry', {}).get('type')})")
            continue
        props = feat["properties"]
        feature_id = f"{WATER_SYSTEM_CODE}_{i:04d}"
        source_ref = f"{URL}#feature:{i}"

        geom = shp_shape(feat["geometry"])
        n_raw = len(geom.coords)
        geom_s = geom.simplify(SIMPLIFY_TOLERANCE_DEG, preserve_topology=True)
        n_simplified = len(geom_s.coords)
        total_vtx_raw += n_raw
        total_vtx_simplified += n_simplified

        coords = list(geom_s.coords)
        length_m = round(approx_length_m(coords), 2)
        start_lon, start_lat = coords[0]
        end_lon, end_lat = coords[-1]

        pref_code_raw, pref_ja = derive_prefecture(props)
        if pref_code_raw and "/" in pref_code_raw:
            n_multi_pref += 1
        pref_counter[pref_code_raw] = pref_counter.get(pref_code_raw, 0) + 1

        section_code_raw = str(props.get("W05_003")) if props.get("W05_003") is not None else None
        orig_src_raw = str(props.get("W05_005")) if props.get("W05_005") is not None else None
        flow_raw = str(props.get("W05_006")) if props.get("W05_006") is not None else None

        row = {
            "feature_id": feature_id,
            "name_ja": props.get("W05_004"),
            "water_system_code": props.get("W05_001"),
            "water_system_name_ja": ws_names.get(props.get("W05_001"), WATER_SYSTEM_NAME_JA),
            "river_code": props.get("W05_002"),
            "river_code_name_ja": river_names.get(props.get("W05_002")),
            "section_type_code_raw": section_code_raw,
            "section_type_ja": SECTION.get(section_code_raw),
            "prefecture_code_raw": pref_code_raw,
            "prefecture_ja": pref_ja,
            "original_source_code_raw": orig_src_raw,
            "original_source_ja": src_names.get(orig_src_raw),
            "flow_direction_known_raw": flow_raw,
            "flow_direction_known": (flow_raw in ("1", "true", "True")) if flow_raw is not None else None,
            "start_node_ref": props.get("W05_007"),
            "end_node_ref": props.get("W05_008"),
            "stream_start_node_ref": props.get("W05_009"),
            "stream_end_node_ref": props.get("W05_010"),
            "length_m": length_m,
            "n_vertices_raw": n_raw,
            "n_vertices_simplified": n_simplified,
            "start_lat": round(start_lat, 8), "start_lon": round(start_lon, 8),
            "end_lat": round(end_lat, 8), "end_lon": round(end_lon, 8),
            "geometry_geojson": json.dumps(shp_mapping(geom_s), ensure_ascii=False),
            "source_id": SID,
            "source_ref": source_ref,
        }
        rows.append(row)

        prop_rows.append({
            "feature_id": feature_id,
            "source_ref": source_ref,
            **{k: props.get(k) for k in
               ("W05_001", "W05_002", "W05_003", "W05_004", "W05_005",
                "W05_006", "W05_007", "W05_008", "W05_009", "W05_010")},
        })

    fields = ["feature_id", "name_ja", "water_system_code", "water_system_name_ja",
              "river_code", "river_code_name_ja", "section_type_code_raw", "section_type_ja",
              "prefecture_code_raw", "prefecture_ja", "original_source_code_raw", "original_source_ja",
              "flow_direction_known_raw", "flow_direction_known",
              "start_node_ref", "end_node_ref", "stream_start_node_ref", "stream_end_node_ref",
              "length_m", "n_vertices_raw", "n_vertices_simplified",
              "start_lat", "start_lon", "end_lat", "end_lon",
              "geometry_geojson", "source_id", "source_ref"]
    p = PROC / f"{SID}.csv"
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"  [write] {p}  {len(rows)} rows")
    write_jsonl(SID, rows)

    prop_fields = ["feature_id", "source_ref", "W05_001", "W05_002", "W05_003", "W05_004", "W05_005",
                   "W05_006", "W05_007", "W05_008", "W05_009", "W05_010"]
    pp = PROC / f"{SID}_props.csv"
    with open(pp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=prop_fields)
        w.writeheader()
        for r in prop_rows:
            w.writerow(r)
    print(f"  [write] {pp}  {len(prop_rows)} rows")

    print(f"  vertices: raw={total_vtx_raw} simplified={total_vtx_simplified} "
          f"(tolerance={SIMPLIFY_TOLERANCE_DEG} deg)")
    print(f"  prefecture breakdown (by node-ref prefix): {pref_counter}")
    print(f"  boundary-crossing features (multiple pref codes among node refs): {n_multi_pref}")
    n_yamanashi_only = pref_counter.get("19", 0)
    n_kanagawa_only = pref_counter.get("14", 0)
    print(f"  山梨県のみ(node_ref由来)区間数: {n_yamanashi_only} / 神奈川県のみ: {n_kanagawa_only} "
          f"/ 県境またぎ: {n_multi_pref} / 判定不能: {pref_counter.get(None, 0)}")

    register(
        source_id=SID,
        name="相模川水系 河川データ(水系単位, NII再パッケージ版)",
        publisher="国立情報学研究所(NII) geoshape.ex.nii.ac.jp / 原データ: 国土交通省 国土数値情報(KSJ) W05 河川",
        url=URL,
        category="gis_river",
        access_method="http_json",
        fmt="geojson->csv+jsonl",
        license_=(
            "geoshape.ex.nii.ac.jp の説明ページには「このウェブサイトのコンテンツは、CC BY 4.0 の下に"
            "提供されています」とある一方、同じ段落で「ただし本サイトで利用している河川データの利用規約"
            "については、国土数値情報を参照して下さい」とも明記されている。NIIのCC BY 4.0はサイト・"
            "GeoJSON変換という再パッケージ行為にかかる権利表示であって、原データ(国土数値情報W05)自体の"
            "利用規約(既存 nlni_w05_rivers に記載の「非商用」条件, "
            "https://nlftp.mlit.go.jp/ksj/other/agreement.html)を上書きするものではないと解釈するのが妥当。"
            "商用利用可への緩和効果は無いと判断する(既存nlni_w05_riversと同じ「非商用」扱いを維持)。"
        ),
        redistributable=1,
        record_count=len(rows),
        notes=(
            f"水系コード830307(相模川水系)の全流路 {len(rows)} 本(LineString)。properties実キーは "
            "W05_001〜W05_010で、既存source_registry `nlni_w05_rivers`(神奈川県単位KSJシェープファイル、"
            "同じW05_001〜W05_010属性)と同一原データ(先頭featureの河川名・端点参照が完全一致)であることを確認。"
            "nlni_w05_riversは神奈川県(都道府県コード14)単位取得のため相模川水系分は712行のみ。本データは"
            "水系単位のため、山梨県側の桂川上流部を含む流域全体が入る。"
            f"prefecture_ja は河川端点参照(#gb03_XXNNNNN 形式)の先頭2桁(都道府県コード)から機械的に判定した"
            "もので、ジオコーディングによる推測ではない(既存nlni_w05_riversの出力ノード参照と同一形式であることを"
            f"突き合わせて確認済み)。judged breakdown: {pref_counter} "
            f"(山梨県のみ={n_yamanashi_only}, 神奈川県のみ={n_kanagawa_only}, 県境またぎ={n_multi_pref})。"
            f"length_m は shapely.simplify(tolerance={SIMPLIFY_TOLERANCE_DEG}度≒1.1m, preserve_topology=True)"
            "後の頂点列に対し、緯度1度≒111,320m・経度1度≒111,320*cos(緯度)の平面近似で区間距離を積算した概算値"
            "(測地線計算ではない)。geometry_geojsonも同じsimplify後の座標を使用。"
            "既存nlni_w05_riversとの重複判定・マージはこのスクリプトでは行わない(ローダー側の仕事)。"
            f"全キー(W05_001〜010)は {SID}_props.csv にそのまま保存。"
        ),
    )


if __name__ == "__main__":
    main()
