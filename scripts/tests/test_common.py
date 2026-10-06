"""scripts/reconcile/common.py の単体テスト（指紋計算・数値の正準化・YAML 読み込み）。"""

import pytest

from reconcile import common, datasource

from .fixtures import make_fixture_db


@pytest.fixture()
def fixture_db(tmp_path):
    path = tmp_path / "fixture.sqlite"
    make_fixture_db(path)
    return path


def test_format_number_fixed_six_decimals():
    assert common.format_number(1) == "1.000000"
    assert common.format_number(1.23456789) == "1.234568"
    assert common.format_number(0) == "0.000000"


def test_numeric_columns_of(fixture_db):
    """回帰テスト（レビュー指摘 B-3）。列ごとに別クエリを打っていたのを
    1テーブル1クエリにまとめた後も、判定結果自体は変わらないこと。
    """
    conn = common.open_readonly(fixture_db)
    try:
        columns = common.get_columns(conn, "t_dims")
        numeric = common.numeric_columns_of(conn, "t_dims", columns)
    finally:
        conn.close()
    assert numeric == ["year", "n", "avg"]


def test_numeric_columns_of_empty_columns_list(fixture_db):
    conn = common.open_readonly(fixture_db)
    try:
        assert common.numeric_columns_of(conn, "t_dims", []) == []
    finally:
        conn.close()


def test_compute_fingerprint_is_deterministic_across_two_runs(fixture_db):
    columns = ["site", "year", "kind", "n", "avg"]
    key = ["site", "year", "kind"]
    numeric = ["year", "n", "avg"]

    conn1 = common.open_readonly(fixture_db)
    fp1 = common.compute_fingerprint(datasource.SqliteSource(conn1), "t_dims", columns, key, numeric)
    conn1.close()

    conn2 = common.open_readonly(fixture_db)
    fp2 = common.compute_fingerprint(datasource.SqliteSource(conn2), "t_dims", columns, key, numeric)
    conn2.close()

    assert fp1 == fp2
    assert fp1["row_count"] == 4


def test_compute_fingerprint_detects_a_single_changed_value(fixture_db, tmp_path):
    import sqlite3

    columns = ["site", "year", "kind", "n", "avg"]
    key = ["site", "year", "kind"]
    numeric = ["year", "n", "avg"]

    conn = common.open_readonly(fixture_db)
    baseline_fp = common.compute_fingerprint(datasource.SqliteSource(conn), "t_dims", columns, key, numeric)
    conn.close()

    changed_path = tmp_path / "changed.sqlite"
    make_fixture_db(changed_path)
    edit_conn = sqlite3.connect(str(changed_path))
    edit_conn.execute("UPDATE t_dims SET avg = 9.99 WHERE site='s1' AND year=2020 AND kind='daily'")
    edit_conn.commit()
    edit_conn.close()

    conn2 = common.open_readonly(changed_path)
    changed_fp = common.compute_fingerprint(datasource.SqliteSource(conn2), "t_dims", columns, key, numeric)
    conn2.close()

    assert changed_fp["content_hash"] != baseline_fp["content_hash"]
    assert changed_fp["row_count"] == baseline_fp["row_count"]
    assert changed_fp["numeric_stats"]["avg"] != baseline_fp["numeric_stats"]["avg"]


def test_load_yaml_returns_empty_dict_for_a_missing_or_empty_file(tmp_path):
    assert common.load_yaml(tmp_path / "none.yaml") == {}
    empty = tmp_path / "empty.yaml"
    empty.write_text("", encoding="utf-8")
    assert common.load_yaml(empty) == {}


def test_load_yaml_reads_a_mapping(tmp_path):
    path = tmp_path / "a.yaml"
    path.write_text("a:\n  b: 1\n", encoding="utf-8")
    assert common.load_yaml(path) == {"a": {"b": 1}}
