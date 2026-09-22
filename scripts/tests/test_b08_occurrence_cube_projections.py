"""scripts/b08_project_occurrence_v1.py の O-1b 部分（年キー8表・
`species_month`）の統合テスト。本物の `data/db/v2.sqlite`/`registry.sqlite` を
要さず、`scripts/tests/occurrence_fixtures.py` の小さな自作 sqlite だけで
完結する。`org_norm`（O-1a）は `test_b08_project_occurrence_v1.py` に残す。
"""
import sqlite3

import pytest

import b08_project_occurrence_v1 as b08
from migrate import common

from .occurrence_fixtures import (
    make_occurrence_registry_db,
    make_taxon_group_yaml,
    make_v2_db_with_occurrence_and_agg,
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

_PLACE = [("common:place:grid01.3550_13900", None, "grid01")]
_PLACE_SOURCE_REF = [("common:place:grid01.3550_13900", "grid01:3550,13900", "organism_records.lat_lon")]

_PLACE_ID = "common:place:grid01.3550_13900"


def _agg_row(
    taxon_id, grain, period_start, period_end, n, n_red_list=0,
    source_id="gbif_kanagawa_occurrences", place_id=_PLACE_ID, region_id="jp-14",
):
    return (
        region_id, source_id, place_id, taxon_id, grain, period_start, period_end,
        n, n_red_list, "occurrence", "phase-b-fact-slice/v1",
    )


def _occ_row(record_id, taxon_id, period_raw, source_id="gbif_kanagawa_occurrences", record_id_suffix=1):
    """`species2` の L2 由来列（en_name/red_list_category）・`species_month`
    向けの `occurrence` 行。period_start/period_end はこのテストでは
    使わない列（NULL でよい）——`_build_cube_projections` が `occurrence` に
    要求するのは `taxon_id`/`period_raw`/`vernacular_name`/`red_list_category`
    だけ。
    """
    return (
        record_id, "organism_records", record_id_suffix, source_id, "jp-14", taxon_id,
        _PLACE_ID, "grid01", None, 35.505, 139.005,
        "day", None, None, period_raw,
        "Foo bar", "フーバー", "SPECIES", "LC", 0, "CC-BY", "公開",
    )


def _setup(tmp_path, occurrence_rows, occurrence_agg_rows, taxa=None, default_label_ja="未判定"):
    cube_db = tmp_path / "v2.sqlite"
    registry_db = tmp_path / "registry.sqlite"
    taxon_group_yaml = tmp_path / "taxon_group.yaml"
    make_v2_db_with_occurrence_and_agg(cube_db, occurrence_rows, occurrence_agg_rows)
    make_occurrence_registry_db(
        registry_db, taxa=taxa if taxa is not None else _TAXA, places=_PLACE, place_refs=_PLACE_SOURCE_REF,
    )
    make_taxon_group_yaml(taxon_group_yaml, default_label_ja)
    return cube_db, registry_db, taxon_group_yaml


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


def test_leaf_cell_is_attributed_to_its_start_year(tmp_path):
    """年キーの表は leaf セル（grain='survey_period'。年をまたぐ区間）を、
    セルの period_start の年（＝記録の開始年）に入れる（ADR-0025 D3）。
    """
    occurrence_agg_rows = [
        _agg_row("common:taxon:gbif.1001", "survey_period", "1990-01-01", "1992-12-31", n=5, n_red_list=1),
    ]
    occurrence_rows = [_occ_row("gbif__leaf", "common:taxon:gbif.1001", "1990/1992")]
    cube_db, registry_db, taxon_group_yaml = _setup(tmp_path, occurrence_rows, occurrence_agg_rows)
    out = tmp_path / "out.sqlite"
    counts = b08.build_occurrence_cube_projections(cube_db, registry_db, out, taxon_group_yaml)
    assert counts["mesh_year"] == 1
    assert counts["org_group_year"] == 1
    assert counts["effort_year"] == 1

    mesh_year = _read(out, "mesh_year", ["mlat", "mlon", "year", "n", "species_n", "rl_n"])[0]
    assert mesh_year == {"mlat": 3550, "mlon": 13900, "year": 1990, "n": 5, "species_n": 1, "rl_n": 1}

    org_group_year = _read(out, "org_group_year", ["year", "taxon_group", "source_id", "n"])[0]
    assert org_group_year["year"] == 1990
    assert org_group_year["n"] == 5

    effort_year = _read(out, "effort_year", ["year", "n", "n_gbif"])[0]
    assert effort_year == {"year": 1990, "n": 5, "n_gbif": 5}


def test_year_cell_uses_its_own_calendar_year(tmp_path):
    """grain='year' セルは（暦年境界へ丸められた）自身の period_start の年に
    入る。
    """
    occurrence_agg_rows = [
        _agg_row("common:taxon:gbif.1001", "year", "2020-01-01", "2020-12-31", n=3),
    ]
    occurrence_rows = [_occ_row("gbif__year", "common:taxon:gbif.1001", "2020")]
    cube_db, registry_db, taxon_group_yaml = _setup(tmp_path, occurrence_rows, occurrence_agg_rows)
    out = tmp_path / "out.sqlite"
    b08.build_occurrence_cube_projections(cube_db, registry_db, out, taxon_group_yaml)
    row = _read(out, "mesh_year", ["mlat", "mlon", "year", "n"])[0]
    assert row == {"mlat": 3550, "mlon": 13900, "year": 2020, "n": 3}


def test_species_mesh_year_and_mesh_species_collapse_multiple_taxon_ids_to_one_binom(tmp_path):
    """複数の `taxon_id`（GBIF由来・iNat由来）が同じ `binom` に対応する場合、
    `species_mesh_year` は `SUM(n)` で1行に畳まれ、`mesh_species` の
    `COUNT(DISTINCT binom)`/`rl_species_n` も taxon_id ではなく binom で
    正しく1つに数えられる。
    """
    occurrence_agg_rows = [
        _agg_row("common:taxon:gbif.1001", "year", "2020-01-01", "2020-12-31", n=40, n_red_list=0,
                 source_id="gbif_kanagawa_occurrences"),
        _agg_row("common:taxon:inat.2002", "year", "2020-01-01", "2020-12-31", n=40, n_red_list=0,
                 source_id="inaturalist_kanagawa"),
        # 全期間で n>=80 になるように、別の年にもう1セル足す（species2.n は
        # 全年・全記録なので、このセル分も合算される）。
        _agg_row("common:taxon:gbif.1001", "survey_period", "1990-01-01", "1992-12-31", n=5, n_red_list=1,
                 source_id="gbif_kanagawa_occurrences"),
    ]
    occurrence_rows = [
        _occ_row("gbif__1", "common:taxon:gbif.1001", "2020-01-05", record_id_suffix=1),
        _occ_row("inat__1", "common:taxon:inat.2002", "2020-06-01", source_id="inaturalist_kanagawa",
                  record_id_suffix=2),
    ]
    cube_db, registry_db, taxon_group_yaml = _setup(tmp_path, occurrence_rows, occurrence_agg_rows)
    out = tmp_path / "out.sqlite"
    counts = b08.build_occurrence_cube_projections(cube_db, registry_db, out, taxon_group_yaml)

    species2 = _read(out, "species2", ["binom", "n"])
    assert species2 == [{"binom": "Foo bar", "n": 85}]  # 40+40+5, n>=80 を満たす

    assert counts["species_mesh_year"] == 2  # (2020年) と (1990年) の2行に畳まれる
    smy = _read(out, "species_mesh_year", ["binom", "year", "mlat", "mlon", "n"], order_by="year")
    assert smy == [
        {"binom": "Foo bar", "year": 1990, "mlat": 3550, "mlon": 13900, "n": 5},
        {"binom": "Foo bar", "year": 2020, "mlat": 3550, "mlon": 13900, "n": 80},  # 2つの taxon_id が1行に集約
    ]

    mesh_species = _read(out, "mesh_species", ["mlat", "mlon", "species_n", "rl_species_n"])[0]
    # binom で畳まれるので species_n=1（taxon_id の数=2 ではない）。
    # rl_species_n も、1990年セルの n_red_list=1 が同じ binom に属するため1。
    assert mesh_species == {"mlat": 3550, "mlon": 13900, "species_n": 1, "rl_species_n": 1}


def test_species_month_reproduces_v1_year_interval_mo_quirk(tmp_path):
    """`species_month` は `occurrence`（L2）から直接、`org_norm` と同じ式
    （`yr=substr(period_raw,1,4)`・`mo=substr(period_raw,6,2)`）を適用する。
    'YYYY/YYYY' 区間では `mo` が「月」ではない値（例: 18）になる v1 の癖を
    そのまま再現する（`yr>=2018` の対象に入るよう、開始年は2018にしてある）。
    """
    occurrence_agg_rows = [
        _agg_row("common:taxon:gbif.1001", "year", "2020-01-01", "2020-12-31", n=100),  # species2.n>=80
    ]
    occurrence_rows = [
        _occ_row("gbif__year_cell", "common:taxon:gbif.1001", "2020-01-05", record_id_suffix=1),
        # yr=2018（substr(1,4)）、mo=CAST(substr(raw,6,2))=CAST('18')=18（月ではない）。
        _occ_row("gbif__interval", "common:taxon:gbif.1001", "2018/1834", record_id_suffix=2),
    ]
    cube_db, registry_db, taxon_group_yaml = _setup(tmp_path, occurrence_rows, occurrence_agg_rows)
    out = tmp_path / "out.sqlite"
    b08.build_occurrence_cube_projections(cube_db, registry_db, out, taxon_group_yaml)

    rows = _read(out, "species_month", ["binom", "month", "n"], order_by="month")
    months = {r["month"] for r in rows}
    assert 18 in months
    row18 = next(r for r in rows if r["month"] == 18)
    assert row18 == {"binom": "Foo bar", "month": 18, "n": 1}


def test_species_month_excludes_years_before_2018(tmp_path):
    occurrence_agg_rows = [
        _agg_row("common:taxon:gbif.1001", "year", "2020-01-01", "2020-12-31", n=100),
    ]
    occurrence_rows = [
        _occ_row("gbif__year_cell", "common:taxon:gbif.1001", "2020-01-05", record_id_suffix=1),
        _occ_row("gbif__old", "common:taxon:gbif.1001", "2010-05-01", record_id_suffix=2),  # yr<2018 で除外
    ]
    cube_db, registry_db, taxon_group_yaml = _setup(tmp_path, occurrence_rows, occurrence_agg_rows)
    out = tmp_path / "out.sqlite"
    b08.build_occurrence_cube_projections(cube_db, registry_db, out, taxon_group_yaml)
    rows = _read(out, "species_month", ["binom", "month", "n"])
    assert sum(r["n"] for r in rows) == 1  # 2020-01-05 の1件だけ（2010-05-01 は除外）


def test_species_month_excludes_species_below_n80(tmp_path):
    """`species2.n < 80` の binom は `species_month`/`species_mesh_year` の
    対象外（v1 のとおり。全年・全記録で判定）。
    """
    occurrence_agg_rows = [
        _agg_row("common:taxon:gbif.1001", "year", "2020-01-01", "2020-12-31", n=10),  # n<80
    ]
    occurrence_rows = [_occ_row("gbif__minor", "common:taxon:gbif.1001", "2020-01-05")]
    cube_db, registry_db, taxon_group_yaml = _setup(tmp_path, occurrence_rows, occurrence_agg_rows)
    out = tmp_path / "out.sqlite"
    counts = b08.build_occurrence_cube_projections(cube_db, registry_db, out, taxon_group_yaml)
    assert counts["species_month"] == 0
    assert counts["species_mesh_year"] == 0


def test_stale_taxon_id_in_occurrence_agg_raises(tmp_path):
    """`occurrence_agg.taxon_id` は NULL ではないのに `registry.taxon` に無い
    （古い registry）場合、`build_occurrence_cube_projections` を止める
    （`org_norm` 側の同じ検証をキューブ側にも一般化したもの。コードレビュー
    指摘7の一般化）。
    """
    occurrence_agg_rows = [
        _agg_row("common:taxon:gbif.9999", "year", "2020-01-01", "2020-12-31", n=1),  # registry に無い
    ]
    occurrence_rows = [_occ_row("gbif__ghost", "common:taxon:gbif.9999", "2020-01-05")]
    cube_db, registry_db, taxon_group_yaml = _setup(tmp_path, occurrence_rows, occurrence_agg_rows)
    out = tmp_path / "out.sqlite"
    with pytest.raises(common.MigrationError, match="registry.taxon に無い taxon_id が1種"):
        b08.build_occurrence_cube_projections(cube_db, registry_db, out, taxon_group_yaml)


def test_build_all_projections_writes_org_norm_and_nine_more_tables(tmp_path):
    """`build_all_projections` は `org_norm` と年キー8表・`species_month` を
    同じファイルに一緒に書く（`main()` が使う経路）。
    """
    occurrence_agg_rows = [
        _agg_row("common:taxon:gbif.1001", "year", "2020-01-01", "2020-12-31", n=1),
    ]
    occurrence_rows = [_occ_row("gbif__1", "common:taxon:gbif.1001", "2020-01-05")]
    cube_db, registry_db, taxon_group_yaml = _setup(tmp_path, occurrence_rows, occurrence_agg_rows)
    out = tmp_path / "out.sqlite"
    counts = b08.build_all_projections(cube_db, registry_db, out, taxon_group_yaml)
    assert set(counts) == {
        "org_norm", "org_group_year", "effort_year", "species2", "species_year2",
        "mesh_year", "mesh_all", "mesh_species", "species_mesh_year", "species_month",
    }
    assert counts["org_norm"] == 1

    conn = sqlite3.connect(f"file:{out}?mode=ro", uri=True)
    try:
        tables = {
            r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    finally:
        conn.close()
    assert tables == set(counts)
