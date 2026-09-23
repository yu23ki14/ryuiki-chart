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

# O-1b（b07・b08）のテスト用フィクスチャが共有する grid01 の place_id
# （/simplify 指摘7: 複数のテストファイルに同じ文字列リテラルが散っていた）。
DEFAULT_GRID01_PLACE_ID = "common:place:grid01.3550_13900"

DEFAULT_PLACE = [
    # place_id, region_id, place_kind
    (DEFAULT_GRID01_PLACE_ID, None, "grid01"),
]

DEFAULT_PLACE_SOURCE_REF = [
    # place_id, external_key, source_id
    (DEFAULT_GRID01_PLACE_ID, "grid01:3550,13900", "organism_records.lat_lon"),
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


# scripts/b07_build_occurrence_cube.py（occurrence_cube_declarations.yaml。leaf
# セルの元記録数の宣言）用。`make_period_shapes_yaml`/`make_source_regions_yaml`
# と同じ形（/simplify 指摘4: test_b07_build_occurrence_cube.py・
# test_b08_occurrence_cube_projections.py がそれぞれ同じテキストを組み立てて
# いたものを1箇所に集約）。
def occurrence_cube_declarations_yaml_text(expected_row_count: int = 1191) -> str:
    return f"leaf_cell_source_rows:\n  expected_row_count: {expected_row_count}\n  note: テスト用\n"


def make_occurrence_cube_declarations_yaml(
    path, text: str | None = None, expected_row_count: int = 1191,
) -> None:
    path.write_text(
        text if text is not None else occurrence_cube_declarations_yaml_text(expected_row_count),
        encoding="utf-8",
    )


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


def occurrence_row(
    record_id, taxon_id, period_start, period_end, period_raw, *,
    source_id="gbif_kanagawa_occurrences", region_id="jp-14",
    place_id=DEFAULT_GRID01_PLACE_ID, place_kind="grid01",
    source_row_id=1, red_list_category="",
    lat=35.505, lon=139.005, scientific_name="Foo bar", is_alien=0,
) -> tuple:
    """`_OCCURRENCE_COLUMNS`（≡ `scripts/b06_build_occurrence.py` の
    `_CREATE_OCCURRENCE_SQL`）の並びで `occurrence` の1行を組み立てる
    （/simplify 指摘7: `test_b07_build_occurrence_cube.py` の `_row`・
    `test_b08_occurrence_cube_projections.py` の `_dated_row`/`_occ_row` の
    3通りに分かれていたものを1つに集約した。`lat`/`lon`/`scientific_name`/
    `is_alien` は既定値が従来の固定値のままの追加キーワード引数——O-2a の
    `occurrence_place`/`org_watershed_year` のテストが座標を変えた複数の記録を
    要るために足した。以前は `occurrence_row_at()` という別名の関数がほぼ
    同じ22列タプルを複製していた。/simplify 指摘6）。

    `period_start`/`period_end` は b06 が展開済みの形で渡す（'YYYY/YYYY' 区間
    なら実際の年境界。b07 のテストで使う）。`period_start=None,
    period_end=None` を渡せば b08 のテスト（`species2`/`species_month` の
    L2 由来列だけを使い、`occurrence_agg` は別途手で作る）向けの薄い行になる。
    """
    return (
        record_id, "organism_records", source_row_id, source_id, region_id, taxon_id,
        place_id, place_kind, None, lat, lon,
        "day", period_start, period_end, period_raw,
        scientific_name, "フーバー", "SPECIES", red_list_category, is_alien, "CC-BY", "公開",
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


# occurrence_place（O-2a、scripts/b09_build_occurrence_place.py）のスキーマは
# `_CREATE_OCCURRENCE_PLACE_SQL` 1箇所が正（同じ考え方）。
_OCCURRENCE_PLACE_COLUMNS = ("record_id", "place_kind", "place_id", "method", "built_from", "spec_version")


def occurrence_place_row(record_id, place_id, *, place_kind="watershed") -> tuple:
    return (record_id, place_kind, place_id, "point_in_polygon:even_odd", "テスト用", "テスト用/v1")


def add_occurrence_place_table(conn: sqlite3.Connection, rows: list[tuple]) -> None:
    """開いている接続 `conn`（`occurrence` を持つ v2.sqlite）に
    `occurrence_place`（O-2a）テーブルを作って `rows` を入れる（コミットは
    呼び出し側の責務）。`make_v2_db_with_occurrence_and_place()`
    （ここから接続を開いて呼ぶ）と `test_b08_occurrence_cube_projections.py`
    の `_add_occurrence_place()`（既存の db に後付けで足す）が共有する
    （/simplify 指摘7）。
    """
    import b09_build_occurrence_place as b09

    conn.execute(b09._CREATE_OCCURRENCE_PLACE_SQL.format(table="occurrence_place"))
    placeholders = ", ".join("?" for _ in _OCCURRENCE_PLACE_COLUMNS)
    conn.executemany(f"INSERT INTO occurrence_place VALUES ({placeholders})", rows)


def make_v2_db_with_occurrence_and_place(
    path, occurrence_rows: list[tuple], occurrence_place_rows: list[tuple],
) -> None:
    """`occurrence`（L2）と `occurrence_place`（O-2a サテライト）の両方を持つ
    v2.sqlite 相当を作る（`scripts/b08_project_occurrence_v1.py` の
    `_build_watershed` は両方を読む）。
    """
    import b06_build_occurrence as b06

    conn = sqlite3.connect(f"file:{path}", uri=True)
    try:
        conn.execute(b06._CREATE_OCCURRENCE_SQL.format(table="occurrence"))
        placeholders = ", ".join("?" for _ in _OCCURRENCE_COLUMNS)
        conn.executemany(f"INSERT INTO occurrence VALUES ({placeholders})", occurrence_rows)
        add_occurrence_place_table(conn, occurrence_place_rows)
        conn.commit()
    finally:
        conn.close()


def make_taxon_group_yaml(path, default_label_ja: str = "未判定") -> None:
    path.write_text(f'default_label_ja: "{default_label_ja}"\nrules: []\n', encoding="utf-8")


# O-1b（`scripts/b07_build_occurrence_cube.py`/年キー8表・species_month）の
# テスト用: `occurrence_agg` のスキーマは `_CREATE_OCCURRENCE_AGG_SQL` 1箇所が正
# （同じ考え方。b07 の DIM_COLUMNS の並びで列を持つ）。
_OCCURRENCE_AGG_COLUMNS = (
    "region_id", "source_id", "place_id", "place_kind", "taxon_id", "grain", "period_start", "period_end",
    "n", "n_red_list", "built_from", "spec_version",
)


# O-2a（scripts/b09_build_occurrence_place.py・scripts/b08_project_occurrence_v1.py
# の org_watershed_year/org_watershed）のテスト用フィクスチャ。

def make_ryuiki_sites_db(path, sites_rows) -> None:
    """b09 の site→watershed 突き合わせ（`sites.watershed` との比較）用の、
    `sites` テーブルだけを持つ `ryuiki.sqlite` 相当。`sites_rows` は
    `(site_id, lat, lon, watershed)` の列。
    """
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(
            "CREATE TABLE sites (site_id TEXT PRIMARY KEY, lat REAL, lon REAL, watershed TEXT)"
        )
        conn.executemany("INSERT INTO sites VALUES (?,?,?,?)", sites_rows)
        conn.commit()
    finally:
        conn.close()


def write_watershed_geojson(path, features) -> None:
    """`data/processed/nlni_w12_watersheds.geojson` 相当のテスト用フィクスチャ。

    `features` は `(watershed_id, rings)` のリスト（`rings` は
    `[[[x,y], ...], ...]`——外環+穴のリング列。単純な矩形なら外環1つだけでよい）。
    すべて `geometry.type='Polygon'` として書く（MultiPolygon が要るテストは
    直接 `Polygon`/`build_grid` を組み立てる `test_migrate_point_in_polygon.py`
    側でカバーする）。
    """
    import json

    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"watershed_id": wid},
                "geometry": {"type": "Polygon", "coordinates": rings},
            }
            for wid, rings in features
        ],
    }
    path.write_text(json.dumps(geojson), encoding="utf-8")


def occurrence_place_declarations_yaml_text(
    n_watershed_polygons: int, place_id_null_count: int, resolved_count: int,
) -> str:
    return (
        f"n_watershed_polygons:\n  expected_row_count: {n_watershed_polygons}\n  note: テスト用\n"
        f"place_id_null_count:\n  expected_row_count: {place_id_null_count}\n  note: テスト用\n"
        f"resolved_count:\n  expected_row_count: {resolved_count}\n  note: テスト用\n"
    )


def make_occurrence_place_declarations_yaml(
    path, *, n_watershed_polygons: int, place_id_null_count: int, resolved_count: int, text: str | None = None,
) -> None:
    path.write_text(
        text if text is not None else occurrence_place_declarations_yaml_text(
            n_watershed_polygons, place_id_null_count, resolved_count,
        ),
        encoding="utf-8",
    )


def occurrence_watershed_v1_declarations_yaml_text(
    *, moved: int, ws_to_ws: int, v1_assigned_exact_unassigned: int, v1_unassigned_exact_assigned: int,
    mixed_buckets: int, keys_changed: int,
) -> str:
    return (
        "memo_moved_records:\n"
        f"  expected_count: {moved}\n"
        "  breakdown:\n"
        f"    ws_to_ws: {ws_to_ws}\n"
        f"    v1_assigned_exact_unassigned: {v1_assigned_exact_unassigned}\n"
        f"    v1_unassigned_exact_assigned: {v1_unassigned_exact_assigned}\n"
        "  note: テスト用\n"
        "memo_mixed_buckets:\n"
        f"  expected_count: {mixed_buckets}\n"
        "  note: テスト用\n"
        "org_watershed_year_keys_changed_vs_exact:\n"
        f"  expected_count: {keys_changed}\n"
        "  note: テスト用\n"
    )


def make_occurrence_watershed_v1_declarations_yaml(path, text: str | None = None, **kwargs) -> None:
    path.write_text(
        text if text is not None else occurrence_watershed_v1_declarations_yaml_text(**kwargs),
        encoding="utf-8",
    )


def make_v2_db_with_occurrence_and_agg(
    path, occurrence_rows: list[tuple], occurrence_agg_rows: list[tuple],
) -> None:
    """`occurrence`（L2）と `occurrence_agg`（キューブ）の両方を持つ v2.sqlite
    相当を作る（`scripts/b08_project_occurrence_v1.py` の
    `_build_cube_projections` は両方を読む——年キー8表は `occurrence_agg`
    だけから、`species2.en_name`/`red_list_category` と `species_month` は
    `occurrence` から）。
    """
    import b06_build_occurrence as b06
    import b07_build_occurrence_cube as b07

    conn = sqlite3.connect(f"file:{path}", uri=True)
    try:
        conn.execute(b06._CREATE_OCCURRENCE_SQL.format(table="occurrence"))
        placeholders = ", ".join("?" for _ in _OCCURRENCE_COLUMNS)
        conn.executemany(f"INSERT INTO occurrence VALUES ({placeholders})", occurrence_rows)

        conn.execute(b07._CREATE_OCCURRENCE_AGG_SQL.format(table="occurrence_agg"))
        agg_placeholders = ", ".join("?" for _ in _OCCURRENCE_AGG_COLUMNS)
        conn.executemany(f"INSERT INTO occurrence_agg VALUES ({agg_placeholders})", occurrence_agg_rows)
        conn.commit()
    finally:
        conn.close()
