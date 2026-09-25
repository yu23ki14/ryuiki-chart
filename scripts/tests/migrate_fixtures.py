"""b03/b04/b05（`scripts/migrate/` パッケージ）用の、本物の `data/db/*.sqlite` を
要さない小さな sqlite フィクスチャ。

`measurements`/`sensor_timeseries`/`sites`（`ryuiki.sqlite` 相当）と
`variable_alias`/`variable`/`place_source_ref`/`place`（`registry.sqlite` 相当）
のうち、b03〜b05 が実際に `SELECT` する列だけを持つ最小限の形にしてある
（実データの全列を真似ない）。

`measurements` と `sensor_timeseries` は実データでは同じ `ryuiki.sqlite` に
同居している（`scripts/b03_build_observation.py` は1つの `--ryuiki-db` から
両方読む）ため、`make_measurements_db` は既定で両方のテーブルを作る
（`sensor_rows` を渡さなければ `sensor_timeseries` は空のまま——測定値のみを
テストしたい既存のテストは何も変える必要が無い）。
"""
from __future__ import annotations

import sqlite3

import b03_build_observation as b03  # scripts/ が sys.path にある前提（scripts/tests/__init__.py 参照）
from migrate import common
from reconcile import common as reconcile_common
from reconcile import datasource

# 既定の2地点×2変数（水質っぽい1変数・気温っぽい1変数）。alias/place は全行解決する
# 「正常系」のベースライン。個々のテストはこれを土台に、崩したい部分だけ差し替える。
DEFAULT_MEASUREMENTS = [
    # measurement_id, site_id, measured_on, variable, source_id, value, value_raw,
    # unit, quality_stage, is_synthetic, source_ref, event_id
    ("m1", "S1", "2020-01-01", "BOD", "src_a", 1.2, "1.2", "mg/L", "公開済", 0, "ref1", "ev1"),
    ("m2", "S1", "2020-01-02", "BOD", "src_a", None, "<0.5", "mg/L", "公開済", 0, "ref1", "ev1"),
    ("m3", "S2", "2020-01-01", "kion", "src_a", 12.3, "12.3", "degC", "公開済", 0, "ref1", None),
]

# `sensor_timeseries` の既定フィクスチャ。日次1系列（src_daily/TEMP_DAILY）・
# 毎時1系列（src_hourly/RAIN。24時ラベル＝日をまたぐケースを含む）・瞬時1系列
# （src_instant/WTEMP）をそれぞれ最小限持つ（T1〜T6 の主要な分岐を一通り踏める
# ように選んだ。site_id は measurements と同じ S1/S2 の名前空間を再利用する
# ——実データでも `place_source_ref(source_id='sites.site_id')` は出典を
# 問わない単一の名前空間なので、フィクスチャでもそれに合わせる）。
DEFAULT_SENSOR_ROWS = [
    # site_id, datastream, phenomenon_time, result, unit, instrument_id, source_id, is_synthetic
    ("S1", "TEMP_DAILY", "2020-01-01", 5.0, "degC", None, "src_daily", 0),
    ("S1", "TEMP_DAILY", "2020-01-02", 7.0, "degC", None, "src_daily", 0),
    ("S1", "RAIN", "2020-01-01T01:00:00+09:00", 1.0, None, None, "src_hourly", 0),
    ("S1", "RAIN", "2020-01-01T02:00:00+09:00", 2.0, None, None, "src_hourly", 0),
    # 「24時」ラベル（翌日 00:00 として ISO 表記済み）。hour_ending で
    # period_start=前日23:00 になり、v1 のラベル日割りとキューブの日割りが
    # ここで1日ずれる（T6 の検証対象）。
    ("S1", "RAIN", "2020-01-02T00:00:00+09:00", 3.0, None, None, "src_hourly", 0),
    ("S1", "WTEMP", "2020-01-01T00:00:00+09:00", 10.0, "degC", None, "src_instant", 0),
    ("S1", "WTEMP", "2020-01-01T12:00:00+09:00", 11.0, "degC", None, "src_instant", 0),
]

DEFAULT_SENSOR_ALIASES = [
    # dataset, alias, source_id, variable_id, unit_id, stat, grain
    # variable_id は measurements 側の既定 alias（"kion"→weather.air_temp）と
    # 意図的に重ならない値にする（T5「tuple → dataset の一意性」——重ねてしまうと
    # assert_alias_tuple_maps_to_single_dataset が全テストで引っかかる）。
    ("sensor_timeseries", "TEMP_DAILY", "src_daily", "common:variable:air.pm25", "common:unit:ug_per_m3", None, "day"),
    ("sensor_timeseries", "RAIN", "src_hourly", "common:variable:weather.precipitation", None, None, "hour"),
    ("sensor_timeseries", "WTEMP", "src_instant", "common:variable:water.water_temp", None, None, "instant"),
]

DEFAULT_ALIASES = [
    ("measurements", "BOD", "src_a", "common:variable:water.bod", "common:unit:mg_per_l", None, "day"),
    ("measurements", "kion", "src_a", "common:variable:weather.air_temp", "common:unit:degc", None, "day"),
] + DEFAULT_SENSOR_ALIASES

DEFAULT_PLACES = [
    # place_id, region_id, place_kind
    ("place_s1", "jp-14", "site"),
    ("place_s2", "jp-14", "site"),
]

DEFAULT_PLACE_REFS = [
    # place_id, external_key, source_id
    ("place_s1", "S1", "sites.site_id"),
    ("place_s2", "S2", "sites.site_id"),
]

# ゾーン（`place_relation`、ADR-0022 決定2）のフィクスチャ。地点→ゾーンの辺を
# テストするときは、DEFAULT_PLACES/DEFAULT_PLACE_REFS にこれらを連結して渡す
# （`make_registry_db` の `places`/`place_refs` は完全上書きのため、足したい側が
# 連結する）。S1 をゾーン1に属させる（S2 はどのゾーンにも属さない——v1 の
# `sites.zone IS NULL` に相当。zone_year/zone_clim では自然に除外される）。
DEFAULT_ZONE_PLACES = [
    ("place_zone1", "jp-14", "zone"),
]

DEFAULT_ZONE_PLACE_REFS = [
    ("place_zone1", "1", "sites.zone"),
]

DEFAULT_PLACE_RELATIONS = [
    # parent_id (ゾーン), child_id (地点), relation, fraction, basis
    ("place_zone1", "place_s1", "within", 1.0, "test"),
]

# ゾーンを1つ足した `places`/`place_refs`（/simplify 指摘: テスト側で
# `DEFAULT_PLACES + DEFAULT_ZONE_PLACES` / `DEFAULT_PLACE_REFS +
# DEFAULT_ZONE_PLACE_REFS` を6箇所書いていたものをここに1組まとめた）。
PLACES_WITH_ZONE = DEFAULT_PLACES + DEFAULT_ZONE_PLACES
PLACE_REFS_WITH_ZONE = DEFAULT_PLACE_REFS + DEFAULT_ZONE_PLACE_REFS

# `variable.default_stat`（b04 の T4-2「sum」の絞り込みが読む）・`name_ja`
# （P-1b の landuse_watershed/landuse_change が `reg.variable.name_ja` を
# landuse_name として読む。既存の4変数はどれも landuse ではないので None のまま）。
# weather.precipitation だけ 'sum' にしておくと、RAIN（sensor 側）の日次セルに
# sum 行が足されることをテストできる。
DEFAULT_VARIABLES = [
    # variable_id, default_stat, name_ja
    ("common:variable:water.bod", None, None),
    ("common:variable:weather.air_temp", None, None),
    ("common:variable:weather.precipitation", "sum", None),
    ("common:variable:water.water_temp", None, None),
]

# `time_label_conventions.yaml` 相当（T2）。既定フィクスチャの `src_hourly`
# （RAIN、5行）だけを宣言する。
DEFAULT_TIME_LABEL_CONVENTIONS_YAML_TEXT = (
    "src_hourly:\n"
    "  convention: hour_ending\n"
    "  expected_row_count: 3\n"
    "  evidence: テスト用\n"
)


def make_measurements_db(path, rows=None, sensor_rows=None) -> None:
    """`measurements` と `sensor_timeseries` の両方を持つ `ryuiki.sqlite` 相当を
    作る（実データと同じく同一ファイルに同居）。`sensor_rows` を渡さなければ
    `sensor_timeseries` は空のまま（measurements だけをテストしたい既存の
    テストはそのまま動く）。
    """
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(
            """CREATE TABLE measurements (
                measurement_id TEXT PRIMARY KEY, site_id TEXT, measured_on TEXT, variable TEXT,
                source_id TEXT, value REAL, value_raw TEXT, unit TEXT, quality_stage TEXT,
                is_synthetic INTEGER, source_ref TEXT, event_id TEXT
            )"""
        )
        conn.executemany(
            "INSERT INTO measurements VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            rows if rows is not None else DEFAULT_MEASUREMENTS,
        )
        conn.execute(
            """CREATE TABLE sensor_timeseries (
                id INTEGER PRIMARY KEY AUTOINCREMENT, site_id TEXT, datastream TEXT,
                phenomenon_time TEXT, result REAL, unit TEXT, instrument_id TEXT,
                source_id TEXT, is_synthetic INTEGER DEFAULT 0
            )"""
        )
        if sensor_rows:
            conn.executemany(
                "INSERT INTO sensor_timeseries "
                "(site_id, datastream, phenomenon_time, result, unit, instrument_id, source_id, is_synthetic) "
                "VALUES (?,?,?,?,?,?,?,?)",
                sensor_rows,
            )
        conn.commit()
    finally:
        conn.close()


def make_registry_db(
    path, aliases=None, places=None, place_refs=None, variables=None, place_relations=None,
) -> None:
    """`place_relations` の既定は空（ゾーンを持たないテストはそのまま動く。
    `phase-b/zone-slice` で `place_relation`（地点→ゾーンの辺、ADR-0022 決定2）
    を新設。DDL は本物の `scripts/schema_registry.sql` の `place_relation` と
    完全に一致させてある——`id INTEGER PRIMARY KEY AUTOINCREMENT` を含む6列。
    `place_relations` に渡す各要素は `id` を除いた
    `(parent_id, child_id, relation, fraction, basis)` の5つ組）。
    """
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(
            """CREATE TABLE variable_alias (
                dataset TEXT, alias TEXT, source_id TEXT, variable_id TEXT, unit_id TEXT,
                stat TEXT, grain TEXT
            )"""
        )
        conn.execute(
            "CREATE TABLE place (place_id TEXT PRIMARY KEY, region_id TEXT, place_kind TEXT)"
        )
        conn.execute(
            "CREATE TABLE place_source_ref (place_id TEXT, external_key TEXT, source_id TEXT)"
        )
        conn.execute(
            "CREATE TABLE place_relation (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "parent_id TEXT NOT NULL, child_id TEXT NOT NULL, relation TEXT NOT NULL, "
            "fraction REAL NOT NULL, basis TEXT)"
        )
        conn.execute(
            "CREATE TABLE variable (variable_id TEXT PRIMARY KEY, default_stat TEXT, name_ja TEXT)"
        )
        conn.executemany(
            "INSERT INTO variable_alias VALUES (?,?,?,?,?,?,?)",
            aliases if aliases is not None else DEFAULT_ALIASES,
        )
        conn.executemany(
            "INSERT INTO place VALUES (?,?,?)", places if places is not None else DEFAULT_PLACES
        )
        conn.executemany(
            "INSERT INTO place_source_ref VALUES (?,?,?)",
            place_refs if place_refs is not None else DEFAULT_PLACE_REFS,
        )
        conn.executemany(
            "INSERT INTO place_relation (parent_id, child_id, relation, fraction, basis) "
            "VALUES (?,?,?,?,?)",
            place_relations if place_relations is not None else [],
        )
        conn.executemany(
            "INSERT INTO variable VALUES (?,?,?)",
            variables if variables is not None else DEFAULT_VARIABLES,
        )
        conn.commit()
    finally:
        conn.close()


# P-1b（土地利用、docs/plans/PHASE_B_LANDUSE.md）。`scripts/b03_build_observation.py`
# の `_ingest_landuse`/`scripts/b05_project_v1.py` の landuse_watershed/
# landuse_change 用フィクスチャ。実データと同じ列レイアウト（CSVヘッダ）・
# 同じ「2006/2016でコード体系が違う」「同じ日本語名の区分は年をまたいで同じ
# variable_id を共有する」構造を、2流域×最小限の区分数で再現する:
#   - W1: 2006に paddy(コード'1')・forest(コード'5') の2区分、2016は paddy
#     (コード'0100')だけ（forest が年をまたがない区分の再現。landuse_change の
#     km2_2016=0 の経路を踏む）。
#   - W2: 2006/2016とも paddy のみ（複数流域の再現）。
LANDUSE_SOURCE_ID = "test_landuse_source"

LANDUSE_CSV_HEADER = (
    "source_id,source_ref,data_year,watershed_id,water_system_code_old,"
    "water_system_name_ja_estimated,landuse_code_raw,landuse_name_ja,n_cells,area_km2\n"
)

DEFAULT_LANDUSE_CSV_ROWS = [
    # source_id, source_ref, data_year, watershed_id, water_system_code_old,
    # water_system_name_ja_estimated, landuse_code_raw, landuse_name_ja, n_cells, area_km2
    (LANDUSE_SOURCE_ID, "ref2006", 2006, "W1", "OLD1", "水系1", "1", "田", 10, 1.5),
    (LANDUSE_SOURCE_ID, "ref2006", 2006, "W1", "OLD1", "水系1", "5", "森林", 20, 2.0),
    (LANDUSE_SOURCE_ID, "ref2006", 2006, "W2", "OLD2", "水系2", "1", "田", 30, 3.0),
    (LANDUSE_SOURCE_ID, "ref2016", 2016, "W1", "OLD1", "水系1", "0100", "田", 12, 1.8),
    (LANDUSE_SOURCE_ID, "ref2016", 2016, "W2", "OLD2", "水系2", "0100", "田", 32, 3.5),
]

DEFAULT_WATERSHED_PLACES = [
    # place_id, region_id, place_kind（common スコープなので region_id=NULL。
    # ADR-0022 決定1）
    ("place_w1", None, "watershed"),
    ("place_w2", None, "watershed"),
]

DEFAULT_WATERSHED_PLACE_REFS = [
    # place_id, external_key, source_id
    ("place_w1", "W1", "watershed_meta.watershed_id"),
    ("place_w2", "W2", "watershed_meta.watershed_id"),
]

DEFAULT_LANDUSE_ALIASES = [
    # dataset, alias, source_id, variable_id, unit_id, stat, grain
    ("nlni_l03b_landuse_by_watershed@2006", "1:area_km2", LANDUSE_SOURCE_ID,
     "common:variable:landuse.paddy", "common:unit:km2", "sum", "year"),
    ("nlni_l03b_landuse_by_watershed@2006", "1:n_cells", LANDUSE_SOURCE_ID,
     "common:variable:landuse.paddy_n_cells", "common:unit:count", "sum", "year"),
    ("nlni_l03b_landuse_by_watershed@2006", "5:area_km2", LANDUSE_SOURCE_ID,
     "common:variable:landuse.forest", "common:unit:km2", "sum", "year"),
    ("nlni_l03b_landuse_by_watershed@2006", "5:n_cells", LANDUSE_SOURCE_ID,
     "common:variable:landuse.forest_n_cells", "common:unit:count", "sum", "year"),
    ("nlni_l03b_landuse_by_watershed@2016", "0100:area_km2", LANDUSE_SOURCE_ID,
     "common:variable:landuse.paddy", "common:unit:km2", "sum", "year"),
    ("nlni_l03b_landuse_by_watershed@2016", "0100:n_cells", LANDUSE_SOURCE_ID,
     "common:variable:landuse.paddy_n_cells", "common:unit:count", "sum", "year"),
]

# `variable.default_stat`/`name_ja`（landuse 分。DEFAULT_VARIABLES に連結して
# 渡す）。`name_ja` は `scripts/b05_project_v1.py` の landuse_watershed が
# CSV の landuse_name_ja をそのまま復元するのに使う値（P-1b オーナー決定2）。
DEFAULT_LANDUSE_VARIABLES = [
    ("common:variable:landuse.paddy", "sum", "田"),
    ("common:variable:landuse.paddy_n_cells", "sum", "田（セル数）"),
    ("common:variable:landuse.forest", "sum", "森林"),
    ("common:variable:landuse.forest_n_cells", "sum", "森林（セル数）"),
]

DEFAULT_LANDUSE_SOURCE_REGIONS_YAML_TEXT = (
    "sources:\n"
    f"  {LANDUSE_SOURCE_ID}:\n"
    "    region_id: jp-14\n"
    "    consumer: observation\n"
    f"    expected_row_count: {len(DEFAULT_LANDUSE_CSV_ROWS)}\n"
    "    evidence: テスト用\n"
    "regions:\n"
    "  jp-14:\n"
    "    utc_offset: \"+09:00\"\n"
    "    evidence: テスト用\n"
)


def make_landuse_csv(path, rows=None) -> None:
    """`data/processed/nlni_l03b_landuse_by_watershed.csv` 相当のテスト用
    フィクスチャを書く（既定は `DEFAULT_LANDUSE_CSV_ROWS`）。
    """
    lines = [LANDUSE_CSV_HEADER]
    for row in rows if rows is not None else DEFAULT_LANDUSE_CSV_ROWS:
        lines.append(",".join(str(v) for v in row) + "\n")
    path.write_text("".join(lines), encoding="utf-8")


def make_landuse_source_regions_yaml(path, text: str | None = None) -> None:
    """`source_regions.yaml`（consumer='observation' の土地利用宣言）相当の
    テスト用フィクスチャを書く（既定は `DEFAULT_LANDUSE_SOURCE_REGIONS_YAML_TEXT`）。
    """
    path.write_text(
        text if text is not None else DEFAULT_LANDUSE_SOURCE_REGIONS_YAML_TEXT, encoding="utf-8"
    )


def make_landuse_registry_db(registry_db) -> None:
    """土地利用（面積・セル数）を検証するテスト用の registry フィクスチャ
    （`test_b03_build_observation.py`・`test_b05_project_v1.py` の両方が使う
    共通ヘルパ。コードレビュー指摘9: 以前は2ファイルにほぼ同じ関数が
    重複して定義され、しかも `variables` の中身が食い違っていた
    ——b03 側は `DEFAULT_LANDUSE_VARIABLES` のみ、b05 側は
    `DEFAULT_VARIABLES + DEFAULT_LANDUSE_VARIABLES`。後者（より実データに
    近い、base の4変数も含む形）を正として統合した。`_ingest_landuse`
    （b03）自体は `variable` テーブルを読まないため、b03 側のテストの
    挙動はどちらの `variables` でも変わらない）。
    """
    make_registry_db(
        registry_db,
        aliases=DEFAULT_ALIASES + DEFAULT_LANDUSE_ALIASES,
        places=DEFAULT_PLACES + DEFAULT_WATERSHED_PLACES,
        place_refs=DEFAULT_PLACE_REFS + DEFAULT_WATERSHED_PLACE_REFS,
        variables=DEFAULT_VARIABLES + DEFAULT_LANDUSE_VARIABLES,
    )


def build_observation(
    tmp_path, measurements_db, registry_db, exceptions_yaml, time_conventions_yaml, out,
    *, landuse_csv_rows=None, source_regions_yaml_text=None,
):
    """`b03.build_and_write_observation` を、P-1b の土地利用2引数
    （`source_regions_yaml`/`landuse_csv`）を明示的に補って呼ぶ共通ヘルパ
    （`test_b03_build_observation.py`・`test_b05_project_v1.py` の両方が使う。
    コードレビュー指摘9・10）。

    `landuse_csv_rows`/`source_regions_yaml_text` を渡さなければ「土地利用
    0行」の空フィクスチャを使う——土地利用を検証しない既存のテストは
    そのまま動く。本番の `main()` と同じ「明示的に渡す」経路をテストでも
    通す（`build_and_write_observation` の既定値を monkeypatch で差し替える
    設計はやめた。理由はそちらの docstring 参照）。
    """
    landuse_csv = tmp_path / "_landuse.csv"
    make_landuse_csv(landuse_csv, rows=landuse_csv_rows if landuse_csv_rows is not None else [])
    source_regions_yaml = tmp_path / "_source_regions.yaml"
    make_landuse_source_regions_yaml(
        source_regions_yaml,
        text=source_regions_yaml_text if source_regions_yaml_text is not None else "sources: {}\nregions: {}\n",
    )
    return b03.build_and_write_observation(
        measurements_db, registry_db, exceptions_yaml, time_conventions_yaml, out,
        source_regions_yaml, landuse_csv,
    )


def make_time_label_conventions_yaml(path, text: str | None = None) -> None:
    """`time_label_conventions.yaml` 相当のフィクスチャを書く。既定は
    `DEFAULT_TIME_LABEL_CONVENTIONS_YAML_TEXT`（`src_hourly` のみ宣言）。
    """
    path.write_text(text if text is not None else DEFAULT_TIME_LABEL_CONVENTIONS_YAML_TEXT, encoding="utf-8")


def make_v2_db_with_observation(path, create_sql: str, rows: list[tuple]) -> sqlite3.Connection:
    """`observation` テーブルだけを持つ `v2.sqlite` 相当のフィクスチャを作り、
    開いたままの接続を返す（b04 の単体テスト用。呼び出し側が `build_cube(conn,
    registry_db)` に直接渡し、使い終わったら自分で `close()` する）。`create_sql`
    は呼び出し側が `b03_build_observation._CREATE_OBSERVATION_SQL` を渡すことを
    想定している（本物のスキーマとテストのスキーマがずれる事故を避ける——
    スキーマの正は b03 の定義1箇所だけに置く）。A-1 以降 `_CREATE_OBSERVATION_SQL`
    は `{table}` プレースホルダを持つ（`migrate.common.staged_table` が本番名/
    作業用テーブル名のどちらでも使えるように）ので、ここで `"observation"` を
    埋めて実行する。

    `uri=True` で開く（`b04_build_cube.build_cube` が `registry_db` を
    `file:...?mode=ro` として ATTACH するのに必要。実データで踏んだのと同じ
    理由——`scripts/b04_build_cube.py` の `main()` のコメント参照）。

    段階間の指紋（Issue #37 #1）: `scripts/b03_build_observation.py` が本物の
    実行の最後に記録するのと同じ `pipeline_fingerprint` を、ここでも記録する
    （b04 が `build_cube()` の先頭で `common.assert_stage_fingerprint_fresh` を
    呼ぶため、これが無いと本物の b03 を経由しないこのフィクスチャの
    全テストが「指紋が記録されていない」で落ちてしまう）。
    """
    conn = sqlite3.connect(f"file:{path}", uri=True)
    conn.execute(create_sql.format(table="observation"))
    placeholders = ", ".join("?" for _ in rows[0])
    conn.executemany(f"INSERT INTO observation VALUES ({placeholders})", rows)
    common.record_stage_fingerprint(conn, "observation")
    conn.commit()
    return conn


def table_content_hash(path, table: str, key_columns: list[str]) -> str:
    """`path`（sqlite ファイル）の `table` の content_hash（sha256）を返す。

    「同じ入力を2回ビルドしてバイト一致を確認する」決定論テストで
    `test_b03_build_observation.py`（`observation`、鍵 `source_table`/
    `source_row_id`）・`test_b04_build_cube.py`（`observation_agg`、鍵
    `b04.DIM_COLUMNS`）の両方が使う（/simplify 指摘9: 同じ実装をそれぞれが
    別々に持っていたものを1つに集約した）。
    """
    conn = reconcile_common.open_readonly(path)
    try:
        src = datasource.SqliteSource(conn)
        columns = src.columns(table)
        numeric = reconcile_common.numeric_columns_of(conn, table, columns)
        fp = reconcile_common.compute_fingerprint(src, table, columns, key_columns, numeric)
        return fp["content_hash"]
    finally:
        conn.close()
