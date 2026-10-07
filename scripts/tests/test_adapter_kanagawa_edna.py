"""`adapters/kanagawa_edna.py` と `manifests/kanagawa_edna.yml`（docs/plans/KANAGAWA_EDNA.md §3・§7）。

原本（`data/db/ryuiki.sqlite` の `edna_detections`）が手元にあれば実データを検査する
（無い環境〔CI のサンプル・m07 を流す前〕ではスキップ）。
"""
from __future__ import annotations

import json
import pathlib
import sqlite3

import pytest

from adapters import kanagawa_edna as adapter
from ingest import api, boundary, manifest as manifest_lib

ROOT = pathlib.Path(__file__).resolve().parents[2]
SOURCE = "kanagawa_edna"


def _ctx(rows):
    return api.Ctx(source_id=SOURCE, region_id="jp-14", input_rows=lambda: iter(rows))


def _row(i, **over):
    attrs = {
        "dataset_file": "r7_project_kekka.xlsx", "program": "project", "assay": "all_taxa", "fiscal_year": 2025,
        "site_key": "r7_project_kekka:25-Pro-01", "reads": 120, "reliability": "高", "pident_qcov": 1.0,
        "cf": False, "rank_reduced": False, "name_ambiguous": False, "coord_source": "estimated_from_name",
    }
    r = {
        "record_key": f"r7_project_kekka:{i}:25-Pro-01", "taxon_id": "common:taxon:gbif.2440954",
        "scientific_name": "Cervus nippon Temminck, 1838", "vernacular_name": "ニホンジカ", "taxon_rank": "species",
        "red_list_category": None, "observed_on": "2025-07-21", "lat": 35.5, "lon": 139.5,
        "coordinate_uncertainty_m": 1500.0, "attributes_json": json.dumps(attrs, ensure_ascii=False),
    }
    r.update(over)
    return r


def test_adapter_maps_row_with_estimated_coordinates_and_uncertainty():
    out = list(adapter.rows(_ctx([_row(1), _row(2, red_list_category="情報不足（DD）")])))
    assert [r["record_key"] for r in out] == ["r7_project_kekka:1:25-Pro-01", "r7_project_kekka:2:25-Pro-01"]
    r = out[0]
    assert (r["taxon_id"], r["taxon_rank"], r["vernacular_name"]) == ("common:taxon:gbif.2440954", "species", "ニホンジカ")
    assert (r["lat"], r["lon"], r["coordinate_uncertainty_m"]) == (35.5, 139.5, 1500.0)
    assert r["observed_on_raw"] == "2025-07-21"
    assert r["attributes"]["reads"] == 120 and r["attributes"]["coord_source"] == "estimated_from_name"
    assert out[1]["red_list_category"] == "情報不足（DD）"
    assert "individual_count" not in r["attributes"]  # ADR-0025: n は記録数。値はリード数


def test_row_without_coordinates_or_date_is_kept_with_nulls():
    r = list(adapter.rows(_ctx([_row(3, lat=None, lon=None, coordinate_uncertainty_m=None, observed_on=None)])))[0]
    assert r["lat"] is None and r["lon"] is None and r["coordinate_uncertainty_m"] is None
    assert r["observed_on_raw"] is None  # 日付を補わない・落とさない


def test_manifest_is_structurally_valid():
    m = manifest_lib.load_manifests(ROOT / "manifests")[SOURCE]
    assert (m.target, m.adapter, m.region, m.update_mode) == ("occurrence", SOURCE, "jp-14", "snapshot")
    assert m.input == {"table": "edna_detections"}
    assert m.expected_row_count is not None
    # 採水日はすべて day の形。leaf は年をまたぐ区間の記録なので、day だけの出典では 0
    assert set(m.expected["period_shapes"]) == {"day"}
    cube = m.expected["cube"]
    assert cube["leaf_cell_source_rows"] == cube["leaf_cell_source_rows_no_coordinate"] == 0
    assert cube["dated_rows"] == m.expected["period_shapes"]["day"]
    assert cube["watershed_dated_resolved_rows"] + cube["watershed_dated_unresolved_rows"] == cube["dated_rows"]
    # 座標のある行は、日付ありなら全て grid01 の月セルにも流域にも入る（座標あり行 = 日付あり行 − 座標なしの日付あり行）
    coord = m.expected["place"]["coord_resolved"]
    assert coord == cube["month_cell_source_rows"] == cube["watershed_dated_resolved_rows"]
    assert coord == cube["dated_rows"] - cube["dated_no_coordinate_rows"]
    assert m.expected["place"]["coord_unresolved"] == 0


def test_adapter_imports_only_ingest_api():
    assert boundary.adapter_import_problems(ROOT / "scripts" / "adapters" / f"{SOURCE}.py") == []


def test_real_table_maps_every_row_with_a_registered_taxon():
    reg = ROOT / "data" / "db" / "registry.sqlite"
    db = ROOT / "data" / "db" / "ryuiki.sqlite"
    if not db.exists():
        pytest.skip("原本 ryuiki.sqlite が無い環境")
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        conn.row_factory = sqlite3.Row
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'edna_detections'").fetchone() is None:
            pytest.skip("edna_detections が無い（m07 未実行）")
        rows = [dict(r) for r in conn.execute("SELECT * FROM edna_detections ORDER BY rowid")]
    finally:
        conn.close()
    out = list(adapter.rows(_ctx(rows)))
    assert len(out) == len(rows) > 0
    assert len({r["record_key"] for r in out}) == len(out)
    assert all(r["taxon_id"] for r in out)
    # 座標があるなら緯度・経度・精度が揃ってある（設計書 §3.1）
    assert all((r["lat"] is None) == (r["lon"] is None) == (r["coordinate_uncertainty_m"] is None) for r in out)
    assert all(r["coordinate_uncertainty_m"] is None or r["coordinate_uncertainty_m"] > 0 for r in out)
    if not reg.exists():
        pytest.skip("registry.sqlite が無い（taxon_id の実在を検査できない）")
    rc = sqlite3.connect(f"file:{reg}?mode=ro", uri=True)
    try:
        known = {r[0] for r in rc.execute("SELECT taxon_id FROM taxon")}
    finally:
        rc.close()
    missing = sorted({r["taxon_id"] for r in out} - known)
    assert not missing, f"registry に無い taxon_id（supplement の入れ忘れ）: {missing[:5]}"
    assert all(r["observed_on_raw"] is None or len(r["observed_on_raw"]) == 10 for r in out)
