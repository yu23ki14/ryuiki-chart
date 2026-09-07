"""scripts/reconcile/common.py の単体テスト（キー自動導出・指紋計算）。"""
import pytest

from reconcile import common, datasource

from .fixtures import make_fixture_db


@pytest.fixture()
def fixture_db(tmp_path):
    path = tmp_path / "fixture.sqlite"
    make_fixture_db(path)
    return path


def test_derive_key_uses_declared_primary_key(fixture_db):
    conn = common.open_readonly(fixture_db)
    try:
        key, source, note = common.derive_key(conn, "t_pk", overrides={})
    finally:
        conn.close()
    assert key == ["raw"]
    assert source == "pk"
    assert note is None


def test_derive_key_auto_two_phase_needs_untyped_column(fixture_db):
    """t_dims は (site, year) だけでは一意にならず、宣言型の無い 'kind' が要る
    （meas_year の 'kind' と同じ形）。Phase A だけで見つからず Phase B に落ちることを確認する。
    """
    conn = common.open_readonly(fixture_db)
    try:
        key, source, note = common.derive_key(conn, "t_dims", overrides={})
    finally:
        conn.close()
    assert key == ["site", "year", "kind"]
    assert source == "auto"
    assert note is None


def test_derive_key_declared_override_takes_precedence(fixture_db):
    """derived_keys.yaml に宣言があれば、自動探索を待たずにそれを使う。"""
    overrides = {
        "t_dims": {
            "key": ["site", "year", "kind"],
            "reason": "テスト: 宣言があれば自動探索より優先されることの確認",
        }
    }
    conn = common.open_readonly(fixture_db)
    try:
        key, source, note = common.derive_key(conn, "t_dims", overrides=overrides)
    finally:
        conn.close()
    assert key == ["site", "year", "kind"]
    assert source == "declared"
    assert "テスト" in note


def test_derive_key_raises_when_no_key_exists_and_no_override(fixture_db):
    """t_dupe は全列を使っても一意にならない（完全重複行がある）。
    宣言も無ければ、黙って全列をキーにせず例外で止まる。
    """
    conn = common.open_readonly(fixture_db)
    try:
        with pytest.raises(RuntimeError, match="derived_keys.yaml"):
            common.derive_key(conn, "t_dupe", overrides={})
    finally:
        conn.close()


def test_derive_key_declared_override_must_itself_be_unique(fixture_db):
    """宣言されたキーであっても一意性は検証する（宣言だから無条件で信用しない）。"""
    overrides = {"t_dupe": {"key": ["a", "b"], "reason": "テスト: わざと一意にならない宣言"}}
    conn = common.open_readonly(fixture_db)
    try:
        with pytest.raises(AssertionError):
            common.derive_key(conn, "t_dupe", overrides=overrides)
    finally:
        conn.close()


def test_format_number_fixed_six_decimals():
    assert common.format_number(1) == "1.000000"
    assert common.format_number(1.23456789) == "1.234568"
    assert common.format_number(0) == "0.000000"


def test_is_numeric_column(fixture_db):
    conn = common.open_readonly(fixture_db)
    try:
        assert common.is_numeric_column(conn, "t_dims", "year") is True
        assert common.is_numeric_column(conn, "t_dims", "avg") is True
        assert common.is_numeric_column(conn, "t_dims", "site") is False
        assert common.is_numeric_column(conn, "t_dims", "kind") is False
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
