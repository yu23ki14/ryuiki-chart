"""observation の region_id はマニフェストから決め、place 経由の値は照合に使う（ADR-0022 決定3・Issue #40 Phase D）。"""
from __future__ import annotations

import sqlite3

import pytest

import b03_build_observation as b03
from migrate import common, source_regions

from .manifest_fixtures import write_manifest
from .migrate_fixtures import (
    DEFAULT_PLACE_REFS,
    DEFAULT_PLACES,
    build_observation,
    make_measurements_db,
    make_registry_db,
)


def _paths(tmp_path):
    return tmp_path / "no_exc.yaml", tmp_path / "no_conv.yaml"


def test_region_id_comes_from_manifest_when_place_has_no_region(tmp_path):
    """place が地域を持たない（common スコープ。region_id NULL）行でも、マニフェストの region が入る。"""
    measurements_db, registry_db, out = tmp_path / "ryuiki.sqlite", tmp_path / "registry.sqlite", tmp_path / "v2.sqlite"
    make_measurements_db(measurements_db)
    make_registry_db(registry_db, places=[(pid, None, kind) for pid, _r, kind in DEFAULT_PLACES])
    exc, conv = _paths(tmp_path)
    build_observation(tmp_path, measurements_db, registry_db, exc, conv, out)
    conn = sqlite3.connect(f"file:{out}?mode=ro", uri=True)
    assert {r[0] for r in conn.execute("SELECT DISTINCT region_id FROM observation")} == {"jp-14"}


def test_region_mismatch_between_manifest_and_place_stops(tmp_path):
    """マニフェストの region（jp-14）と place 経由の region が食い違えば、黙って片方を採らず止まる。"""
    measurements_db, registry_db, out = tmp_path / "ryuiki.sqlite", tmp_path / "registry.sqlite", tmp_path / "v2.sqlite"
    make_measurements_db(measurements_db)
    make_registry_db(registry_db, places=[(pid, "jp-99", kind) for pid, _r, kind in DEFAULT_PLACES])
    exc, conv = _paths(tmp_path)
    with pytest.raises(common.MigrationError, match="region の照合に失敗"):
        build_observation(tmp_path, measurements_db, registry_db, exc, conv, out)


def test_measurement_source_without_manifest_stops(tmp_path):
    measurements_db, registry_db, out = tmp_path / "ryuiki.sqlite", tmp_path / "registry.sqlite", tmp_path / "v2.sqlite"
    make_measurements_db(measurements_db)
    make_registry_db(registry_db)
    exc, conv = _paths(tmp_path)
    landuse_csv = tmp_path / "landuse.csv"
    landuse_csv.write_text("", encoding="utf-8")
    empty_manifests = tmp_path / "empty_manifests"
    empty_manifests.mkdir()
    with pytest.raises(source_regions.UnknownSourceRegionError, match="src_a"):
        b03.build_and_write_observation(measurements_db, registry_db, exc, conv, out, empty_manifests, landuse_csv)


def test_manifest_without_rows_is_an_unused_declaration(tmp_path):
    """マニフェストにあるのに誰も処理しない（行が 1 件も無い）観測の出典は、宣言の腐敗として止まる。"""
    measurements_db, registry_db, out = tmp_path / "ryuiki.sqlite", tmp_path / "registry.sqlite", tmp_path / "v2.sqlite"
    make_measurements_db(measurements_db)
    make_registry_db(registry_db)
    exc, conv = _paths(tmp_path)
    manifests = tmp_path / "manifests"
    write_manifest(manifests, "src_a", update_mode="append", input={"table": "measurements"})
    write_manifest(manifests, "ghost_source", update_mode="append", input={"table": "measurements"})
    landuse_csv = tmp_path / "landuse.csv"
    landuse_csv.write_text("", encoding="utf-8")
    with pytest.raises(common.MigrationError, match="ghost_source"):
        b03.build_and_write_observation(measurements_db, registry_db, exc, conv, out, manifests, landuse_csv)


def test_non_builtin_observation_manifest_is_not_supported_yet(tmp_path):
    measurements_db, registry_db, out = tmp_path / "ryuiki.sqlite", tmp_path / "registry.sqlite", tmp_path / "v2.sqlite"
    make_measurements_db(measurements_db)
    make_registry_db(registry_db)
    exc, conv = _paths(tmp_path)
    manifests = tmp_path / "manifests"
    write_manifest(manifests, "src_a", update_mode="append", input={"table": "measurements"})
    adapters_dir = tmp_path / "adapters"
    adapters_dir.mkdir()
    (adapters_dir / "obs_src.py").write_text("def rows(ctx):\n    return iter(())\n", encoding="utf-8")
    write_manifest(manifests, "obs_src", update_mode="append", input={"table": "x"}, adapter="obs_src",
                   expected_row_count=0)
    import ingest.manifest as manifest_lib

    original = manifest_lib.DEFAULT_ADAPTERS_DIR
    manifest_lib.DEFAULT_ADAPTERS_DIR = adapters_dir
    try:
        landuse_csv = tmp_path / "landuse.csv"
        landuse_csv.write_text("", encoding="utf-8")
        with pytest.raises(common.MigrationError, match="未実装"):
            b03.build_and_write_observation(measurements_db, registry_db, exc, conv, out, manifests, landuse_csv)
    finally:
        manifest_lib.DEFAULT_ADAPTERS_DIR = original
