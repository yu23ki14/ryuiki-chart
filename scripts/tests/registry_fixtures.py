"""scripts/registry/build_place.py（place / place_source_ref / place_relation を作る）
用の、本物の `data/db/*.sqlite`（828MB/42MB/449MB）を要さない小さな sqlite フィクスチャ。

`sites` / `watershed_meta` / `organism_records` のうち、build_place.build() が実際に
SELECT する列だけを持つ最小限の形にしてある（実データの全列を真似ない。
scripts/tests/migrate_fixtures.py と同じ方針）。site_id の名前空間は
`build_place.SITE_NAMESPACE` に実在する `jma_stations_kanagawa`（-> `jma`）を使う
（未知の名前空間は build_place 側で例外になるため）。

grid01 の入力は Phase B `phase-b/occurrence-registry` で `derived.mesh_all` から
`ryuiki.organism_records` の座標に変わった（`scripts/registry/build_place.py` の
grid01 節参照）。`make_ryuiki_places_db()` の `organism_records_rows` がその入力。
"""
from __future__ import annotations

import sqlite3


def make_ryuiki_places_db(path, sites_rows, organism_records_rows=()) -> None:
    """sites_rows: (site_id, name, lat, lon, elevation_m, source_id, source_ref, zone) の列。
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
                source_id TEXT, source_ref TEXT, zone INTEGER
            )"""
        )
        conn.execute("CREATE TABLE measurements (site_id TEXT)")
        conn.execute("CREATE TABLE sensor_timeseries (site_id TEXT)")
        conn.execute("CREATE TABLE organism_records (lat REAL, lon REAL)")
        conn.executemany("INSERT INTO sites VALUES (?,?,?,?,?,?,?,?)", sites_rows)
        conn.executemany("INSERT INTO organism_records VALUES (?,?)", organism_records_rows)
        conn.commit()
    finally:
        conn.close()


def make_derived_places_db(path, watershed_rows=()) -> None:
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


def open_places_src(ryuiki_path, derived_path) -> dict:
    """build_place.build(conn, src) の src 引数を作る（row_factory=Row。本物の
    scripts/registry/common.open_sources() と同じ形）。呼び出し側が使い終わったら
    自分で close() すること。
    """
    out = {}
    for key, path in (("ryuiki", ryuiki_path), ("derived", derived_path)):
        c = sqlite3.connect(str(path))
        c.row_factory = sqlite3.Row
        out[key] = c
    return out
