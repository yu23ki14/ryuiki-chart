"""place / place_source_ref を作る（docs/plans/PHASE_A.md §A-3）。

対象: site（sites 352件 + sensor_timeseries/measurements 側で不足する分）、
watershed（derived.watershed_meta 377件）、mesh3（derived.mesh_all 4,083件）、
zone（registry/place/zone.yaml 5件）。town_block と river_segment は Phase A では
登録しない。place_source_ref で v1 の site_id / watershed_id / mlat,mlon / zone の
整数値を引けるようにする（ADR-0006）。

region_id は全行 "jp-14"（神奈川県。Phase A の対象地域はここだけ）。

## `place_source_ref.external_key` の合成規則（v1 側の識別子との接続点）

| place_kind | external_key                  | source_id                    |
|---|---|---|
| site       | v1 の `site_id` そのまま       | `sites.site_id`               |
| watershed  | `watershed_meta.watershed_id` そのまま | `watershed_meta.watershed_id` |
| mesh3      | `f"mesh3:{mlat},{mlon}"`（2列を1文字列に合成） | `mesh_all.mlat_mlon`          |
| zone       | `sites.zone` の整数値を文字列化（"1".."5"） | `sites.zone`                  |

site の external_key は「sites テーブルにある行」と「measurements /
sensor_timeseries にしか出てこない行」を区別しない。site_id は3テーブルで共通の
識別子空間なので、どちらも同じ規則（v1 の site_id をそのまま）で引ける。

## site の ID 組み立て

`sites.site_id` は例外なく `<出典名前空間>__<出典側コード>` の形（352件で実測済み）。
`<出典名前空間>` を `SITE_NAMESPACE` で ADR-0004 の短い名前空間トークンに変換し、
`<出典側コード>`（`__` の後ろ）を `common.place_id()` の `local` に渡す
（例: `sites.site_id = "jma_stations_kanagawa__jma_0387"` →
`jp-14:place:site.jma-jma_0387"`。ADR-0004 の例 `jp-14:place:site.env-pubwater-0142`
と同じ組み立て）。`measurements` / `sensor_timeseries` にしか無い site_id も
同じ関数 `_site_place_id()` に通すので、同じ規則で ID が決まる。

## sites に無い site_id の補完（測定 7,846行 / センサー65地点）

`registry/place/site_supplement.csv`（手書き）に、`data/processed/*.csv`（収集
スクリプト `scripts/c11_soramame.py` / `c13_sagamihara_taiki.py` /
`c84_jiban_chinka.py` / `c85_hiratsuka_taiki.py` / `c86_ckan_bodik_yokohama.py` が
書き出した地点台帳・住所録）を実際に当たって拾った `name_ja` / `lat` / `lon` と、
その出どころを記した `definition_ref` を1行ずつ置いてある。

**座標が見つかったのは `yokohama_river_waterlevel`（横浜市河川水位, 55件中53件）
だけ。** 残りは収集スクリプト自身が `"lat": None, "lon": None` と明記しており
（そらまめ君 = 環境省soramame君は「公開CSVに緯度経度は含まれない」とコメント済み、
地盤沈下観測井・厚木市河川水質・平塚/相模原の大気観測局も原本に住所以上の情報が
無い）、**座標を捏造せず** `lat`/`lon` を NULL のまま `status='needs_review'` で
登録する。`kanagawa_jiban_chinka__県全体` は個別の観測井ではなく「表4」の
県全体集計行（`scripts/c84_jiban_chinka.py`）で、そもそも点ではないため同様に扱う。

`site_supplement.csv` に無い site_id が原本に増えた場合は `build()` が例外を
投げる（黙って解決率を落とさないため）。

## zone

`registry/place/zone.yaml`（手書き）を読む。PyYAML（`yaml.safe_load`）で読む
（A-2/A-5 と統一。以前は自前の小さいパーサだったが、YAML の読み方をリポジトリ全体で
1本化するため置き換えた）。
"""
import csv
import pathlib
import sqlite3

import yaml

from . import common

REGION_ID = "jp-14"  # 神奈川県固定（Phase A の対象地域はここだけ）

PLACE_DIR = pathlib.Path(__file__).resolve().parents[2] / "registry" / "place"

# sites.site_id / measurements.site_id / sensor_timeseries.site_id に現れる
# "<出典名前空間>__<出典側コード>" の <出典名前空間> -> place_id 用の短い名前空間
# トークン（ADR-0004 の例 jp-14:place:site.env-pubwater-0142 に合わせた命名）。
# 11種類で全件（sites 352 + 補完143）をカバーする（実測済み）。
SITE_NAMESPACE = {
    "env_kousui_stations_kanagawa": "env-pubwater",
    "moni1000_sites": "moni1000",
    "sagami_livecams": "sagami-livecam",
    "jma_stations_kanagawa": "jma",
    "dams_kanagawa": "dams",
    "kanagawa_jiban_chinka": "jiban-chinka",
    "atsugi_river_water_quality": "atsugi-river",
    "hiratsuka_taiki_stations": "hiratsuka-taiki",
    "sagamihara_taiki_stations": "sagamihara-taiki",
    "soramame_stations_kanagawa": "soramame",
    "yokohama_river_waterlevel": "yokohama-waterlevel",
}


def _site_place_id(site_id: str) -> str:
    prefix, sep, local = site_id.partition("__")
    if not sep:
        raise ValueError(f"site_id が想定外の形（'__' が無い）: {site_id!r}")
    ns = SITE_NAMESPACE.get(prefix)
    if ns is None:
        raise ValueError(
            f"未知の site_id 名前空間: {site_id!r}（SITE_NAMESPACE に無い。"
            "原本に新しい出典が増えた可能性がある）"
        )
    return common.place_id("site", ns, local or "unknown", scope=REGION_ID)


def _load_site_supplement() -> dict[str, dict]:
    """registry/place/site_supplement.csv（手書き）を読む。"""
    path = PLACE_DIR / "site_supplement.csv"
    out: dict[str, dict] = {}
    with path.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            out[row["site_id"]] = row
    return out


def _load_zone_yaml() -> list[dict]:
    """registry/place/zone.yaml（手書き）を PyYAML で読む。"""
    path = PLACE_DIR / "zone.yaml"
    with path.open(encoding="utf-8") as f:
        items = yaml.safe_load(f)
    assert len(items) == 5, f"registry/place/zone.yaml は5件のはずが{len(items)}件"
    return items


def build(conn: sqlite3.Connection, src: dict[str, sqlite3.Connection]) -> dict[str, int]:
    """conn: registry.sqlite への書き込み用コネクション。
    src: {'ryuiki': ..., 'cells': ..., 'derived': ...} の読み取り専用コネクション。
    戻り値: {テーブル名: 挿入した行数}（ログ表示用）。
    """
    ryuiki = src["ryuiki"]
    derived = src["derived"]

    place_rows: list[tuple] = []
    ref_rows: list[tuple] = []

    # --- site: sites テーブル本体（352件） ---------------------------------
    for row in ryuiki.execute(
        "SELECT site_id, name, lat, lon, elevation_m, source_id, source_ref FROM sites"
    ):
        pid = _site_place_id(row["site_id"])
        place_rows.append((
            pid, REGION_ID, "site", row["name"], row["lat"], row["lon"],
            row["elevation_m"], None, row["source_ref"] or row["source_id"], "ok",
        ))
        ref_rows.append((pid, row["site_id"], "sites.site_id"))

    # --- site: sites に無い分の補完 -----------------------------------------
    # （measurements の site_id 250種中78種 / sensor_timeseries の77種中65種）
    known_site_ids = {r["site_id"] for r in ryuiki.execute("SELECT site_id FROM sites")}
    missing_site_ids: set[str] = set()
    for table in ("measurements", "sensor_timeseries"):
        found = {r["site_id"] for r in ryuiki.execute(f"SELECT DISTINCT site_id FROM {table}")}
        missing_site_ids |= found - known_site_ids

    supplement = _load_site_supplement()
    not_in_supplement = sorted(missing_site_ids - supplement.keys())
    if not_in_supplement:
        raise AssertionError(
            "registry/place/site_supplement.csv に無い site_id がある"
            "（原本に新しい未登録地点が増えた）: " + ", ".join(not_in_supplement)
        )

    for site_id in sorted(missing_site_ids):
        sup = supplement[site_id]
        pid = _site_place_id(site_id)
        name_ja = sup["name_ja"] or None
        lat = float(sup["lat"]) if sup["lat"] else None
        lon = float(sup["lon"]) if sup["lon"] else None
        definition_ref = sup["definition_ref"] or None
        status = "ok" if lat is not None else "needs_review"
        place_rows.append((pid, REGION_ID, "site", name_ja, lat, lon, None, None, definition_ref, status))
        ref_rows.append((pid, site_id, "sites.site_id"))

    # --- watershed: derived.watershed_meta（377件） -------------------------
    for row in derived.execute(
        "SELECT watershed_id, water_system_name, area_km2, centroid_lat, centroid_lon, source_ref "
        "FROM watershed_meta"
    ):
        pid = common.place_id("watershed", "nlni", row["watershed_id"], scope="common")
        place_rows.append((
            pid, REGION_ID, "watershed", row["water_system_name"],
            row["centroid_lat"], row["centroid_lon"], None, row["area_km2"],
            row["source_ref"], "ok",
        ))
        ref_rows.append((pid, row["watershed_id"], "watershed_meta.watershed_id"))

    # --- mesh3: derived.mesh_all（4,083件） ---------------------------------
    for row in derived.execute("SELECT mlat, mlon FROM mesh_all"):
        mlat, mlon = row["mlat"], row["mlon"]
        local = f"{mlat}_{mlon}"
        pid = common.place_id("mesh3", "grid01", local, scope="common")
        # web/src/lib/geo.ts meshPolygon(): lat0=mlat/100, lon0=mlon/100 がセルの
        # 南西端。place の代表点はセル中心（+0.005度）にする（0.01度グリッドの
        # 定義から機械的に求まる値であり、実世界の座標を推測しているわけではない）。
        lat = mlat / 100 + 0.005
        lon = mlon / 100 + 0.005
        definition_ref = (
            "0.01度グリッド（web/scripts/build-biota.mjs: "
            "mlat=CAST(FLOOR(lat*100) AS INT), mlon=CAST(FLOOR(lon*100) AS INT)）の"
            "セル中心。国土地理院の標準地域メッシュ（3次メッシュ）ではなく、本アプリが "
            "organism_records の座標から独自に定義した集計用グリッド。"
        )
        place_rows.append((pid, REGION_ID, "mesh3", None, lat, lon, None, None, definition_ref, "ok"))
        ref_rows.append((pid, f"mesh3:{mlat},{mlon}", "mesh_all.mlat_mlon"))

    # --- zone: registry/place/zone.yaml（5件） ------------------------------
    disclaimer = (
        "Ridge to Reef ゾーン(1-5)の操作的定義。標高と海岸線からの距離のみを用いて"
        "機械的に算出した、本データ統合作業独自の操作的区分であり、公式の行政区分・"
        "学術区分ではない。分水嶺・尾根線・行政界等の地形学的境界は考慮していない。"
        "閾値は仮に置いた値であり、専門家レビューで確定する必要がある"
        "（docs/ZONE_DEFINITION.md）。"
    )
    for item in _load_zone_yaml():
        n = int(item["zone"])
        pid = common.place_id("zone", "r2r", str(n), scope=REGION_ID)
        definition_ref = f"{disclaimer} 条件: {item['condition_ja']}。"
        place_rows.append((
            pid, REGION_ID, "zone", item["name_ja"], None, None, None, None, definition_ref, "ok",
        ))
        ref_rows.append((pid, str(n), "sites.zone"))

    common.insert_many(
        conn, "place",
        ["place_id", "region_id", "place_kind", "name_ja", "lat", "lon",
         "elevation_m", "area_km2", "definition_ref", "status"],
        place_rows,
    )
    common.insert_many(
        conn, "place_source_ref",
        ["place_id", "external_key", "source_id"],
        ref_rows,
    )

    return {"place": len(place_rows), "place_source_ref": len(ref_rows)}
