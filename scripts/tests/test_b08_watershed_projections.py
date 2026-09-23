"""scripts/b08_project_occurrence_v1.py の `org_watershed_year`/`org_watershed`
（O-2a）の統合テスト。

本物の `data/db/*.sqlite` を要さず、`scripts/tests/occurrence_fixtures.py` の
小さなフィクスチャだけで完結する。`occurrence_place`（O-2a、b09 が作る
サテライト表）の中身は直接フィクスチャで与える——b08 のこの節は
`occurrence`/`occurrence_place` の中身を信用して読むだけで、点内包判定
そのものは行わない（それは b09/`scripts/migrate/point_in_polygon.py` の責務。
`test_b09_build_occurrence_place.py`・`test_migrate_point_in_polygon.py` 参照）。
"""
import sqlite3

import pytest

import b08_project_occurrence_v1 as b08
from migrate import common

from .occurrence_fixtures import (
    make_occurrence_registry_db,
    make_occurrence_watershed_v1_declarations_yaml,
    make_v2_db_with_occurrence_and_place,
    occurrence_place_row,
    occurrence_row_at,
)

pytestmark = pytest.mark.skipif(
    sqlite3.sqlite_version_info < common.MIN_SQLITE_VERSION,
    reason=f"SQLite {common.MIN_SQLITE_VERSION} 未満（実際: {sqlite3.sqlite_version}）",
)

_W1_PLACE_ID = "common:place:watershed.w1"
_W2_PLACE_ID = "common:place:watershed.w2"
_PLACE_REFS = [
    (_W1_PLACE_ID, "W1", "watershed_meta.watershed_id"),
    (_W2_PLACE_ID, "W2", "watershed_meta.watershed_id"),
]


def _setup(tmp_path, occurrence_rows, occurrence_place_rows):
    v2_db = tmp_path / "v2.sqlite"
    make_v2_db_with_occurrence_and_place(v2_db, occurrence_rows, occurrence_place_rows)

    registry_db = tmp_path / "registry.sqlite"
    places = [(pid, None, "watershed") for pid, _ext, _sid in _PLACE_REFS]
    make_occurrence_registry_db(registry_db, taxa=[], places=places, place_refs=_PLACE_REFS)
    return v2_db, registry_db


def _declarations(tmp_path, **kwargs):
    path = tmp_path / "occurrence_watershed_v1_declarations.yaml"
    make_occurrence_watershed_v1_declarations_yaml(path, **kwargs)
    return path


def test_representative_requires_dated_population_and_moved_records_are_measured(tmp_path):
    """1つのバケット（(139010, 35010)。`FLOOR(x*1000+0.5)`）に4記録:

    - A: 日付なし・rowid最小(1)・自身の正確な解決は W1。
      → 母集団（日付あり）から除外されるため代表にならない
        （もし誤って全行で代表を選ぶと、このバケットの memo は W1 になり、
        以下の期待値がすべて W2 からずれる）。
    - B: 日付あり(2020)・rowid=2（日付ありの中で最小 → 代表）・正確な解決は W2。
    - C: 日付あり(2021)・rowid=3・正確な解決は W2（B と同じ→moved なし）。
    - E: 日付あり(2022)・rowid=4・正確な解決は NULL（B と食い違う→moved）。

    代表 B の正確な解決（W2）が、バケット全体（B・C・E）の「メモの流域」になる。
    """
    occurrence_rows = [
        occurrence_row_at("A", 35.0096, 139.0096, source_row_id=1, period_raw=None),
        occurrence_row_at(
            "B", 35.0104, 139.0104, source_row_id=2,
            period_start="2020-05-01", period_end="2020-05-01", period_raw="2020-05-01",
        ),
        occurrence_row_at(
            "C", 35.0100, 139.0100, source_row_id=3,
            period_start="2021-06-01", period_end="2021-06-01", period_raw="2021-06-01",
        ),
        occurrence_row_at(
            "E", 35.0102, 139.0101, source_row_id=4,
            period_start="2022-07-01", period_end="2022-07-01", period_raw="2022-07-01",
        ),
    ]
    occurrence_place_rows = [
        occurrence_place_row("A", _W1_PLACE_ID),
        occurrence_place_row("B", _W2_PLACE_ID),
        occurrence_place_row("C", _W2_PLACE_ID),
        occurrence_place_row("E", None),
    ]
    v2_db, registry_db = _setup(tmp_path, occurrence_rows, occurrence_place_rows)
    decl = _declarations(
        tmp_path, moved=1, ws_to_ws=0, v1_assigned_exact_unassigned=1,
        v1_unassigned_exact_assigned=0, mixed_buckets=1, keys_changed=1,
    )
    out = tmp_path / "out.sqlite"

    counts, diagnostics = b08.build_watershed_projections(v2_db, registry_db, out, decl)

    assert counts["org_watershed_year"] == 3  # (W2,2020) (W2,2021) (W2,2022)
    assert diagnostics["memo_moved_records"] == 1
    assert diagnostics["ws_to_ws"] == 0
    assert diagnostics["v1_assigned_exact_unassigned"] == 1
    assert diagnostics["v1_unassigned_exact_assigned"] == 0
    assert diagnostics["memo_mixed_buckets"] == 1
    assert diagnostics["org_watershed_year_keys_changed_vs_exact"] == 1

    conn = sqlite3.connect(f"file:{out}?mode=ro", uri=True)
    rows = sorted(conn.execute("SELECT watershed_id, year, n FROM org_watershed_year"))
    assert rows == [("W2", 2020, 1), ("W2", 2021, 1), ("W2", 2022, 1)]
    # A（日付なし）は代表候補から除外され、B/C/E の全てが W2 になる
    # （誤って A が代表になれば watershed_id が 'W1' になるはず）。
    assert {r[0] for r in rows} == {"W2"}


def test_floor_half_up_boundary_merges_into_same_bucket(tmp_path):
    """`CAST(FLOOR(lon*1000+0.5) AS INT)` の丸め（v1 の `Math.round(x*1000)`
    と同じ「0.001度単位で最も近い整数に丸める」規則）が、実際に**丸め方に
    よって結果が変わる**境界値で正しく動くことを確認する。

    `lon_c=139.0105` は `x*1000+0.5=139011.0` ちょうどで、`floor`（＝
    `floor(x+0.5)`、正の値の四捨五入）では 139011 になるが、単純な切り捨て
    （`int(x*1000)=139010`）や Python の `round()`（銀行丸め、
    `round(139010.5)=139010`）では 139010 になる——**丸め方によって別の
    バケットに分かれてしまう値**（`lon_b=139.0112` はどの丸め方でも139011に
    なる値。以前のテストは `139.0100`/`139.0104` を使っていたが、これは
    floor+0.5・truncate・round のどれでも同じ結果になり、丸め規則の実装を
    区別できていなかった——コードレビュー指摘8）。
    """
    import math

    bx_target = math.floor(139.0112 * 1000 + 0.5)
    lon_b, lon_c = 139.0112, 139.0105
    assert math.floor(lon_c * 1000 + 0.5) == bx_target  # floor+0.5 では同じバケットに入る前提の確認
    assert int(lon_c * 1000) != bx_target  # truncate なら別バケットになる（丸め方の違いが効く値であることの確認）
    assert round(lon_c * 1000) != bx_target  # round()（銀行丸め）でも別バケットになる
    occurrence_rows = [
        occurrence_row_at(
            "B", 35.0100, lon_b, source_row_id=1,
            period_start="2020-01-01", period_end="2020-01-01", period_raw="2020-01-01",
        ),
        occurrence_row_at(
            "C", 35.0100, lon_c, source_row_id=2,
            period_start="2020-02-01", period_end="2020-02-01", period_raw="2020-02-01",
        ),
    ]
    occurrence_place_rows = [
        occurrence_place_row("B", _W1_PLACE_ID),
        occurrence_place_row("C", _W2_PLACE_ID),
    ]
    v2_db, registry_db = _setup(tmp_path, occurrence_rows, occurrence_place_rows)
    # キーの変化は2件: (W1,2020) は memo（n=2、B+C）と exact（n=1、B のみ。
    # C の正確な解決は W2 なので exact 側では (W1,2020) に入らない）で値が
    # 食い違う1件＋ (W2,2020)（C の正確な解決だけが持つキー）が exact 側にしか
    # 無い1件、の計2件。
    decl = _declarations(
        tmp_path, moved=1, ws_to_ws=1, v1_assigned_exact_unassigned=0,
        v1_unassigned_exact_assigned=0, mixed_buckets=1, keys_changed=2,
    )
    out = tmp_path / "out.sqlite"

    counts, diagnostics = b08.build_watershed_projections(v2_db, registry_db, out, decl)

    # 代表は rowid=1 の B（W1）。同じバケットの C も B のメモ（W1）を受け取る
    # ——C 自身の正確な解決（W2）ではなく、バケット代表の解決が使われる
    # （これが v1 のメモ化の癖の再現）。
    conn = sqlite3.connect(f"file:{out}?mode=ro", uri=True)
    rows = sorted(conn.execute("SELECT watershed_id, year, n FROM org_watershed_year"))
    assert rows == [("W1", 2020, 2)]
    assert counts["org_watershed_year"] == 1
    assert diagnostics["ws_to_ws"] == 1  # C は B と別バケット扱いなら moved にならないはず


def test_org_watershed_rolls_up_from_org_watershed_year(tmp_path):
    occurrence_rows = [
        occurrence_row_at(
            "A", 35.0100, 139.0100, source_row_id=1,
            period_start="2019-01-01", period_end="2019-01-01", period_raw="2019-01-01",
        ),
        occurrence_row_at(
            "B", 35.0100, 139.0101, source_row_id=2,
            period_start="2019-02-01", period_end="2019-02-01", period_raw="2019-02-01",
        ),
        occurrence_row_at(
            "C", 35.0300, 139.0300, source_row_id=3,
            period_start="2021-01-01", period_end="2021-01-01", period_raw="2021-01-01",
        ),
    ]
    occurrence_place_rows = [
        occurrence_place_row("A", _W1_PLACE_ID),
        occurrence_place_row("B", _W1_PLACE_ID),
        occurrence_place_row("C", _W1_PLACE_ID),
    ]
    v2_db, registry_db = _setup(tmp_path, occurrence_rows, occurrence_place_rows)
    decl = _declarations(
        tmp_path, moved=0, ws_to_ws=0, v1_assigned_exact_unassigned=0,
        v1_unassigned_exact_assigned=0, mixed_buckets=0, keys_changed=0,
    )
    out = tmp_path / "out.sqlite"

    counts, diagnostics = b08.build_watershed_projections(v2_db, registry_db, out, decl)
    assert counts["org_watershed"] == 1
    assert diagnostics["memo_moved_records"] == 0

    conn = sqlite3.connect(f"file:{out}?mode=ro", uri=True)
    row = conn.execute("SELECT watershed_id, n, y_from, y_to FROM org_watershed").fetchone()
    assert row == ("W1", 3, 2019, 2021)


def test_declaration_mismatch_halts(tmp_path):
    occurrence_rows = [
        occurrence_row_at(
            "A", 35.0100, 139.0100, source_row_id=1,
            period_start="2019-01-01", period_end="2019-01-01", period_raw="2019-01-01",
        ),
    ]
    occurrence_place_rows = [occurrence_place_row("A", _W1_PLACE_ID)]
    v2_db, registry_db = _setup(tmp_path, occurrence_rows, occurrence_place_rows)
    # moved の宣言をわざと実測（0）と食い違わせる。
    decl = _declarations(
        tmp_path, moved=999, ws_to_ws=0, v1_assigned_exact_unassigned=0,
        v1_unassigned_exact_assigned=0, mixed_buckets=0, keys_changed=0,
    )
    out = tmp_path / "out.sqlite"

    with pytest.raises(common.MigrationError, match="memo_moved_records"):
        b08.build_watershed_projections(v2_db, registry_db, out, decl)


def test_unresolvable_place_id_halts(tmp_path):
    """`occurrence_place.place_id` が NULL でないのに `place_watershed_lookup`
    （registry の `place_source_ref`）で `watershed_id` が引けない行があれば
    止める（コードレビュー指摘3。mesh 側の `_assert_all_places_resolve_to_mesh`
    と同じ考え方）。
    """
    occurrence_rows = [
        occurrence_row_at(
            "A", 35.0100, 139.0100, source_row_id=1,
            period_start="2019-01-01", period_end="2019-01-01", period_raw="2019-01-01",
        ),
    ]
    # registry の place_refs（_PLACE_REFS）に無い place_id を指す。
    occurrence_place_rows = [occurrence_place_row("A", "common:place:watershed.unknown")]
    v2_db, registry_db = _setup(tmp_path, occurrence_rows, occurrence_place_rows)
    decl = _declarations(
        tmp_path, moved=0, ws_to_ws=0, v1_assigned_exact_unassigned=0,
        v1_unassigned_exact_assigned=0, mixed_buckets=0, keys_changed=0,
    )
    out = tmp_path / "out.sqlite"

    with pytest.raises(common.MigrationError, match="watershed_id が解決できない"):
        b08.build_watershed_projections(v2_db, registry_db, out, decl)


def test_population_record_missing_from_occurrence_place_halts(tmp_path):
    """v1 の母集団の記録なのに `occurrence_place`（`place_kind='watershed'`）に
    対応する行が無い（b06 の後に b09 を実行し忘れた・occurrence_place が
    古いスナップショットのまま、を模す）場合に止める（コードレビュー指摘6）。
    それまでは `LEFT JOIN` が黙って NULL（＝「どの流域にも入らない」正常系）
    と区別が付かなかった。
    """
    occurrence_rows = [
        occurrence_row_at(
            "A", 35.0100, 139.0100, source_row_id=1,
            period_start="2019-01-01", period_end="2019-01-01", period_raw="2019-01-01",
        ),
        occurrence_row_at(
            "B", 35.0100, 139.0101, source_row_id=2,
            period_start="2019-02-01", period_end="2019-02-01", period_raw="2019-02-01",
        ),
    ]
    # B の occurrence_place 行が無い（occurrence_place が古い・部分的な状況を模す）。
    occurrence_place_rows = [occurrence_place_row("A", _W1_PLACE_ID)]
    v2_db, registry_db = _setup(tmp_path, occurrence_rows, occurrence_place_rows)
    decl = _declarations(
        tmp_path, moved=0, ws_to_ws=0, v1_assigned_exact_unassigned=0,
        v1_unassigned_exact_assigned=0, mixed_buckets=0, keys_changed=0,
    )
    out = tmp_path / "out.sqlite"

    with pytest.raises(common.MigrationError, match="occurrence_place"):
        b08.build_watershed_projections(v2_db, registry_db, out, decl)


def test_declaration_breakdown_sum_mismatch_is_rejected_at_load_time(tmp_path):
    """宣言ファイル自体の自己矛盾（breakdown の合計が expected_count と
    食い違う）は、実測を待たずに構造検証の時点で止まる。
    """
    path = tmp_path / "bad.yaml"
    path.write_text(
        "memo_moved_records:\n"
        "  expected_count: 100\n"
        "  breakdown:\n"
        "    ws_to_ws: 1\n"
        "    v1_assigned_exact_unassigned: 1\n"
        "    v1_unassigned_exact_assigned: 1\n"
        "  note: テスト用\n"
        "memo_mixed_buckets:\n"
        "  expected_count: 0\n"
        "  note: テスト用\n"
        "org_watershed_year_keys_changed_vs_exact:\n"
        "  expected_count: 0\n"
        "  note: テスト用\n",
        encoding="utf-8",
    )
    with pytest.raises(common.MigrationError, match="breakdown"):
        b08.load_and_validate_watershed_declarations(path)
