"""place / place_source_ref / place_relation / place_watershed を作る
（docs/plans/PHASE_A.md §A-3、place_relation は Phase B `phase-b/region-scope`、
ADR-0022。grid01 の入力切り替えは Phase B `phase-b/occurrence-registry`、
docs/plans/PHASE_B_OCCURRENCE.md §2-3。watershed の入力切り替え・place_watershed・
地点→流域の辺は Phase B `phase-b/place-attributes`（P-1a）、
docs/plans/PHASE_B_PLACE_ATTRIBUTES.md）。

対象: site（sites 352件 + sensor_timeseries/measurements 側で不足する分）、
watershed（`data/processed/nlni_w12_watersheds.jsonl`、L1、377件。下記「watershed」節
参照）、grid01（`ryuiki.organism_records` の座標から直接作る。件数・実体・命名の経緯は
後述）、zone（registry/place/zone.yaml 5件）。town_block と river_segment は
Phase A では登録しない。place_source_ref で v1 の site_id / watershed_id / mlat,mlon /
zone の整数値を引けるようにする（ADR-0006）。place_relation は地点→ゾーンの辺
（`sites.zone` 由来）と地点→流域の辺（`sites.watershed` 由来、下記「place_relation」）を作る。
place_watershed は watershed だけが持つ属性サテライト（下記「watershed」節参照）。

## region_id（ADR-0022 決定1。理由・経緯はそちらを参照）

`place.region_id` は `place_id` のスコープと一致させる。`common.region_id_for_scoped_id()`
で発行済みの `place_id` から機械的に導く（`PLACE_SCOPE` 定数を region_id 列に直接
代入しない）。site / zone は scope=`jp-14` なので `region_id='jp-14'`、
watershed / grid01 は scope=`common`（県境をまたぐ流域・独自グリッド）なので
`region_id=NULL`。

## `place_kind='grid01'` について（ADR-0006 のコードリストからの逸脱）

当初は `place_kind='mesh3'` としていたが、レビューで「3次メッシュ（標準地域メッシュ）
ではなく本アプリ独自の0.01度グリッドなのに、ADR-0006 のコードリストの語である
`mesh3` を名乗っている」と指摘された。実測（`data/db/derived.sqlite` の
`mesh_all.mlat`/`mlon`、Phase B `phase-b/occurrence-registry` 以降は
`ryuiki.organism_records` の座標そのもの）で確認した事実:

- `mlat` は 3500, 3501, 3502, … と **1刻み**（= 0.01度刻み）。国土地理院の標準
  3次メッシュ（緯度30秒×経度45秒 ≒ 約1km四方、緯度は約1/120度刻み）とは刻み幅が
  一致しない。
- 本ビルドの `lat = mlat / 100 + 0.005` という計算自体が「1/100度グリッドの
  セル中心」を表しており、3次メッシュのコード体系（都道府県コード+地域メッシュ
  コード）とは無関係。
- `mlat`/`mlon` は `web/scripts/build-biota.mjs` が `organism_records` の
  座標から `FLOOR(lat*100)`/`FLOOR(lon*100)` で機械的に作る、本アプリ独自の
  集計用グリッドであり、標準地域メッシュではないことを確認済み。

このため `place_kind` を `grid01`（0.01度グリッドの意）に改め、ID も
`common:place:grid01.<mlat>_<mlon>` の形にした（`grid01` は namespace を持たず、
`<mlat>_<mlon>` を直接 local key にする。後述の合成規則表を参照）。
**ADR-0006 のコードリスト（`site`/`watershed`/`mesh3`/`municipality`/…）は
本体を編集せず、この逸脱は Phase B 以降で ADR 側にコードリストの追記
（`grid01` を正式な値として追加するか、将来 grid01 とは別に本物の3次メッシュを
登録する地域が出た時点で区別する）を申し送る。詳細は `registry/README.md`。**

### grid01 の入力を `derived.mesh_all` から `organism_records` の座標に変える
（Phase B `phase-b/occurrence-registry`、docs/plans/PHASE_B_OCCURRENCE.md §2-3）

`derived.mesh_all` は `web/scripts/build-biota.mjs` の `mesh_year`
（`WHERE lat IS NOT NULL AND yr BETWEEN 1970 AND 2026` でフィルタ済み）を
`GROUP BY mlat, mlon` で畳んだものなので、**年フィルタで弾かれた記録しか
持たないセルが grid01 から欠落する**。実測: `derived.mesh_all` 由来の grid01 は
4,083セルだが、`organism_records` の座標を直接 `FLOOR(lat*100)`/`FLOOR(lon*100)`
で丸めると **4,087セル**（4件差）。内訳:

- **3セル**は1970年より前の記録（6行）しか無いために `mesh_year` の年フィルタで
  弾かれていた（(3521,13898)/(3544,13913)/(3544,13968)）。v1 の `mesh_species`
  （年フィルタ無し、org_norm 全行から集計）には元々この3セルが存在しており、
  `mesh_all` だけが取りこぼしていた食い違い。
- **1セル**は `observed_on` が無い記録（iNaturalist 由来1行、緯度経度のみ）しか
  持たない（(3537,13977)）。`organism_records` は日付の無い記録も823,692行中
  6,836行持つが、座標（lat/lon）は**全行に入っている**（NULL 0件、実測済み）。

**日付の無い記録の座標も含める（=後者の1セルも作る）ことに決めた。** 理由:
1. 座標はそもそも全行にあり、座標の有無と日付の有無は独立（座標が使えない理由がない）。
2. occurrence ファクト（将来の O-1）は ADR-0007 原則1により日付の無い記録も
   保持する設計になる見込みで、その記録がいつか grid01 に解決されようとしたときに
   解決先の place が無い、という将来の欠落を今のうちに塞いでおける。
3. 「place（空間の集計単位）は場所そのものを表す」という ADR-0006 の設計に立つと、
   ある座標に有効な記録が存在するかどうかは日付の有無に依存しない。

一方、**分類（F2）の多数決の母集団は v1 と同じ日付ありに揃えたまま**にしてある
（`scripts/registry/build_taxon.py` の `_DATED_POPULATION_WHERE`）。grid01（場所の
集計単位を洗い出す）と taxon の分類多数決（v1 の値を変えない）は別の設計判断で、
根拠も別々なので意図的に扱いを分けている。

## watershed（Phase B `phase-b/place-attributes`、P-1a。入力を `derived.watershed_meta`
## から `data/processed/nlni_w12_watersheds.jsonl` の直読みに切り替えた）

以前は `derived.watershed_meta`（v1 の派生表、`web/scripts/build-geo.mjs` が
`nlni_w12_watersheds.jsonl` から作る）を読んでいたが、これは「v2 の registry を
v1 の出力（derived.sqlite）から作る」循環になっていた（P-1a の致命的な前提。
`docs/plans/PHASE_B_PLACE_ATTRIBUTES.md` 参照）。grid01 を `derived.mesh_all` から
`organism_records` に切り替えた前例（上記「grid01 の入力を...」節）と同じ理由・
同じ手順で、L1 の JSONL を直読みするように変えた。

**切り替えても値は1ビットも変わらない**（実測: 旧 `derived.watershed_meta` と
JSONL を Python で直読みした値を377行×9列（`watershed_id` を除く全列）で突き合わせ、
diff 0件。型・NULL・丸めの差も無い。詳細・突き合わせの再現手順は
`docs/plans/PHASE_B_PLACE_ATTRIBUTES.md`）。`place`/`place_source_ref` に載せる5列
（`name_ja`=`water_system_name_ja_estimated`、`lat`/`lon`=`centroid_lat`/`centroid_lon`、
`area_km2`、`definition_ref`=`source_ref`）は今まで通り。

残り4列（`water_system_code_old`・`water_system_category_ja`・`main_river_names_ja`・
`data_year`）は `place` 本体の列を増やさず、watershed 専用の属性サテライト
`place_watershed(place_id PK, water_system_code, water_system_category, main_rivers,
data_year)` に置く（ADR-0006「place の属性」節。ADR-0011 の `place_attribute`
カテゴリの具体形）。実測（377件）: `main_rivers` は234/377件が非空文字列
（v1・JSONL とも空文字列で持ち、NULLではない。空文字列をNULLに丸めない——main_rivers
だけ v1側のJS実装が `??`（nullish coalescing）を使っており `||` ではないため）。
`data_year` は377件全件が`1977`。`place_watershed` は D1（`web/src/db/schema-registry.ts`）
には載せない（`place_relation` と同じ判断。消費者が現れたら足す）。

## `place_source_ref.external_key` の合成規則（v1 側の識別子との接続点）

| place_kind | external_key                  | source_id                    |
|---|---|---|
| site       | v1 の `site_id` そのまま       | `sites.site_id`               |
| watershed  | `watershed_meta.watershed_id` そのまま | `watershed_meta.watershed_id` |
| grid01     | `f"grid01:{mlat},{mlon}"`（2列を1文字列に合成。旧`mesh3:{mlat},{mlon}`から改名。**形は変えない**） | `organism_records.lat_lon`（旧`mesh_all.mlat_mlon`から変更。入力が `derived.mesh_all` から `ryuiki.organism_records` の座標に変わったため） |
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

### 局番コードが空の site_id（`yokohama_river_waterlevel__`）

`sensor_timeseries` に730行だけ現れる `site_id="yokohama_river_waterlevel__"` は
`"__"` の後ろ（局番コード）が空文字で、`data/processed/yokohama_river_waterlevel_stations.csv`
にも対応する行が無い（原本側で局が特定できない欠測行。件数は実測で確認済み）。

以前はここで `local or "unknown"` として `site.yokohama-waterlevel-unknown` という
ID を機械的に作っていたが、レビューで「ID は不変（ADR-0004規約2）なのに、空文字を
理由に捏造したキーがそのまま固定される」と指摘された。ID を不変にするなら、
「何を local にするか」は黙って埋めずに人間が決めて記録すべき値である。

そのため `_site_place_id()` は局番コードが空のとき、`site_supplement.csv` の
**`place_local` 列**（この行にだけ値が入っている。他の143行は空欄で、これまで通り
`"__"` の後ろをそのまま使う）を明示の local として使う。`place_local` も無ければ
（＝原本に新しい「局番コードが空の site_id」が増えた場合）例外を投げる
（「未知の site_id」を `site_supplement.csv` に無いまま通す既存の防御と同じ考え方）。

## zone

`registry/place/zone.yaml`（手書き）を読む。PyYAML（`yaml.safe_load`）で読む
（A-2/A-5 と統一。以前は自前の小さいパーサだったが、YAML の読み方をリポジトリ全体で
1本化するため置き換えた）。

## place_relation（ADR-0006 / ADR-0022 決定2、Phase B で新設。理由・経緯はそちらを参照）

作る辺は2種類。地点→ゾーン（ADR-0022 決定2で新設）:

    place_relation(parent_id=ゾーンのplace_id, child_id=地点のplace_id,
                    relation='within', fraction=1.0, basis=<zone.yamlの定義を指す文字列>)

対象は `sites` テーブル本体のうち `zone IS NOT NULL` の行（290件。`site_supplement.csv`
側の補完地点は zone 列を持たないため対象外）。`parent_id` は `place_source_ref
(source_id='sites.zone')` 相当の対応から解決し、`registry/place/zone.yaml` に無い
ゾーン番号が現れたら例外を投げて止める（`_zone_relation_rows()`）。

地点→流域（Phase B `phase-b/place-attributes`、P-1a で新設）:

    place_relation(parent_id=流域のplace_id, child_id=地点のplace_id,
                    relation='within', fraction=1.0,
                    basis=<m01_sites.py の点内包判定を指す文字列>)

対象は `sites` テーブル本体のうち `watershed IS NOT NULL` の行（278件）。
`sites.watershed` は申告値ではなく、`scripts/m01_sites.py:110-128` が
`nlni_w12_watersheds.geojson`（1977年版 W12 ポリゴン）への点内包判定（shapely の
`contains`/`intersects`）で機械的に決定した値——ゾーンと違って「地点の属性を
そのまま転記する」辺ではないことに注意（basis にその旨を明記する）。`parent_id` は
`place_source_ref(source_id='watershed_meta.watershed_id')` 相当の対応から解決し、
対応する流域が place に無ければ例外を投げて止める（`_watershed_relation_rows()`、
`_zone_relation_rows()` と同じ流儀）。

どちらも `fraction` は NOT NULL・常に `1.0`（地点は1つのゾーン・1つの流域に完全に
含まれる。`sites.watershed` は単一列なので地点はゾーンと同様に流域への `within` 辺も
高々1本しか持たない——`scripts/r01_build_registry.py`
`_assert_watershed_relation_child_is_single_valued()` が機械検証する。
`_assert_zone_relation_child_is_single_valued()` と同じ不変条件をkindを変えて
2つ持つ形）。`source_edition_id`（ADR-0006 の列）はまだ持たない。
"""
import csv
import json
import pathlib
import sqlite3

import yaml

from . import common

# site / zone の place_id を発行する scope（Phase A の対象地域は神奈川県だけ）。
PLACE_SCOPE = "jp-14"

PLACE_DIR = pathlib.Path(__file__).resolve().parents[2] / "registry" / "place"

# watershed 節の入力（L1、国土数値情報 W12 流域界 1977年版、377面）。
# common.WATERSHED_JSONL_RELPATH と共有する（指紋計算とビルド側が同じファイルを
# 指す。scripts/registry/common.py の同名の定数のコメント参照）。テストは
# monkeypatch でこのモジュール変数を差し替える（build_taxon.CROSSWALK_CSV と
# 同じ流儀）。
WATERSHED_JSONL = common.ROOT / common.WATERSHED_JSONL_RELPATH


def _load_watershed_jsonl() -> list[dict]:
    """`WATERSHED_JSONL` を1行1レコードの JSON として読む。

    以前は `derived.watershed_meta`（v1 の派生表）を読んでいたが、これは
    「v2 の registry を v1 の出力から作る」循環になっていた（モジュール
    docstring の「watershed」節参照）。読み方を変えても値は1ビットも変わらない
    ことを実測で確認済み（同節参照）。
    """
    if not WATERSHED_JSONL.exists():
        raise FileNotFoundError(
            f"流域界の原本が無い: {WATERSHED_JSONL}\n"
            "リポジトリの data/processed/ に配布物として置く（CLAUDE.md の worktree "
            "運用の symlink 手順を参照。scripts/c*.py で再生成できるものではない）。"
        )
    rows: list[dict] = []
    with WATERSHED_JSONL.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


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


def _site_place_id(site_id: str, place_local_override: str | None = None, *, seen=None) -> str:
    prefix, sep, local = site_id.partition("__")
    if not sep:
        raise ValueError(f"site_id が想定外の形（'__' が無い）: {site_id!r}")
    ns = SITE_NAMESPACE.get(prefix)
    if ns is None:
        raise ValueError(
            f"未知の site_id 名前空間: {site_id!r}（SITE_NAMESPACE に無い。"
            "原本に新しい出典が増えた可能性がある）"
        )
    if not local:
        if not place_local_override:
            raise ValueError(
                f"site_id の局番コードが空: {site_id!r}。"
                "registry/place/site_supplement.csv の place_local 列に明示の local を"
                "記録すること（黙って 'unknown' 等を補って埋めない。"
                "docs/COLLECTOR_CONTRACT.md）。"
            )
        local = place_local_override
    return common.place_id("site", ns, local, scope=PLACE_SCOPE, seen=seen)


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
    # 件数のハードコード assert ではなく、zone 番号の一意性チェックにする（/simplify 修正5）。
    zones = [item["zone"] for item in items]
    dupes = sorted({z for z in zones if zones.count(z) > 1})
    assert not dupes, f"registry/place/zone.yaml の zone が重複している: {dupes}"
    return items


def _zone_relation_rows(
    site_zone_pairs: list[tuple[str, int]],
    zone_place_id_by_external_key: dict[str, str],
) -> list[tuple]:
    """place_relation の地点->ゾーンの辺を組み立てる（sites.zone 由来。ADR-0022 決定2）。

    `site_zone_pairs`: (地点の place_id, sites.zone の値) のペア。sites 本体のうち
    zone IS NOT NULL の行だけが対象（zone は sites にしか無い列なので、
    site_supplement.csv 側の補完地点は対象外）。
    `zone_place_id_by_external_key`: ゾーン番号(文字列) -> place_id
    （place_source_ref(source_id='sites.zone') 相当の対応）。
    `registry/place/zone.yaml` に無いゾーン番号が現れたら、黙って捨てず例外を投げる。

    place_relation の辺の種類が増えたときは、この関数と同じ単一責務の
    `_xxx_relation_rows()` を足して build() から呼ぶ形に揃える（地点->流域
    （`_watershed_relation_rows()`）で実際にこの形で1種類増やした）。
    """
    basis = (
        "sites.zone（Ridge to Reef ゾーン1-5、registry/place/zone.yaml の操作的定義。"
        "標高・海岸線からの距離のみに基づく操作的区分であり、公式の行政区分・学術区分ではない）"
        "の値から機械的に生成。"
    )
    rows: list[tuple] = []
    for site_pid, zone in site_zone_pairs:
        zone_key = str(zone)
        zone_pid = zone_place_id_by_external_key.get(zone_key)
        if zone_pid is None:
            raise ValueError(
                f"sites.zone={zone!r}（地点 place_id={site_pid!r}）を解決できるゾーンが "
                "registry/place/zone.yaml に無い（黙って捨てない。ADR-0022 決定2）。"
            )
        rows.append((zone_pid, site_pid, "within", 1.0, basis))
    return rows


def _watershed_relation_rows(
    site_watershed_pairs: list[tuple[str, str]],
    watershed_place_id_by_external_key: dict[str, str],
) -> list[tuple]:
    """place_relation の地点->流域の辺を組み立てる（sites.watershed 由来。
    Phase B `phase-b/place-attributes`、P-1a。`_zone_relation_rows()` と同じ形）。

    `site_watershed_pairs`: (地点の place_id, sites.watershed の値) のペア。
    sites 本体のうち watershed IS NOT NULL の行だけが対象（watershed は sites に
    しか無い列なので、site_supplement.csv 側の補完地点は対象外）。
    `sites.watershed` は申告値ではなく `scripts/m01_sites.py:110-128` が
    `nlni_w12_watersheds.geojson`（1977年版 W12 ポリゴン）への点内包判定で
    機械的に決定した値（モジュール docstring「place_relation」節参照）。
    `watershed_place_id_by_external_key`: 流域ID(文字列、v1の watershed_id) ->
    place_id（place_source_ref(source_id='watershed_meta.watershed_id') 相当の対応）。
    対応する流域が place に無ければ、黙って捨てず例外を投げる。
    """
    basis = (
        "sites.watershed（scripts/m01_sites.py の nlni_w12_watersheds.geojson "
        "(国土数値情報W12, 1977年版) への点内包判定で機械的に決定。地点の属性を"
        "そのまま転記した値ではない）から機械的に生成。"
    )
    rows: list[tuple] = []
    for site_pid, watershed_id in site_watershed_pairs:
        watershed_pid = watershed_place_id_by_external_key.get(watershed_id)
        if watershed_pid is None:
            raise ValueError(
                f"sites.watershed={watershed_id!r}（地点 place_id={site_pid!r}）を解決できる"
                "流域が place に無い（黙って捨てない。sites.watershed が指す "
                "watershed_meta.watershed_id と、watershed 節が nlni_w12_watersheds.jsonl "
                "から作った place_source_ref が食い違っている可能性がある）。"
            )
        rows.append((watershed_pid, site_pid, "within", 1.0, basis))
    return rows


def build(conn: sqlite3.Connection, src: dict[str, sqlite3.Connection]) -> dict[str, int]:
    """conn: registry.sqlite への書き込み用コネクション。
    src: {'ryuiki': ..., 'cells': ..., 'derived': ...} の読み取り専用コネクション
    （このモジュールは 'derived' を使わない。watershed の入力は WATERSHED_JSONL の
    直読みに切り替え済み——モジュール docstring「watershed」節参照）。
    戻り値: {テーブル名: 挿入した行数}（ログ表示用）。
    """
    ryuiki = src["ryuiki"]

    place_rows: list[tuple] = []
    ref_rows: list[tuple] = []
    # place_id の local を slug 化した後の衝突検知用（common.place_id() が
    # place_kind・namespace ごとに分けて衝突を見る。レビュー指摘: ID の
    # スラッグ化で別々の元キーが黙って同じIDに潰れてはいけない）。
    place_id_seen: dict = {}

    # (地点の place_id, sites.zone の値) のペア。zone IS NOT NULL の行だけ
    # site loop 内で貯める（_zone_relation_rows() に渡す。sites 本体への
    # 2回目の SELECT を避けるため）。
    site_zone_pairs: list[tuple[str, int]] = []
    # (地点の place_id, sites.watershed の値) のペア。watershed IS NOT NULL の
    # 行だけ site loop 内で貯める（_watershed_relation_rows() に渡す。理由は
    # site_zone_pairs と同じ）。
    site_watershed_pairs: list[tuple[str, str]] = []

    # --- site: sites テーブル本体（352件） ---------------------------------
    for row in ryuiki.execute(
        "SELECT site_id, name, lat, lon, elevation_m, source_id, source_ref, zone, watershed FROM sites"
    ):
        pid = _site_place_id(row["site_id"], seen=place_id_seen)
        if row["zone"] is not None:
            site_zone_pairs.append((pid, row["zone"]))
        if row["watershed"] is not None:
            site_watershed_pairs.append((pid, row["watershed"]))
        place_rows.append((
            pid, common.region_id_for_scoped_id(pid), "site", row["name"], row["lat"], row["lon"],
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
        pid = _site_place_id(site_id, sup.get("place_local") or None, seen=place_id_seen)
        name_ja = sup["name_ja"] or None
        lat = float(sup["lat"]) if sup["lat"] else None
        lon = float(sup["lon"]) if sup["lon"] else None
        definition_ref = sup["definition_ref"] or None
        status = "ok" if lat is not None else "needs_review"
        place_rows.append((
            pid, common.region_id_for_scoped_id(pid), "site", name_ja, lat, lon,
            None, None, definition_ref, status,
        ))
        ref_rows.append((pid, site_id, "sites.site_id"))

    # --- watershed: data/processed/nlni_w12_watersheds.jsonl（L1、377件） -----
    # 入力は Phase B `phase-b/place-attributes` で derived.watershed_meta から
    # 切り替えた（モジュール docstring「watershed」節参照）。`place` に載せる5列は
    # 旧実装と同じ列（water_system_name_ja_estimated は v1（build-geo.mjs）が
    # `|| null` で欠落を落としているのに合わせ、ここでも `or None` を使う——
    # 実測ではこの列に空文字列は無い（145件は元から JSON null）ので `or`/`??` の
    # 差は結果に出ないが、v1 の式をそのまま踏襲して再現の根拠を明示する）。
    # 残り4列は place_watershed（属性サテライト）に積む。main_rivers は v1
    # （`?? null`、nullish coalescing）に合わせて空文字列をそのまま持つ
    # （None に丸めない）。
    watershed_attr_rows: list[tuple] = []
    for o in _load_watershed_jsonl():
        pid = common.place_id("watershed", "nlni", o["watershed_id"], scope="common", seen=place_id_seen)
        place_rows.append((
            pid, common.region_id_for_scoped_id(pid), "watershed",
            o.get("water_system_name_ja_estimated") or None,
            o.get("centroid_lat"), o.get("centroid_lon"), None, o.get("area_km2"),
            o.get("source_ref"), "ok",
        ))
        ref_rows.append((pid, o["watershed_id"], "watershed_meta.watershed_id"))
        watershed_attr_rows.append((
            pid,
            o.get("water_system_code_old"),
            o.get("water_system_category_ja"),
            o.get("main_river_names_ja"),
            o.get("data_year"),
        ))

    # --- grid01: ryuiki.organism_records の座標（4,087件） -------------------
    # 旧 place_kind='mesh3'。ADR-0006 のコードリストの mesh3（標準地域メッシュ/
    # 3次メッシュ）とは実体が違うため grid01 に改名した（モジュール docstring参照）。
    # Phase B `phase-b/occurrence-registry` で入力を derived.mesh_all から
    # ryuiki.organism_records の座標そのものに変えた（モジュール docstring「grid01 の
    # 入力を derived.mesh_all から organism_records の座標に変える」参照。年フィルタで
    # 欠落していた3セルと、日付の無い記録しか持たない1セルを拾えるようになる）。
    # 日付の有無・年の範囲でフィルタしない（座標は全行に入っている。lat IS NOT NULL は
    # 実測上つねに真だが、将来座標欠損行が増えても黙って混ぜないための防御として残す）。
    for row in ryuiki.execute(
        "SELECT DISTINCT CAST(FLOOR(lat*100) AS INT) AS mlat, "
        "CAST(FLOOR(lon*100) AS INT) AS mlon "
        "FROM organism_records WHERE lat IS NOT NULL AND lon IS NOT NULL"
    ):
        mlat, mlon = row["mlat"], row["mlon"]
        local = f"{mlat}_{mlon}"
        # namespace=None: common:place:grid01.<mlat>_<mlon>（watershed の
        # "nlni-..." のような出典名前空間は無く、mlat_mlon 自体が本アプリ内で
        # 一意に定まる値のため）。
        pid = common.place_id("grid01", None, local, scope="common", seen=place_id_seen)
        # web/src/lib/geo.ts meshPolygon(): lat0=mlat/100, lon0=mlon/100 がセルの
        # 南西端。place の代表点はセル中心（+0.005度）にする（0.01度グリッドの
        # 定義から機械的に求まる値であり、実世界の座標を推測しているわけではない）。
        lat = mlat / 100 + 0.005
        lon = mlon / 100 + 0.005
        definition_ref = (
            "0.01度グリッド（organism_records: "
            "mlat=CAST(FLOOR(lat*100) AS INT), mlon=CAST(FLOOR(lon*100) AS INT)）の"
            "セル中心。国土地理院の標準地域メッシュ（3次メッシュ）ではなく、本アプリが "
            "organism_records の座標から独自に定義した集計用グリッド"
            "（place_kind='grid01'。ADR-0006 のコードリストからの逸脱の経緯は "
            "registry/README.md 参照）。日付の無い記録の座標も含む"
            "（docs/plans/PHASE_B_OCCURRENCE.md §2-3）。"
        )
        place_rows.append((
            pid, common.region_id_for_scoped_id(pid), "grid01", None, lat, lon,
            None, None, definition_ref, "ok",
        ))
        ref_rows.append((pid, f"grid01:{mlat},{mlon}", "organism_records.lat_lon"))

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
        pid = common.place_id("zone", "r2r", str(n), scope=PLACE_SCOPE, seen=place_id_seen)
        definition_ref = f"{disclaimer} 条件: {item['condition_ja']}。"
        place_rows.append((
            pid, common.region_id_for_scoped_id(pid), "zone", item["name_ja"],
            None, None, None, None, definition_ref, "ok",
        ))
        ref_rows.append((pid, str(n), "sites.zone"))

    # --- place_relation: 地点 -> ゾーン（sites.zone 由来。ADR-0022 決定2） ------
    # ゾーン番号(文字列) -> place_id を ref_rows から引く（source_id='sites.zone' は
    # 上の zone loop が積んだ行だけなので、zone_place_id_by_number のような専用の
    # 対応表を別途維持しなくても ref_rows 一本から求まる）。
    zone_place_id_by_external_key = {
        external_key: place_id
        for place_id, external_key, source_id in ref_rows
        if source_id == "sites.zone"
    }
    zone_relation_rows = _zone_relation_rows(site_zone_pairs, zone_place_id_by_external_key)

    # --- place_relation: 地点 -> 流域（sites.watershed 由来。Phase B
    # `phase-b/place-attributes`、P-1a） ---------------------------------------
    # 流域ID(文字列) -> place_id を ref_rows から引く（source_id=
    # 'watershed_meta.watershed_id' は上の watershed loop が積んだ行だけ）。
    watershed_place_id_by_external_key = {
        external_key: place_id
        for place_id, external_key, source_id in ref_rows
        if source_id == "watershed_meta.watershed_id"
    }
    watershed_relation_rows = _watershed_relation_rows(
        site_watershed_pairs, watershed_place_id_by_external_key
    )

    relation_rows = zone_relation_rows + watershed_relation_rows

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
    common.insert_many(
        conn, "place_relation",
        ["parent_id", "child_id", "relation", "fraction", "basis"],
        relation_rows,
    )
    common.insert_many(
        conn, "place_watershed",
        ["place_id", "water_system_code", "water_system_category", "main_rivers", "data_year"],
        watershed_attr_rows,
    )

    return {
        "place": len(place_rows),
        "place_source_ref": len(ref_rows),
        "place_relation": len(relation_rows),
        "place_watershed": len(watershed_attr_rows),
    }
