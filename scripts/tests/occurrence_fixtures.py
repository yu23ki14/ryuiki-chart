"""b06/b08（occurrence の縦線。`scripts/b06_build_occurrence.py`/
`scripts/b08_project_occurrence_v1.py`）用の、本物の `data/db/*.sqlite` を
要さない小さな sqlite フィクスチャ。

`organism_records`（`ryuiki.sqlite` 相当）と `taxon`/`place_source_ref`/`place`
（`registry.sqlite` 相当）のうち、b06 が実際に `SELECT` する列だけを持つ
最小限の形にしてある（`scripts/tests/migrate_fixtures.py` と同じ方針）。

## `occurrence_period_shapes.yaml` は12形すべてを宣言する必要がある

`scripts/migrate/occurrence_period.py` の `assert_declared_shapes_match_code()`
は「宣言された形の名前の集合がコードの12形と過不足なく一致すること」を
`scripts/b06_build_occurrence.py` の実行のたびに検証する（コードレビュー
指摘4）。加えて、宣言された形は実際に1回以上使われないと「未使用宣言」として
止まる（既存の `EntryUsage` の仕様）。そのため**既定の `organism_records`
フィクスチャは12形すべてを最低1行ずつ持つ**（`DEFAULT_ORGANISM_RECORDS`）。
特定の失敗系だけを見たいテストは、そのテストの目的に必要な行だけを渡せば
よい（`assert_declared_shapes_match_code`/宣言表の検証より前に別の理由で
止まるテストは12形を揃えなくてよい）。
"""
from __future__ import annotations

import sqlite3

from migrate import occurrence_period as _occurrence_period

# 既定のフィクスチャ: 12形すべてを1行ずつ（gbif 11行・inat 1行）。
# gbif__1（day, taxon_key あり）と inat__1（instant_minute_z, taxon_key 無し
# ＝ taxon_id NULL の正常系）は元からのテストが record_id で直接参照するため
# 名前を変えていない。残り10形は "gbif__<shape>" という素直な名前にした。
# 座標はすべて grid01 (3550, 13900) に解決する位置（lat=35.50..35.51,
# lon=139.00..139.01）。
DEFAULT_ORGANISM_RECORDS = [
    # record_id, source_id, observed_on, lat, lon, coordinate_uncertainty_m,
    # scientific_name, vernacular_name, taxon_rank, taxon_key,
    # red_list_category, is_alien, license_class, publication_scope
    (
        "gbif__1", "gbif_kanagawa_occurrences", "2020-01-05", 35.505, 139.005, 10.0,
        "Foo bar", "フーバー", "SPECIES", "1001",
        "LC", 0, "CC-BY", "公開",
    ),  # day
    (
        "inat__1", "inaturalist_kanagawa", "2020-02-01T03:00Z", 35.506, 139.006, None,
        "", "", "", "",
        "", 0, "", "限定共有",
    ),  # instant_minute_z, taxon_key 無し
    (
        "gbif__year", "gbif_kanagawa_occurrences", "2020", 35.505, 139.005, None,
        "Foo bar", "", "SPECIES", "1001", "", 0, "", "公開",
    ),
    (
        "gbif__month", "gbif_kanagawa_occurrences", "2020-02", 35.505, 139.005, None,
        "Foo bar", "", "SPECIES", "1001", "", 0, "", "公開",
    ),
    (
        "gbif__year_interval", "gbif_kanagawa_occurrences", "1990/1992", 35.505, 139.005, None,
        "Foo bar", "", "SPECIES", "1001", "", 0, "", "公開",
    ),
    (
        "gbif__month_interval", "gbif_kanagawa_occurrences", "2012-08/2013-06", 35.505, 139.005, None,
        "Foo bar", "", "SPECIES", "1001", "", 0, "", "公開",
    ),
    (
        "gbif__instant_minute", "gbif_kanagawa_occurrences", "2020-01-05T12:30", 35.505, 139.005, None,
        "Foo bar", "", "SPECIES", "1001", "", 0, "", "公開",
    ),
    (
        "gbif__instant_second", "gbif_kanagawa_occurrences", "2020-01-05T12:30:45", 35.505, 139.005, None,
        "Foo bar", "", "SPECIES", "1001", "", 0, "", "公開",
    ),
    (
        "gbif__instant_second_z", "gbif_kanagawa_occurrences", "2020-01-05T12:30:45Z", 35.505, 139.005, None,
        "Foo bar", "", "SPECIES", "1001", "", 0, "", "公開",
    ),
    (
        "gbif__day_interval", "gbif_kanagawa_occurrences", "2019-08-01/2019-08-31", 35.505, 139.005, None,
        "Foo bar", "", "SPECIES", "1001", "", 0, "", "公開",
    ),
    (
        "gbif__instant_millisecond_z", "gbif_kanagawa_occurrences", "2020-01-05T12:30:45.123Z",
        35.505, 139.005, None, "Foo bar", "", "SPECIES", "1001", "", 0, "", "公開",
    ),
    (
        "gbif__instant_minute_z_interval", "gbif_kanagawa_occurrences",
        "2020-01-05T12:30Z/2020-01-06T12:30Z", 35.505, 139.005, None,
        "Foo bar", "", "SPECIES", "1001", "", 0, "", "公開",
    ),
]

# 12形の名前の正は `migrate.occurrence_period._SHAPE_NAMES`（コード。モジュール
# docstring 参照）——ここでリテラルの一覧を2つ持たない（/simplify 指摘8）。
_ALL_SHAPE_NAMES = tuple(sorted(_occurrence_period._SHAPE_NAMES))

# 形の名前 -> 既定フィクスチャでの実際の件数（`DEFAULT_ORGANISM_RECORDS` と対で
# 保つ。`period_shapes_yaml_text()` の既定値、および出典ごとの件数の算出に使う）。
# `DEFAULT_ORGANISM_RECORDS` は12形すべてを1行ずつ持つので、既定は全形1件。
DEFAULT_SHAPE_COUNTS = {name: 1 for name in _ALL_SHAPE_NAMES}

DEFAULT_TAXA = [
    # taxon_id, canonical_binomial, rank, class, kingdom, phylum, "order", family, taxon_group
    (
        "common:taxon:gbif.1001", "Foo bar", "species", "Insecta", "Animalia",
        "Arthropoda", "Fooales", "Fooidae", "昆虫類",
    ),
]

DEFAULT_PLACE = [
    # place_id, region_id, place_kind
    ("common:place:grid01.3550_13900", None, "grid01"),
]

DEFAULT_PLACE_SOURCE_REF = [
    # place_id, external_key, source_id
    ("common:place:grid01.3550_13900", "grid01:3550,13900", "organism_records.lat_lon"),
]

# 既定フィクスチャの出典別件数（gbif 11行・inat 1行。`DEFAULT_ORGANISM_RECORDS`
# 参照）。
DEFAULT_SOURCE_REGIONS_YAML_TEXT = (
    "sources:\n"
    "  gbif_kanagawa_occurrences:\n"
    "    region_id: jp-14\n"
    "    expected_row_count: 11\n"
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
                taxon_id TEXT PRIMARY KEY, canonical_binomial TEXT, rank TEXT, class TEXT,
                kingdom TEXT, phylum TEXT, "order" TEXT, family TEXT, taxon_group TEXT
            )"""
        )
        conn.execute("CREATE TABLE place (place_id TEXT PRIMARY KEY, region_id TEXT, place_kind TEXT)")
        conn.execute(
            "CREATE TABLE place_source_ref (place_id TEXT, external_key TEXT, source_id TEXT)"
        )
        conn.executemany(
            "INSERT INTO taxon VALUES (?,?,?,?,?,?,?,?,?)", taxa if taxa is not None else DEFAULT_TAXA
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


def period_shapes_yaml_text(counts: dict[str, int] | None = None) -> str:
    """`occurrence_period_shapes.yaml` 相当のテキストを、コードの12形**全部**に
    ついて組み立てる（`assert_declared_shapes_match_code()` が過不足を許さない
    ため）。`counts` で個別に上書きできる（既定は `DEFAULT_SHAPE_COUNTS`）。
    """
    merged = dict(DEFAULT_SHAPE_COUNTS)
    if counts:
        merged.update(counts)
    lines = []
    for name in _ALL_SHAPE_NAMES:
        n = merged.get(name, 0)
        lines.append(f"{name}:\n  expected_row_count: {n}\n  note: テスト用\n")
    return "".join(lines)


DEFAULT_PERIOD_SHAPES_YAML_TEXT = period_shapes_yaml_text()


def make_period_shapes_yaml(path, text: str | None = None, counts: dict[str, int] | None = None) -> None:
    if text is not None:
        path.write_text(text, encoding="utf-8")
    else:
        path.write_text(period_shapes_yaml_text(counts), encoding="utf-8")


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
