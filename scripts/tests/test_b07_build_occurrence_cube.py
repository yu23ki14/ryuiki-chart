"""scripts/b07_build_occurrence_cube.py の統合テスト。

本物の `data/db/v2.sqlite` を要さず、`scripts/tests/occurrence_fixtures.py` の
`make_v2_db_with_occurrence_and_place`（`occurrence`・`occurrence_place` の
両方を持つ小さな sqlite。スキーマはそれぞれ `scripts/b06_build_occurrence.py`/
`scripts/b09_build_occurrence_place.py` の `_CREATE_*_SQL` が正）だけで完結する。

Issue #48 PR-3a（O-2b）で b07 が「place_kind × grain 族」の行列を作るように
なったため、`build_cube()` は `occurrence_place` の存在・鮮度を要求する
（`occurrence_place` 無しでは動かない）。
"""
import sqlite3

import pytest

import b07_build_occurrence_cube as b07
from migrate import common

from .occurrence_fixtures import (
    DEFAULT_WATERSHED_PLACE_ID,
    make_occurrence_cube_declarations_yaml as _make_declarations_yaml,
    make_v2_db_with_occurrence_and_place,
    occurrence_place_row,
    occurrence_row,
)

# b07 は `assert_grouped_totals_match`（FULL OUTER JOIN、SQLite 3.39以降）を
# 使うため `common.require_sqlite_version()` で古い SQLite を拒む
# （`scripts/migrate/common.py` 参照）。この版のガード自体の単体テストは
# `scripts/tests/test_migrate_common.py`。ここでは環境の SQLite が実際に
# 古いとき、意味の無い失敗の山を作らずスキップする。
pytestmark = pytest.mark.skipif(
    sqlite3.sqlite_version_info < common.MIN_SQLITE_VERSION,
    reason=f"SQLite {common.MIN_SQLITE_VERSION} 未満（実際: {sqlite3.sqlite_version}）",
)

# `occurrence` テーブルの列インデックス（`occurrence_fixtures._OCCURRENCE_COLUMNS`
# の並び）。テストの declaration 自動算出だけに使う——本体コードはこの並びに
# 依存しない。
_PERIOD_START_IDX = 12
_PERIOD_END_IDX = 13
_PERIOD_RAW_IDX = 14

# `occurrence_place` テーブルの列インデックス（`_OCCURRENCE_PLACE_COLUMNS` の並び）。
_PLACE_RECORD_ID_IDX = 0
_PLACE_PLACE_ID_IDX = 2


def _row(
    record_id, period_start, period_end, period_raw, *,
    source_id="gbif_kanagawa_occurrences", region_id="jp-14",
    taxon_id="common:taxon:gbif.1001", red_list_category="", is_alien=0,
):
    """`occurrence_fixtures.occurrence_row` への薄い呼び出し——引数の並びだけ
    この既存テストの慣習（`record_id, period_start, period_end, period_raw`
    の順）に合わせてある。
    """
    return occurrence_row(
        record_id, taxon_id, period_start, period_end, period_raw,
        source_id=source_id, region_id=region_id, red_list_category=red_list_category,
        is_alien=is_alien,
    )


def _default_declaration_counts(rows: list[tuple], place_rows: list[tuple]) -> dict[str, int]:
    """`rows`（occurrence）・`place_rows`（occurrence_place）から、b07 が要求
    する4つの宣言値を実測どおりに算出する（`s01_build_sample.py` の
    `build_declaration_counts` の簡易版——テストのフィクスチャ専用）。
    """
    leaf = 0
    month = 0
    for r in rows:
        if r[_PERIOD_RAW_IDX] is None:
            continue
        start, end = r[_PERIOD_START_IDX], r[_PERIOD_END_IDX]
        if start[:4] != end[:4]:
            leaf += 1
        if start[:7] == end[:7]:
            month += 1
    place_id_by_record = {p[_PLACE_RECORD_ID_IDX]: p[_PLACE_PLACE_ID_IDX] for p in place_rows}
    dated_record_ids = {r[0] for r in rows if r[_PERIOD_RAW_IDX] is not None}
    resolved = sum(1 for rid in dated_record_ids if place_id_by_record.get(rid) is not None)
    unresolved = len(dated_record_ids) - resolved
    return {
        "leaf_cell_source_rows": leaf,
        "month_cell_source_rows": month,
        "watershed_dated_resolved_rows": resolved,
        "watershed_dated_unresolved_rows": unresolved,
    }


def _write_declarations_yaml(tmp_path, counts: dict[str, int]):
    """`scripts/tests/occurrence_fixtures.make_occurrence_cube_declarations_yaml`
    （/simplify 指摘4: このテキスト組み立ては1箇所に集約してある）への薄い
    呼び出し——このファイルの呼び出し慣習（`tmp_path` から標準ファイル名で
    パスを組み立てて返す）だけをここに残す。
    """
    path = tmp_path / "occurrence_cube_declarations.yaml"
    _make_declarations_yaml(path, counts)
    return path


def _build(tmp_path, rows, place_rows=None, declarations_yaml=None, dirname="cube"):
    """`occurrence`・`occurrence_place` を持つ v2.sqlite を作り、開いた接続と
    宣言 YAML のパスを返す。

    `place_rows` 省略時は全記録を単一の watershed（`DEFAULT_WATERSHED_PLACE_ID`）
    に解決する（＝ watershed の宣言は「日付あり全行が解決済み」になる）。
    `declarations_yaml` 省略時は `rows`/`place_rows` から4つの宣言値を実測どおり
    自動算出する（`_default_declaration_counts`）。
    """
    d = tmp_path / dirname
    d.mkdir()
    db_path = d / "v2.sqlite"
    if place_rows is None:
        place_rows = [occurrence_place_row(r[0], DEFAULT_WATERSHED_PLACE_ID) for r in rows]
    make_v2_db_with_occurrence_and_place(db_path, rows, place_rows)
    conn = sqlite3.connect(f"file:{db_path}", uri=True)
    if declarations_yaml is None:
        declarations_yaml = _write_declarations_yaml(d, _default_declaration_counts(rows, place_rows))
    return conn, declarations_yaml


# ---------------------------------------------------------------------------
# year/leaf（既存の族。watershed 込みで動くことを確かめる）
# ---------------------------------------------------------------------------


def test_same_year_day_and_month_records_go_to_year_grain(tmp_path):
    """day/month 等、期間が1つの暦年に収まる記録は grain='year' のセルに入り、
    セルの period_start/period_end は暦年境界（YYYY-01-01〜YYYY-12-31）に
    丸められる。'Z' 変換後の瞬時記録（変換後も同年）も同じ扱い。
    """
    rows = [
        _row("gbif__day", "2020-01-05", "2020-01-05", "2020-01-05"),
        _row("gbif__month", "2020-02-01", "2020-02-29", "2020-02"),
        # 'Z' 変換後を模した瞬時記録（同年）。
        _row("gbif__z_instant", "2020-06-01T12:30:45", "2020-06-01T12:30:45", "2020-06-01T12:30:45Z"),
    ]
    conn, decl = _build(tmp_path, rows)
    try:
        stats = b07.build_cube(conn, decl, place_declarations_yaml=None)
        assert stats["n_leaf_cells"] == 0
        assert stats["n_year_cells"] == 1  # 同じ (source, place, taxon) なら1セルに集約される
        cell = conn.execute(
            "SELECT grain, period_start, period_end, n FROM occurrence_agg "
            "WHERE place_kind = 'grid01' AND grain = 'year'"
        ).fetchone()
        assert cell == ("year", "2020-01-01", "2020-12-31", 3)
    finally:
        conn.close()


def test_same_year_interval_goes_to_year_grain_not_leaf(tmp_path):
    """同年内に収まる区間（day_interval 等、年をまたがない）は grain='year'
    に入る（leaf には入らない）。
    """
    rows = [_row("gbif__same_year_interval", "2019-08-01", "2019-08-31", "2019-08-01/2019-08-31")]
    conn, decl = _build(tmp_path, rows)
    try:
        stats = b07.build_cube(conn, decl, place_declarations_yaml=None)
        assert stats["n_leaf_cells"] == 0
        assert stats["n_year_cells"] == 1
        cell = conn.execute(
            "SELECT grain, period_start, period_end FROM occurrence_agg "
            "WHERE place_kind = 'grid01' AND grain = 'year'"
        ).fetchone()
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
        stats = b07.build_cube(conn, decl, place_declarations_yaml=None)
        assert stats["n_year_cells"] == 0
        assert stats["n_leaf_cells"] == 1
        cell = conn.execute(
            "SELECT grain, period_start, period_end, n FROM occurrence_agg WHERE place_kind = 'grid01'"
        ).fetchone()
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
        stats = b07.build_cube(conn, decl, place_declarations_yaml=None)
        assert stats["n_dated"] == 1
        # year 族（grid01）は日付あり全行の分割なので、その Σn がそのまま
        # 「キューブに入った記録数」になる（month 族は独立な部分集合なので
        # 単純合計すると二重に数える）。
        n = conn.execute(
            "SELECT SUM(n) FROM occurrence_agg WHERE place_kind = 'grid01' AND grain != 'month'"
        ).fetchone()[0]
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
        b07.build_cube(conn, decl, place_declarations_yaml=None)
        n, n_rl = conn.execute(
            "SELECT SUM(n), SUM(n_red_list) FROM occurrence_agg "
            "WHERE place_kind = 'grid01' AND grain != 'month'"
        ).fetchone()
        assert (n, n_rl) == (2, 1)
    finally:
        conn.close()


def test_n_alien_sums_is_alien_flag(tmp_path):
    """`n_alien = SUM(is_alien)`（Issue #48 PR-3a 決定 D3）。"""
    rows = [
        _row("gbif__alien", "2020-01-05", "2020-01-05", "2020-01-05", is_alien=1),
        _row("gbif__native", "2020-01-06", "2020-01-06", "2020-01-06", is_alien=0),
    ]
    conn, decl = _build(tmp_path, rows)
    try:
        b07.build_cube(conn, decl, place_declarations_yaml=None)
        n, n_alien = conn.execute(
            "SELECT SUM(n), SUM(n_alien) FROM occurrence_agg "
            "WHERE place_kind = 'grid01' AND grain != 'month'"
        ).fetchone()
        assert (n, n_alien) == (2, 1)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# month 族（新設）
# ---------------------------------------------------------------------------


def test_same_month_record_goes_to_month_grain_cell(tmp_path):
    """同一月に収まる記録（day/instant/month と、同月内の区間）は
    grain='month' のセルにも入る（year 族のセルとは別に、両方に入る——
    year 族と month 族は独立な分割）。
    """
    rows = [_row("gbif__day", "2020-01-05", "2020-01-05", "2020-01-05")]
    conn, decl = _build(tmp_path, rows)
    try:
        stats = b07.build_cube(conn, decl, place_declarations_yaml=None)
        assert stats["n_month_cells"] == 1
        cell = conn.execute(
            "SELECT grain, period_start, period_end, n FROM occurrence_agg "
            "WHERE place_kind = 'grid01' AND grain = 'month'"
        ).fetchone()
        assert cell == ("month", "2020-01-01", "2020-01-31", 1)
    finally:
        conn.close()


def test_month_bounds_handle_leap_year_february(tmp_path):
    """月末日の計算（`calendar.monthrange` 経由）が閏年2月を正しく扱う。"""
    rows = [_row("gbif__leap", "2020-02-10", "2020-02-10", "2020-02-10")]
    conn, decl = _build(tmp_path, rows)
    try:
        b07.build_cube(conn, decl, place_declarations_yaml=None)
        cell = conn.execute(
            "SELECT period_start, period_end FROM occurrence_agg WHERE grain = 'month'"
        ).fetchone()
        assert cell == ("2020-02-01", "2020-02-29")
    finally:
        conn.close()


def test_cross_month_same_year_interval_excluded_from_month_grain(tmp_path):
    """同一年内だが月をまたぐ区間は month セルに入らない（year セルには
    入る）——ADR-0024 決定3「セルの宣言する期間＝メンバーの期間」を破らない
    ため、複数月にまたがる記録を1つの月セルに丸めて詰めない。
    """
    rows = [_row("gbif__cross_month", "2020-03-01", "2020-04-05", "2020-03-01/2020-04-05")]
    conn, decl = _build(tmp_path, rows)
    try:
        stats = b07.build_cube(conn, decl, place_declarations_yaml=None)
        assert stats["n_month_cells"] == 0
        assert stats["n_year_cells"] == 1
    finally:
        conn.close()


def test_year_grain_shape_record_excluded_from_month_grain(tmp_path):
    """`period_grain='year'`（`'2020'` のような年だけの記録）は暦年全体に
    広がるため、同一月には収まらず month セルに入らない。
    """
    rows = [_row("gbif__year_shape", "2020-01-01", "2020-12-31", "2020")]
    conn, decl = _build(tmp_path, rows)
    try:
        stats = b07.build_cube(conn, decl, place_declarations_yaml=None)
        assert stats["n_month_cells"] == 0
        assert stats["n_year_cells"] == 1
    finally:
        conn.close()


def test_cross_year_leaf_record_excluded_from_month_grain(tmp_path):
    """年をまたぐ区間（leaf）は当然 month セルにも入らない。"""
    rows = [_row("gbif__cross_year", "1990-01-01", "1992-12-31", "1990/1992")]
    conn, decl = _build(tmp_path, rows)
    try:
        stats = b07.build_cube(conn, decl, place_declarations_yaml=None)
        assert stats["n_month_cells"] == 0
        assert stats["n_leaf_cells"] == 1
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# watershed 族（O-2b 新設）
# ---------------------------------------------------------------------------


def test_watershed_year_cell_uses_occurrence_place_place_id(tmp_path):
    """watershed×year セルの `place_id` は `occurrence_place`
    （`place_kind='watershed'`）から取る（`occurrence.place_id`——grid01 の
    メッシュ——ではない）。
    """
    rows = [_row("gbif__day", "2020-01-05", "2020-01-05", "2020-01-05")]
    place_rows = [occurrence_place_row("gbif__day", DEFAULT_WATERSHED_PLACE_ID)]
    conn, decl = _build(tmp_path, rows, place_rows=place_rows)
    try:
        stats = b07.build_cube(conn, decl, place_declarations_yaml=None)
        assert stats["n_watershed_year_cells"] == 1
        place_id = conn.execute(
            "SELECT place_id FROM occurrence_agg WHERE place_kind = 'watershed' AND grain = 'year'"
        ).fetchone()[0]
        assert place_id == DEFAULT_WATERSHED_PLACE_ID
    finally:
        conn.close()


def test_watershed_unresolved_record_kept_as_null_place_id_cell(tmp_path):
    """流域に解決できない記録（`occurrence_place.place_id IS NULL`）は
    `place_kind='watershed', place_id NULL` のセルとして持つ（ADR-0025 D2
    「データを落とさない」・Issue #48 PR-3a 決定 D1）——year セルの外に
    捨てない。
    """
    rows = [_row("gbif__unresolved", "2020-01-05", "2020-01-05", "2020-01-05")]
    place_rows = [occurrence_place_row("gbif__unresolved", None)]
    conn, decl = _build(tmp_path, rows, place_rows=place_rows)
    try:
        stats = b07.build_cube(conn, decl, place_declarations_yaml=None)
        assert stats["n_watershed_year_cells"] == 1
        place_id, n = conn.execute(
            "SELECT place_id, n FROM occurrence_agg WHERE place_kind = 'watershed' AND grain = 'year'"
        ).fetchone()
        assert (place_id, n) == (None, 1)
    finally:
        conn.close()


def test_watershed_leaf_cell_can_also_have_null_place_id(tmp_path):
    """年をまたぐ区間（leaf）も、流域に解決できなければ watershed 族では
    `place_id NULL` のセルになる。
    """
    rows = [_row("gbif__cross_year", "1990-01-01", "1992-12-31", "1990/1992")]
    place_rows = [occurrence_place_row("gbif__cross_year", None)]
    conn, decl = _build(tmp_path, rows, place_rows=place_rows)
    try:
        stats = b07.build_cube(conn, decl, place_declarations_yaml=None)
        assert stats["n_watershed_leaf_cells"] == 1
        place_id = conn.execute(
            "SELECT place_id FROM occurrence_agg WHERE place_kind = 'watershed' AND grain = 'survey_period'"
        ).fetchone()[0]
        assert place_id is None
    finally:
        conn.close()


def test_watershed_month_cells_are_not_built(tmp_path):
    """D2: watershed×month は消費者が無いので作らない
    （`CELL_FAMILIES` に無い組み合わせ）。"""
    rows = [_row("gbif__day", "2020-01-05", "2020-01-05", "2020-01-05")]
    conn, decl = _build(tmp_path, rows)
    try:
        b07.build_cube(conn, decl, place_declarations_yaml=None)
        n = conn.execute(
            "SELECT COUNT(*) FROM occurrence_agg WHERE place_kind = 'watershed' AND grain = 'month'"
        ).fetchone()[0]
        assert n == 0
    finally:
        conn.close()


def test_occurrence_place_missing_row_for_dated_record_is_caught(tmp_path):
    """日付あり記録が `occurrence_place` に1行も持たない（b09 の回し忘れ・
    別スナップショット混在）と、母集団の完全性検査で止まる。
    """
    rows = [
        _row("gbif__has_place", "2020-01-05", "2020-01-05", "2020-01-05"),
        _row("gbif__no_place", "2020-01-06", "2020-01-06", "2020-01-06"),
    ]
    place_rows = [occurrence_place_row("gbif__has_place", DEFAULT_WATERSHED_PLACE_ID)]  # 2件目が無い
    conn, decl = _build(tmp_path, rows, place_rows=place_rows)
    try:
        with pytest.raises(common.MigrationError, match="母集団.*一致しない|一致しない.*母集団"):
            b07.build_cube(conn, decl, place_declarations_yaml=None)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 宣言との突合（(ii)）
# ---------------------------------------------------------------------------


def test_leaf_declared_row_count_mismatch_raises(tmp_path):
    rows = [_row("gbif__cross_year", "1990-01-01", "1992-12-31", "1990/1992")]
    counts = _default_declaration_counts(rows, [occurrence_place_row("gbif__cross_year", DEFAULT_WATERSHED_PLACE_ID)])
    counts["leaf_cell_source_rows"] = 2  # 実際は1件
    decl = _write_declarations_yaml(tmp_path, counts)
    conn, _ = _build(tmp_path, rows, declarations_yaml=decl)
    try:
        with pytest.raises(common.MigrationError, match="宣言.*食い違う|食い違う.*宣言"):
            b07.build_cube(conn, decl, place_declarations_yaml=None)
    finally:
        conn.close()


def test_month_declared_row_count_mismatch_raises(tmp_path):
    rows = [_row("gbif__day", "2020-01-05", "2020-01-05", "2020-01-05")]
    counts = _default_declaration_counts(rows, [occurrence_place_row("gbif__day", DEFAULT_WATERSHED_PLACE_ID)])
    counts["month_cell_source_rows"] = 0  # 実際は1件
    decl = _write_declarations_yaml(tmp_path, counts)
    conn, _ = _build(tmp_path, rows, declarations_yaml=decl)
    try:
        with pytest.raises(common.MigrationError, match="month.*宣言|宣言.*month"):
            b07.build_cube(conn, decl, place_declarations_yaml=None)
    finally:
        conn.close()


def test_watershed_resolved_declared_row_count_mismatch_raises(tmp_path):
    rows = [_row("gbif__day", "2020-01-05", "2020-01-05", "2020-01-05")]
    place_rows = [occurrence_place_row("gbif__day", DEFAULT_WATERSHED_PLACE_ID)]
    counts = _default_declaration_counts(rows, place_rows)
    counts["watershed_dated_resolved_rows"] = 0  # 実際は1件（解決済み）
    counts["watershed_dated_unresolved_rows"] = 1
    decl = _write_declarations_yaml(tmp_path, counts)
    conn, _ = _build(tmp_path, rows, place_rows=place_rows, declarations_yaml=decl)
    try:
        with pytest.raises(common.MigrationError, match="watershed_dated_resolved_rows"):
            b07.build_cube(conn, decl, place_declarations_yaml=None)
    finally:
        conn.close()


def test_watershed_unresolved_declared_row_count_mismatch_raises(tmp_path):
    rows = [_row("gbif__day", "2020-01-05", "2020-01-05", "2020-01-05")]
    place_rows = [occurrence_place_row("gbif__day", None)]
    counts = _default_declaration_counts(rows, place_rows)
    counts["watershed_dated_unresolved_rows"] = 0  # 実際は1件（未解決）——resolved は実測どおり（0）のまま
    decl = _write_declarations_yaml(tmp_path, counts)
    conn, _ = _build(tmp_path, rows, place_rows=place_rows, declarations_yaml=decl)
    try:
        with pytest.raises(common.MigrationError, match="watershed_dated_unresolved_rows"):
            b07.build_cube(conn, decl, place_declarations_yaml=None)
    finally:
        conn.close()


def test_declarations_shape_rejects_unknown_name(tmp_path):
    """宣言名の集合が4件と過不足なく一致しない（未知の名前がある）宣言は
    構造検証で止まる。
    """
    path = tmp_path / "bad.yaml"
    path.write_text(
        "leaf_cell_source_rows:\n  expected_row_count: 1\n  note: x\n"
        "month_cell_source_rows:\n  expected_row_count: 1\n  note: x\n"
        "watershed_dated_resolved_rows:\n  expected_row_count: 1\n  note: x\n"
        "watershed_dated_unresolved_rows:\n  expected_row_count: 1\n  note: x\n"
        "unexpected_entry:\n  expected_row_count: 1\n  note: x\n",
        encoding="utf-8",
    )
    with pytest.raises(common.MigrationError, match="宣言名が想定と一致しない"):
        b07.validate_cube_declarations_shape(path)


def test_declarations_shape_rejects_missing_entry(tmp_path):
    """4件のうち1件でも欠ければ構造検証で止まる。"""
    path = tmp_path / "bad.yaml"
    path.write_text(
        "leaf_cell_source_rows:\n  expected_row_count: 1\n  note: x\n",
        encoding="utf-8",
    )
    with pytest.raises(common.MigrationError, match="宣言名が想定と一致しない"):
        b07.validate_cube_declarations_shape(path)


def test_declarations_shape_rejects_missing_required_key(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text(
        "leaf_cell_source_rows:\n  note: x\n"  # expected_row_count が無い
        "month_cell_source_rows:\n  expected_row_count: 1\n  note: x\n"
        "watershed_dated_resolved_rows:\n  expected_row_count: 1\n  note: x\n"
        "watershed_dated_unresolved_rows:\n  expected_row_count: 1\n  note: x\n",
        encoding="utf-8",
    )
    with pytest.raises(common.MigrationError, match="必須キー"):
        b07.validate_cube_declarations_shape(path)


def test_real_declarations_yaml_is_valid_shape():
    """リポジトリに実際にコミットされている宣言 YAML が構造検証を通る。"""
    b07.validate_cube_declarations_shape()


# ---------------------------------------------------------------------------
# (iv) 月セルは年セルの部分和
# ---------------------------------------------------------------------------


def test_month_cells_are_subset_of_year_cells_passes_for_normal_data(tmp_path):
    rows = [
        _row("gbif__day1", "2020-01-05", "2020-01-05", "2020-01-05"),
        _row("gbif__day2", "2020-01-06", "2020-01-06", "2020-01-06"),
        _row("gbif__cross_month", "2020-03-01", "2020-04-05", "2020-03-01/2020-04-05"),
    ]
    conn, decl = _build(tmp_path, rows)
    try:
        b07.build_cube(conn, decl, place_declarations_yaml=None)  # 例外が出なければ OK
    finally:
        conn.close()


def test_month_cells_subset_check_is_detected_when_broken(tmp_path):
    """`_assert_month_cells_are_subset_of_year_cells` が、意図的に壊した
    staging に対して直接 `MigrationError` を投げることを確認する（月セルの
    Σn が対応する年セルの n を超える場合）。
    """
    conn = sqlite3.connect(":memory:")
    conn.execute(b07._CREATE_OCCURRENCE_AGG_SQL.format(table="staging"))
    year_row = (
        "jp-14", "gbif_kanagawa_occurrences", "common:place:grid01.3550_13900", "grid01",
        "common:taxon:gbif.1001", "year", "2020-01-01", "2020-12-31", 1, 0, 0, "occurrence", "v",
    )
    month_row = (
        "jp-14", "gbif_kanagawa_occurrences", "common:place:grid01.3550_13900", "grid01",
        "common:taxon:gbif.1001", "month", "2020-01-01", "2020-01-31", 5, 0, 0, "occurrence", "v",
    )
    placeholders = ", ".join("?" for _ in year_row)
    conn.executemany(f'INSERT INTO "staging" VALUES ({placeholders})', [year_row, month_row])
    conn.commit()
    with pytest.raises(common.MigrationError, match="月セルは年セルの部分和"):
        b07._assert_month_cells_are_subset_of_year_cells(conn, "staging")


# ---------------------------------------------------------------------------
# 形の検証を直接呼ぶ（実際のビルドで崩すのが難しい壊れ方）
# ---------------------------------------------------------------------------


def _make_staging(conn, rows):
    conn.execute(b07._CREATE_OCCURRENCE_AGG_SQL.format(table='"staging"'))
    cols = ", ".join(b07._INSERT_COLUMNS)
    placeholders = ", ".join("?" for _ in b07._INSERT_COLUMNS)
    conn.executemany(f'INSERT INTO "staging" ({cols}) VALUES ({placeholders})', rows)
    conn.commit()


def _staging_row(
    grain, period_start, period_end, n, taxon_id="common:taxon:gbif.1001",
    n_red_list=0, n_alien=0, place_kind="grid01",
):
    return (
        "jp-14", "gbif_kanagawa_occurrences", "common:place:grid01.3550_13900", place_kind, taxon_id,
        grain, period_start, period_end, n, n_red_list, n_alien, "occurrence", "phase-b-fact-slice/v2",
    )


def test_cube_shape_rejects_unknown_grain(tmp_path):
    conn = sqlite3.connect(":memory:")
    _make_staging(conn, [_staging_row("week", "2020-01-01", "2020-01-07", n=1)])
    with pytest.raises(common.MigrationError, match="grain が"):
        b07._assert_cell_shapes(conn, "staging")


def test_cube_shape_rejects_unrounded_year_cell(tmp_path):
    conn = sqlite3.connect(":memory:")
    _make_staging(conn, [_staging_row("year", "2020-01-05", "2020-01-05", n=1)])  # 丸めていない
    with pytest.raises(common.MigrationError, match="暦年境界"):
        b07._assert_cell_shapes(conn, "staging")


def test_cube_shape_rejects_same_year_leaf_cell(tmp_path):
    conn = sqlite3.connect(":memory:")
    _make_staging(conn, [_staging_row("survey_period", "2020-01-01", "2020-12-31", n=1)])  # 同年
    with pytest.raises(common.MigrationError, match="同じ年に収まっている"):
        b07._assert_cell_shapes(conn, "staging")


def test_cube_shape_rejects_month_cell_not_starting_on_day_one(tmp_path):
    conn = sqlite3.connect(":memory:")
    _make_staging(conn, [_staging_row("month", "2020-01-05", "2020-01-31", n=1)])
    with pytest.raises(common.MigrationError, match="暦月境界"):
        b07._assert_cell_shapes(conn, "staging")


def test_cube_shape_rejects_month_cell_spanning_two_months(tmp_path):
    conn = sqlite3.connect(":memory:")
    _make_staging(conn, [_staging_row("month", "2020-01-01", "2020-02-29", n=1)])
    with pytest.raises(common.MigrationError, match="暦月境界"):
        b07._assert_cell_shapes(conn, "staging")


def test_dimension_key_unique_raises_with_examples(tmp_path):
    conn = sqlite3.connect(":memory:")
    _make_staging(conn, [_staging_row("year", "2020-01-01", "2020-12-31", n=1)] * 2)
    with pytest.raises(common.MigrationError, match="次元キーが一意でない"):
        b07._assert_dimension_key_unique(conn, "staging")


# ---------------------------------------------------------------------------
# 変異テスト（コードレビュー指摘1と同じ考え方: 検証が staging/母集団を
# 実際に見ているために、セル生成 SQL 自体が壊れても検出できることを示す）。
# ---------------------------------------------------------------------------


def test_mutation_year_and_leaf_classification_swapped_is_caught(tmp_path, monkeypatch):
    """年セル/leaf セルの分類条件を入れ替える変異（同年の記録が
    `survey_period` に、年をまたぐ記録が `year` に入る）は、grain='survey_period'
    の構造チェック（全行が年をまたいでいるか）で捕まる。
    """
    rows = [
        _row("gbif__same_year", "2020-01-05", "2020-01-05", "2020-01-05"),
        _row("gbif__cross_year", "1990-01-01", "1992-12-31", "1990/1992"),
    ]
    conn, decl = _build(tmp_path, rows)
    try:
        mutated_year = b07._YEAR_CELLS_SQL.replace(
            f"WHERE {b07._SAME_YEAR_EXPR}", f"WHERE {b07._CROSS_YEAR_EXPR}",
        )
        mutated_leaf = b07._LEAF_CELLS_SQL.replace(
            f"WHERE {b07._CROSS_YEAR_EXPR}", f"WHERE {b07._SAME_YEAR_EXPR}",
        )
        assert mutated_year != b07._YEAR_CELLS_SQL
        assert mutated_leaf != b07._LEAF_CELLS_SQL
        monkeypatch.setattr(b07, "_YEAR_CELLS_SQL", mutated_year)
        monkeypatch.setattr(b07, "_LEAF_CELLS_SQL", mutated_leaf)
        with pytest.raises(common.MigrationError, match="同じ年に収まっている"):
            b07.build_cube(conn, decl, place_declarations_yaml=None)
    finally:
        conn.close()


def test_mutation_month_predicate_swapped_for_year_predicate_is_caught(tmp_path, monkeypatch):
    """月セルの述語（同一月に収まるか）を年の述語（同一年に収まるか）に
    差し替える変異——同一年内で月をまたぐ記録まで月セルに（誤った月境界で）
    入ってしまう。セルの形自体は常に有効に見える（境界は独立に計算し直す
    ため）が、月セルの宣言 Σn が実測と食い違うため (ii) で止まる。
    """
    rows = [
        _row("gbif__day", "2020-01-05", "2020-01-05", "2020-01-05"),
        _row("gbif__cross_month", "2020-03-01", "2020-04-05", "2020-03-01/2020-04-05"),
    ]
    conn, decl = _build(tmp_path, rows)
    try:
        mutated_sql = b07._MONTH_CELLS_SQL.replace(
            f"WHERE {b07._SAME_MONTH_EXPR}", f"WHERE {b07._SAME_YEAR_EXPR}",
        )
        assert mutated_sql != b07._MONTH_CELLS_SQL
        monkeypatch.setattr(b07, "_MONTH_CELLS_SQL", mutated_sql)
        # `_materialize_month_bounds` も同じ述語を参照する（1箇所だけに持つ
        # という設計どおり、両方が同時にずれて初めて「月セルの母集団その
        # ものが広がる」実際の壊れ方を再現できる）。
        monkeypatch.setattr(b07, "_SAME_MONTH_EXPR", b07._SAME_YEAR_EXPR)
        with pytest.raises(common.MigrationError, match="month_cell_source_rows|grain='month'"):
            b07.build_cube(conn, decl, place_declarations_yaml=None)
    finally:
        conn.close()


def test_mutation_dropping_unresolved_watershed_rows_is_caught(tmp_path, monkeypatch):
    """流域母集団から NULL 行（未解決の記録）を落とす変異は、母集団の完全性
    検査（行数が日付あり全行数と一致しない）で止まる。
    """
    rows = [
        _row("gbif__resolved", "2020-01-05", "2020-01-05", "2020-01-05"),
        _row("gbif__unresolved", "2020-01-06", "2020-01-06", "2020-01-06"),
    ]
    place_rows = [
        occurrence_place_row("gbif__resolved", DEFAULT_WATERSHED_PLACE_ID),
        occurrence_place_row("gbif__unresolved", None),
    ]
    conn, decl = _build(tmp_path, rows, place_rows=place_rows)
    try:
        orig = b07._POP_SOURCE_SQL[b07.WATERSHED_PLACE_KIND]
        mutated = orig.replace(
            "WHERE o.period_raw IS NOT NULL",
            "WHERE o.period_raw IS NOT NULL AND op.place_id IS NOT NULL",
        )
        assert mutated != orig
        monkeypatch.setitem(b07._POP_SOURCE_SQL, b07.WATERSHED_PLACE_KIND, mutated)
        with pytest.raises(common.MigrationError, match="母集団.*一致しない|一致しない.*母集団"):
            b07.build_cube(conn, decl, place_declarations_yaml=None)
    finally:
        conn.close()


def test_mutation_watershed_join_left_and_wrong_place_kind_is_caught(tmp_path, monkeypatch):
    """`occurrence_place` との JOIN を `LEFT JOIN` に変え、`place_kind` の
    リテラルも書き間違える変異——母集団の行数は変わらない（LEFT JOIN が
    行を落とさないため、単純な行数チェックはすり抜ける）が、全行が
    `place_id NULL` になるため、解決/未解決の宣言 Σn が食い違って止まる。
    """
    rows = [_row("gbif__resolved", "2020-01-05", "2020-01-05", "2020-01-05")]
    place_rows = [occurrence_place_row("gbif__resolved", DEFAULT_WATERSHED_PLACE_ID)]
    conn, decl = _build(tmp_path, rows, place_rows=place_rows)
    try:
        orig = b07._POP_SOURCE_SQL[b07.WATERSHED_PLACE_KIND]
        mutated = orig.replace("JOIN occurrence_place op", "LEFT JOIN occurrence_place op").replace(
            f"op.place_kind = {b07.WATERSHED_PLACE_KIND!r}", "op.place_kind = 'grid01'",
        )
        assert mutated != orig
        assert "LEFT JOIN" in mutated
        monkeypatch.setitem(b07._POP_SOURCE_SQL, b07.WATERSHED_PLACE_KIND, mutated)
        with pytest.raises(common.MigrationError, match="watershed_dated_resolved_rows"):
            b07.build_cube(conn, decl, place_declarations_yaml=None)
    finally:
        conn.close()


def test_mutation_n_alien_formula_swapped_for_n_red_list_is_caught(tmp_path, monkeypatch):
    """`n_alien` の式を `n_red_list` の式にすり替える変異は、系列ごとの
    Σn_alien が母集団と食い違うため (i) で止まる。
    """
    rows = [_row("gbif__alien_only", "2020-01-05", "2020-01-05", "2020-01-05", is_alien=1, red_list_category="")]
    conn, decl = _build(tmp_path, rows)
    try:
        wrong_alien_expr = f"SUM(CASE WHEN {b07._RED_LIST_NONEMPTY_EXPR} THEN 1 ELSE 0 END) AS n_alien"
        for name in ("_YEAR_CELLS_SQL", "_LEAF_CELLS_SQL", "_MONTH_CELLS_SQL"):
            original = getattr(b07, name)
            mutated = original.replace("SUM(is_alien) AS n_alien", wrong_alien_expr)
            assert mutated != original, name
            monkeypatch.setattr(b07, name, mutated)
        with pytest.raises(common.MigrationError, match="Σn/Σn_red_list/Σn_alien"):
            b07.build_cube(conn, decl, place_declarations_yaml=None)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 段階間の指紋（Issue #37 #1。scripts/migrate/common.py 参照）
# ---------------------------------------------------------------------------


def test_build_cube_halts_when_occurrence_changed_since_b06_recorded_it(tmp_path):
    """b07 を1回成功させた後、`occurrence`（b06 の出力）の内容を b06 を経由せず
    直接書き換える（＝b06 が別内容で再実行されたのに b07 が再実行されて
    いない状態を模す）と、2回目の `build_cube` は集計を始める前に
    `scripts/b06_build_occurrence.py を再実行すること` と案内する
    `MigrationError` で止まる。
    """
    rows = [_row("gbif__day", "2020-01-05", "2020-01-05", "2020-01-05")]
    conn, decl = _build(tmp_path, rows)
    try:
        b07.build_cube(conn, decl, place_declarations_yaml=None)

        conn.execute("UPDATE occurrence SET taxon_id = 'common:taxon:gbif.9999' WHERE record_id = 'gbif__day'")
        conn.commit()

        with pytest.raises(common.MigrationError, match="scripts/b06_build_occurrence.py を再実行すること"):
            b07.build_cube(conn, decl, place_declarations_yaml=None)
    finally:
        conn.close()


def test_build_cube_halts_when_occurrence_place_changed_since_b09_recorded_it(tmp_path):
    """同様に、`occurrence_place`（b09 の出力）が b09 を経由せず書き換えられた
    （b09 が再実行されたのに b07 が追随していない）状態は、
    `scripts/b09_build_occurrence_place.py を再実行すること` で止まる。
    """
    rows = [_row("gbif__day", "2020-01-05", "2020-01-05", "2020-01-05")]
    conn, decl = _build(tmp_path, rows)
    try:
        b07.build_cube(conn, decl, place_declarations_yaml=None)

        conn.execute(
            "UPDATE occurrence_place SET place_id = 'common:place:watershed.other' "
            "WHERE record_id = 'gbif__day'"
        )
        conn.commit()

        with pytest.raises(common.MigrationError, match="scripts/b09_build_occurrence_place.py を再実行すること"):
            b07.build_cube(conn, decl, place_declarations_yaml=None)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# b09 の宣言との整合（§1.1「両宣言の整合」）
# ---------------------------------------------------------------------------


def test_consistent_with_place_declarations_passes_when_resolved_count_is_at_least_as_large(tmp_path):
    rows = [_row("gbif__day", "2020-01-05", "2020-01-05", "2020-01-05")]
    conn, decl = _build(tmp_path, rows)
    try:
        place_decl = tmp_path / "occurrence_place_declarations.yaml"
        place_decl.write_text(
            "n_watershed_polygons:\n  expected_row_count: 1\n  note: t\n"
            "place_id_null_count:\n  expected_row_count: 0\n  note: t\n"
            "resolved_count:\n  expected_row_count: 1\n  note: t\n",  # >= 1（このテストの実際の宣言値）
            encoding="utf-8",
        )
        b07.build_cube(conn, decl, place_declarations_yaml=place_decl)  # 例外が出なければ OK
    finally:
        conn.close()


def test_consistent_with_place_declarations_raises_when_resolved_count_too_small(tmp_path):
    rows = [_row("gbif__day", "2020-01-05", "2020-01-05", "2020-01-05")]
    conn, decl = _build(tmp_path, rows)
    try:
        place_decl = tmp_path / "occurrence_place_declarations.yaml"
        place_decl.write_text(
            "n_watershed_polygons:\n  expected_row_count: 1\n  note: t\n"
            "place_id_null_count:\n  expected_row_count: 1\n  note: t\n"
            "resolved_count:\n  expected_row_count: 0\n  note: t\n",  # < 1（このテストの実際の宣言値）
            encoding="utf-8",
        )
        with pytest.raises(common.MigrationError, match="watershed_dated_resolved_rows"):
            b07.build_cube(conn, decl, place_declarations_yaml=place_decl)
    finally:
        conn.close()
