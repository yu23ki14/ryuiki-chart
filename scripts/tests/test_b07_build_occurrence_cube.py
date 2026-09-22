"""scripts/b07_build_occurrence_cube.py の統合テスト。

本物の `data/db/v2.sqlite` を要さず、`scripts/tests/occurrence_fixtures.py` の
`make_v2_db_with_occurrence`（`occurrence` テーブルだけを持つ小さな sqlite。
スキーマは `scripts/b06_build_occurrence.py` の `_CREATE_OCCURRENCE_SQL` が正）
だけで完結する。
"""
import sqlite3

import pytest

import b07_build_occurrence_cube as b07
from migrate import common

from .occurrence_fixtures import make_v2_db_with_occurrence

_DECLARATIONS_YAML_TEXT = (
    "leaf_cell_source_rows:\n"
    "  expected_row_count: {n}\n"
    "  note: テスト用\n"
)


def _write_declarations_yaml(tmp_path, expected_row_count: int):
    path = tmp_path / "occurrence_cube_declarations.yaml"
    path.write_text(_DECLARATIONS_YAML_TEXT.format(n=expected_row_count), encoding="utf-8")
    return path


def _row(
    record_id, period_start, period_end, period_raw,
    source_id="gbif_kanagawa_occurrences", region_id="jp-14",
    taxon_id="common:taxon:gbif.1001", place_id="common:place:grid01.3550_13900",
    red_list_category="",
):
    return (
        record_id, "organism_records", 1, source_id, region_id, taxon_id,
        place_id, "grid01", None, 35.505, 139.005,
        "day", period_start, period_end, period_raw,
        "Foo bar", "", "SPECIES", red_list_category, 0, "CC-BY", "公開",
    )


def _build(tmp_path, rows, declarations_yaml=None, dirname="cube"):
    d = tmp_path / dirname
    d.mkdir()
    db_path = d / "v2.sqlite"
    make_v2_db_with_occurrence(db_path, rows)  # 作って閉じるだけ（戻り値は無い）
    conn = sqlite3.connect(f"file:{db_path}", uri=True)
    if declarations_yaml is None:
        declarations_yaml = _write_declarations_yaml(d, expected_row_count=sum(
            1 for r in rows if r[12] is not None and r[12][:4] != r[13][:4]
        ))
    return conn, declarations_yaml


def test_same_year_day_and_month_records_go_to_year_grain(tmp_path):
    """day/month 等、期間が1つの暦年に収まる記録は grain='year' のセルに入り、
    セルの period_start/period_end は暦年境界（YYYY-01-01〜YYYY-12-31）に
    丸められる。'Z' 変換後の瞬時記録（変換後も同年）も同じ扱い——b07 は
    `occurrence.period_start`/`period_end`（既に展開・変換済み）だけを見るため、
    元の形が 'Z' 終端だったかどうかは判定に影響しない。
    """
    rows = [
        _row("gbif__day", "2020-01-05", "2020-01-05", "2020-01-05"),
        _row("gbif__month", "2020-02-01", "2020-02-29", "2020-02"),
        # 'Z' 変換後を模した瞬時記録（同年）。
        _row("gbif__z_instant", "2020-06-01T12:30:45", "2020-06-01T12:30:45", "2020-06-01T12:30:45Z"),
    ]
    conn, decl = _build(tmp_path, rows)
    try:
        stats = b07.build_cube(conn, decl)
        assert stats["n_leaf_cells"] == 0
        assert stats["n_year_cells"] == 1  # 同じ (source, place, taxon) なら1セルに集約される
        cell = conn.execute(
            "SELECT grain, period_start, period_end, n FROM occurrence_agg"
        ).fetchone()
        assert cell == ("year", "2020-01-01", "2020-12-31", 3)
    finally:
        conn.close()


def test_same_year_interval_goes_to_year_grain_not_leaf(tmp_path):
    """同年内に収まる区間（day_interval 等、年をまたがない）は grain='year'
    に入る（leaf には入らない）。O-1 設計 v2「実測」節: 区間4,840行のうち
    同年内のものが3,649行（894+2,755）ある。
    """
    rows = [_row("gbif__same_year_interval", "2019-08-01", "2019-08-31", "2019-08-01/2019-08-31")]
    conn, decl = _build(tmp_path, rows)
    try:
        stats = b07.build_cube(conn, decl)
        assert stats["n_leaf_cells"] == 0
        assert stats["n_year_cells"] == 1
        cell = conn.execute("SELECT grain, period_start, period_end FROM occurrence_agg").fetchone()
        assert cell == ("year", "2019-01-01", "2019-12-31")
    finally:
        conn.close()


def test_cross_year_interval_goes_to_leaf_grain_not_year(tmp_path):
    """年をまたぐ区間は grain='survey_period'（leaf）に入り、year セルには
    入らない。leaf セルの period_start/period_end は記録自身の区間そのもの
    （丸めない）。
    """
    rows = [_row("gbif__cross_year", "1990-01-01", "1992-12-31", "1990/1992")]
    conn, decl = _build(tmp_path, rows)
    try:
        stats = b07.build_cube(conn, decl)
        assert stats["n_year_cells"] == 0
        assert stats["n_leaf_cells"] == 1
        cell = conn.execute("SELECT grain, period_start, period_end, n FROM occurrence_agg").fetchone()
        assert cell == ("survey_period", "1990-01-01", "1992-12-31", 1)
    finally:
        conn.close()


def test_undated_records_are_excluded_from_cube(tmp_path):
    """`period_raw IS NULL`（観測日の無い記録）はキューブに入らない（ADR-0025 D2）。"""
    rows = [
        _row("gbif__dated", "2020-01-05", "2020-01-05", "2020-01-05"),
        _row("gbif__undated", None, None, None),
    ]
    conn, decl = _build(tmp_path, rows)
    try:
        stats = b07.build_cube(conn, decl)
        assert stats["n_dated"] == 1
        n = conn.execute("SELECT SUM(n) FROM occurrence_agg").fetchone()[0]
        assert n == 1
    finally:
        conn.close()


def test_n_red_list_counts_nonempty_raw_red_list_category(tmp_path):
    """`n_red_list` は `red_list_category` の原表記が NULL でも '' でもない
    記録の数（v1 の mesh_year.rl_n・mesh_species.rl_species_n と同じ定義）。
    """
    rows = [
        _row("gbif__lc", "2020-01-05", "2020-01-05", "2020-01-05", red_list_category="LC"),
        _row("gbif__empty", "2020-01-06", "2020-01-06", "2020-01-06", red_list_category=""),
    ]
    conn, decl = _build(tmp_path, rows)
    try:
        b07.build_cube(conn, decl)
        n, n_rl = conn.execute("SELECT SUM(n), SUM(n_red_list) FROM occurrence_agg").fetchone()
        assert (n, n_rl) == (2, 1)
    finally:
        conn.close()


def test_leaf_declared_row_count_mismatch_raises(tmp_path):
    """leaf セルに入る元の記録数が宣言（occurrence_cube_declarations.yaml）と
    食い違えば止まる。
    """
    rows = [_row("gbif__cross_year", "1990-01-01", "1992-12-31", "1990/1992")]
    decl = _write_declarations_yaml(tmp_path, expected_row_count=2)  # 実際は1件
    d = tmp_path / "cube"
    d.mkdir()
    db_path = d / "v2.sqlite"
    make_v2_db_with_occurrence(db_path, rows)
    conn = sqlite3.connect(f"file:{db_path}", uri=True)
    try:
        with pytest.raises(common.MigrationError, match="宣言.*食い違う|食い違う.*宣言"):
            b07.build_cube(conn, decl)
    finally:
        conn.close()


def test_declarations_shape_rejects_unknown_name(tmp_path):
    """宣言名の集合が `leaf_cell_source_rows` 1件と過不足なく一致しない
    （未知の名前がある）宣言は構造検証で止まる。
    """
    path = tmp_path / "bad.yaml"
    path.write_text(
        "leaf_cell_source_rows:\n  expected_row_count: 1\n  note: x\n"
        "unexpected_entry:\n  expected_row_count: 1\n  note: x\n",
        encoding="utf-8",
    )
    with pytest.raises(common.MigrationError, match="宣言名が想定と一致しない"):
        b07.validate_cube_declarations_shape(path)


def test_declarations_shape_rejects_missing_required_key(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("leaf_cell_source_rows:\n  note: x\n", encoding="utf-8")  # expected_row_count が無い
    with pytest.raises(common.MigrationError, match="必須キー"):
        b07.validate_cube_declarations_shape(path)


def test_series_totals_mismatch_is_detected(tmp_path):
    """(i) 系列（source_id, taxon_id）ごとの Σn/Σn_red_list 検証
    （`_assert_series_totals_match_l2`）が、意図的に食い違わせた作業用
    テーブルに対して `MigrationError` を投げることを直接確認する
    （`scripts/tests/test_b04_build_cube.py` の
    `test_assert_dimension_key_unique_raises_with_examples` と同じ考え方:
    実際のビルドで崩すのが難しい壊れ方は、検証関数を直接呼んで確かめる）。
    """
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE occurrence (source_id TEXT, taxon_id TEXT, period_raw TEXT, "
        "period_start TEXT, period_end TEXT, red_list_category TEXT)"
    )
    conn.execute(
        "INSERT INTO occurrence VALUES ('gbif_kanagawa_occurrences', 'common:taxon:gbif.1001', "
        "'2020-01-05', '2020-01-05', '2020-01-05', 'LC')"
    )
    conn.execute('CREATE TABLE "staging" (source_id TEXT, taxon_id TEXT, n INTEGER, n_red_list INTEGER)')
    # 本来 n=1, n_red_list=1 のはずが、わざと n=5 にして食い違わせる。
    conn.execute(
        "INSERT INTO \"staging\" VALUES ('gbif_kanagawa_occurrences', 'common:taxon:gbif.1001', 5, 1)"
    )
    conn.commit()
    with pytest.raises(common.MigrationError, match="Σn/Σn_red_list"):
        b07._assert_series_totals_match_l2(conn, "staging")


def test_partition_covers_all_dated_rows_detects_mismatch(tmp_path):
    """(iii) 年セルの元記録数 + leaf セルの元記録数が日付あり行数と一致しない
    ことを直接検出する（`_assert_partition_covers_all_dated_rows` を、わざと
    誤った `leaf_source_rows` で呼ぶ）。
    """
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE occurrence (source_id TEXT, taxon_id TEXT, period_raw TEXT, "
        "period_start TEXT, period_end TEXT, red_list_category TEXT)"
    )
    conn.execute(
        "INSERT INTO occurrence VALUES ('s', 't', '2020-01-05', '2020-01-05', '2020-01-05', '')"
    )
    conn.commit()
    with pytest.raises(common.MigrationError, match="日付あり行数と"):
        b07._assert_partition_covers_all_dated_rows(conn, leaf_source_rows=1)  # 実際は0件


def test_dimension_key_unique_raises_with_examples(tmp_path):
    """C-3: `_assert_dimension_key_unique` が重複キーを実例つきの
    `MigrationError` として検出する（`test_b04_build_cube.py` と同じ考え方）。
    """
    db_path = tmp_path / "t.sqlite"
    conn = sqlite3.connect(f"file:{db_path}", uri=True)
    conn.execute(b07._CREATE_OCCURRENCE_AGG_SQL.format(table='"staging"'))
    row = (
        "jp-14", "gbif_kanagawa_occurrences", "common:place:grid01.3550_13900",
        "common:taxon:gbif.1001", "year", "2020-01-01", "2020-12-31", 1, 0, "occurrence", "v1",
    )
    placeholders = ", ".join("?" for _ in row)
    conn.executemany(f'INSERT INTO "staging" VALUES ({placeholders})', [row, row])
    conn.commit()
    try:
        with pytest.raises(common.MigrationError, match="次元キーが一意でない"):
            b07._assert_dimension_key_unique(conn, "staging")
    finally:
        conn.close()
