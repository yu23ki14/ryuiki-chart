"""b03/b04/b05（`scripts/migrate/` パッケージ）用の、本物の `data/db/*.sqlite` を
要さない小さな sqlite フィクスチャ。

`measurements`/`sites`（`ryuiki.sqlite` 相当）と `variable_alias`/
`place_source_ref`/`place`（`registry.sqlite` 相当）のうち、b03〜b05 が実際に
`SELECT` する列だけを持つ最小限の形にしてある（実データの全列を真似ない）。
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

DEFAULT_ALIASES = [
    # dataset, alias, source_id, variable_id, unit_id, stat, grain
    ("measurements", "BOD", "src_a", "common:variable:water.bod", "common:unit:mg_per_l", None, "day"),
    ("measurements", "kion", "src_a", "common:variable:weather.air_temp", "common:unit:degc", None, "day"),
]

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


def make_measurements_db(path, rows=None) -> None:
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
        conn.commit()
    finally:
        conn.close()


def make_registry_db(path, aliases=None, places=None, place_refs=None) -> None:
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
        conn.commit()
    finally:
        conn.close()


def make_v2_db_with_observation(path, create_sql: str, rows: list[tuple]) -> sqlite3.Connection:
    """`observation` テーブルだけを持つ `v2.sqlite` 相当のフィクスチャを作り、
    開いたままの接続を返す（b04 の単体テスト用。呼び出し側が `build_cube(conn)`
    に直接渡し、使い終わったら自分で `close()` する）。`create_sql` は呼び出し側が
    `b03_build_observation._CREATE_OBSERVATION_SQL` を渡すことを想定している
    （本物のスキーマとテストのスキーマがずれる事故を避ける——スキーマの正は
    b03 の定義1箇所だけに置く）。
    """
    conn = sqlite3.connect(str(path))
    conn.execute(create_sql)
    placeholders = ", ".join("?" for _ in rows[0])
    conn.executemany(f"INSERT INTO observation VALUES ({placeholders})", rows)
    conn.commit()
    return conn
