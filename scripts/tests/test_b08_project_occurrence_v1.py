"""scripts/b08_project_occurrence_v1.py の統合テスト。

本物の `data/db/v2.sqlite`/`registry.sqlite` を要さず、
`scripts/tests/occurrence_fixtures.py` の小さな自作 sqlite だけで完結する。
"""
import sqlite3

import b08_project_occurrence_v1 as b08

from .occurrence_fixtures import make_occurrence_registry_db, make_taxon_group_yaml, make_v2_db_with_occurrence

_TAXON_RESOLVED_ROW = (
    "gbif__1", "organism_records", "1", "gbif_kanagawa_occurrences", "jp-14",
    "common:taxon:gbif.1001", "common:place:grid01.3550_13900", "grid01", 10.0, 35.505, 139.005,
    "day", "2020-01-05", "2020-01-05", "2020-01-05",
    "Foo bar", "フーバー", "SPECIES", "LC", 0, "CC-BY", "公開",
)

_TAXON_NULL_ROW = (
    "inat__1", "organism_records", "2", "inaturalist_kanagawa", "jp-14",
    None, "common:place:grid01.3550_13900", "grid01", None, 35.506, 139.006,
    "instant", "2020-02-01T12:00:00", "2020-02-01T12:00:00", "2020-02-01T03:00Z",
    "", "", "", "", 0, "", "限定共有",
)

_UNDATED_ROW = (
    "gbif__2", "organism_records", "3", "gbif_kanagawa_occurrences", "jp-14",
    "common:taxon:gbif.1001", "common:place:grid01.3550_13900", "grid01", None, 35.505, 139.005,
    None, None, None, None,
    "Foo bar", "", "SPECIES", "", 0, "", "公開",
)

# v1 の癖の再現: 'YYYY/YYYY'（年区間）の period_raw に substr(raw,6,2) を適用すると
# 「月」ではない値になる（O-1 設計 v2「実測」節。実データで '20' 等が現れる）。
_YEAR_INTERVAL_ROW = (
    "gbif__3", "organism_records", "4", "gbif_kanagawa_occurrences", "jp-14",
    "common:taxon:gbif.1001", "common:place:grid01.3550_13900", "grid01", None, 35.505, 139.005,
    "survey_period", "1976-01-01", "2004-12-31", "1976/2004",
    "Foo bar", "", "SPECIES", "", 0, "", "公開",
)


def _setup(tmp_path, rows, default_label_ja="未判定"):
    cube_db = tmp_path / "v2.sqlite"
    registry_db = tmp_path / "registry.sqlite"
    taxon_group_yaml = tmp_path / "taxon_group.yaml"
    make_v2_db_with_occurrence(cube_db, rows)
    make_occurrence_registry_db(registry_db)
    make_taxon_group_yaml(taxon_group_yaml, default_label_ja)
    return cube_db, registry_db, taxon_group_yaml


def _row_dict(columns, rows, key):
    idx = columns.index("record_id")
    by_id = {r[idx]: dict(zip(columns, r)) for r in rows}
    return by_id[key]


def test_taxon_attributes_projected_from_registry(tmp_path):
    cube_db, registry_db, taxon_group_yaml = _setup(tmp_path, [_TAXON_RESOLVED_ROW])
    columns, rows = b08.build_org_norm_projection(cube_db, registry_db, taxon_group_yaml)
    assert len(rows) == 1
    row = _row_dict(columns, rows, "gbif__1")

    assert row["source_id"] == "gbif_kanagawa_occurrences"
    assert row["binom"] == "Foo bar"  # taxon.canonical_binomial 由来
    assert row["cls"] == "Insecta"
    assert row["kdm"] == "Animalia"
    assert row["phy"] == "Arthropoda"
    assert row["ord"] == "Fooales"
    assert row["family"] == "Fooidae"
    assert row["taxon_group"] == "昆虫類"
    # 記録の原表記（taxon の属性ではない）。
    assert row["scientific_name"] == "Foo bar"
    assert row["vernacular_name"] == "フーバー"
    assert row["rank_l"] == "species"  # lower(taxon_rank)
    assert row["red_list_category"] == "LC"
    assert row["is_alien"] == 0
    # period_raw から v1 の式で yr/mo を出す。
    assert row["yr"] == 2020
    assert row["mo"] == 1
    # mlat/mlon は CAST(FLOOR(lat*100) AS INT)。
    assert row["mlat"] == 3550
    assert row["mlon"] == 13900


def test_taxon_id_null_uses_default_taxon_group_and_null_attributes(tmp_path):
    cube_db, registry_db, taxon_group_yaml = _setup(tmp_path, [_TAXON_NULL_ROW], default_label_ja="未判定")
    columns, rows = b08.build_org_norm_projection(cube_db, registry_db, taxon_group_yaml)
    row = _row_dict(columns, rows, "inat__1")

    assert row["binom"] is None
    assert row["cls"] is None
    assert row["kdm"] is None
    assert row["phy"] is None
    assert row["ord"] is None
    assert row["family"] is None
    assert row["taxon_group"] == "未判定"  # taxon_group.yaml の default_label_ja
    # 'Z' 変換後（b06 の period_raw はまだ原表記のまま）: mo は substr(period_raw,6,2)。
    assert row["yr"] == 2020
    assert row["mo"] == 2


def test_undated_rows_are_excluded(tmp_path):
    """`period_raw IS NULL`（observed_on の無い記録）は org_norm の対象外
    （v1 org_norm の母集団と同値）。"""
    cube_db, registry_db, taxon_group_yaml = _setup(tmp_path, [_TAXON_RESOLVED_ROW, _UNDATED_ROW])
    columns, rows = b08.build_org_norm_projection(cube_db, registry_db, taxon_group_yaml)
    ids = {r[columns.index("record_id")] for r in rows}
    assert ids == {"gbif__1"}


def test_year_interval_raw_reproduces_v1_mo_quirk(tmp_path):
    """v1 の癖（'YYYY/YYYY' に substr(raw,6,2) を適用すると「月」ではない値に
    なる）をそのまま再現する（O-1 設計 v2 D3。ここで直さない）。"""
    cube_db, registry_db, taxon_group_yaml = _setup(tmp_path, [_YEAR_INTERVAL_ROW])
    columns, rows = b08.build_org_norm_projection(cube_db, registry_db, taxon_group_yaml)
    row = _row_dict(columns, rows, "gbif__3")
    assert row["yr"] == 1976
    assert row["mo"] == 20  # substr('1976/2004', 6, 2) == '20'（月ではない）


def test_yr_mo_mlat_mlon_are_integer_storage_class(tmp_path):
    """設計 v2 D3: yr/mo/mlat/mlon は INTEGER で入れる（b02 が typeof で数値列を
    決めて比較するため）。"""
    cube_db, registry_db, taxon_group_yaml = _setup(tmp_path, [_TAXON_RESOLVED_ROW])
    columns, rows = b08.build_org_norm_projection(cube_db, registry_db, taxon_group_yaml)
    row = rows[0]
    for col in ("yr", "mo", "mlat", "mlon"):
        value = row[columns.index(col)]
        assert isinstance(value, int), f"{col} は int であるはず（実際: {type(value)}）"


def test_write_projection_round_trips_through_sqlite(tmp_path):
    cube_db, registry_db, taxon_group_yaml = _setup(tmp_path, [_TAXON_RESOLVED_ROW])
    columns, rows = b08.build_org_norm_projection(cube_db, registry_db, taxon_group_yaml)
    out = tmp_path / "v1_projection_occurrence.sqlite"
    b08.write_projection(columns, rows, out)

    conn = sqlite3.connect(f"file:{out}?mode=ro", uri=True)
    got_columns = [d[1] for d in conn.execute("PRAGMA table_info(org_norm)")]
    n = conn.execute("SELECT COUNT(*) FROM org_norm").fetchone()[0]
    conn.close()
    assert got_columns == list(columns)
    assert n == 1
