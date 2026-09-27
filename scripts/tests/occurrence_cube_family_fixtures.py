"""Issue #48 PR-3a U2（b08）用の追加フィクスチャ。

`scripts/tests/occurrence_fixtures.py` は U1（`scripts/b07_build_occurrence_
cube.py`・宣言・s01）も並行して触るため、そちらは変更しない
（`_OCCURRENCE_AGG_COLUMNS`/`_CREATE_OCCURRENCE_AGG_SQL` に `n_alien` が無い
・族×place_kind のセルを持たない、今の b07 のスキーマのまま）。ここでは
b08 のテスト専用に、`n_alien` 列・`watershed` セル・`month` セルを含む
`occurrence_agg` を手書きで作るための別ヘルパを持つ。

b07 が本物の「族×place_kind」構築ロジック（O-1 設計 v2 §0-1: `grid01`×
`year`/`grid01`×`month`/`watershed`×`year`）を実装するのは別 PR（U1）の
担当——ここでは b08 側の射影・検証（`grain IN (年 族)` の絞り込み、
`_assert_watershed_cells_match_exact` 等）を確かめるための、値の辻褄が
合った最小限のセルを手で組み立てるだけで、b07 の実装は再現しない。
"""
from __future__ import annotations

import sqlite3

from . import occurrence_fixtures as _occurrence_fixtures

# `scripts/b07_build_occurrence_cube.py` の `DIM_COLUMNS`（8列: region_id,
# source_id, place_id, place_kind, taxon_id, grain, period_start,
# period_end）+ 測度（n, n_red_list, n_alien）+ 由来（built_from,
# spec_version）——設計書 PR-3a §1.1 の `n_alien` 追加を先取りした形。
_OCCURRENCE_AGG_COLUMNS = (
    "region_id", "source_id", "place_id", "place_kind", "taxon_id", "grain", "period_start", "period_end",
    "n", "n_red_list", "n_alien", "built_from", "spec_version",
)

_CREATE_OCCURRENCE_AGG_SQL = """
CREATE TABLE occurrence_agg (
  region_id TEXT, source_id TEXT, place_id TEXT, place_kind TEXT, taxon_id TEXT,
  grain TEXT, period_start TEXT, period_end TEXT,
  n INTEGER, n_red_list INTEGER, n_alien INTEGER,
  built_from TEXT, spec_version TEXT
)
"""


def occurrence_agg_row(
    *, place_id, place_kind, grain, period_start, period_end, n,
    taxon_id=None, n_red_list=0, n_alien=0,
    source_id="gbif_kanagawa_occurrences", region_id="jp-14",
    built_from="occurrence+occurrence_place", spec_version="phase-b-fact-slice/v2-test",
) -> tuple:
    """`_OCCURRENCE_AGG_COLUMNS` の並びで `occurrence_agg` の1行を組み立てる。"""
    return (
        region_id, source_id, place_id, place_kind, taxon_id, grain, period_start, period_end,
        n, n_red_list, n_alien, built_from, spec_version,
    )


def add_occurrence_agg_table(conn: sqlite3.Connection, rows: list[tuple]) -> None:
    """開いている接続 `conn`（`occurrence`〔＋ `occurrence_place`〕を持つ
    v2.sqlite）に、`n_alien` 列を持つ `occurrence_agg` を作って `rows` を
    入れる（コミットは呼び出し側の責務）。
    """
    conn.execute(_CREATE_OCCURRENCE_AGG_SQL)
    placeholders = ", ".join("?" for _ in _OCCURRENCE_AGG_COLUMNS)
    conn.executemany(f"INSERT INTO occurrence_agg VALUES ({placeholders})", rows)


def make_v2_db_with_occurrence_and_agg_family(path, occurrence_rows: list[tuple], occurrence_agg_rows: list[tuple]) -> None:
    """`occurrence`（L2）と、`n_alien` 列を持つ `occurrence_agg` の両方を持つ
    v2.sqlite 相当を作る（`occurrence_place` は無し——grid01 側〔年キー8表〕
    のテスト専用）。
    """
    conn = sqlite3.connect(f"file:{path}", uri=True)
    try:
        _occurrence_fixtures._create_and_fill_occurrence(conn, occurrence_rows)
        add_occurrence_agg_table(conn, occurrence_agg_rows)
        conn.commit()
    finally:
        conn.close()


def make_v2_db_with_occurrence_place_and_agg(
    path, occurrence_rows: list[tuple], occurrence_place_rows: list[tuple], occurrence_agg_rows: list[tuple],
) -> None:
    """`occurrence`・`occurrence_place`・（`n_alien` 列を持つ）`occurrence_agg`
    の3つを持つ v2.sqlite 相当を作る（O-2a・watershed セルのテスト用。
    `occurrence_fixtures.make_v2_db_with_occurrence_and_place()`〔公開 API〕
    で先に前2つを作ってから、この worktree 専用の `occurrence_agg` を
    別接続で足す——`occurrence_fixtures.py` 自体は変更しない）。
    """
    _occurrence_fixtures.make_v2_db_with_occurrence_and_place(path, occurrence_rows, occurrence_place_rows)
    conn = sqlite3.connect(f"file:{path}", uri=True)
    try:
        add_occurrence_agg_table(conn, occurrence_agg_rows)
        conn.commit()
    finally:
        conn.close()


def build_matching_occurrence_agg_watershed_rows(
    occurrence_rows: list[tuple], occurrence_place_rows: list[tuple], place_watershed_map: dict[str, str],
    *, taxon_id=None, source_id: str = "gbif_kanagawa_occurrences", region_id: str = "jp-14",
) -> list[tuple]:
    """`occurrence_rows`（`occurrence_fixtures.occurrence_row()` の形）と
    `occurrence_place_rows`（`occurrence_fixtures.occurrence_place_row()` の
    形、`place_kind='watershed'`）から、記録自身の「正確な」解決を
    (watershed_id, year) で畳んだ `occurrence_agg` の watershed セル
    （`grain='year'`）を機械的に組み立てる。

    b08 の `_assert_watershed_cells_match_exact` が比較する「キューブ側」を、
    b08 自身が独立に組む `org_watershed_year_exact`（`occurrence`+
    `occurrence_place` の記録単位の正確な解決を `(exact_watershed_id, year)`
    で集計し直したもの——年は `period_raw` の先頭4桁、`n_alien=SUM(is_alien)`、
    `n_red_list` は red_list_category が非空かどうかの件数）と一致するように
    作る。母集団の条件（`period_raw` が4桁以上）も同じ式（`_V1_POPULATION_
    WHERE_TMPL` の `period_raw` 部分。`lat IS NOT NULL` は既定値がある
    テストフィクスチャでは常に真なのでここでは見ない）で揃えてある。

    `place_watershed_map` は `{watershed の place_id: watershed_id}`
    （registry の `place_source_ref` と対にする、各 watershed_id につき
    place_id は1つの前提）。この関数自体は b07 の本物の「族×place_kind」
    構築ロジックを再現しない——テスト専用の最小限の組み立て。
    """
    # occurrence_place_row() は (record_id, place_kind, place_id, method,
    # built_from, spec_version) の並び。
    place_by_record = {
        row[0]: row[2] for row in occurrence_place_rows if row[1] == "watershed"
    }
    place_id_by_watershed = {v: k for k, v in place_watershed_map.items()}

    cells: dict[tuple[str, int], list[int]] = {}
    for row in occurrence_rows:
        record_id = row[0]
        period_raw = row[14]
        red_list_category = row[18]
        is_alien = row[19] or 0
        if not period_raw or len(period_raw) < 4:
            continue
        place_id = place_by_record.get(record_id)
        if place_id is None:
            continue
        watershed_id = place_watershed_map.get(place_id)
        if watershed_id is None:
            continue
        year = int(period_raw[:4])
        key = (watershed_id, year)
        n, n_red_list, n_alien = cells.get(key, [0, 0, 0])
        n += 1
        n_red_list += 1 if (red_list_category not in (None, "")) else 0
        n_alien += is_alien
        cells[key] = [n, n_red_list, n_alien]

    rows: list[tuple] = []
    for (watershed_id, year), (n, n_red_list, n_alien) in cells.items():
        place_id = place_id_by_watershed[watershed_id]
        rows.append(occurrence_agg_row(
            region_id=region_id, source_id=source_id, place_id=place_id, place_kind="watershed",
            taxon_id=taxon_id, grain="year", period_start=f"{year:04d}-01-01", period_end=f"{year:04d}-12-31",
            n=n, n_red_list=n_red_list, n_alien=n_alien,
        ))
    return rows
