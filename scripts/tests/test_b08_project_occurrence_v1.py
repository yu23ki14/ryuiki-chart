"""scripts/b08_project_occurrence_v1.py の統合テスト。

本物の `data/db/v2.sqlite`/`registry.sqlite` を要さず、
`scripts/tests/occurrence_fixtures.py` の小さな自作 sqlite だけで完結する。
"""
import sqlite3

import pytest

import b08_project_occurrence_v1 as b08
from migrate import common

from .occurrence_fixtures import make_occurrence_registry_db, make_taxon_group_yaml, make_v2_db_with_occurrence

_TAXON_RESOLVED_ROW = (
    "gbif__1", "organism_records", 1, "gbif_kanagawa_occurrences", "jp-14",
    "common:taxon:gbif.1001", "common:place:grid01.3550_13900", "grid01", 10.0, 35.505, 139.005,
    "day", "2020-01-05", "2020-01-05", "2020-01-05",
    "Foo bar", "フーバー", "SPECIES", "LC", 0, "CC-BY", "公開",
)

_TAXON_NULL_ROW = (
    "inat__1", "organism_records", 2, "inaturalist_kanagawa", "jp-14",
    None, "common:place:grid01.3550_13900", "grid01", None, 35.506, 139.006,
    "instant", "2020-02-01T12:00:00", "2020-02-01T12:00:00", "2020-02-01T03:00Z",
    "", "", "", "", 0, "", "限定共有",
)

_UNDATED_ROW = (
    "gbif__2", "organism_records", 3, "gbif_kanagawa_occurrences", "jp-14",
    "common:taxon:gbif.1001", "common:place:grid01.3550_13900", "grid01", None, 35.505, 139.005,
    None, None, None, None,
    "Foo bar", "", "SPECIES", "", 0, "", "公開",
)

# v1 の癖の再現: 'YYYY/YYYY'（年区間）の period_raw に substr(raw,6,2) を適用すると
# 「月」ではない値になる（O-1 設計 v2「実測」節。実データで '20' 等が現れる）。
_YEAR_INTERVAL_ROW = (
    "gbif__3", "organism_records", 4, "gbif_kanagawa_occurrences", "jp-14",
    "common:taxon:gbif.1001", "common:place:grid01.3550_13900", "grid01", None, 35.505, 139.005,
    "survey_period", "1976-01-01", "2004-12-31", "1976/2004",
    "Foo bar", "", "SPECIES", "", 0, "", "公開",
)

# taxon_id はあるが registry.taxon に無い（古い registry。コードレビュー指摘7）。
_STALE_TAXON_ROW = (
    "gbif__stale", "organism_records", 5, "gbif_kanagawa_occurrences", "jp-14",
    "common:taxon:gbif.9999", "common:place:grid01.3550_13900", "grid01", None, 35.505, 139.005,
    "day", "2020-03-01", "2020-03-01", "2020-03-01",
    "Ghost sp.", "", "SPECIES", "", 0, "", "公開",
)


def _setup(tmp_path, rows, default_label_ja="未判定"):
    cube_db = tmp_path / "v2.sqlite"
    registry_db = tmp_path / "registry.sqlite"
    taxon_group_yaml = tmp_path / "taxon_group.yaml"
    make_v2_db_with_occurrence(cube_db, rows)
    make_occurrence_registry_db(registry_db)
    make_taxon_group_yaml(taxon_group_yaml, default_label_ja)
    return cube_db, registry_db, taxon_group_yaml


def _read_org_norm(out_path, columns):
    conn = sqlite3.connect(f"file:{out_path}?mode=ro", uri=True)
    try:
        collist = ", ".join(columns)
        rows = conn.execute(f"SELECT {collist} FROM org_norm ORDER BY record_id").fetchall()
        return [dict(zip(columns, row)) for row in rows]
    finally:
        conn.close()


def test_projection_writes_expected_values_for_taxon_resolved_row(tmp_path):
    """列名だけでなく実際に書き出された**値**を照合する（列を入れ替えたら
    落ちる形。コードレビュー指摘8・10）。"""
    cube_db, registry_db, taxon_group_yaml = _setup(tmp_path, [_TAXON_RESOLVED_ROW])
    out = tmp_path / "v1_projection_occurrence.sqlite"
    result = b08.build_org_norm_projection(cube_db, registry_db, out, taxon_group_yaml)
    assert result == {"n": 1}

    rows = _read_org_norm(out, b08._ORG_NORM_COLUMNS)
    assert len(rows) == 1
    row = rows[0]

    assert row == {
        "record_id": "gbif__1",
        "source_id": "gbif_kanagawa_occurrences",
        "yr": 2020,
        "mo": 1,
        "binom": "Foo bar",  # taxon.canonical_binomial 由来
        "scientific_name": "Foo bar",
        "vernacular_name": "フーバー",
        "rank_l": "species",  # taxon.rank 由来（コードレビュー指摘15）
        "cls": "Insecta",
        "kdm": "Animalia",
        "phy": "Arthropoda",
        "ord": "Fooales",
        "family": "Fooidae",
        "lat": 35.505,
        "lon": 139.005,
        "mlat": 3550,
        "mlon": 13900,
        "red_list_category": "LC",
        "license_class": "CC-BY",
        "is_alien": 0,
        "taxon_group": "昆虫類",
    }


def test_taxon_id_null_uses_default_taxon_group_and_null_attributes(tmp_path):
    cube_db, registry_db, taxon_group_yaml = _setup(tmp_path, [_TAXON_NULL_ROW], default_label_ja="未判定")
    out = tmp_path / "v1_projection_occurrence.sqlite"
    b08.build_org_norm_projection(cube_db, registry_db, out, taxon_group_yaml)
    row = _read_org_norm(out, b08._ORG_NORM_COLUMNS)[0]

    assert row["binom"] is None
    assert row["cls"] is None
    assert row["kdm"] is None
    assert row["phy"] is None
    assert row["ord"] is None
    assert row["family"] is None
    assert row["rank_l"] is None
    assert row["taxon_group"] == "未判定"  # taxon_group.yaml の default_label_ja
    # 'Z' 変換後（b06 の period_raw はまだ原表記のまま）: mo は substr(period_raw,6,2)。
    assert row["yr"] == 2020
    assert row["mo"] == 2


def test_undated_rows_are_excluded(tmp_path):
    """`period_raw IS NULL`（observed_on の無い記録）は org_norm の対象外
    （v1 org_norm の母集団と同値）。"""
    cube_db, registry_db, taxon_group_yaml = _setup(tmp_path, [_TAXON_RESOLVED_ROW, _UNDATED_ROW])
    out = tmp_path / "v1_projection_occurrence.sqlite"
    result = b08.build_org_norm_projection(cube_db, registry_db, out, taxon_group_yaml)
    assert result == {"n": 1}
    ids = {r["record_id"] for r in _read_org_norm(out, ["record_id"])}
    assert ids == {"gbif__1"}


def test_year_interval_raw_reproduces_v1_mo_quirk(tmp_path):
    """v1 の癖（'YYYY/YYYY' に substr(raw,6,2) を適用すると「月」ではない値に
    なる）をそのまま再現する（O-1 設計 v2 D3。ここで直さない）。"""
    cube_db, registry_db, taxon_group_yaml = _setup(tmp_path, [_YEAR_INTERVAL_ROW])
    out = tmp_path / "v1_projection_occurrence.sqlite"
    b08.build_org_norm_projection(cube_db, registry_db, out, taxon_group_yaml)
    row = _read_org_norm(out, ["record_id", "yr", "mo"])[0]
    assert row["yr"] == 1976
    assert row["mo"] == 20  # substr('1976/2004', 6, 2) == '20'（月ではない）


def test_yr_mo_mlat_mlon_are_integer_storage_class(tmp_path):
    """設計 v2 D3: yr/mo/mlat/mlon は INTEGER で入れる（b02 が typeof で数値列を
    決めて比較するため）。"""
    cube_db, registry_db, taxon_group_yaml = _setup(tmp_path, [_TAXON_RESOLVED_ROW])
    out = tmp_path / "v1_projection_occurrence.sqlite"
    b08.build_org_norm_projection(cube_db, registry_db, out, taxon_group_yaml)

    conn = sqlite3.connect(f"file:{out}?mode=ro", uri=True)
    try:
        row = conn.execute(
            "SELECT typeof(yr), typeof(mo), typeof(mlat), typeof(mlon) FROM org_norm"
        ).fetchone()
    finally:
        conn.close()
    assert row == ("integer", "integer", "integer", "integer")


def test_stale_taxon_id_raises(tmp_path):
    """`occurrence.taxon_id` は NULL ではないのに `registry.taxon` に無い行が
    あれば止める（古い registry を検出する。コードレビュー指摘7）。"""
    cube_db, registry_db, taxon_group_yaml = _setup(tmp_path, [_TAXON_RESOLVED_ROW, _STALE_TAXON_ROW])
    out = tmp_path / "v1_projection_occurrence.sqlite"
    with pytest.raises(common.MigrationError, match="registry.taxon"):
        b08.build_org_norm_projection(cube_db, registry_db, out, taxon_group_yaml)


def test_column_order_mismatch_between_create_and_select_is_caught_by_construction():
    """`_ORG_NORM_COLUMNS` と `_ORG_NORM_SELECT_EXPRS` の対応がずれていないかを
    構造的に確認する（列名リストと SELECT 式リストを1箇所ずつに保ち、2つの
    長さが一致することをモジュール読み込み時に assert している。コードレビュー
    指摘8・10の「列がずれたら落ちる」を、値の一致確認に加えて構造面でも
    担保する）。"""
    assert len(b08._ORG_NORM_COLUMNS) == len(b08._ORG_NORM_SELECT_EXPRS) == 21


def test_write_creates_fresh_file_each_time(tmp_path):
    """`common.fresh_sqlite` で毎回作り直す（前回実行の残骸を引きずらない）。"""
    cube_db, registry_db, taxon_group_yaml = _setup(tmp_path, [_TAXON_RESOLVED_ROW])
    out = tmp_path / "v1_projection_occurrence.sqlite"
    b08.build_org_norm_projection(cube_db, registry_db, out, taxon_group_yaml)

    # 2回目: 別の1行だけを持つ occurrence で作り直す。
    second_dir = tmp_path / "second"
    second_dir.mkdir()
    cube_db2, registry_db2, taxon_group_yaml2 = _setup(second_dir, [_TAXON_NULL_ROW])
    result = b08.build_org_norm_projection(cube_db2, registry_db2, out, taxon_group_yaml2)
    assert result == {"n": 1}
    ids = {r["record_id"] for r in _read_org_norm(out, ["record_id"])}
    assert ids == {"inat__1"}  # 前回の gbif__1 が残っていない
