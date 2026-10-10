"""zone v2 のテスト用フィクスチャ（terrain_points.csv・region.yaml の手書き小片）。

実データ（c68 の出力）は使わない。`zone_row()` は、指定した zone に classify() が必ずなる指標を作る
（閾値の中央付近の値。境界値の検査は test_zone_rule.py が別に持つ）。
"""
from __future__ import annotations

import csv

import yaml

from registry import zone_rule

SUMMIT_M = 1673.0
REGION_ID = "jp-14"


def real_terrain() -> dict:
    return zone_rule.load_zone_definition()["terrain"]


def write_region_yaml(path, summits: dict | None = None) -> None:
    summits = {REGION_ID: SUMMIT_M} if summits is None else summits
    doc = {
        rid: {
            "name_ja": rid, "tz_name": "Asia/Tokyo", "utc_offset": "+09:00", "evidence": "fixture",
            "terrain": {"summit": {"name_ja": "x", "lat": 35.0, "lon": 139.0, "elevation_m": m}},
        }
        for rid, m in summits.items()
    }
    path.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")


# zone -> (elevation, relief_wide, relief_near, floor_min, coast_dist)
_METRICS = {
    1: (1200.0, 400.0, 100.0, 300.0, 20000.0),
    2: (300.0, 300.0, 100.0, 100.0, 20000.0),
    3: (60.0, 50.0, 10.0, 0.0, 20000.0),
    4: (10.0, 10.0, 5.0, 5.0, 20000.0),
    5: (5.0, 10.0, 5.0, 0.0, 500.0),
}


def zone_row(lat, lon, zone, *, region_id=REGION_ID, summit_m=SUMMIT_M, digest=None) -> dict:
    """terrain_points.csv の1行。zone=None は標高が取れない地点（空欄）。"""
    digest = digest or zone_rule.terrain_params_digest(real_terrain())
    row = {"lat": f"{lat:.6f}", "lon": f"{lon:.6f}", "region_id": region_id, "summit_m": summit_m,
           "elevation_m": "", "relief_wide_m": "", "relief_near_m": "", "floor_min_m": "",
           "coast_dist_m": "", "params_digest": digest}
    if zone is not None:
        e, rw, rn, fl, cd = _METRICS[zone]
        row.update(elevation_m=e, relief_wide_m=rw, relief_near_m=rn, floor_min_m=fl, coast_dist_m=cd)
    return row


def write_terrain_csv(path, rows) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(zone_rule.TERRAIN_CSV_COLUMNS), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
