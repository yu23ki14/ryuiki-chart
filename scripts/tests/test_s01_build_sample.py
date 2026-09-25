"""`scripts/s01_build_sample.py` の単体テスト。自前の小さなフィクスチャ
sqlite（`ryuiki.sqlite`/`cells.sqlite` の必要最小限の列だけ）だけで完結する
——本物の原本（828MB/42MB）は一切使わない。
"""
from __future__ import annotations

import pathlib
import sqlite3
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import s01_build_sample as s01  # noqa: E402


def _build_fixture_ryuiki(path: pathlib.Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE measurements (
          measurement_id TEXT, site_id TEXT, measured_on TEXT, variable TEXT,
          value REAL, value_raw TEXT, source_id TEXT
        );
        CREATE TABLE sites (site_id TEXT PRIMARY KEY, name TEXT);
        CREATE TABLE quality_transitions (
          id INTEGER PRIMARY KEY, target_table TEXT, target_id TEXT
        );
        CREATE TABLE organism_records (
          record_id TEXT, observed_on TEXT, lat REAL, lon REAL, scientific_name TEXT,
          is_alien INTEGER, red_list_category TEXT, source_id TEXT, genus TEXT
        );
        CREATE TABLE sensor_timeseries (source_id TEXT);
        """
    )
    # site A: 3行（うち1つが below_lod predicate に一致）、これで
    # site x variable の閉包が効くか確かめられる。
    rows = [
        ("m1", "A", "2020-01-01", "v1", 1.0, "1.0", "src1"),
        ("m2", "A", "2020-01-02", "v1", None, "<0.5", "src1"),
        ("m3", "A", "2020-01-03", "v1", 2.0, "2.0", "src1"),
        ("m4", "B", "2020-01-01", "v2", 3.0, "3.0", "src2"),
        # quality_transitions が参照する行（predicate には引っかからない）。
        ("m5", "C", "2020-01-01", "v3", 4.0, "4.0", "src3"),
    ]
    conn.executemany(
        "INSERT INTO measurements (measurement_id, site_id, measured_on, variable, value, value_raw, source_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.executemany(
        "INSERT INTO sites (site_id, name) VALUES (?, ?)", [("A", "Site A"), ("B", "Site B"), ("C", "Site C")]
    )
    conn.execute(
        "INSERT INTO quality_transitions (id, target_table, target_id) VALUES (1, 'measurements', 'm5')"
    )
    conn.commit()
    conn.close()


def _write_fixture_coverage_yaml(path: pathlib.Path) -> None:
    path.write_text(
        "version: 1\n"
        "default_limit: 10\n"
        "predicates:\n"
        "  - name: below_lod\n"
        "    table: measurements\n"
        "    where: \"value_raw LIKE '<%'\"\n"
        "    limit: 10\n"
        "    min_rows: 1\n"
        "full_closures: []\n"
        "document_closure:\n"
        "  doc_ids: []\n"
        "  min_documents: 0\n"
        "wholesale_ryuiki_tables:\n"
        "  - sites\n"
        "wholesale_cells_tables: []\n"
        "wholesale_processed_files: []\n",
        encoding="utf-8",
    )


def test_apply_measurement_site_variable_closure_pulls_in_full_history():
    """below_lod の predicate は m2（site A）だけを選ぶが、site×variable の
    閉包で site A の全行（m1/m2/m3）が入る。site B（別の site×variable）は入らない。
    """
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        "CREATE TABLE measurements (site_id TEXT, variable TEXT);"
        "INSERT INTO measurements VALUES ('A','v1'),('A','v1'),('A','v1'),('B','v2');"
    )
    seed = {2}  # 2行目（0-indexedでrowid=2）だけを種にする
    closed = s01.apply_measurement_site_variable_closure(conn, seed)
    assert closed == {1, 2, 3}


def test_apply_quality_transitions_closure_pulls_in_referenced_measurements():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        "CREATE TABLE measurements (measurement_id TEXT);"
        "INSERT INTO measurements VALUES ('m1'),('m2'),('m3');"
        "CREATE TABLE quality_transitions (target_table TEXT, target_id TEXT);"
        "INSERT INTO quality_transitions VALUES ('measurements','m3');"
    )
    closed = s01.apply_quality_transitions_closure(conn, {1})
    assert closed == {1, 3}


def test_build_declaration_counts_atsugi_predicate(tmp_path):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        "CREATE TABLE measurements (site_id TEXT, variable TEXT, measured_on TEXT, source_id TEXT);"
        "INSERT INTO measurements (site_id, measured_on, source_id) VALUES "
        "('s1', '2020', 'atsugi_river_water_quality'), "
        "('s2', '2020-01-01', 'atsugi_river_water_quality'), "
        "('s3', '1999', 'other_source');"
        "CREATE TABLE organism_records (record_id TEXT, observed_on TEXT, lat REAL, lon REAL, "
        "scientific_name TEXT, is_alien INTEGER, red_list_category TEXT, source_id TEXT, genus TEXT);"
        "CREATE TABLE sensor_timeseries (source_id TEXT);"
    )
    selected = {"measurements": {1, 2, 3}, "organism_records": set(), "sensor_timeseries": set()}
    counts = s01.build_declaration_counts(conn, selected)
    assert counts["period_exceptions.yaml:atsugi_river_water_quality"] == 1


def test_sql_literal_distinguishes_null_from_empty_string():
    assert s01._sql_literal(None) == "NULL"
    assert s01._sql_literal("") == "''"
    assert s01._sql_literal("it's") == "'it''s'"
    assert s01._sql_literal(3) == "3"
    assert s01._sql_literal(3.5) == "3.5"


def test_write_table_sql_round_trips_null_and_empty_string(tmp_path):
    src = sqlite3.connect(":memory:")
    src.row_factory = sqlite3.Row
    src.executescript("CREATE TABLE t (a TEXT, b TEXT); INSERT INTO t VALUES (NULL, '');")
    out_path = tmp_path / "t.sql"
    n = s01._write_table_sql(src, "t", [1], out_path)
    assert n == 1

    dst = sqlite3.connect(":memory:")
    dst.executescript("CREATE TABLE t (a TEXT, b TEXT);")
    dst.executescript(out_path.read_text(encoding="utf-8"))
    row = dst.execute("SELECT a, b FROM t").fetchone()
    assert row == (None, "")


def test_end_to_end_determinism_on_fixture_db(tmp_path):
    """同じ原本（フィクスチャ）から2回 s01 を実行すると、書き出すテキストが
    バイト単位で一致する（決定論。A-1）。
    """
    ryuiki_db = tmp_path / "ryuiki.sqlite"
    cells_db = tmp_path / "cells.sqlite"
    _build_fixture_ryuiki(ryuiki_db)
    conn = sqlite3.connect(str(cells_db))
    conn.executescript(
        "CREATE TABLE documents (doc_id TEXT PRIMARY KEY);"
        "CREATE TABLE cells (doc_id TEXT);"
    )
    conn.commit()
    conn.close()

    coverage_yaml = tmp_path / "coverage.yaml"
    _write_fixture_coverage_yaml(coverage_yaml)

    baseline_json = tmp_path / "derived_baseline.json"
    baseline_json.write_text('{"tables": {}}', encoding="utf-8")

    out_dir_1 = tmp_path / "out1"
    out_dir_2 = tmp_path / "out2"

    for out_dir in (out_dir_1, out_dir_2):
        argv_backup = sys.argv
        sys.argv = [
            "s01_build_sample.py",
            "--ryuiki-db", str(ryuiki_db),
            "--cells-db", str(cells_db),
            "--processed-dir", str(tmp_path),
            "--coverage-yaml", str(coverage_yaml),
            "--baseline-json", str(baseline_json),
            "--out-dir", str(out_dir),
        ]
        try:
            assert s01.main() == 0
        finally:
            sys.argv = argv_backup

    measurements_1 = (out_dir_1 / "ryuiki" / "measurements.sql").read_text(encoding="utf-8")
    measurements_2 = (out_dir_2 / "ryuiki" / "measurements.sql").read_text(encoding="utf-8")
    assert measurements_1 == measurements_2

    # site×variable の閉包で site A の3行が全部入り、quality_transitions が
    # 参照する m5（site C）も参照の整合で入る。site B は入らない。
    assert "'m1'" in measurements_1 and "'m2'" in measurements_1 and "'m3'" in measurements_1
    assert "'m5'" in measurements_1
    assert "'m4'" not in measurements_1

    manifest_1 = (out_dir_1 / "manifest.json").read_text(encoding="utf-8")
    manifest_2 = (out_dir_2 / "manifest.json").read_text(encoding="utf-8")
    # generated_at だけ実行のたびに変わりうるので、それ以外が一致することを見る。
    import json

    m1 = json.loads(manifest_1)
    m2 = json.loads(manifest_2)
    m1.pop("generated_at")
    m2.pop("generated_at")
    assert m1 == m2
