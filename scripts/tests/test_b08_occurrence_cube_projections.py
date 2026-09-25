"""scripts/b08_project_occurrence_v1.py の O-1b 部分（年キー8表・
`species_month`）の統合テスト。本物の `data/db/v2.sqlite`/`registry.sqlite` を
要さず、`scripts/tests/occurrence_fixtures.py` の小さな自作 sqlite だけで
完結する。`org_norm`（O-1a）は `test_b08_project_occurrence_v1.py` に残す。

## 2つのキューブの作り方

- `_build_cube_via_b07`: `occurrence`（L2）フィクスチャを実際に
  `b07_build_occurrence_cube.build_cube()` に通して `occurrence_agg` を作る。
  値が本物のロジックから出るため、L2 と食い違わない（コードレビュー指摘13:
  「手で作った辻褄の合わない agg だけにしない」）。年キー8表の射影ロジック
  そのものを確かめるテストはこちらを使う。
- `make_v2_db_with_occurrence_and_agg`（`occurrence_fixtures`）: `occurrence`
  と `occurrence_agg` を別々に手で作る。b08 側の機械検証（L2-キューブの
  Σn 突合・grain の語彙・place 解決）が「本当に崩れを検出できるか」を
  確かめるテスト（わざと食い違わせる）だけがこちらを使う。
"""
import sqlite3

import pytest

import b07_build_occurrence_cube as b07
import b08_project_occurrence_v1 as b08
from migrate import common

from .occurrence_fixtures import (
    DEFAULT_GRID01_PLACE_ID,
    add_occurrence_place_table,
    make_occurrence_cube_declarations_yaml,
    make_occurrence_registry_db,
    make_occurrence_watershed_v1_declarations_yaml,
    make_taxon_group_yaml,
    make_v2_db_with_occurrence,
    make_v2_db_with_occurrence_and_agg,
    occurrence_place_row,
    occurrence_row,
)

# b07/b08 は `assert_grouped_totals_match`（FULL OUTER JOIN、SQLite 3.39以降）
# を使うため `common.require_sqlite_version()` で古い SQLite を拒む
# （`scripts/migrate/common.py` 参照）。この版のガード自体の単体テストは
# `scripts/tests/test_migrate_common.py`。ここでは環境の SQLite が実際に
# 古いとき、意味の無い失敗の山を作らずスキップする。
pytestmark = pytest.mark.skipif(
    sqlite3.sqlite_version_info < common.MIN_SQLITE_VERSION,
    reason=f"SQLite {common.MIN_SQLITE_VERSION} 未満（実際: {sqlite3.sqlite_version}）",
)

# 2つの taxon_id（GBIF由来・iNat由来）が同じ binom（canonical_binomial）に
# 対応するシナリオ（O-1b brief: 「species_mesh_year・mesh_species の DISTINCT
# が複数 taxon_id → 同じ binom で正しく数えられる」の fixture）。
_TAXA = [
    (
        "common:taxon:gbif.1001", "Foo bar", "species", "Insecta", "Animalia",
        "Arthropoda", "Fooales", "Fooidae", "昆虫類",
    ),
    (
        "common:taxon:inat.2002", "Foo bar", "species", "Insecta", "Animalia",
        "Arthropoda", "Fooales", "Fooidae", "昆虫類",
    ),
]

_PLACE = [(DEFAULT_GRID01_PLACE_ID, None, "grid01")]
_PLACE_SOURCE_REF = [(DEFAULT_GRID01_PLACE_ID, "grid01:3550,13900", "organism_records.lat_lon")]

_PLACE_ID = DEFAULT_GRID01_PLACE_ID


# ---------------------------------------------------------------------------
# 実際に b07 を通してキューブを作る側（本物のロジックから値が出る。行の
# 組み立ては `occurrence_fixtures.occurrence_row` に集約——/simplify 指摘7:
# 以前は `_row`〔test_b07〕・`_dated_row`〔ここ〕・`_occ_row`〔下〕の3通りに
# 分かれていた）。
# ---------------------------------------------------------------------------

def _bulk_dated_rows(taxon_id, source_id, date_str, count, *, prefix=None, start_source_row_id=1):
    """同じ日付（`date_str`）を持つ、日付ありの `occurrence` 行を `count` 件
    作る（`species2.n >= 80` のようなしきい値をまたぐテスト用。全件が
    本物の L2 レコードなので、`b07` を通せば一貫したキューブになる）。
    """
    prefix = prefix or f"{source_id}__{taxon_id}__{date_str}"
    return [
        occurrence_row(
            f"{prefix}__{i}", taxon_id, date_str, date_str, date_str,
            source_id=source_id, source_row_id=start_source_row_id + i,
        )
        for i in range(count)
    ]


def _build_cube_via_b07(tmp_path, occurrence_rows, *, leaf_expected: int, dirname="cube"):
    """`occurrence_rows` から `occurrence` を作り、実際に `b07.build_cube()`
    を通して `occurrence_agg` を構築した `v2.sqlite` のパスを返す。
    """
    d = tmp_path / dirname
    d.mkdir()
    db_path = d / "v2.sqlite"
    make_v2_db_with_occurrence(db_path, occurrence_rows)
    conn = sqlite3.connect(f"file:{db_path}", uri=True)
    decl_path = d / "occurrence_cube_declarations.yaml"
    make_occurrence_cube_declarations_yaml(decl_path, expected_row_count=leaf_expected)
    try:
        b07.build_cube(conn, decl_path)
        conn.commit()
    finally:
        conn.close()
    return db_path


def _add_occurrence_place(db_path, rows) -> None:
    """`db_path`（`occurrence` を持つ v2.sqlite）に `occurrence_place`
    （O-2a）テーブルを追加で作る（`build_all_projections`/
    `build_watershed_projections` が要求するため）。`rows` は
    `occurrence_fixtures.occurrence_place_row()` で組み立てたタプル列。
    テーブルの作り方自体は `occurrence_fixtures.add_occurrence_place_table()`
    （`make_v2_db_with_occurrence_and_place()` と共有。/simplify 指摘7）に
    委ねる——ここでは「既存の db を開いて追加する」薄い接続管理だけを持つ。
    """
    conn = sqlite3.connect(f"file:{db_path}", uri=True)
    try:
        add_occurrence_place_table(conn, rows)
        conn.commit()
    finally:
        conn.close()


def _setup_registry(tmp_path, *, taxa=None, default_label_ja="未判定", dirname="registry"):
    d = tmp_path / dirname
    d.mkdir()
    registry_db = d / "registry.sqlite"
    taxon_group_yaml = d / "taxon_group.yaml"
    make_occurrence_registry_db(
        registry_db, taxa=taxa if taxa is not None else _TAXA, places=_PLACE, place_refs=_PLACE_SOURCE_REF,
    )
    make_taxon_group_yaml(taxon_group_yaml, default_label_ja)
    return registry_db, taxon_group_yaml


def _read(out_path, table, columns, order_by=None):
    conn = sqlite3.connect(f"file:{out_path}?mode=ro", uri=True)
    try:
        collist = ", ".join(columns)
        sql = f"SELECT {collist} FROM {table}"
        if order_by:
            sql += f" ORDER BY {order_by}"
        rows = conn.execute(sql).fetchall()
        return [dict(zip(columns, row)) for row in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 手で occurrence/occurrence_agg を別々に作る側（機械検証が崩れを検出できる
# ことを確かめる専用。値の食い違いをわざと作る）
# ---------------------------------------------------------------------------

def _agg_row(
    taxon_id, grain, period_start, period_end, n, n_red_list=0,
    source_id="gbif_kanagawa_occurrences", place_id=_PLACE_ID, region_id="jp-14", place_kind="grid01",
):
    return (
        region_id, source_id, place_id, place_kind, taxon_id, grain, period_start, period_end,
        n, n_red_list, "occurrence", "phase-b-fact-slice/v1",
    )


def _occ_row(record_id, taxon_id, period_raw, source_id="gbif_kanagawa_occurrences", record_id_suffix=1):
    """`_agg_row` と組み合わせて `make_v2_db_with_occurrence_and_agg` に渡す
    `occurrence` 行。`period_start`/`period_end` はこの用途では使わない列
    （NULL でよい）——`species2` の L2 由来列・`species_month` が読むのは
    `taxon_id`/`period_raw`/`vernacular_name`/`red_list_category` だけ。
    `occurrence_row` に `period_start=None, period_end=None` を渡すだけの
    薄い呼び出し（/simplify 指摘7）。
    """
    return occurrence_row(
        record_id, taxon_id, None, None, period_raw,
        source_id=source_id, source_row_id=record_id_suffix, red_list_category="LC",
    )


# ===========================================================================
# 年キー8表・species_month の射影ロジック（実際に b07 を通したキューブから）
# ===========================================================================

def test_leaf_cell_is_attributed_to_its_start_year(tmp_path):
    """年キーの表は leaf セル（grain='survey_period'。年をまたぐ区間）を、
    セルの period_start の年（＝記録の開始年）に入れる（ADR-0025 D3）。
    """
    rows = [occurrence_row(
        "gbif__leaf", "common:taxon:gbif.1001", "1990-01-01", "1992-12-31", "1990/1992",
        red_list_category="LC",
    )]
    cube_db = _build_cube_via_b07(tmp_path, rows, leaf_expected=1)
    registry_db, taxon_group_yaml = _setup_registry(tmp_path)
    out = tmp_path / "out.sqlite"
    counts = b08.build_occurrence_cube_projections(cube_db, registry_db, out, taxon_group_yaml)
    assert counts["mesh_year"] == 1

    mesh_year = _read(out, "mesh_year", ["mlat", "mlon", "year", "n", "species_n", "rl_n"])[0]
    assert mesh_year == {"mlat": 3550, "mlon": 13900, "year": 1990, "n": 1, "species_n": 1, "rl_n": 1}

    org_group_year = _read(out, "org_group_year", ["year", "n"])[0]
    assert org_group_year == {"year": 1990, "n": 1}

    effort_year = _read(out, "effort_year", ["year", "n", "n_gbif"])[0]
    assert effort_year == {"year": 1990, "n": 1, "n_gbif": 1}


def test_year_cell_uses_its_own_calendar_year(tmp_path):
    """grain='year' セルは（暦年境界へ丸められた）自身の period_start の年に
    入る。
    """
    rows = [occurrence_row("gbif__year", "common:taxon:gbif.1001", "2020-01-05", "2020-01-05", "2020-01-05")]
    cube_db = _build_cube_via_b07(tmp_path, rows, leaf_expected=0)
    registry_db, taxon_group_yaml = _setup_registry(tmp_path)
    out = tmp_path / "out.sqlite"
    b08.build_occurrence_cube_projections(cube_db, registry_db, out, taxon_group_yaml)
    row = _read(out, "mesh_year", ["mlat", "mlon", "year", "n"])[0]
    assert row == {"mlat": 3550, "mlon": 13900, "year": 2020, "n": 1}


def test_full_pipeline_collapses_taxon_ids_and_reproduces_species_month_quirk(tmp_path):
    """端から端まで（`occurrence` フィクスチャ → 実際の `b07.build_cube` →
    `b08`）の1本のシナリオで、複数の `taxon_id` → 同じ `binom` の DISTINCT
    集約（`species_mesh_year`/`mesh_species`）・leaf セルの開始年への帰属・
    `species_month` の `mo` 非月値の再現（'YYYY/YYYY' 区間）・
    `species2.n >= 80` しきい値をまとめて確かめる
    （コードレビュー指摘13: 手で辻褄を合わせた `occurrence_agg` だけに
    頼らない）。
    """
    bulk_gbif = _bulk_dated_rows("common:taxon:gbif.1001", "gbif_kanagawa_occurrences", "2020-06-15", 40)
    bulk_inat = _bulk_dated_rows(
        "common:taxon:inat.2002", "inaturalist_kanagawa", "2020-06-15", 40, start_source_row_id=1000,
    )
    # 年をまたぐ区間2件（leaf。1990/1992 は yr<2018 で species_month の対象外、
    # 2018/2020 は yr>=2018 で対象——substr(raw,6,2) が「月」ではない値になる
    # v1 の癖をここで再現する: mo=CAST('20')=20）。
    leaf_old = occurrence_row(
        "gbif__leaf_old", "common:taxon:gbif.1001", "1990-01-01", "1992-12-31", "1990/1992",
        source_row_id=2001, red_list_category="LC",
    )
    leaf_recent = occurrence_row(
        "gbif__leaf_recent", "common:taxon:gbif.1001", "2018-01-01", "2020-12-31", "2018/2020",
        source_row_id=2002,
    )
    rows = bulk_gbif + bulk_inat + [leaf_old, leaf_recent]
    cube_db = _build_cube_via_b07(tmp_path, rows, leaf_expected=2)
    registry_db, taxon_group_yaml = _setup_registry(tmp_path)
    out = tmp_path / "out.sqlite"
    b08.build_occurrence_cube_projections(cube_db, registry_db, out, taxon_group_yaml)

    species2 = _read(out, "species2", ["binom", "n"])
    assert species2 == [{"binom": "Foo bar", "n": 82}]  # 40+40+1+1, n>=80 を満たす

    smy = _read(out, "species_mesh_year", ["binom", "year", "mlat", "mlon", "n"], order_by="year")
    assert smy == [
        {"binom": "Foo bar", "year": 1990, "mlat": 3550, "mlon": 13900, "n": 1},
        {"binom": "Foo bar", "year": 2018, "mlat": 3550, "mlon": 13900, "n": 1},
        # 2つの taxon_id（gbif.1001/inat.2002）のセルが binom で1行に集約される。
        {"binom": "Foo bar", "year": 2020, "mlat": 3550, "mlon": 13900, "n": 80},
    ]

    mesh_species = _read(out, "mesh_species", ["mlat", "mlon", "species_n", "rl_species_n"])[0]
    # binom で畳まれるので species_n=1（taxon_id の数=2 ではない）。rl_species_n も
    # leaf_old（n_red_list=1）が同じ binom に属するため1。
    assert mesh_species == {"mlat": 3550, "mlon": 13900, "species_n": 1, "rl_species_n": 1}

    species_month = _read(out, "species_month", ["binom", "month", "n"], order_by="month")
    assert species_month == [
        {"binom": "Foo bar", "month": 6, "n": 80},  # 2020-06-15 の bulk 80件
        {"binom": "Foo bar", "month": 20, "n": 1},  # '2018/2020' の mo 非月値（1990/1992 は yr<2018 で除外）
    ]


def test_species_month_excludes_years_before_2018(tmp_path):
    bulk = _bulk_dated_rows("common:taxon:gbif.1001", "gbif_kanagawa_occurrences", "2020-01-05", 80)
    old = occurrence_row(
        "gbif__old", "common:taxon:gbif.1001", "2010-05-01", "2010-05-01", "2010-05-01", source_row_id=9001,
    )
    cube_db = _build_cube_via_b07(tmp_path, bulk + [old], leaf_expected=0)
    registry_db, taxon_group_yaml = _setup_registry(tmp_path)
    out = tmp_path / "out.sqlite"
    b08.build_occurrence_cube_projections(cube_db, registry_db, out, taxon_group_yaml)
    rows_out = _read(out, "species_month", ["binom", "month", "n"])
    assert rows_out == [{"binom": "Foo bar", "month": 1, "n": 80}]  # 2010年分は除外


def test_species_month_excludes_species_below_n80(tmp_path):
    """`species2.n < 80` の binom は `species_month`/`species_mesh_year` の
    対象外（v1 のとおり。全年・全記録で判定）。
    """
    rows = _bulk_dated_rows("common:taxon:gbif.1001", "gbif_kanagawa_occurrences", "2020-01-05", 10)  # n<80
    cube_db = _build_cube_via_b07(tmp_path, rows, leaf_expected=0)
    registry_db, taxon_group_yaml = _setup_registry(tmp_path)
    out = tmp_path / "out.sqlite"
    counts = b08.build_occurrence_cube_projections(cube_db, registry_db, out, taxon_group_yaml)
    assert counts["species_month"] == 0
    assert counts["species_mesh_year"] == 0
    species2 = _read(out, "species2", ["binom", "n"])
    assert species2 == [{"binom": "Foo bar", "n": 10}]


def test_taxon_id_null_cell_uses_default_label_and_is_excluded_from_species_tables(tmp_path):
    """`taxon_id` が NULL の記録は `org_group_year` に既定ラベルで入り、
    `species2`/`species_mesh_year`/`mesh_species` の DISTINCT（`binom` 基準）
    からは除外される。
    """
    rows = [occurrence_row("gbif__unresolved", None, "2020-01-05", "2020-01-05", "2020-01-05")]
    cube_db = _build_cube_via_b07(tmp_path, rows, leaf_expected=0)
    registry_db, taxon_group_yaml = _setup_registry(tmp_path, default_label_ja="未判定")
    out = tmp_path / "out.sqlite"
    b08.build_occurrence_cube_projections(cube_db, registry_db, out, taxon_group_yaml)

    org_group_year = _read(out, "org_group_year", ["year", "taxon_group", "n"])[0]
    assert org_group_year == {"year": 2020, "taxon_group": "未判定", "n": 1}

    assert _read(out, "species2", ["binom"]) == []
    assert _read(out, "species_mesh_year", ["binom"]) == []

    mesh_species = _read(out, "mesh_species", ["mlat", "mlon", "species_n"])[0]
    assert mesh_species == {"mlat": 3550, "mlon": 13900, "species_n": 0}  # binom NULL は数えない


def test_mesh_species_includes_null_place_but_mesh_year_excludes_it(tmp_path):
    """v1 のとおり `mesh_species` は座標フィルタが無い（`(NULL, NULL)` の行が
    そのまま出る）。`mesh_year` は座標ありのセルだけを対象にする
    （`place_id IS NOT NULL`。コードレビュー指摘4）。
    """
    occurrence_rows = [
        _occ_row("gbif__with_place", "common:taxon:gbif.1001", "2020-01-05", record_id_suffix=1),
        _occ_row("gbif__no_place", "common:taxon:gbif.1001", "2020-01-06", record_id_suffix=2),
    ]
    occurrence_agg_rows = [
        _agg_row("common:taxon:gbif.1001", "year", "2020-01-01", "2020-12-31", n=1, place_id=_PLACE_ID),
        _agg_row("common:taxon:gbif.1001", "year", "2020-01-01", "2020-12-31", n=1, place_id=None),
    ]
    cube_db = tmp_path / "v2.sqlite"
    make_v2_db_with_occurrence_and_agg(cube_db, occurrence_rows, occurrence_agg_rows)
    registry_db, taxon_group_yaml = _setup_registry(tmp_path)
    out = tmp_path / "out.sqlite"
    b08.build_occurrence_cube_projections(cube_db, registry_db, out, taxon_group_yaml)

    assert _read(out, "mesh_year", ["mlat", "mlon", "n"]) == [{"mlat": 3550, "mlon": 13900, "n": 1}]

    mesh_species = _read(out, "mesh_species", ["mlat", "mlon", "species_n"])
    assert len(mesh_species) == 2
    assert {"mlat": 3550, "mlon": 13900, "species_n": 1} in mesh_species
    assert {"mlat": None, "mlon": None, "species_n": 1} in mesh_species


# ===========================================================================
# 機械検証が崩れを検出できること（わざと食い違わせた手作りフィクスチャ）
# ===========================================================================

def test_grain_month_cell_stops_projection(tmp_path):
    """`occurrence_agg` に想定外の grain（`'month'`）が混ざっていたら、年
    キー8表を作る前に止まる（コードレビュー指摘2。将来 month セルを黙って
    足しても年の表の n が倍になったりしない——絞り込みで捨てず、明示的に
    止める）。
    """
    occurrence_rows = [_occ_row("gbif__1", "common:taxon:gbif.1001", "2020-01-05")]
    occurrence_agg_rows = [
        _agg_row("common:taxon:gbif.1001", "month", "2020-01-01", "2020-01-31", n=1),
    ]
    cube_db = tmp_path / "v2.sqlite"
    make_v2_db_with_occurrence_and_agg(cube_db, occurrence_rows, occurrence_agg_rows)
    registry_db, taxon_group_yaml = _setup_registry(tmp_path)
    out = tmp_path / "out.sqlite"
    with pytest.raises(common.MigrationError, match="grain が 'year'/'survey_period' 以外"):
        b08.build_occurrence_cube_projections(cube_db, registry_db, out, taxon_group_yaml)


def test_unknown_place_kind_stops_projection(tmp_path):
    """`occurrence_agg.place_kind` が既知の値（`'grid01'`/`'watershed'`）以外
    だと、年キー8表を作る前に止まる（/simplify 指摘9:
    `_assert_known_place_kinds` に対応するテストが無かった）。
    """
    occurrence_rows = [_occ_row("gbif__1", "common:taxon:gbif.1001", "2020-01-05")]
    occurrence_agg_rows = [
        _agg_row(
            "common:taxon:gbif.1001", "year", "2020-01-01", "2020-12-31", n=1,
            place_kind="mesh3",  # ADR-0011 の語彙にはあるが _KNOWN_PLACE_KINDS には無い
        ),
    ]
    cube_db = tmp_path / "v2.sqlite"
    make_v2_db_with_occurrence_and_agg(cube_db, occurrence_rows, occurrence_agg_rows)
    registry_db, taxon_group_yaml = _setup_registry(tmp_path)
    out = tmp_path / "out.sqlite"
    with pytest.raises(common.MigrationError, match="place_kind が想定外の値を持つ"):
        b08.build_occurrence_cube_projections(cube_db, registry_db, out, taxon_group_yaml)


def test_l2_cube_mismatch_stops_projection(tmp_path):
    """`occurrence_agg` の `Σn` が `occurrence`（L2）の日付あり行数と食い違うと
    （＝キューブが『今の occurrence の分割』になっていない）、年キー8表を
    作る前に止まる（コードレビュー指摘2）。
    """
    occurrence_rows = [_occ_row("gbif__1", "common:taxon:gbif.1001", "2020-01-05")]  # L2は1件
    occurrence_agg_rows = [
        _agg_row("common:taxon:gbif.1001", "year", "2020-01-01", "2020-12-31", n=5),  # キューブは5件と主張
    ]
    cube_db = tmp_path / "v2.sqlite"
    make_v2_db_with_occurrence_and_agg(cube_db, occurrence_rows, occurrence_agg_rows)
    registry_db, taxon_group_yaml = _setup_registry(tmp_path)
    out = tmp_path / "out.sqlite"
    with pytest.raises(
        common.MigrationError,
        match=r"scripts/b06_build_occurrence\.py の後に scripts/b07_build_occurrence_cube\.py を再実行",
    ):
        b08.build_occurrence_cube_projections(cube_db, registry_db, out, taxon_group_yaml)


def test_place_id_without_mesh_resolution_stops_projection(tmp_path):
    """`place_id` はあるのに `place_mesh_lookup`（grid01 の
    `place_source_ref`）で解決できないセルがあれば、黙って `mlat=NULL` に
    せず止める（コードレビュー指摘4）。
    """
    occurrence_rows = [_occ_row("gbif__1", "common:taxon:gbif.1001", "2020-01-05")]
    occurrence_agg_rows = [
        _agg_row(
            "common:taxon:gbif.1001", "year", "2020-01-01", "2020-12-31", n=1,
            place_id="common:place:watershed.unknown",  # grid01 の place_source_ref に無い
        ),
    ]
    cube_db = tmp_path / "v2.sqlite"
    make_v2_db_with_occurrence_and_agg(cube_db, occurrence_rows, occurrence_agg_rows)
    registry_db, taxon_group_yaml = _setup_registry(tmp_path)
    out = tmp_path / "out.sqlite"
    with pytest.raises(common.MigrationError, match="mlat/mlon が解決できない"):
        b08.build_occurrence_cube_projections(cube_db, registry_db, out, taxon_group_yaml)


def test_stale_taxon_id_in_occurrence_agg_raises(tmp_path):
    """`occurrence_agg.taxon_id` は NULL ではないのに `registry.taxon` に無い
    （古い registry）場合、`build_occurrence_cube_projections` を止める
    （`org_norm` 側の同じ検証をキューブ側にも一般化したもの。コードレビュー
    指摘7）。メッセージは文脈（occurrence_agg）に応じて b06→b07 の再実行を
    案内する。
    """
    rows = [occurrence_row("gbif__ghost", "common:taxon:gbif.9999", "2020-01-05", "2020-01-05", "2020-01-05")]
    cube_db = _build_cube_via_b07(tmp_path, rows, leaf_expected=0)
    registry_db, taxon_group_yaml = _setup_registry(tmp_path)  # registry には gbif.9999 が無い
    out = tmp_path / "out.sqlite"
    with pytest.raises(
        common.MigrationError,
        match=r"registry\.taxon に無い taxon_id が1種.*scripts/b06_build_occurrence\.py の後に "
        r"scripts/b07_build_occurrence_cube\.py",
    ):
        b08.build_occurrence_cube_projections(cube_db, registry_db, out, taxon_group_yaml)


# ===========================================================================
# 前提の確認（出力ファイルを消す前に。コードレビュー指摘6）
# ===========================================================================

def test_missing_occurrence_agg_table_stops_before_wiping_output(tmp_path):
    """`occurrence_agg` がまだ無い `v2.sqlite`（b07 未実行を模す）に対して
    `build_occurrence_cube_projections` を呼ぶと、出力ファイルを消す前に
    案内メッセージで止まる（コードレビュー指摘6。以前は出力を消した後で
    生の `OperationalError` になり、空の `org_norm` だけが残っていた）。
    """
    cube_db = tmp_path / "v2.sqlite"
    make_v2_db_with_occurrence(
        cube_db, [occurrence_row("gbif__1", "common:taxon:gbif.1001", "2020-01-05", "2020-01-05", "2020-01-05")],
    )
    # occurrence_agg はまだ作っていない。
    registry_db, taxon_group_yaml = _setup_registry(tmp_path)
    out = tmp_path / "out.sqlite"
    out.write_text("前回の出力（消えてはいけない）", encoding="utf-8")
    with pytest.raises(common.MigrationError, match=r"scripts/b07_build_occurrence_cube\.py"):
        b08.build_occurrence_cube_projections(cube_db, registry_db, out, taxon_group_yaml)
    assert out.read_text(encoding="utf-8") == "前回の出力（消えてはいけない）"


def test_missing_cube_db_file_stops_with_friendly_message_before_wiping_output(tmp_path):
    """`cube_db` 自体が存在しない（b06 未実行を模す）場合も同様。"""
    registry_db, taxon_group_yaml = _setup_registry(tmp_path)
    out = tmp_path / "out.sqlite"
    out.write_text("前回の出力（消えてはいけない）", encoding="utf-8")
    with pytest.raises(common.MigrationError, match=r"scripts/b06_build_occurrence\.py"):
        b08.build_org_norm_projection(tmp_path / "no_such_v2.sqlite", registry_db, out, tmp_path / "no.yaml")
    assert out.read_text(encoding="utf-8") == "前回の出力（消えてはいけない）"


# ===========================================================================
# 全体の組み立て
# ===========================================================================

def test_build_all_projections_writes_org_norm_and_eleven_more_tables(tmp_path):
    """`build_all_projections` は `org_norm`・年キー8表・`species_month`・
    `org_watershed_year`/`org_watershed`（O-2a）を同じファイルに一緒に書く
    （`main()` が使う経路）。
    """
    rows = [occurrence_row("gbif__1", "common:taxon:gbif.1001", "2020-01-05", "2020-01-05", "2020-01-05")]
    cube_db = _build_cube_via_b07(tmp_path, rows, leaf_expected=0)
    # 座標はどの流域にも解決しない（place_id=None）——単純な最小フィクスチャ。
    _add_occurrence_place(cube_db, [occurrence_place_row("gbif__1", None)])
    registry_db, taxon_group_yaml = _setup_registry(tmp_path)
    watershed_decl = tmp_path / "occurrence_watershed_v1_declarations.yaml"
    make_occurrence_watershed_v1_declarations_yaml(
        watershed_decl, moved=0, ws_to_ws=0, v1_assigned_exact_unassigned=0,
        v1_unassigned_exact_assigned=0, mixed_buckets=0, keys_changed=0,
    )
    out = tmp_path / "out.sqlite"
    counts, diagnostics = b08.build_all_projections(
        cube_db, registry_db, out, taxon_group_yaml, watershed_decl,
    )
    _table_keys = {
        "org_norm", "org_group_year", "effort_year", "species2", "species_year2",
        "mesh_year", "mesh_all", "mesh_species", "species_mesh_year", "species_month",
        "org_watershed_year", "org_watershed", "ias_species",
    }
    # `counts` はテーブル行数だけを持つ（コードレビュー指摘2・12: 統計値
    # 〔memo_moved_records 等〕を混ぜない）——完全一致で確認する。
    assert set(counts) == _table_keys
    assert counts["org_norm"] == 1
    assert counts["org_watershed_year"] == 0  # place_id=None なのでどの流域にも入らない
    assert counts["org_watershed"] == 0
    assert counts["ias_species"] == 0  # taxon_assessment が空のフィクスチャ
    assert diagnostics["memo_moved_records"] == 0
    assert diagnostics["ias_origin_delta"]["delta_binoms"] == []

    conn = sqlite3.connect(f"file:{out}?mode=ro", uri=True)
    try:
        # `pipeline_fingerprint`（Issue #37 #1、段階間の指紋のメタ表）は
        # v1テーブルとは無関係な実装詳細なので除外する。
        tables = {
            r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            if r[0] != common.PIPELINE_FINGERPRINT_TABLE
        }
    finally:
        conn.close()
    assert tables == _table_keys
