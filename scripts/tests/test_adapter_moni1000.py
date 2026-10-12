"""`adapters/moni1000_*.py`（5 本）と `manifests/moni1000_*.yml`（docs/plans/MONI1000.md §3）。

入力表 `moni1000_counts` は 5 出典で共有。各 adapter は自出典かつ `in_occurrence=1` の行だけを返す。
原本に表があれば実データで件数・契約を検査する（無い環境ではスキップ）。manifest の `expected_row_count` は
担当 A の m10 の実測で確定するまで仮置き。
"""
from __future__ import annotations

import importlib
import pathlib
import sqlite3

import pytest

from ingest import api, boundary, manifest as manifest_lib

ROOT = pathlib.Path(__file__).resolve().parents[2]
SOURCES = (
    "moni1000_satochi_bird", "moni1000_satochi_butterfly", "moni1000_satochi_mammal",
    "moni1000_forest_bird", "moni1000_coast_shorebird",
)


def _adapter(sid):
    return importlib.import_module(f"adapters.{sid}")


def _ctx(sid, rows):
    return api.Ctx(source_id=sid, region_id="jp-14", input_rows=lambda: iter(rows))


def _row(sid, i, **over):
    r = {
        "record_id": f"{sid}:{i}", "source_id": sid, "source_ref": "https://example/ (X)", "survey_id": "S1",
        "site_key": "S060", "site_name_ja": "地点", "place_id": None, "lat": 35.4, "lon": 139.5,
        "lat_lon_basis": "site_table", "coord_decimals": 1, "coordinate_uncertainty_m": 10000.0, "observed_on": "2010-05-03", "season_ja": "春",
        "survey_round": "1", "section_ja": "A", "species_ja": "ウグイス", "scientific_name": "Horornis diphone",
        "individual_count": 3.0, "individual_count_raw": "3", "count_qualifier": None, "id_note_ja": None,
        "out_of_range": 0, "out_of_time": 0, "start_time": None, "taxon_id": "common:taxon:inat.1",
        "in_occurrence": 1, "exclude_reason": None,
    }
    r.update(over)
    return r


@pytest.mark.parametrize("sid", SOURCES)
def test_adapter_returns_only_own_source_and_in_occurrence(sid):
    other = next(s for s in SOURCES if s != sid)
    rows = [
        _row(sid, 1),
        _row(sid, 2, in_occurrence=0, exclude_reason="zero_count", individual_count=0.0, taxon_id=None),
        _row(other, 3),
    ]
    out = list(_adapter(sid).rows(_ctx(sid, rows)))
    assert [r["record_key"] for r in out] == [f"{sid}:1"]


def test_row_mapping_keeps_source_values_and_counts_as_attributes():
    sid = "moni1000_forest_bird"
    r = list(_adapter(sid).rows(_ctx(sid, [_row(sid, 1, count_qualifier="+", individual_count=None,
                                                 individual_count_raw="－", out_of_range=1)])))[0]
    assert (r["lat"], r["lon"], r["observed_on_raw"]) == (35.4, 139.5, "2010-05-03")
    assert r["coordinate_uncertainty_m"] == 10000
    assert r["vernacular_name"] == "ウグイス" and r["scientific_name"] == "Horornis diphone"
    a = r["attributes"]
    assert a["count_qualifier"] == "+" and a["individual_count"] is None and a["individual_count_raw"] == "－"
    assert a["out_of_range"] == 1


@pytest.mark.parametrize("unc", [10000.0, 1000.0, 100.0, 10.0])
def test_uncertainty_is_copied_from_the_column(unc):
    sid = "moni1000_satochi_bird"
    r = list(_adapter(sid).rows(_ctx(sid, [_row(sid, 1, coordinate_uncertainty_m=unc)])))[0]
    assert r["coordinate_uncertainty_m"] == unc


def test_no_coordinates_not_invented_and_missing_date_kept():
    sid = "moni1000_satochi_mammal"
    r = list(_adapter(sid).rows(_ctx(sid, [_row(sid, 1, lat=None, lon=None, observed_on=None, coord_decimals=2,
                                                 coordinate_uncertainty_m=None)])))[0]
    assert r["lat"] is None and r["lon"] is None and r["observed_on_raw"] is None
    assert r["coordinate_uncertainty_m"] is None


@pytest.mark.parametrize("sid", SOURCES)
def test_manifest_valid_and_adapter_boundary(sid):
    m = manifest_lib.load_manifests(ROOT / "manifests")[sid]
    assert (m.target, m.adapter, m.region, m.update_mode) == ("occurrence", sid, "jp-14", "snapshot")
    assert m.input == {"table": "moni1000_counts"}
    assert m.sample_input_max_rows == 50000
    assert m.expected_row_count is not None
    assert boundary.adapter_import_problems(ROOT / "scripts" / "adapters" / f"{sid}.py") == []


@pytest.mark.parametrize("sid", SOURCES)
def test_real_table_rows_are_valid_and_match_manifest(sid):
    db = ROOT / "data" / "db" / "ryuiki.sqlite"
    if not db.exists():
        pytest.skip("原本 ryuiki.sqlite が無い環境")
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        conn.row_factory = sqlite3.Row
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'moni1000_counts'").fetchone() is None:
            pytest.skip("moni1000_counts が無い（m10 の実行前）")
        rows = [dict(r) for r in conn.execute("SELECT * FROM moni1000_counts ORDER BY rowid")]
    finally:
        conn.close()
    out = list(_adapter(sid).rows(_ctx(sid, rows)))
    assert len({r["record_key"] for r in out}) == len(out)
    assert all(r["taxon_id"] for r in out)
    assert all((r["lat"] is None) == (r["lon"] is None) for r in out)
    m = manifest_lib.load_manifests(ROOT / "manifests")[sid]
    assert len(out) == m.expected_row_count  # 仮置きの間は食い違う。m10 の実測で確定する
