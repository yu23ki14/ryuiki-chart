"""adapter 経由の出現（`manifests/` の非 builtin）を b06 に通す統合テストと、runner の契約検査（Issue #40 Phase D）。

adapter は tmp に置いたモジュールを `adapters` パッケージの検索パスに足して読ませる
（`manifest.DEFAULT_ADAPTERS_DIR` も同じ tmp に向ける）。原本 DB・本物の registry は使わない。
"""
from __future__ import annotations

import json
import sqlite3
import sys
import textwrap

import pytest

import adapters
import b06_build_occurrence as b06
from ingest import manifest as manifest_lib
from migrate import common

from .manifest_fixtures import write_manifest, write_manifests_from_sources_text
from .occurrence_fixtures import (
    DEFAULT_ORGANISM_RECORDS,
    DEFAULT_SHAPE_COUNTS,
    DEFAULT_SOURCE_REGIONS_YAML_TEXT,
    make_occurrence_registry_db,
    make_organism_records_db,
    make_period_shapes_yaml,
)

SOURCE = "adapter_test_source"
TAXON = "common:taxon:gbif.1001"  # DEFAULT_TAXA にある

_ADAPTER_SRC = textwrap.dedent(
    '''
    from ingest.api import occurrence_row


    def rows(ctx):
        for r in ctx.input_rows():
            yield occurrence_row(
                f"s{r['id']}", taxon_id=r["taxon"], observed_on_raw=r["day"], lat=r["lat"], lon=r["lon"],
                attributes={"situation": r["situation"]},
            )
    '''
)

_INPUT_ROWS = [
    # id, taxon, day, lat, lon, situation
    (1, TAXON, "2020-03-01", None, None, "目撃"),
    (2, TAXON, "2020-03-02", None, None, "痕跡"),
    (3, TAXON, None, None, None, "その他"),  # 日付なし
]


def _expected(**over):
    exp = {
        "period_shapes": {"day": 2},
        "place": {"coord_resolved": 0, "coord_unresolved": 0},
        "cube": {
            "dated_rows": 2, "dated_no_coordinate_rows": 2, "leaf_cell_source_rows": 0,
            "leaf_cell_source_rows_no_coordinate": 0, "month_cell_source_rows": 0,
            "watershed_dated_resolved_rows": 0, "watershed_dated_unresolved_rows": 2,
        },
    }
    exp.update(over)
    return exp


@pytest.fixture
def env(tmp_path, monkeypatch):
    adapters_dir = tmp_path / "adapters_dir"
    adapters_dir.mkdir()
    monkeypatch.setattr(manifest_lib, "DEFAULT_ADAPTERS_DIR", adapters_dir)
    monkeypatch.setattr(adapters, "__path__", [*adapters.__path__, str(adapters_dir)])
    sys.modules.pop(f"adapters.{SOURCE}", None)
    (adapters_dir / f"{SOURCE}.py").write_text(_ADAPTER_SRC, encoding="utf-8")

    ryuiki_db = tmp_path / "ryuiki.sqlite"
    make_organism_records_db(ryuiki_db)
    conn = sqlite3.connect(ryuiki_db)
    conn.execute("CREATE TABLE wildlife_sightings (id INTEGER, taxon TEXT, day TEXT, lat REAL, lon REAL, situation TEXT)")
    conn.executemany("INSERT INTO wildlife_sightings VALUES (?,?,?,?,?,?)", _INPUT_ROWS)
    conn.commit()
    conn.close()

    registry_db = tmp_path / "registry.sqlite"
    make_occurrence_registry_db(registry_db)
    conn = sqlite3.connect(registry_db)
    conn.execute(
        "INSERT INTO source_edition VALUES (?, ?, '20260101', NULL)", (f"common:edition:{SOURCE}.20260101", SOURCE)
    )
    conn.commit()
    conn.close()

    manifests = tmp_path / "manifests"
    write_manifests_from_sources_text(manifests, DEFAULT_SOURCE_REGIONS_YAML_TEXT)
    yield tmp_path, ryuiki_db, registry_db, manifests, adapters_dir
    sys.modules.pop(f"adapters.{SOURCE}", None)


def _write_adapter_manifest(manifests, **over):
    kwargs = dict(
        target="occurrence", update_mode="append", input={"table": "wildlife_sightings"}, expected_row_count=3,
        adapter=SOURCE, extra={"expected": _expected()},
    )
    kwargs.update(over)
    write_manifest(manifests, SOURCE, **kwargs)


def _run(tmp_path, ryuiki_db, registry_db, manifests, *, shape_counts=None):
    shapes = tmp_path / "shapes.yaml"
    make_period_shapes_yaml(shapes, counts=shape_counts or DEFAULT_SHAPE_COUNTS)
    return b06.build_and_write_occurrence(ryuiki_db, registry_db, manifests, shapes, tmp_path / "v2.sqlite")


def test_adapter_rows_flow_into_occurrence_without_touching_builtin_rows(env):
    tmp_path, ryuiki_db, registry_db, manifests, _ = env
    _write_adapter_manifest(manifests)
    stats = _run(tmp_path, ryuiki_db, registry_db, manifests)

    assert stats["adapter_counts"] == {SOURCE: 3}
    assert stats["adapter_attributes_count"] == {SOURCE: 3}
    assert stats["no_coordinate_count"] == 3
    conn = sqlite3.connect(f"file:{tmp_path / 'v2.sqlite'}?mode=ro", uri=True)
    rows = conn.execute(
        "SELECT record_id, source_table, source_row_id, region_id, taxon_id, place_id, place_kind, lat, lon, "
        "period_grain, period_start, period_raw, occurrence_id, source_edition_id, attributes "
        "FROM occurrence WHERE source_id = ? ORDER BY source_row_id", (SOURCE,)
    ).fetchall()
    assert len(rows) == 3
    first = rows[0]
    assert first[0] == f"{SOURCE}__s1" and first[1] == "wildlife_sightings" and first[2] == 1
    assert first[3] == "jp-14" and first[4] == TAXON
    assert first[5:9] == (None, None, None, None)  # 座標を補完しない（place も NULL のまま）
    assert first[9:12] == ("day", "2020-03-01", "2020-03-01")
    assert first[12] == f"common:occ:{SOURCE}.s1"
    assert first[13] == f"common:edition:{SOURCE}.20260101"
    assert json.loads(first[14]) == {"situation": "目撃"}  # attributes は JSON 文字列で保存される
    assert rows[2][9] is None  # 日付なしの記録も落とさない
    assert conn.execute("SELECT COUNT(*) FROM occurrence WHERE source_id <> ? AND attributes IS NOT NULL", (SOURCE,)).fetchone()[0] == 0
    # 既存出典の行は従来どおり（件数）
    assert conn.execute("SELECT COUNT(*) FROM occurrence WHERE source_id <> ?", (SOURCE,)).fetchone()[0] == len(
        DEFAULT_ORGANISM_RECORDS
    )


def test_adapter_declared_period_shape_count_is_checked_against_manifest_expected(env):
    tmp_path, ryuiki_db, registry_db, manifests, _ = env
    _write_adapter_manifest(manifests, extra={"expected": _expected(period_shapes={"day": 5})})
    with pytest.raises(common.MigrationError, match="occurrence_period_shapes"):
        _run(tmp_path, ryuiki_db, registry_db, manifests)


def test_adapter_row_count_is_checked_against_manifest(env):
    tmp_path, ryuiki_db, registry_db, manifests, _ = env
    _write_adapter_manifest(manifests, expected_row_count=4)
    with pytest.raises(common.MigrationError, match="expected_row_count"):
        _run(tmp_path, ryuiki_db, registry_db, manifests)


def test_adapter_taxon_not_in_registry_stops(env):
    tmp_path, ryuiki_db, registry_db, manifests, adapters_dir = env
    _write_adapter_manifest(manifests)
    conn = sqlite3.connect(ryuiki_db)
    conn.execute("UPDATE wildlife_sightings SET taxon = 'common:taxon:gbif.99999' WHERE id = 1")
    conn.commit()
    conn.close()
    with pytest.raises(common.MigrationError, match="registry.taxon に無い"):
        _run(tmp_path, ryuiki_db, registry_db, manifests)


def test_adapter_duplicate_record_key_stops(env):
    tmp_path, ryuiki_db, registry_db, manifests, adapters_dir = env
    _write_adapter_manifest(manifests)
    (adapters_dir / f"{SOURCE}.py").write_text(
        _ADAPTER_SRC.replace('f"s{r[\'id\']}"', '"same"'), encoding="utf-8"
    )
    with pytest.raises(common.MigrationError, match="record_key が重複"):
        _run(tmp_path, ryuiki_db, registry_db, manifests)


def test_adapter_returning_wrong_columns_stops(env):
    tmp_path, ryuiki_db, registry_db, manifests, adapters_dir = env
    _write_adapter_manifest(manifests)
    (adapters_dir / f"{SOURCE}.py").write_text(
        "def rows(ctx):\n    yield {'record_key': 'a', 'oops': 1}\n", encoding="utf-8"
    )
    with pytest.raises(common.MigrationError, match="列が契約と違う"):
        _run(tmp_path, ryuiki_db, registry_db, manifests)


def test_adapter_half_coordinate_stops(env):
    tmp_path, ryuiki_db, registry_db, manifests, adapters_dir = env
    _write_adapter_manifest(manifests)
    (adapters_dir / f"{SOURCE}.py").write_text(
        "from ingest.api import occurrence_row\n"
        "def rows(ctx):\n    yield occurrence_row('a', lat=35.0)\n", encoding="utf-8"
    )
    with pytest.raises(common.MigrationError, match="lat/lon の片方"):
        _run(tmp_path, ryuiki_db, registry_db, manifests)


@pytest.mark.parametrize(
    "check, match",
    [
        ({"not_null": ["observed_on_raw"]}, "not_null"),
        ({"row_count_between": [10, 20]}, "row_count_between"),
        ({"date_between": ["2021-01-01", "2030-01-01"]}, "date_between"),
        ({"unique": ["taxon_id"]}, "unique"),
    ],
)
def test_manifest_checks_stop_the_build(env, check, match):
    tmp_path, ryuiki_db, registry_db, manifests, _ = env
    _write_adapter_manifest(manifests, extra={"expected": _expected(), "checks": [check]})
    with pytest.raises(common.MigrationError, match=match):
        _run(tmp_path, ryuiki_db, registry_db, manifests)


def test_manifest_without_processing_adapter_rows_is_an_unused_declaration(env):
    """マニフェストにあるのに誰も処理しない出典（adapter が 0 行を返す）は止まる（宣言の腐敗を許さない）。"""
    tmp_path, ryuiki_db, registry_db, manifests, adapters_dir = env
    _write_adapter_manifest(manifests, expected_row_count=0)
    (adapters_dir / f"{SOURCE}.py").write_text("def rows(ctx):\n    return iter(())\n", encoding="utf-8")
    with pytest.raises(common.MigrationError, match="1件も該当しなかった"):
        _run(tmp_path, ryuiki_db, registry_db, manifests)
