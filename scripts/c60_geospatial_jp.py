"""G空間情報センター (https://www.geospatial.jp/ckan/) から
神奈川県・相模川流域関連データセットの目録化と、一部データの実データ化を行う。

対象外（他エージェント担当のため触れない）: 国土数値情報(KSJ) そのもの。
  -> geospatial.jp 上で KSJ をミラー配信している package (name が "ksj-" で
     始まるもの) はカタログには含めるが、実データ化の対象からは明示的に除外する。
"""
import sys, json, pathlib, zipfile, io
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from common import get, get_json, download, register, write_jsonl, PROC, RAW, now
import pandas as pd

BASE = "https://www.geospatial.jp/ckan"
API = f"{BASE}/api/3/action/package_search"
SHOW = f"{BASE}/api/3/action/package_show"

# ---------------------------------------------------------------------------
# 1) 目録化: q=神奈川 / tags=神奈川県 / 相模川流域の主要語 でカタログを収穫
# ---------------------------------------------------------------------------

def harvest(params):
    out, start, rows = [], 0, 1000
    while True:
        p = dict(params); p.update({"rows": rows, "start": start})
        j = get_json(API, params=p)
        res = j["result"]; out += res["results"]
        start += rows
        if start >= res["count"] or not res["results"]:
            break
    return out

QUERIES = [
    {"q": "神奈川"},
    {"fq": 'tags:"神奈川県"'},
    {"q": "相模川"},
    {"q": "相模原"},
    {"q": "丹沢"},
    {"q": "道志川"},
    {"q": "宮ヶ瀬"},
    {"q": "城山ダム"},
    {"q": "相模湖"},
    {"q": "津久井"},
    # 相模川流域を含む神奈川県内主要市町村名（PLATEAU等、q=神奈川/tags=神奈川県 に
    # ヒットしない市町村単位データセットを拾うため）
    {"q": "横浜市"}, {"q": "川崎市"}, {"q": "相模原市"}, {"q": "横須賀市"},
    {"q": "鎌倉市"}, {"q": "藤沢市"}, {"q": "厚木市"}, {"q": "箱根町"},
    {"q": "秦野市"}, {"q": "伊勢原市"}, {"q": "海老名市"}, {"q": "座間市"},
    {"q": "大和市"}, {"q": "愛川町"}, {"q": "清川村"}, {"q": "寒川町"},
    {"q": "平塚市"}, {"q": "茅ヶ崎市"},
]

def build_catalog():
    all_ds = {}
    for q in QUERIES:
        try:
            r = harvest(q)
        except Exception as e:
            print(f"  [skip query] {q}: {e}")
            continue
        print(f"  query {q}: {len(r)} hits")
        for d in r:
            all_ds[d["id"]] = d
    print(f"TOTAL unique datasets: {len(all_ds)}")
    return list(all_ds.values())


def catalog_row(p):
    title = p.get("title") or ""
    fmts = "|".join(sorted(set((r.get("format") or "").upper() for r in p.get("resources") or [] if r.get("format"))))
    return {
        "dataset_id": p.get("id"),
        "name": p.get("name"),
        "title": title,
        "title_ja": title,  # CKAN 上の原表記(日本語)そのもの。英訳は存在しないため同値を保持。
        "notes": (p.get("notes") or "").replace("\r\n", "\n")[:1500],
        "organization": (p.get("organization") or {}).get("title"),
        "organization_slug": (p.get("organization") or {}).get("name"),
        "license": p.get("license_title") or p.get("license_id"),
        "license_id": p.get("license_id"),
        "license_url": p.get("license_url"),
        "tags": "|".join(t.get("display_name", "") for t in p.get("tags") or []),
        "formats": fmts,
        "n_resources": len(p.get("resources") or []),
        "metadata_modified": p.get("metadata_modified"),
        "metadata_created": p.get("metadata_created"),
        "area_raw": p.get("area"),
        "charge_raw": p.get("charge"),
        "restriction_raw": p.get("restriction"),
        "url": f"{BASE}/dataset/{p.get('name')}",
        "source_id": "geospatial_jp_kanagawa_catalog",
        "source_ref": f"{BASE}/dataset/{p.get('name')}",
    }


def main():
    datasets = build_catalog()
    rows = [catalog_row(p) for p in datasets]
    df = pd.DataFrame(rows)
    df.to_csv(PROC / "geospatial_jp_kanagawa.csv", index=False)
    write_jsonl("geospatial_jp_kanagawa", rows)

    register(
        "geospatial_jp_kanagawa_catalog",
        "G空間情報センター 神奈川県・相模川流域関連データセット目録",
        "国土交通省 G空間情報センター（運営: 一般社団法人 社会基盤情報流通推進協議会）",
        f"{BASE}/dataset?q=神奈川",
        "オープンデータ目録", "CKAN API (package_search)", "JSON/CSV",
        "データセットごとに異なる（cc-by, ol=独自利用規約, ogl=政府標準利用規約, notspecified 等混在。個票の license 列参照）",
        True, len(rows),
        "q=神奈川 / fq=tags:神奈川県 / 相模川・相模原・丹沢・道志川・宮ヶ瀬・城山ダム・相模湖・津久井 の"
        "各キーワードで package_search を実行し id で重複排除して統合した目録。"
        "国土数値情報(KSJ)ミラー(name先頭ksj-)は目録には含めるが実データ化対象からは除外"
        "（国土数値情報は別の並行エージェントの担当領域のため）。",
    )

    # -----------------------------------------------------------------
    # PLATEAU 神奈川県内市町村 (実体は巨大なため未取得、目録のみ)
    # -----------------------------------------------------------------
    plateau = [d for d in datasets if d.get("name", "").startswith("plateau-14")]
    plateau_titles = [d["title"] for d in plateau]
    register(
        "geospatial_jp_plateau_kanagawa",
        "G空間情報センター PLATEAU 神奈川県内市町村 3D都市モデル目録",
        "国土交通省 Project PLATEAU",
        f"{BASE}/dataset?q=plateau",
        "3D都市モデル目録", "CKAN API (package_search)", "3D Tiles/CityGML/MVT 等",
        "PLATEAU Site Policy「3. 著作権について」に拠る（実質CC-BY 4.0相当）",
        True, len(plateau),
        "神奈川県内(市町村コード14始まり)のPLATEAU 3D都市モデルデータセットを目録化: "
        + " / ".join(plateau_titles)
        + " 。実体(3D Tiles/CityGML等)は1都市年度あたり数百MB〜数GBと巨大で、"
          "本デモ(流域カルテ)のスコープ(表形式の環境・生物・河川データ中心)では"
          "3D建物形状データそのものは不要と判断し、目録登録のみでダウンロードは行っていない。",
    )

    # -----------------------------------------------------------------
    # 航空レーザ測量 3次元点群データ（森林資源解析用途, カタログのみ）
    # -----------------------------------------------------------------
    pointcloud = [d for d in datasets if d.get("name", "").endswith("-pointcloud")]
    pc_titles = [d["title"] for d in pointcloud]
    register(
        "geospatial_jp_pointcloud_kanagawa",
        "G空間情報センター 神奈川県 航空レーザ測量3次元点群データ目録",
        "神奈川県 環境農政局緑政部森林再生課",
        f"{BASE}/dataset/kanagawa-2022-pointcloud",
        "地形・森林資源目録", "CKAN API (package_search)", "点群/PBF(ベクトルタイル)/TIF/DXF",
        "cc-by（データ提供元クレジット表記必須の付帯条件あり）",
        True, len(pointcloud),
        "森林資源データ解析目的で取得された県内3次元点群データ(令和元年度〜令和6年度、"
        "相模原市域を含む)を目録化: " + " / ".join(pc_titles) + " 。"
        "配信形式が {z}/{x}/{y} のPBF(ベクトルタイル)ピラミッド等でファイル総数が"
        "非常に多く一括ダウンロードが実務的でないこと、および元データが数十GB規模と"
        "本デモのスコープを超える点群/画像データであることから、実データ取得は見送り"
        "目録登録のみとした。",
    )

    return datasets


# ---------------------------------------------------------------------------
# 2) 実データ化: 相模川流域の主要市町村を対象に、農地筆ポリゴン（農林水産省作成・
#    aigid配信、土地利用データ）の重心点CSVを取得・統合。ポリゴン本体(SHP)は
#    生ファイルのみ保存（geopandas/pyshp未導入のため属性抽出は行わない）。
# ---------------------------------------------------------------------------

# 相模川水系の流域および河口部にあたる市町村 (JISコード: 市町村名)
SAGAMI_BASIN_MUNI = {
    "14150": "相模原市", "14212": "厚木市", "14211": "秦野市", "14214": "伊勢原市",
    "14215": "海老名市", "14216": "座間市", "14213": "大和市", "14401": "愛川町",
    "14402": "清川村", "14321": "寒川町", "14361": "中井町", "14362": "大井町",
    "14363": "松田町", "14364": "山北町", "14366": "開成町",
    "14203": "平塚市", "14207": "茅ヶ崎市", "14205": "藤沢市",
}


def agri_point_2021():
    """農地筆ポリゴン2021（世界測地系）重心点データ_14神奈川県 (agri-point-2021-14)
    のうち相模川流域市町村分の CSV を取得し統合する。CC-BY, 再配布可。"""
    j = get_json(SHOW, params={"id": "agri-point-2021-14"})
    r = j["result"]
    outdir = RAW / "geospatial_jp" / "agri_point_2021"
    rows = []
    used_resources = []
    for res in r["resources"]:
        jiscode = res["name"][:5]
        if jiscode not in SAGAMI_BASIN_MUNI:
            continue
        dest = outdir / f"{res['name']}.csv"
        try:
            download(res["url"], dest)
        except Exception as e:
            print(f"  [skip] {res['name']}: {e}")
            continue
        used_resources.append(res["name"])
        df = pd.read_csv(dest, encoding="cp932", dtype=str)
        for _, row in df.iterrows():
            rows.append({
                "parcel_id": row.get("id"),
                "open_fiscal_year": pd.to_numeric(row.get("OpenYear"), errors="coerce"),
                "edit_fiscal_year": pd.to_numeric(row.get("EditYear"), errors="coerce"),
                "land_use_kind_ja": row.get("Kind"),
                "centroid_lon": pd.to_numeric(row.get("CentroidX"), errors="coerce"),
                "centroid_lat": pd.to_numeric(row.get("CentroidY"), errors="coerce"),
                "jis_code": row.get("JisCode"),
                "city_ja": row.get("City"),
                "open_fiscal_year_raw": row.get("OpenYear"),
                "edit_fiscal_year_raw": row.get("EditYear"),
                "source_id": "geospatial_jp_agri_point_2021_sagami",
                "source_ref": res["url"],
            })
    if not rows:
        register("geospatial_jp_agri_point_2021_sagami",
                  "農地筆ポリゴン2021 重心点データ（相模川流域市町村, geospatial.jp）",
                  "農林水産省（配信: aigid, G空間情報センター）",
                  f"{BASE}/dataset/agri-point-2021-14", "土地利用", "CKAN resource download (CSV)",
                  "CSV", "CC-BY", True, 0, "対象市町村のCSV取得に失敗したため0件。")
        return
    df_all = pd.DataFrame(rows)
    df_all.to_csv(PROC / "geospatial_jp_agri_point_2021_sagami.csv", index=False)
    write_jsonl("geospatial_jp_agri_point_2021_sagami", df_all.to_dict("records"))
    register(
        "geospatial_jp_agri_point_2021_sagami",
        "農地筆ポリゴン2021 重心点データ（相模川流域市町村, geospatial.jp）",
        "農林水産省（配信: 一般社団法人社会基盤情報流通推進協議会 aigid, G空間情報センター）",
        f"{BASE}/dataset/agri-point-2021-14", "土地利用", "CKAN resource download (CSV)",
        "CSV", "CC-BY 4.0", True, len(df_all),
        f"相模川流域および河口部にあたる{len(SAGAMI_BASIN_MUNI)}市町村のうち"
        f"取得できた{len(used_resources)}市町村分({'/'.join(used_resources)})の農地筆重心点"
        "(2021年度, 農林水産省 筆ポリゴンデータより, 各筆の代表点・地目Kind等)を統合。"
        "元は市町村別CSV(cp932)。地目(Kind)は原文のまま land_use_kind_ja に保持し翻訳・分類はしていない。",
    )


def agri_poly_2021():
    """農地筆ポリゴン2021（世界測地系）_14神奈川県 (agri-poly-2021-14) の
    ポリゴン本体(SHP,zip)は、相模川流域市町村分のみ生ファイルを保存する。
    geopandas/pyshp が未導入のため属性抽出は行わない（ファイル存在・サイズ確認のみ）。"""
    j = get_json(SHOW, params={"id": "agri-poly-2021-14"})
    r = j["result"]
    outdir = RAW / "geospatial_jp" / "agri_poly_2021"
    saved = []
    for res in r["resources"]:
        jiscode = res["name"][:5]
        if jiscode not in SAGAMI_BASIN_MUNI:
            continue
        dest = outdir / f"{res['name']}.zip"
        try:
            download(res["url"], dest)
        except Exception as e:
            print(f"  [skip] {res['name']}: {e}")
            continue
        saved.append((res["name"], dest.stat().st_size))
    detail = ", ".join(f"{n}({sz:,}B)" for n, sz in saved)
    register(
        "geospatial_jp_agri_poly_2021_sagami",
        "農地筆ポリゴン2021 ポリゴン本体（相模川流域市町村, geospatial.jp, 生ファイルのみ）",
        "農林水産省（配信: aigid, G空間情報センター）",
        f"{BASE}/dataset/agri-poly-2021-14", "土地利用", "CKAN resource download (SHP/ZIP)",
        "SHP", "CC-BY 4.0", True, 0,
        f"相模川流域市町村{len(saved)}件のSHP(zip)を data/raw/geospatial_jp/agri_poly_2021/ に保存: "
        f"{detail}. 属性抽出は環境制約(geopandas/pyshp未導入)により未実施のため record_count は "
        "ファイル存在確認のみで0としている。ポイント版(重心点CSV)は geospatial_jp_agri_point_2021_sagami "
        "として実データ化済み。",
    )


def kokudo_river_and_landclass():
    """国土調査（土地分類基本調査・水基本調査）成果のうち、相模川水系調査(SHP)と
    神奈川県の20万分の1土地分類基本調査(SHP)を取得。生ファイルのみ保存し、
    属性抽出は行わない。

    ライセンス注記: geospatial.jp 上の license_id は 'ol'(独自利用規約)。
    相模川水系データ同梱の readme.txt に以下の記載があるため、そのままの複製・
    頒布は禁止と解釈し redistributable=0 として扱う（原文引用）:
      「ご利用にあたっては、特に手続き等の必要はありませんが、成果の一部を
      引用・転載又は複製・加工して再配布する場合は、出典の表示と実施者の責任を
      明示してください。ただし、原則として、成果をそのまま複製して有償・無償に
      関わらず頒布することは禁じます」
    """
    river_dir = RAW / "geospatial_jp" / "kokudo_river_sagami"
    land_dir = RAW / "geospatial_jp" / "kokudo_landclass_kanagawa"
    river_zip = river_dir / "h14_0301_sagamigawa.zip"
    land_zip = land_dir / "14_kanagawa.zip"
    download("https://nlftp.mlit.go.jp/kokjo/tochimizu/F7/GIS/h14_0301.zip", river_zip)
    download("https://nlftp.mlit.go.jp/kokjo/tochimizu/F2/GIS/14.zip", land_zip)

    def n_shp(zpath):
        with zipfile.ZipFile(zpath) as z:
            return sum(1 for n in z.namelist() if n.lower().endswith(".shp"))

    n_river = n_shp(river_zip)
    n_land = n_shp(land_zip)

    restriction_quote = (
        "「ご利用にあたっては、特に手続き等の必要はありませんが、成果の一部を引用・"
        "転載又は複製・加工して再配布する場合は、出典の表示と実施者の責任を明示して"
        "ください。ただし、原則として、成果をそのまま複製して有償・無償に関わらず"
        "頒布することは禁じます」（h14_0301相模川地域 readme.txtより原文引用）"
    )

    register(
        "geospatial_jp_kokudo_river_sagami",
        "国土調査 主要水系調査（一級水系）相模川地域（生ファイルのみ）",
        "国土交通省 国土政策局 国土情報課",
        f"{BASE}/dataset/mlit-kokudo-6", "河川", "HTTPダウンロード (SHP/ZIP)",
        "SHP", "独自利用規約(ol)", False, n_river,
        "1/50,000主要水系調査利水現況図数値データ（相模川水系, H14年度版）。"
        f"data/raw/geospatial_jp/kokudo_river_sagami/ に生ファイル保存(shapeレイヤ数={n_river})。"
        "geopandas/pyshp未導入のため属性抽出は未実施。ライセンスは同梱readme.txtにより"
        "そのままの複製頒布を禁じる独自規約と判明したため redistributable=0 とした。"
        + restriction_quote,
    )
    register(
        "geospatial_jp_kokudo_landclass_kanagawa",
        "国土調査 20万分の1土地分類基本調査等 神奈川県（生ファイルのみ）",
        "国土交通省 国土政策局 国土情報課",
        f"{BASE}/dataset/mlit-kokudo-2", "土地利用", "HTTPダウンロード (SHP/ZIP)",
        "SHP", "独自利用規約(ol)", False, n_land,
        "地形区分・表層地質・土壌分類等のポリゴン/ラインSHP（神奈川県）。"
        f"data/raw/geospatial_jp/kokudo_landclass_kanagawa/ に生ファイル保存(shapeレイヤ数={n_land})。"
        "geopandas/pyshp未導入のため属性抽出は未実施。同一プログラム(国土調査)・同一組織の"
        "mlit-kokudo-6に同梱されていた readme.txt と同様の独自利用規約が適用されると判断し、"
        "予防的に redistributable=0 とした（本データセット自体には readme が同梱されていなかったため"
        "組織単位の慣行からの推定である旨を明記）。" + restriction_quote,
    )


if __name__ == "__main__":
    main()
    agri_point_2021()
    agri_poly_2021()
    kokudo_river_and_landclass()
