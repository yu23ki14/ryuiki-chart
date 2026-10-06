"""`scripts/s01_build_sample.py` の単体テスト。自前の小さなフィクスチャ
sqlite（`ryuiki.sqlite`/`cells.sqlite` の必要最小限の列だけ）だけで完結する
——本物の原本（828MB/42MB）は一切使わない。
"""
from __future__ import annotations

import pathlib

import pytest
import sqlite3
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import s01_build_sample as s01  # noqa: E402
from scripts.tests.manifest_fixtures import write_manifests_from_sources_text  # noqa: E402


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


_EMPTY_GEOJSON = '{"type": "FeatureCollection", "features": []}'

# `build_declaration_counts` の既定引数 `landuse_csv_path=DEFAULT_LANDUSE_CSV`
# は正規のパス（`data/processed/nlni_l03b_landuse_by_watershed.csv`）を指す。
# 原本の無い環境（CI の `reconcile` ジョブ）では実在しないため、`geojson_path`
# と同じく、このテスト専用の一時ファイルを明示的に渡す（実測で FileNotFoundError
# を確認済み——このテストが worktree で「たまたま」通っていたのは、原本
# symlink 越しに本物のCSVが存在していたため。CI の実際の失敗で発覚）。
# 値そのものはこのテストの検証対象ではないので、ヘッダ+1行の最小構成でよい。
_MINIMAL_LANDUSE_CSV = "watershed_id,year,landuse_code,area_ha,n_cells\nW001,2016,100,1.0,1\n"


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
    geojson_path = tmp_path / "watersheds.geojson"
    geojson_path.write_text(_EMPTY_GEOJSON, encoding="utf-8")
    landuse_csv_path = tmp_path / "landuse.csv"
    landuse_csv_path.write_text(_MINIMAL_LANDUSE_CSV, encoding="utf-8")
    counts = s01.build_declaration_counts(conn, selected, geojson_path, landuse_csv_path)
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

    # --processed-dir は tmp_path なので、そこに W12 相当のフィクスチャを置く
    # （0件の organism_records でも build_declaration_counts が読みに行くため）。
    (tmp_path / "nlni_w12_watersheds.geojson").write_text(_EMPTY_GEOJSON, encoding="utf-8")
    # manifest.json の source_files（pipeline_inputs.SOURCE_FILE_KEYS）は
    # data/processed の6ファイルすべての実在を要求するので、残り5つもダミーで置く。
    for name in (
        "nlni_w12_watersheds.jsonl", "nlni_l03b_landuse_by_watershed.csv",
        "moe_ias_list.csv", "taxon_crosswalk.csv", "taxon_gbif_accepted.csv",
    ):
        (tmp_path / name).write_text("dummy", encoding="utf-8")

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


# ---------------------------------------------------------------------------
# Issue #48 PR-3a（occurrence_cube_declarations.yaml の新設3キー）
# ---------------------------------------------------------------------------

_SOURCE_REGIONS_YAML_TEXT = (
    "sources:\n"
    "  gbif_kanagawa_occurrences:\n"
    "    region_id: jp-14\n"
    "    consumer: occurrence\n"
    "    expected_row_count: 1\n"
    "    evidence: テスト用\n"
)


def _make_org_rows(conn: sqlite3.Connection, rows: list[tuple]) -> list[sqlite3.Row]:
    """`compute_month_cell_source_rows`/`compute_leaf_cell_source_rows` が読む
    列（`record_id, observed_on, source_id, lat, lon, scientific_name,
    is_alien, red_list_category, rowid`）を持つ `sqlite3.Row` の並びを作る。
    """
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE t (record_id TEXT, observed_on TEXT, source_id TEXT, lat REAL, lon REAL, "
        "scientific_name TEXT, is_alien INTEGER, red_list_category TEXT)"
    )
    conn.executemany("INSERT INTO t VALUES (?,?,?,?,?,?,?,?)", rows)
    return conn.execute("SELECT rowid, * FROM t ORDER BY rowid").fetchall()


def test_load_utc_offset_by_source_reads_declared_sources(tmp_path):
    path = tmp_path / "manifests"
    write_manifests_from_sources_text(path, _SOURCE_REGIONS_YAML_TEXT)
    mapping = s01.load_utc_offset_by_source(path)
    assert mapping == {"gbif_kanagawa_occurrences": "+09:00"}


def test_compute_month_cell_source_rows_counts_same_month_records():
    conn = sqlite3.connect(":memory:")
    rows = _make_org_rows(
        conn,
        [
            ("r1", "2020-01-05", "gbif_kanagawa_occurrences", 35.5, 139.0, "Foo", 0, ""),  # day, 同一月
            ("r2", "2020-03-01/2020-04-05", "gbif_kanagawa_occurrences", 35.5, 139.0, "Foo", 0, ""),  # 月をまたぐ
        ],
    )
    n = s01.compute_month_cell_source_rows(rows, {"gbif_kanagawa_occurrences": "+09:00"})
    assert n == 1


def test_compute_month_cell_source_rows_uses_expand_period_not_raw_string_split():
    """'Z' 終端の区間は、raw 文字列をそのまま '/' で割って月を比べる近似では
    誤判定する（月境界をまたいで変換されることがあるため）。
    `compute_leaf_cell_source_rows`（年境界の近似で足りる）と違い、この関数は
    `occurrence_period.expand_period()` で実際に展開してから判定することを
    確かめる。

    `"2020-01-31T23:30Z/2020-02-01T00:30Z"`（UTC）は raw のままだと月が
    '01'/'02' で異なる（近似なら「月をまたぐ」と誤判定する）が、
    utc_offset='+09:00' で変換すると両端とも '2020-02' になり、実際には
    同一月に収まる。
    """
    conn = sqlite3.connect(":memory:")
    rows = _make_org_rows(
        conn,
        [
            (
                "r1", "2020-01-31T23:30Z/2020-02-01T00:30Z", "gbif_kanagawa_occurrences",
                35.5, 139.0, "Foo", 0, "",
            ),
        ],
    )
    n = s01.compute_month_cell_source_rows(rows, {"gbif_kanagawa_occurrences": "+09:00"})
    assert n == 1  # 変換後は同一月（'2020-02'）に収まる


def test_compute_occurrence_place_and_watershed_stats_reports_dated_resolved_and_unresolved(tmp_path):
    """`watershed_dated_resolved_rows`/`watershed_dated_unresolved_rows` は
    「日付あり」記録だけを母集団にする——`occurrence_place_declarations.yaml`
    の `resolved_count`（座標のある全記録が母集団）とは異なる母集団になりうる。
    """
    from .occurrence_fixtures import write_watershed_geojson

    geojson_path = tmp_path / "watersheds.geojson"
    # 1辺1度の正方形ポリゴン（lat 35.0〜36.0, lon 139.0〜140.0）。
    write_watershed_geojson(
        geojson_path,
        [("W001", [[[139.0, 35.0], [140.0, 35.0], [140.0, 36.0], [139.0, 36.0], [139.0, 35.0]]])],
    )
    conn = sqlite3.connect(":memory:")
    rows = _make_org_rows(
        conn,
        [
            # 日付あり・ポリゴン内（解決）。
            ("r_in", "2020-01-05", "gbif_kanagawa_occurrences", 35.5, 139.5, "Foo", 0, ""),
            # 日付あり・ポリゴン外（未解決）。
            ("r_out", "2020-01-06", "gbif_kanagawa_occurrences", 10.0, 10.0, "Foo", 0, ""),
            # 座標はあるが日付なし（どちらの宣言の母集団にも入らない）。
            ("r_undated", None, "gbif_kanagawa_occurrences", 35.5, 139.5, "Foo", 0, ""),
        ],
    )
    stats = s01.compute_occurrence_place_and_watershed_stats(rows, geojson_path)
    assert stats["watershed_dated_resolved_rows"] == 1
    assert stats["watershed_dated_unresolved_rows"] == 1
    # occurrence_place_declarations.yaml 側（座標のある全記録が母集団）は
    # r_undated も数えるので3件。
    assert stats["resolved_count"] + stats["place_id_null_count"] == 3


def test_build_declaration_counts_wires_new_occurrence_cube_keys(tmp_path):
    """`build_declaration_counts` が3つの新しい宣言キーを
    `occurrence_cube_declarations.yaml` の名前空間で返すことを確認する
    （値そのものは上の専用テストで確かめ済みなので、ここではキーの配線だけ見る）。
    """
    from .occurrence_fixtures import write_watershed_geojson

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        "CREATE TABLE measurements (site_id TEXT, variable TEXT, measured_on TEXT, source_id TEXT);"
        "CREATE TABLE organism_records (record_id TEXT, observed_on TEXT, lat REAL, lon REAL, "
        "scientific_name TEXT, is_alien INTEGER, red_list_category TEXT, source_id TEXT, genus TEXT);"
        "INSERT INTO organism_records "
        "(record_id, observed_on, lat, lon, scientific_name, is_alien, red_list_category, source_id) "
        "VALUES ('r1', '2020-01-05', 35.5, 139.5, 'Foo', 0, '', 'gbif_kanagawa_occurrences');"
        "CREATE TABLE sensor_timeseries (source_id TEXT);"
    )
    selected = {"measurements": set(), "organism_records": {1}, "sensor_timeseries": set()}

    geojson_path = tmp_path / "watersheds.geojson"
    write_watershed_geojson(
        geojson_path,
        [("W001", [[[139.0, 35.0], [140.0, 35.0], [140.0, 36.0], [139.0, 36.0], [139.0, 35.0]]])],
    )
    landuse_csv_path = tmp_path / "landuse.csv"
    landuse_csv_path.write_text(_MINIMAL_LANDUSE_CSV, encoding="utf-8")
    manifests_dir = tmp_path / "manifests"
    write_manifests_from_sources_text(manifests_dir, _SOURCE_REGIONS_YAML_TEXT)

    counts = s01.build_declaration_counts(
        conn, selected, geojson_path, landuse_csv_path, manifests_dir=manifests_dir,
    )
    assert counts["occurrence_cube_declarations.yaml:leaf_cell_source_rows"] == 0
    assert counts["occurrence_cube_declarations.yaml:month_cell_source_rows"] == 1
    assert counts["occurrence_cube_declarations.yaml:watershed_dated_resolved_rows"] == 1
    assert counts["occurrence_cube_declarations.yaml:watershed_dated_unresolved_rows"] == 0


# ---------------------------------------------------------------------------
# adapter 出典（マニフェストの非 builtin）の入力はマニフェストから導いてサンプルに入れる（Issue #40）
# ---------------------------------------------------------------------------

def _adapter_manifest(tmp_path, monkeypatch, *, table="wildlife_sightings", file=None, n=400):
    import ingest.manifest as manifest_lib
    from scripts.tests.manifest_fixtures import write_manifest

    adapters = tmp_path / "adapters"
    adapters.mkdir(exist_ok=True)
    (adapters / "src_a.py").write_text("def rows(ctx):\n    return iter(())\n", encoding="utf-8")
    monkeypatch.setattr(manifest_lib, "DEFAULT_ADAPTERS_DIR", adapters)
    expected = {
        "period_shapes": {"day": n},
        "place": {"coord_resolved": 0, "coord_unresolved": 0},
        "cube": {k: 0 for k in manifest_lib.EXPECTED_CUBE_KEYS},
    }
    d = tmp_path / ("m_file" if file else "m")
    write_manifest(
        d, "src_a", target="occurrence", adapter="src_a", expected_row_count=n,
        input={"file": file} if file else {"table": table}, extra={"expected": expected},
    )
    return d


def test_adapter_input_table_is_included_whole_without_touching_coverage_yaml(tmp_path, monkeypatch):
    m = _adapter_manifest(tmp_path, monkeypatch)
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE wildlife_sightings (id INTEGER)")
    conn.executemany("INSERT INTO wildlife_sightings VALUES (?)", [(i,) for i in range(400)])
    chosen = s01.select_adapter_input_tables(conn, s01.adapter_inputs(m), selected={})
    assert set(chosen) == {"wildlife_sightings"} and len(chosen["wildlife_sightings"]) == 400


def test_adapter_input_table_over_limit_or_already_narrowed_stops(tmp_path, monkeypatch):
    m = _adapter_manifest(tmp_path, monkeypatch)
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE wildlife_sightings (id INTEGER)")
    conn.executemany("INSERT INTO wildlife_sightings VALUES (?)", [(i,) for i in range(s01.ADAPTER_INPUT_WHOLESALE_MAX_ROWS + 1)])
    with pytest.raises(SystemExit, match="上限"):
        s01.select_adapter_input_tables(conn, s01.adapter_inputs(m), selected={})
    with pytest.raises(SystemExit, match="predicate"):
        s01.select_adapter_input_tables(conn, s01.adapter_inputs(m), selected={"wildlife_sightings": {1}})


def test_adapter_input_file_must_be_under_data_processed(tmp_path, monkeypatch):
    m = _adapter_manifest(tmp_path, monkeypatch, file="data/processed/x.csv")
    assert s01.adapter_input_files(s01.adapter_inputs(m)) == ["x.csv"]


def test_adapter_input_file_elsewhere_stops(tmp_path, monkeypatch):
    m = _adapter_manifest(tmp_path, monkeypatch, file="data/elsewhere/x.csv")
    with pytest.raises(SystemExit, match="data/processed"):
        s01.adapter_input_files(s01.adapter_inputs(m))


def test_declaration_counts_keys_come_from_adapter_manifests(tmp_path, monkeypatch):
    m = _adapter_manifest(tmp_path, monkeypatch)
    assert {sid: x.expected_row_count for sid, x in s01.adapter_inputs(m).items()} == {"src_a": 400}
