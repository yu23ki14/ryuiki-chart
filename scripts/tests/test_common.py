"""scripts/reconcile/common.py の単体テスト（キー自動導出・指紋計算）。"""
import pytest

from reconcile import common, datasource

from .fixtures import make_fixture_db, make_null_key_fixture_db


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


def test_derive_key_null_in_typed_dimension_column_is_not_pruned_away(tmp_path):
    """回帰テスト（レビュー指摘 #1）。

    `t_null_dim` は `(grp, sub)` が一意な次元列だけの組み合わせ（`sub` に
    NULL を含む）。`_DistinctCache` が `COUNT(DISTINCT sub)`（NULL を数えない）
    だけを見ていると、鳩の巣原理の枝刈りが `(grp,sub)` を「一意になり得ない」と
    誤判定し、探索Aで見つからず探索Bに落ちて、宣言型を持たない集計列もどきの
    `val` がキーに紛れ込んでいた。修正後は探索Aだけで `(grp, sub)` が
    見つかり、`val` は絶対にキーに入らないことを確認する。
    """
    path = tmp_path / "null_dim.sqlite"
    make_null_key_fixture_db(path)
    conn = common.open_readonly(path)
    try:
        key, source, note = common.derive_key(conn, "t_null_dim", overrides={})
    finally:
        conn.close()
    assert key == ["grp", "sub"]
    assert source == "auto"
    assert note is None
    assert "val" not in key


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


# ---------------------------------------------------------------------------
# load_expected_diffs / validate_expected_diffs（変更9・CI 構造検証）
# ---------------------------------------------------------------------------

def test_load_expected_diffs_rejects_mapping_instead_of_list(tmp_path):
    """`meas_daily:` の直下に `key:`/`kind:` を書いてしまう（宣言のリストでは
    なくマッピングにしてしまう）と、以前はここでは何も検証しておらず、
    呼び出し側の `for d in diffs: d.get(...)` が文字列キーを回して
    `AttributeError: 'str' object has no attribute 'get'` という生のトレースバックに
    なっていた（レビュー指摘）。テーブル名を含む説明的なエラーで止まることを確認する。
    """
    path = tmp_path / "expected_diffs.yaml"
    path.write_text(
        "meas_daily:\n"
        "  key: [\"a\"]\n"
        "  kind: row_only_in_candidate\n",
        encoding="utf-8",
    )
    with pytest.raises(SystemExit, match="meas_daily"):
        common.load_expected_diffs(path)


def test_load_expected_diffs_accepts_well_formed_list(tmp_path):
    path = tmp_path / "expected_diffs.yaml"
    path.write_text(
        "meas_daily:\n"
        "  - key: [\"a\"]\n"
        "    kind: row_only_in_candidate\n",
        encoding="utf-8",
    )
    diffs = common.load_expected_diffs(path)
    assert diffs == {"meas_daily": [{"key": ["a"], "kind": "row_only_in_candidate"}]}


def test_load_expected_diffs_missing_file_returns_empty(tmp_path):
    assert common.load_expected_diffs(tmp_path / "does_not_exist.yaml") == {}


# `REQUIRED_DIFF_KEYS`（B-2）を満たす宣言の共通部分。`key`/`kind` 以外の必須項目
# （非空であること自体を検証する側の対象）を毎回書かずに済ませる。
_REQUIRED_EXTRAS = {"reason": "テスト用の理由", "found_on": "2026-09-08", "record": "テスト"}


def test_validate_expected_diffs_unknown_table_name_raises(tmp_path):
    with pytest.raises(SystemExit, match="no_such_table"):
        common.validate_expected_diffs(
            {"no_such_table": [{"key": ["a"], "kind": "row_only_in_candidate", **_REQUIRED_EXTRAS}]},
            {"t_pk": {"key": ["raw"]}},
            "expected_diffs.yaml",
        )


def test_validate_expected_diffs_bad_kind_raises():
    with pytest.raises(SystemExit, match="kind が不正"):
        common.validate_expected_diffs(
            {"t_pk": [{"key": ["a"], "kind": "not_a_real_kind", **_REQUIRED_EXTRAS}]},
            {"t_pk": {"key": ["raw"]}},
            "expected_diffs.yaml",
        )


def test_validate_expected_diffs_bad_key_length_raises():
    with pytest.raises(SystemExit, match="要素数"):
        common.validate_expected_diffs(
            {"t_dims": [{"key": ["a"], "kind": "row_only_in_candidate", **_REQUIRED_EXTRAS}]},
            {"t_dims": {"key": ["site", "year", "kind"]}},
            "expected_diffs.yaml",
        )


def test_validate_expected_diffs_accepts_well_formed_declaration():
    common.validate_expected_diffs(
        {"t_pk": [{"key": ["a"], "kind": "row_only_in_candidate", **_REQUIRED_EXTRAS}]},
        {"t_pk": {"key": ["raw"]}},
        "expected_diffs.yaml",
    )  # 例外を投げなければ良い


def test_validate_expected_diffs_missing_required_key_raises():
    """B-2: `reason`/`found_on`/`record` のいずれかが欠けていると、免除ゲート自体を
    免除する宣言なのに『なぜ免除するか』が機械可読な形で残らない。`kind`/`key`
    の検証と非対称にならないよう、こちらも欠落を検出して止まる。
    """
    with pytest.raises(SystemExit, match="必須項目が欠けている"):
        common.validate_expected_diffs(
            {"t_pk": [{"key": ["a"], "kind": "row_only_in_candidate"}]},  # reason 等が無い
            {"t_pk": {"key": ["raw"]}},
            "expected_diffs.yaml",
        )


def test_validate_expected_diffs_empty_required_value_raises():
    """`reason: ""` のように項目自体はあっても空文字なら、キーが欠けているのと
    同じ扱いで止まる（空文字1つで免除ゲートの説明義務を骨抜きにできないように）。
    """
    entry = {"key": ["a"], "kind": "row_only_in_candidate", **_REQUIRED_EXTRAS, "reason": ""}
    with pytest.raises(SystemExit, match="必須項目が欠けている"):
        common.validate_expected_diffs(
            {"t_pk": [entry]},
            {"t_pk": {"key": ["raw"]}},
            "expected_diffs.yaml",
        )
