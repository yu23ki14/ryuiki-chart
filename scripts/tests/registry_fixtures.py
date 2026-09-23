"""scripts/registry/build_place.py（place / place_source_ref / place_relation /
place_watershed を作る）用の、本物の `data/db/*.sqlite`（828MB/42MB/449MB）を
要さない小さな sqlite フィクスチャ。

`sites` / `organism_records` のうち、build_place.build() が実際に SELECT する列だけを
持つ最小限の形にしてある（実データの全列を真似ない。scripts/tests/migrate_fixtures.py
と同じ方針）。site_id の名前空間は `build_place.SITE_NAMESPACE` に実在する
`jma_stations_kanagawa`（-> `jma`）を使う（未知の名前空間は build_place 側で例外になるため）。

grid01 の入力は Phase B `phase-b/occurrence-registry` で `derived.mesh_all` から
`ryuiki.organism_records` の座標に変わった（`scripts/registry/build_place.py` の
grid01 節参照）。`make_ryuiki_places_db()` の `organism_records_rows` がその入力。

watershed の入力は Phase B `phase-b/place-attributes` で `derived.watershed_meta`
から `data/processed/nlni_w12_watersheds.jsonl`（L1）直読みに変わった
（`scripts/registry/build_place.py` の watershed 節参照）。`write_watershed_jsonl()`
がその入力を作る。呼び出し側が `build_place_module.WATERSHED_JSONL` をこの JSONL の
パスに monkeypatch すること（`scripts/registry/build_taxon.py` の `CROSSWALK_CSV` と
同じ流儀）。`make_derived_places_db()` は watershed 節ではもう使わない
（derived.sqlite は registry ビルドの入力ではなくなった）が、「derived.sqlite の
中身は指紋・ビルドに一切影響しない」ことを確認するテスト
（scripts/tests/test_r01_registry_atomic.py）専用に残してある。
"""
from __future__ import annotations

import json
import sqlite3


def make_ryuiki_places_db(path, sites_rows, organism_records_rows=()) -> None:
    """sites_rows: (site_id, name, lat, lon, elevation_m, source_id, source_ref, zone,
    watershed) の列（`watershed` は Phase B `phase-b/place-attributes` で追加。
    地点->流域の place_relation の入力）。
    organism_records_rows: (lat, lon) の列（grid01 の入力。build_place.build() は
    `FLOOR(lat*100)`/`FLOOR(lon*100)` で丸めるだけなので、他の列は要らない）。

    `measurements` / `sensor_timeseries` は空のまま作る（build_place.build() が
    `sites` に無い site_id の補完対象を探すために SELECT するが、このフィクスチャは
    常に `sites` 側だけで完結させ、`registry/place/site_supplement.csv` 依存を避ける）。
    """
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(
            """CREATE TABLE sites (
                site_id TEXT PRIMARY KEY, name TEXT, lat REAL, lon REAL, elevation_m REAL,
                source_id TEXT, source_ref TEXT, zone INTEGER, watershed TEXT
            )"""
        )
        conn.execute("CREATE TABLE measurements (site_id TEXT)")
        conn.execute("CREATE TABLE sensor_timeseries (site_id TEXT)")
        conn.execute("CREATE TABLE organism_records (lat REAL, lon REAL)")
        conn.executemany("INSERT INTO sites VALUES (?,?,?,?,?,?,?,?,?)", sites_rows)
        conn.executemany("INSERT INTO organism_records VALUES (?,?)", organism_records_rows)
        conn.commit()
    finally:
        conn.close()


def write_watershed_jsonl(path, rows) -> None:
    """`data/processed/nlni_w12_watersheds.jsonl` 相当のテスト用フィクスチャを書く。

    `rows` は dict のリスト。build_place.py が実際に読むキーだけを持たせればよい
    （`watershed_id`/`water_system_code_old`/`water_system_name_ja_estimated`/
    `water_system_category_ja`/`main_river_names_ja`/`area_km2`/`centroid_lat`/
    `centroid_lon`/`data_year`/`source_ref`）。実物と同じ1行1レコードの JSON。
    """
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False))
            f.write("\n")


def make_derived_places_db(path, watershed_rows=()) -> None:
    """`derived.sqlite` の一般的な代用フィクスチャ（任意の形の `watershed_meta`
    テーブルを持つ）。registry ビルド本体はもうこのテーブルを読まないので
    （モジュール docstring 参照）、「derived.sqlite が存在しても指紋・ビルドに
    影響しない」ことを確認するテスト専用に残してある。
    """
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(
            """CREATE TABLE watershed_meta (
                watershed_id TEXT, water_system_name TEXT, area_km2 REAL,
                centroid_lat REAL, centroid_lon REAL, source_ref TEXT
            )"""
        )
        conn.executemany("INSERT INTO watershed_meta VALUES (?,?,?,?,?,?)", watershed_rows)
        conn.commit()
    finally:
        conn.close()


def make_ryuiki_taxon_db(path, organism_records_rows=(), taxa_rows=()) -> None:
    """scripts/registry/build_taxon.py 用の最小限フィクスチャ。

    organism_records_rows: (source_id, taxon_key, scientific_name, taxon_rank,
      kingdom, phylum, class, order, family, observed_on) の列
      （build_taxon.py が実際に SELECT する列だけ。record_id/lat/lon 等は使わないので持たない）。
    taxa_rows: (taxon_id, scientific_name, vernacular_name_ja, gbif_taxon_key,
      gbif_match_type, kingdom, phylum, class, order, family) の列。
    """
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(
            """CREATE TABLE organism_records (
                source_id TEXT, taxon_key TEXT, scientific_name TEXT, taxon_rank TEXT,
                kingdom TEXT, phylum TEXT, class TEXT, "order" TEXT, family TEXT,
                observed_on TEXT
            )"""
        )
        conn.execute(
            """CREATE TABLE taxa (
                taxon_id TEXT PRIMARY KEY, scientific_name TEXT, vernacular_name_ja TEXT,
                gbif_taxon_key TEXT, gbif_match_type TEXT,
                kingdom TEXT, phylum TEXT, class TEXT, "order" TEXT, family TEXT
            )"""
        )
        conn.executemany(
            'INSERT INTO organism_records VALUES (?,?,?,?,?,?,?,?,?,?)', organism_records_rows
        )
        conn.executemany("INSERT INTO taxa VALUES (?,?,?,?,?,?,?,?,?,?)", taxa_rows)
        conn.commit()
    finally:
        conn.close()


def open_taxon_src(ryuiki_path) -> dict:
    """build_taxon.build(conn, src) の src 引数を作る（'ryuiki' キーだけを使う）。"""
    conn = sqlite3.connect(str(ryuiki_path))
    conn.row_factory = sqlite3.Row
    return {"ryuiki": conn}


def open_places_src(ryuiki_path) -> dict:
    """build_place.build(conn, src) の src 引数を作る（row_factory=Row）。
    'ryuiki' キーだけを使う（build_place.py は Phase B `phase-b/place-attributes`
    で 'derived' を読まなくなった——watershed の入力を WATERSHED_JSONL の直読みに
    切り替えたため。呼び出し側が使い終わったら自分で close() すること。
    """
    conn = sqlite3.connect(str(ryuiki_path))
    conn.row_factory = sqlite3.Row
    return {"ryuiki": conn}


# ---------------------------------------------------------------------------
# scripts/registry/build_taxon_assessment.py（P-2）用
# ---------------------------------------------------------------------------

# ryuiki.redlist_assessments の列（scripts/registry/build_taxon_assessment.py
# ._load_redlist_assessment_rows() が実際に SELECT する列だけ）。
REDLIST_ASSESSMENT_COLUMNS = (
    "assessment_id", "list_name", "list_year", "taxon_group_ja", "taxon_subgroup_ja",
    "family_ja", "vernacular_name_ja", "scientific_name",
    "category_ja", "category_prev_ja", "national_category_ja", "source_id",
)


def make_ryuiki_redlist_db(path, redlist_rows=()) -> None:
    """scripts/registry/build_taxon_assessment.py 用の最小限フィクスチャ
    （`redlist_assessments` だけを持つ。`redlist_rows` は
    `REDLIST_ASSESSMENT_COLUMNS` の順のタプル列）。
    """
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(
            f"""CREATE TABLE redlist_assessments (
                {", ".join(REDLIST_ASSESSMENT_COLUMNS)}
            )"""
        )
        placeholders = ",".join("?" for _ in REDLIST_ASSESSMENT_COLUMNS)
        conn.executemany(f"INSERT INTO redlist_assessments VALUES ({placeholders})", redlist_rows)
        conn.commit()
    finally:
        conn.close()


def open_taxon_assessment_src(ryuiki_path) -> dict:
    """build_taxon_assessment.build(conn, src) の src 引数を作る
    （'ryuiki' キーだけを使う）。"""
    conn = sqlite3.connect(str(ryuiki_path))
    conn.row_factory = sqlite3.Row
    return {"ryuiki": conn}


def write_moe_ias_list_csv(path, rows) -> None:
    """`data/processed/moe_ias_list.csv` 相当のテスト用フィクスチャを書く。
    `rows` は dict のリスト。build_taxon_assessment.py が実際に読む列だけを
    持たせればよい（`category_ja`/`origin_ja`/`taxon_group_ja`/`family_ja`/
    `scientific_name`/`vernacular_name_ja`/`source_id`）。
    """
    import csv

    fieldnames = [
        "category_ja", "category_parent_ja", "origin_ja", "taxon_group_ja", "family_ja",
        "scientific_name", "vernacular_name_ja", "ias_law_status_ja", "establishment_stage_ja",
        "selection_reason_ja", "problem_area_ja", "kingdom_sheet_ja", "note_ja",
        "source_id", "source_ref",
    ]
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for row in rows:
            full = {k: "" for k in fieldnames}
            full.update(row)
            w.writerow(full)


def insert_taxon_rows(registry_conn, taxon_rows) -> None:
    """`registry_conn`（`common.create_registry_db()` で作った書き込み用接続）の
    `taxon` テーブルに、taxon_id 解決テスト用の最小限の行を入れる。
    `taxon_rows` は `(taxon_id, scientific_name, canonical_binomial)` の列
    （他の列は NULL のままで taxon_id 解決には影響しない）。
    """
    registry_conn.executemany(
        "INSERT INTO taxon (taxon_id, scientific_name, canonical_binomial) VALUES (?, ?, ?)",
        taxon_rows,
    )
