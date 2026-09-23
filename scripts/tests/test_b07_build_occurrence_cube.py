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
    """(i) 系列（place_kind, source_id, taxon_id）ごとの Σn/Σn_red_list 検証
    （`_assert_series_totals_match_l2`）が、意図的に食い違わせた作業用
    テーブルに対して `MigrationError` を投げることを直接確認する
    （`scripts/tests/test_b04_build_cube.py` の
    `test_assert_dimension_key_unique_raises_with_examples` と同じ考え方:
    実際のビルドで崩すのが難しい壊れ方は、検証関数を直接呼んで確かめる）。
    """
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE occurrence (place_kind TEXT, source_id TEXT, taxon_id TEXT, period_raw TEXT, "
        "period_start TEXT, period_end TEXT, red_list_category TEXT)"
    )
    conn.execute(
        "INSERT INTO occurrence VALUES ('grid01', 'gbif_kanagawa_occurrences', 'common:taxon:gbif.1001', "
        "'2020-01-05', '2020-01-05', '2020-01-05', 'LC')"
    )
    conn.execute(
        'CREATE TABLE "staging" (place_kind TEXT, source_id TEXT, taxon_id TEXT, n INTEGER, n_red_list INTEGER)'
    )
    # 本来 n=1, n_red_list=1 のはずが、わざと n=5 にして食い違わせる。
    conn.execute(
        "INSERT INTO \"staging\" VALUES ('grid01', 'gbif_kanagawa_occurrences', "
        "'common:taxon:gbif.1001', 5, 1)"
    )
    conn.commit()
    with pytest.raises(common.MigrationError, match="Σn/Σn_red_list"):
        b07._assert_series_totals_match_l2(conn, "staging")


def _make_staging(conn, rows):
    """`_CREATE_OCCURRENCE_AGG_SQL` と同じ形の `staging` テーブルを作り、
    `rows`（`_INSERT_COLUMNS` の並び）を入れる。
    """
    conn.execute(b07._CREATE_OCCURRENCE_AGG_SQL.format(table='"staging"'))
    cols = ", ".join(b07._INSERT_COLUMNS)
    placeholders = ", ".join("?" for _ in b07._INSERT_COLUMNS)
    conn.executemany(f'INSERT INTO "staging" ({cols}) VALUES ({placeholders})', rows)
    conn.commit()


def _staging_row(
    grain, period_start, period_end, n, taxon_id="common:taxon:gbif.1001", n_red_list=0, place_kind="grid01",
):
    return (
        "jp-14", "gbif_kanagawa_occurrences", "common:place:grid01.3550_13900", place_kind, taxon_id,
        grain, period_start, period_end, n, n_red_list, "occurrence", "phase-b-fact-slice/v1",
    )


def test_cube_partition_leaf_sum_mismatch_is_detected(tmp_path):
    """(ii) `staging` の `place_kind='grid01'` に絞った
    `SUM(n) WHERE grain='survey_period'` が宣言値と食い違えば止まる
    （`_assert_cube_partition_and_shape` を直接呼ぶ。コードレビュー指摘1:
    L2 ではなく staging 自身の値を見る）。
    """
    conn = sqlite3.connect(":memory:")
    _make_staging(conn, [_staging_row("survey_period", "1990-01-01", "1992-12-31", n=1)])
    with pytest.raises(common.MigrationError, match="survey_period.*宣言|宣言.*survey_period"):
        b07._assert_cube_partition_and_shape(
            conn, "staging", leaf_expected=2, n_dated_by_place_kind={"grid01": 1},
            declarations_yaml=tmp_path / "x.yaml",
        )


def test_cube_partition_year_sum_mismatch_is_detected(tmp_path):
    """(iii) `staging` の `place_kind='grid01'` に絞った
    `SUM(n) WHERE grain='year'` が「grid01 の日付あり行数 − leaf 宣言値」と
    食い違えば止まる。
    """
    conn = sqlite3.connect(":memory:")
    _make_staging(
        conn,
        [
            _staging_row("year", "2020-01-01", "2020-12-31", n=5),
            _staging_row("survey_period", "1990-01-01", "1992-12-31", n=1),
        ],
    )
    # 日付あり行数=10 のはずが year=5+leaf=1=6 でしか説明できない（4件足りない）。
    with pytest.raises(common.MigrationError, match="grain='year' セルの"):
        b07._assert_cube_partition_and_shape(
            conn, "staging", leaf_expected=1, n_dated_by_place_kind={"grid01": 10},
            declarations_yaml=tmp_path / "x.yaml",
        )


def test_cube_partition_rejects_unknown_grain(tmp_path):
    conn = sqlite3.connect(":memory:")
    _make_staging(conn, [_staging_row("month", "2020-01-01", "2020-01-31", n=1)])
    with pytest.raises(common.MigrationError, match="grain が 'year'/'survey_period' 以外"):
        b07._assert_cube_partition_and_shape(
            conn, "staging", leaf_expected=0, n_dated_by_place_kind={"grid01": 1},
            declarations_yaml=tmp_path / "x.yaml",
        )


def test_cube_partition_rejects_unrounded_year_cell(tmp_path):
    """grain='year' なのに period_start/period_end が暦年境界に丸められて
    いない行（例: 記録自身の日付のまま）は止まる。
    """
    conn = sqlite3.connect(":memory:")
    _make_staging(conn, [_staging_row("year", "2020-01-05", "2020-01-05", n=1)])  # 丸めていない
    with pytest.raises(common.MigrationError, match="暦年境界"):
        b07._assert_cube_partition_and_shape(
            conn, "staging", leaf_expected=0, n_dated_by_place_kind={"grid01": 1},
            declarations_yaml=tmp_path / "x.yaml",
        )


def test_cube_partition_rejects_same_year_leaf_cell(tmp_path):
    """grain='survey_period' なのに同じ年に収まっている行（年をまたいでいない）
    は止まる。
    """
    conn = sqlite3.connect(":memory:")
    _make_staging(conn, [_staging_row("survey_period", "2020-01-01", "2020-12-31", n=1)])  # 同年
    with pytest.raises(common.MigrationError, match="同じ年に収まっている"):
        b07._assert_cube_partition_and_shape(
            conn, "staging", leaf_expected=1, n_dated_by_place_kind={"grid01": 1},
            declarations_yaml=tmp_path / "x.yaml",
        )


def test_t1_invariant_rejects_timezone_suffixed_period(tmp_path):
    """`occurrence.period_start`/`period_end` が時刻帯付き（'+'/'Z'）だと
    `_assert_t1_invariant` が止まる（b06 の T1 を b07 自身も確かめる）。
    """
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE occurrence (period_raw TEXT, period_start TEXT, period_end TEXT)"
    )
    conn.execute(
        "INSERT INTO occurrence VALUES ('2020-01-05T12:30:45Z', '2020-01-05T12:30:45+09:00', "
        "'2020-01-05T12:30:45+09:00')"
    )
    conn.commit()
    with pytest.raises(common.MigrationError, match="T1"):
        b07._assert_t1_invariant(conn)


# ---------------------------------------------------------------------------
# 変異テスト（コードレビュー指摘1）: 年セル/leaf セルの SQL 自体が壊れても、
# (ii)(iii) の検証が staging を直接見ているために検出できることを確かめる。
# ---------------------------------------------------------------------------

def test_mutation_year_and_leaf_classification_swapped_is_caught(tmp_path, monkeypatch):
    """**コードレビュー指摘1が指した穴そのものの再現**: 年セル/leaf セルの
    分類条件を入れ替える変異（同年の記録が `survey_period` に、年をまたぐ
    記録が `year` に入る）。

    記録の総数・系列ごとの Σn は変わらない（入れ替わるだけで、どちらの
    グループにも同じ2件が1件ずつ入る）ため、(i)（系列ごとの Σn 突合）も
    (ii) の宣言値との比較（件数だけを見る）も**この変異をすり抜ける**。
    検出できるのは `grain='survey_period'` の構造チェック（全行が年を
    またいでいるか）だけ——このテストは、以前の実装（`occurrence`=L2 に
    対して同じ年境界の述語を独立に再計算し、`staging` の中身を一切見て
    いなかった `_assert_leaf_source_row_count`/
    `_assert_partition_covers_all_dated_rows`）では検出できなかった穴を、
    現在の実装（`staging` 自身の構造を直接見る）が塞いでいることを示す。
    """
    rows = [
        _row("gbif__same_year", "2020-01-05", "2020-01-05", "2020-01-05"),
        _row("gbif__cross_year", "1990-01-01", "1992-12-31", "1990/1992"),
    ]
    # leaf_expected はフィクスチャの「正しい」形（cross_year だけが年をまたぐ）
    # から自動算出される——1件（`_build` のデフォルト計算）。変異後の実際の
    # 分類（same_year が survey_period に入る）とは無関係に、この「正しい」
    # 値のまま検証することが、この変異がすり抜けを狙う理由そのもの。
    conn, decl = _build(tmp_path, rows)
    try:
        same_where = f"WHERE period_raw IS NOT NULL AND {b07._SAME_YEAR_EXPR}"
        cross_where = f"WHERE period_raw IS NOT NULL AND {b07._CROSS_YEAR_EXPR}"
        mutated_year = b07._YEAR_CELLS_SQL.replace(same_where, cross_where)
        mutated_leaf = b07._LEAF_CELLS_SQL.replace(cross_where, same_where)
        assert mutated_year != b07._YEAR_CELLS_SQL  # 置換が実際に効いたことを先に確認する
        assert mutated_leaf != b07._LEAF_CELLS_SQL
        monkeypatch.setattr(b07, "_YEAR_CELLS_SQL", mutated_year)
        monkeypatch.setattr(b07, "_LEAF_CELLS_SQL", mutated_leaf)
        with pytest.raises(common.MigrationError, match="同じ年に収まっている"):
            b07.build_cube(conn, decl)
    finally:
        conn.close()


def test_mutation_empty_leaf_cells_sql_is_caught(tmp_path, monkeypatch):
    """leaf セルの SQL を空にする変異（年をまたぐ記録がどのセルにも入らなく
    なる）を仕込むと `build_cube` が止まることを確かめる。この変異は
    (i)（系列ごとの Σn が L2 と食い違う。cross_year の系列がキューブ側に
    存在しなくなる）で最初に捕まる——(ii)(iii) まで行く前に止まること自体が
    「検証がキューブを実際に見ている」証拠。
    """
    rows = [_row("gbif__cross_year", "1990-01-01", "1992-12-31", "1990/1992")]
    conn, decl = _build(tmp_path, rows)
    try:
        mutated = b07._LEAF_CELLS_SQL.replace(
            f"WHERE period_raw IS NOT NULL AND {b07._CROSS_YEAR_EXPR}",
            "WHERE 0",
        )
        assert mutated != b07._LEAF_CELLS_SQL
        monkeypatch.setattr(b07, "_LEAF_CELLS_SQL", mutated)
        with pytest.raises(common.MigrationError, match="Σn/Σn_red_list"):
            b07.build_cube(conn, decl)
    finally:
        conn.close()


def test_dimension_key_unique_raises_with_examples(tmp_path):
    """C-3: `_assert_dimension_key_unique` が重複キーを実例つきの
    `MigrationError` として検出する（`test_b04_build_cube.py` と同じ考え方）。
    """
    db_path = tmp_path / "t.sqlite"
    conn = sqlite3.connect(f"file:{db_path}", uri=True)
    conn.execute(b07._CREATE_OCCURRENCE_AGG_SQL.format(table='"staging"'))
    row = (
        "jp-14", "gbif_kanagawa_occurrences", "common:place:grid01.3550_13900", "grid01",
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
