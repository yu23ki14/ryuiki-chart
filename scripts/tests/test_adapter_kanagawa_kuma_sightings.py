"""`adapters/kanagawa_kuma_sightings.py` と `manifests/kanagawa_kuma_sightings.yml`（Issue #40 Phase D 担当 S）。

原本（`data/db/ryuiki.sqlite` の `wildlife_sightings`）が手元にあれば実データで 400 行を検査する
（無い環境〔CI のサンプル〕ではスキップ。サンプルは `wildlife_sightings` を持たない）。
"""
from __future__ import annotations

import pathlib
import sqlite3

import pytest

from adapters import kanagawa_kuma_sightings as adapter
from ingest import api, boundary, manifest as manifest_lib

ROOT = pathlib.Path(__file__).resolve().parents[2]
SOURCE = "kanagawa_kuma_sightings"


def _ctx(rows):
    return api.Ctx(source_id=SOURCE, region_id="jp-14", input_rows=lambda: iter(rows))


def _row(i, **over):
    r = {
        "sighting_id": f"kuma_2022_{i:03d}", "observed_on": "2022-04-30", "lat": None, "lon": None,
        "situation_ja": "目撃", "area_kind_ja": "山中", "is_preliminary": 0, "locality_ja": "山北町世附",
        "individual_count": 1.0,
    }
    r.update(over)
    return r


def test_adapter_maps_row_without_inventing_coordinates():
    out = list(adapter.rows(_ctx([_row(1), _row(2, is_preliminary=1, situation_ja="痕跡")])))
    assert [r["record_key"] for r in out] == ["kuma_2022_001", "kuma_2022_002"]
    assert {r["taxon_id"] for r in out} == {"common:taxon:inat.41647"}
    assert all(r["lat"] is None and r["lon"] is None for r in out)
    assert out[0]["observed_on_raw"] == "2022-04-30"
    assert out[0]["attributes"] == {
        "situation_ja": "目撃", "area_kind_ja": "山中", "is_preliminary": False, "locality_ja": "山北町世附",
    }
    assert out[1]["attributes"]["is_preliminary"] is True
    assert "individual_count" not in out[0]["attributes"]  # ADR-0025: n は記録数


def test_manifest_is_structurally_valid_and_declares_no_coordinates():
    manifests = manifest_lib.load_manifests(ROOT / "manifests")
    m = manifests[SOURCE]
    assert (m.target, m.adapter, m.region, m.update_mode) == ("occurrence", SOURCE, "jp-14", "snapshot")
    assert m.expected_row_count == 400
    exp = m.expected
    assert exp["period_shapes"] == {"day": 396}
    assert exp["cube"]["dated_no_coordinate_rows"] == exp["cube"]["dated_rows"] == 396
    assert exp["cube"]["watershed_dated_unresolved_rows"] == 396
    assert exp["place"] == {"coord_resolved": 0, "coord_unresolved": 0}


def test_adapter_imports_only_ingest_api():
    assert boundary.adapter_import_problems(ROOT / "scripts" / "adapters" / f"{SOURCE}.py") == []


def test_real_table_yields_400_rows_one_taxon_no_coordinates_31_preliminary():
    db = ROOT / "data" / "db" / "ryuiki.sqlite"
    if not db.exists():
        pytest.skip("原本 ryuiki.sqlite が無い環境")
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        conn.row_factory = sqlite3.Row
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'wildlife_sightings'").fetchone() is None:
            pytest.skip("wildlife_sightings が無い")
        rows = [dict(r) for r in conn.execute("SELECT * FROM wildlife_sightings ORDER BY rowid")]
    finally:
        conn.close()
    out = list(adapter.rows(_ctx(rows)))
    assert len(out) == 400
    assert len({r["record_key"] for r in out}) == 400
    assert {r["taxon_id"] for r in out} == {adapter.TAXON_ID}
    assert all(r["lat"] is None and r["lon"] is None for r in out)
    assert all(r["observed_on_raw"] is None or len(r["observed_on_raw"]) == 10 for r in out)
    assert sum(r["observed_on_raw"] is None for r in out) == 4  # 日付が確定できなかった行も落とさない
    assert sum(r["attributes"]["is_preliminary"] for r in out) == 31
