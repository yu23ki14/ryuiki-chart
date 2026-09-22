"""b06/b08（occurrence の縦線。`scripts/b06_build_occurrence.py`/
`scripts/b08_project_occurrence_v1.py`）用の、本物の `data/db/*.sqlite` を
要さない小さな sqlite フィクスチャ。

`organism_records`（`ryuiki.sqlite` 相当）と `taxon`/`place_source_ref`/`place`
（`registry.sqlite` 相当）のうち、b06 が実際に `SELECT` する列だけを持つ
最小限の形にしてある（`scripts/tests/migrate_fixtures.py` と同じ方針）。
"""
from __future__ import annotations

import sqlite3

# 既定の2出典×2行。source_id は本物の値
# （`scripts/taxon_namespaces.py` の `TAXON_KEY_SOURCE_NAMESPACE` が実際に
# 知っている2値。b06 はこの対応表を注入できない作りなので、フィクスチャも
# 本物の source_id を使う——`scripts/tests/test_registry_taxon.py` と同じ方針）。
# gbif 側は taxon_key 解決あり、inat 側は taxon_key 無し（taxon_id=NULL に
# なる正常系）。座標は両方とも grid01 (3550, 13900) に解決する位置
# （lat=35.50..35.51, lon=139.00..139.01）。
DEFAULT_ORGANISM_RECORDS = [
    # record_id, source_id, observed_on, lat, lon, coordinate_uncertainty_m,
    # scientific_name, vernacular_name, taxon_rank, taxon_key,
    # red_list_category, is_alien, license_class, publication_scope
    (
        "gbif__1", "gbif_kanagawa_occurrences", "2020-01-05", 35.505, 139.005, 10.0,
        "Foo bar", "フーバー", "SPECIES", "1001",
        "LC", 0, "CC-BY", "公開",
    ),
    (
        "inat__1", "inaturalist_kanagawa", "2020-02-01T03:00Z", 35.506, 139.006, None,
        "", "", "", "",
        "", 0, "", "限定共有",
    ),
]

DEFAULT_TAXA = [
    # taxon_id, canonical_binomial, class, kingdom, phylum, "order", family, taxon_group
    ("common:taxon:gbif.1001", "Foo bar", "Insecta", "Animalia", "Arthropoda", "Fooales", "Fooidae", "昆虫類"),
]

DEFAULT_PLACE = [
    # place_id, region_id, place_kind
    ("common:place:grid01.3550_13900", None, "grid01"),
]

DEFAULT_PLACE_SOURCE_REF = [
    # place_id, external_key, source_id
    ("common:place:grid01.3550_13900", "grid01:3550,13900", "organism_records.lat_lon"),
]

DEFAULT_SOURCE_REGIONS_YAML_TEXT = (
    "sources:\n"
    "  gbif_kanagawa_occurrences:\n"
    "    region_id: jp-14\n"
    "    expected_row_count: 1\n"
    "    evidence: テスト用\n"
    "  inaturalist_kanagawa:\n"
    "    region_id: jp-14\n"
    "    expected_row_count: 1\n"
    "    evidence: テスト用\n"
    "regions:\n"
    "  jp-14:\n"
    "    utc_offset: \"+09:00\"\n"
    "    evidence: テスト用\n"
)


def make_organism_records_db(path, rows=None) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(
            """CREATE TABLE organism_records (
                record_id TEXT PRIMARY KEY, source_id TEXT, observed_on TEXT,
                lat REAL, lon REAL, coordinate_uncertainty_m REAL,
                scientific_name TEXT, vernacular_name TEXT, taxon_rank TEXT, taxon_key TEXT,
                red_list_category TEXT, is_alien INTEGER, license_class TEXT, publication_scope TEXT
            )"""
        )
        conn.executemany(
            "INSERT INTO organism_records VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows if rows is not None else DEFAULT_ORGANISM_RECORDS,
        )
        conn.commit()
    finally:
        conn.close()


def make_occurrence_registry_db(path, taxa=None, places=None, place_refs=None) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(
            """CREATE TABLE taxon (
                taxon_id TEXT PRIMARY KEY, canonical_binomial TEXT, class TEXT, kingdom TEXT,
                phylum TEXT, "order" TEXT, family TEXT, taxon_group TEXT
            )"""
        )
        conn.execute("CREATE TABLE place (place_id TEXT PRIMARY KEY, region_id TEXT, place_kind TEXT)")
        conn.execute(
            "CREATE TABLE place_source_ref (place_id TEXT, external_key TEXT, source_id TEXT)"
        )
        conn.executemany(
            "INSERT INTO taxon VALUES (?,?,?,?,?,?,?,?)", taxa if taxa is not None else DEFAULT_TAXA
        )
        conn.executemany(
            "INSERT INTO place VALUES (?,?,?)", places if places is not None else DEFAULT_PLACE
        )
        conn.executemany(
            "INSERT INTO place_source_ref VALUES (?,?,?)",
            place_refs if place_refs is not None else DEFAULT_PLACE_SOURCE_REF,
        )
        conn.commit()
    finally:
        conn.close()


def make_source_regions_yaml(path, text: str | None = None) -> None:
    path.write_text(text if text is not None else DEFAULT_SOURCE_REGIONS_YAML_TEXT, encoding="utf-8")


# `occurrence_period_shapes.yaml` 相当。既定フィクスチャが使う形
# （day/instant_minute_z）だけを宣言する。
DEFAULT_PERIOD_SHAPES_YAML_TEXT = (
    "day:\n"
    "  length: 10\n"
    "  period_grain: day\n"
    "  expected_row_count: 1\n"
    "  note: テスト用\n"
    "instant_minute_z:\n"
    "  length: 17\n"
    "  period_grain: instant\n"
    "  expected_row_count: 1\n"
    "  note: テスト用\n"
)


def make_period_shapes_yaml(path, text: str | None = None) -> None:
    path.write_text(text if text is not None else DEFAULT_PERIOD_SHAPES_YAML_TEXT, encoding="utf-8")


# b08（射影）のテスト用: occurrence テーブルだけを持つ v2.sqlite 相当。スキーマの
# 正は `scripts/b06_build_occurrence.py` の `_CREATE_OCCURRENCE_SQL` 1箇所
# （`scripts/tests/migrate_fixtures.py` の `make_v2_db_with_observation` と
# 同じ考え方——本物のスキーマとテストのスキーマがずれる事故を避ける）。
_OCCURRENCE_COLUMNS = (
    "record_id", "source_table", "source_row_id", "source_id", "region_id", "taxon_id",
    "place_id", "place_kind", "coordinate_uncertainty_m", "lat", "lon",
    "period_grain", "period_start", "period_end", "period_raw",
    "scientific_name", "vernacular_name", "taxon_rank",
    "red_list_category", "is_alien", "license_class", "publication_scope",
)


def make_v2_db_with_occurrence(path, rows: list[tuple]) -> None:
    import b06_build_occurrence as b06

    conn = sqlite3.connect(f"file:{path}", uri=True)
    try:
        conn.execute(b06._CREATE_OCCURRENCE_SQL.format(table="occurrence"))
        placeholders = ", ".join("?" for _ in _OCCURRENCE_COLUMNS)
        conn.executemany(f"INSERT INTO occurrence VALUES ({placeholders})", rows)
        conn.commit()
    finally:
        conn.close()


def make_taxon_group_yaml(path, default_label_ja: str = "未判定") -> None:
    path.write_text(f'default_label_ja: "{default_label_ja}"\nrules: []\n', encoding="utf-8")
