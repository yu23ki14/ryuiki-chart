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

# `variable.default_stat`（b04 の T4-2「sum」の絞り込みが読む）。
# weather.precipitation だけ 'sum' にしておくと、RAIN（sensor 側）の日次セルに
# sum 行が足されることをテストできる。
DEFAULT_VARIABLES = [
    # variable_id, default_stat
    ("common:variable:water.bod", None),
    ("common:variable:weather.air_temp", None),
    ("common:variable:weather.precipitation", "sum"),
    ("common:variable:water.water_temp", None),
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
        conn.execute("CREATE TABLE variable (variable_id TEXT PRIMARY KEY, default_stat TEXT)")
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
            "INSERT INTO variable VALUES (?,?)",
            variables if variables is not None else DEFAULT_VARIABLES,
        )
        conn.commit()
    finally:
        conn.close()


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
    """
    conn = sqlite3.connect(f"file:{path}", uri=True)
    conn.execute(create_sql.format(table="observation"))
    placeholders = ", ".join("?" for _ in rows[0])
    conn.executemany(f"INSERT INTO observation VALUES ({placeholders})", rows)
    conn.commit()
    return conn
