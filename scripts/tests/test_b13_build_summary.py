"""scripts/b13_build_summary.py の統合テスト。

本物の `data/db/v2.sqlite`（原本由来）を要さず、`scripts/tests/migrate_fixtures.py`
の `make_observation_agg_fixture` が作る小さな `observation_agg` だけで完結する。
"""
from __future__ import annotations

import pathlib
import sqlite3

import pytest
import yaml

import b04_build_cube as b04
import b13_build_summary as b13
from migrate import common

from .migrate_fixtures import make_observation_agg_fixture

ROOT = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_YAML = ROOT / "aggregations" / "serving.yaml"

# `b04.DIM_COLUMNS` の並び: region_id, place_id, place_kind, variable_id,
# obs_stat, unit_id, value_grain, period_start, period_end, grain, input_grain, stat
# に続けて value_zero, value_lod, n, n_censored, n_not_detected, n_places,
# built_from, spec_version。

_ROWS = [
    # p1・2020年・n=10・censored=1
    ("r1", "p1", "site", "v.bod", "mean", "unit.mgl", "day", "2020-01-01", "2020-12-31",
     "year", "day", "mean", 1.0, 1.1, 10, 1, 0, 1, "obs", "v2"),
    # p1・2021年・n=5・censored=0
    ("r1", "p1", "site", "v.bod", "mean", "unit.mgl", "day", "2021-01-01", "2021-12-31",
     "year", "day", "mean", 3.0, 3.1, 5, 0, 0, 1, "obs", "v2"),
    # p2・2020年・n=7・censored=2
    ("r1", "p2", "site", "v.bod", "mean", "unit.mgl", "day", "2020-01-01", "2020-12-31",
     "year", "day", "mean", 5.0, 5.2, 7, 2, 0, 1, "obs", "v2"),
    # filter 対象外: place_kind='watershed'（site ではない）
    ("r1", "w1", "watershed", "v.bod", "mean", "unit.mgl", "day", "2020-01-01", "2020-12-31",
     "year", "day", "mean", 9.0, 9.0, 999, 0, 0, 1, "obs", "v2"),
    # filter 対象外: stat='min'（非代表統計量。mean のみを対象にする）
    ("r1", "p1", "site", "v.bod", "mean", "unit.mgl", "day", "2020-01-01", "2020-12-31",
     "year", "day", "min", 8.0, 8.0, 888, 0, 0, 1, "obs", "v2"),
    # filter 対象外: grain='month'（year/fiscal_year のみを対象にする）
    ("r1", "p1", "site", "v.bod", "mean", "unit.mgl", "day", "2020-01-01", "2020-01-31",
     "month", "day", "mean", 7.0, 7.0, 777, 0, 0, 1, "obs", "v2"),
]

# 機械検証3（無作為抽出した群を、b13 の生成 SQL とは独立の固定 SQL で再計算して
# 一致を確認する）用の、宣言をなぞらない別実装。`aggregations/serving.yaml` の
# 内容が変わったら、この定数もオーナーが手で追随させること（自動生成しない
# ——それでは「独立」でなくなる）。
_REFERENCE_SQL = {
    "summary_variable_catalog": """
        SELECT variable_id, obs_stat, unit_id, value_grain, grain, input_grain,
               SUM(n), COUNT(DISTINCT place_id),
               MIN(CAST(substr(period_start, 1, 4) AS INTEGER)),
               MAX(CAST(substr(period_start, 1, 4) AS INTEGER)),
               SUM(n_censored), SUM(n_not_detected)
        FROM observation_agg
        WHERE place_kind = 'site' AND grain IN ('year', 'fiscal_year') AND stat = 'mean'
        GROUP BY variable_id, obs_stat, unit_id, value_grain, grain, input_grain
        ORDER BY variable_id, obs_stat, unit_id, value_grain, grain, input_grain
    """,
    "summary_place_variable": """
        SELECT place_id, variable_id, obs_stat, unit_id, value_grain, grain, input_grain,
               SUM(n),
               MIN(CAST(substr(period_start, 1, 4) AS INTEGER)),
               MAX(CAST(substr(period_start, 1, 4) AS INTEGER)),
               AVG(value_zero), AVG(value_lod),
               SUM(n_censored), SUM(n_not_detected)
        FROM observation_agg
        WHERE place_kind = 'site' AND grain IN ('year', 'fiscal_year') AND stat = 'mean'
        GROUP BY place_id, variable_id, obs_stat, unit_id, value_grain, grain, input_grain
        ORDER BY place_id, variable_id, obs_stat, unit_id, value_grain, grain, input_grain
    """,
}

_SELECT_ORDER = {
    "summary_variable_catalog": (
        "SELECT variable_id, obs_stat, unit_id, value_grain, grain, input_grain, "
        "n, n_places, y_from, y_to, n_censored, n_not_detected FROM summary_variable_catalog "
        "ORDER BY variable_id, obs_stat, unit_id, value_grain, grain, input_grain"
    ),
    "summary_place_variable": (
        "SELECT place_id, variable_id, obs_stat, unit_id, value_grain, grain, input_grain, "
        "n, y_from, y_to, avg_zero, avg_lod, n_censored, n_not_detected FROM summary_place_variable "
        "ORDER BY place_id, variable_id, obs_stat, unit_id, value_grain, grain, input_grain"
    ),
}


def _write_yaml(tmp_path, data: dict, name: str = "serving.yaml") -> pathlib.Path:
    path = tmp_path / name
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def _load_real_yaml() -> dict:
    return yaml.safe_load(DEFAULT_YAML.read_text(encoding="utf-8"))


def test_build_summary_creates_both_tables_and_conservation_holds(tmp_path):
    db_path = make_observation_agg_fixture(tmp_path, _ROWS)
    conn = sqlite3.connect(f"file:{db_path}", uri=True)
    try:
        stats = b13.build_summary(conn, DEFAULT_YAML)

        assert set(stats) == set(common.V2_SUMMARY_TABLES)
        # 機械検証4: 行数 > 0。
        assert stats["summary_variable_catalog"]["n_rows"] == 1  # 1 variable × 1 obs_stat/unit/grain 組
        assert stats["summary_place_variable"]["n_rows"] == 2  # p1・p2

        # 機械検証3の裏付け: filter 対象外の3行（watershed/非mean/month、
        # n=999/888/777）は一切含まれない——含まれていれば SUM(n) が
        # 22（=10+5+7）から大きくずれる。
        cat_total = conn.execute("SELECT SUM(n) FROM summary_variable_catalog").fetchone()[0]
        place_total = conn.execute("SELECT SUM(n) FROM summary_place_variable").fetchone()[0]
        assert cat_total == 22
        assert place_total == 22
        assert stats["summary_variable_catalog"]["sum_n"] == 22
        assert stats["summary_place_variable"]["sum_n"] == 22

        cat_row = conn.execute(
            "SELECT n, n_places, y_from, y_to, n_censored, n_not_detected FROM summary_variable_catalog"
        ).fetchone()
        assert cat_row == (22, 2, 2020, 2021, 3, 0)  # n_places は distinct place_id（p1, p2）

        place_rows = {
            r[0]: r for r in conn.execute(
                "SELECT place_id, n, y_from, y_to, avg_zero, avg_lod, n_censored "
                "FROM summary_place_variable"
            )
        }
        assert place_rows["p1"] == ("p1", 15, 2020, 2021, 2.0, 2.1, 1)
        assert place_rows["p2"] == ("p2", 7, 2020, 2020, 5.0, 5.2, 2)
    finally:
        conn.close()


def test_build_summary_matches_independent_reference_sql(tmp_path):
    """機械検証3の裏付け: b13 が生成した SQL とは別に手書きした `_REFERENCE_SQL`
    で observation_agg を直接再集計し、実際に作られた summary 表の内容と
    一致することを確認する（宣言〔YAML〕を読むコード自身のバグを、宣言を
    経由しない別実装で検出する）。
    """
    db_path = make_observation_agg_fixture(tmp_path, _ROWS)
    conn = sqlite3.connect(f"file:{db_path}", uri=True)
    try:
        b13.build_summary(conn, DEFAULT_YAML)
        for table_name, reference_sql in _REFERENCE_SQL.items():
            expected = conn.execute(reference_sql).fetchall()
            actual = conn.execute(_SELECT_ORDER[table_name]).fetchall()
            assert actual == expected, table_name
    finally:
        conn.close()


def test_build_summary_raises_when_observation_agg_is_stale(tmp_path):
    """段階間の指紋（`assert_stage_fingerprint_fresh`）: observation_agg の
    中身を、指紋を記録し直さずに変えると（b04 未実行のまま再実行、を模す）
    `common.MigrationError` で止まる。
    """
    db_path = make_observation_agg_fixture(tmp_path, _ROWS)
    conn = sqlite3.connect(f"file:{db_path}", uri=True)
    try:
        conn.execute(
            "UPDATE observation_agg SET n = 12345 WHERE place_id = 'p1' AND period_start = '2020-01-01'"
        )
        conn.commit()
        with pytest.raises(common.MigrationError, match="scripts/b04_build_cube.py"):
            b13.build_summary(conn, DEFAULT_YAML)
    finally:
        conn.close()


def test_build_summary_raises_when_filter_matches_no_rows(tmp_path):
    """機械検証4（行数 > 0）: filter が絞りすぎて0行になれば止まる。
    `_ROWS` に `grain='fiscal_year'` の行は無いので、filter をそちらだけに
    絞ったYAMLを使えば必ず0行になる。
    """
    raw = _load_real_yaml()
    raw["summaries"]["summary_variable_catalog"]["filter"]["grain"] = ["fiscal_year"]
    raw["summaries"]["summary_place_variable"]["filter"]["grain"] = ["fiscal_year"]
    yaml_path = _write_yaml(tmp_path, raw)

    db_path = make_observation_agg_fixture(tmp_path, _ROWS)
    conn = sqlite3.connect(f"file:{db_path}", uri=True)
    try:
        with pytest.raises(common.MigrationError, match="0行"):
            b13.build_summary(conn, yaml_path)
    finally:
        conn.close()


def test_build_summary_raises_on_unknown_fn(tmp_path):
    raw = _load_real_yaml()
    raw["summaries"]["summary_variable_catalog"]["measures"]["n"]["fn"] = "median"  # 未知
    yaml_path = _write_yaml(tmp_path, raw)

    db_path = make_observation_agg_fixture(tmp_path, _ROWS)
    conn = sqlite3.connect(f"file:{db_path}", uri=True)
    try:
        with pytest.raises(common.MigrationError, match="fn が未知"):
            b13.build_summary(conn, yaml_path)
    finally:
        conn.close()


def test_build_summary_raises_on_unknown_measure_column(tmp_path):
    raw = _load_real_yaml()
    raw["summaries"]["summary_variable_catalog"]["measures"]["n"]["col"] = "not_a_real_column"
    yaml_path = _write_yaml(tmp_path, raw)

    db_path = make_observation_agg_fixture(tmp_path, _ROWS)
    conn = sqlite3.connect(f"file:{db_path}", uri=True)
    try:
        with pytest.raises(common.MigrationError, match="col が未知の列"):
            b13.build_summary(conn, yaml_path)
    finally:
        conn.close()


def test_build_summary_raises_on_unknown_filter_column(tmp_path):
    raw = _load_real_yaml()
    raw["summaries"]["summary_variable_catalog"]["filter"]["n"] = 1  # n は次元キーではない
    yaml_path = _write_yaml(tmp_path, raw)

    db_path = make_observation_agg_fixture(tmp_path, _ROWS)
    conn = sqlite3.connect(f"file:{db_path}", uri=True)
    try:
        with pytest.raises(common.MigrationError, match="filter に未知の列"):
            b13.build_summary(conn, yaml_path)
    finally:
        conn.close()


def test_build_summary_raises_on_key_not_matching_group_by(tmp_path):
    raw = _load_real_yaml()
    raw["summaries"]["summary_variable_catalog"]["key"] = ["variable_id"]  # group_by と不一致
    yaml_path = _write_yaml(tmp_path, raw)

    db_path = make_observation_agg_fixture(tmp_path, _ROWS)
    conn = sqlite3.connect(f"file:{db_path}", uri=True)
    try:
        with pytest.raises(common.MigrationError, match="key は group_by と同じ集合"):
            b13.build_summary(conn, yaml_path)
    finally:
        conn.close()


def test_build_summary_raises_on_spec_version_mismatch(tmp_path):
    raw = _load_real_yaml()
    raw["spec_version"] = "serving-summary/v999"
    yaml_path = _write_yaml(tmp_path, raw)

    db_path = make_observation_agg_fixture(tmp_path, _ROWS)
    conn = sqlite3.connect(f"file:{db_path}", uri=True)
    try:
        with pytest.raises(common.MigrationError, match="SUMMARY_SPEC_VERSION"):
            b13.build_summary(conn, yaml_path)
    finally:
        conn.close()


def test_build_summary_raises_when_summaries_table_set_does_not_match(tmp_path):
    raw = _load_real_yaml()
    del raw["summaries"]["summary_place_variable"]
    yaml_path = _write_yaml(tmp_path, raw)

    db_path = make_observation_agg_fixture(tmp_path, _ROWS)
    conn = sqlite3.connect(f"file:{db_path}", uri=True)
    try:
        with pytest.raises(common.MigrationError, match="V2_SUMMARY_TABLES"):
            b13.build_summary(conn, yaml_path)
    finally:
        conn.close()


def test_build_summary_validates_all_tables_before_writing_any_sql(tmp_path):
    """機械検証1は summary 2表**両方**を、SQL を1つも投げる前に検証する
    （`build_summary` docstring 参照）——1表目（`summary_variable_catalog`）は
    正しいが2表目（`summary_place_variable`）の宣言が壊れているとき、1表目も
    作られない（作られてしまうと、次回失敗時に1表目だけ新しく2表目だけ
    古いという食い違った状態が残る）。
    """
    raw = _load_real_yaml()
    raw["summaries"]["summary_place_variable"]["measures"]["n"]["fn"] = "median"
    yaml_path = _write_yaml(tmp_path, raw)

    db_path = make_observation_agg_fixture(tmp_path, _ROWS)
    conn = sqlite3.connect(f"file:{db_path}", uri=True)
    try:
        with pytest.raises(common.MigrationError, match="fn が未知"):
            b13.build_summary(conn, yaml_path)
        tables = {
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'summary_%'"
            )
        }
        assert tables == set(), f"検証失敗にもかかわらず summary 表が作られている: {tables}"
    finally:
        conn.close()
