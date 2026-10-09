"""宣言済みの差分 reports/zone_v2_migration.csv（m09 が書く）が、classify() の結果と一致し続けること
（docs/plans/AMAMI_STEP0.md §3・§6-B）。

パラメータ（zone.yaml）やデータ（terrain_points.csv・sites）を変えて zone が動いたら、この宣言を
m09 で作り直さない限り落ちる——「ゲートを緑にするためにラベルを曲げない。差分は列挙して機械検証する」。
サンプルに無い地点・座標は飛ばす（CI のサンプルは縮小版）。実ファイルが無い間（統合前）は skip。
"""
import csv
import pathlib
import sqlite3

import pytest

from registry import zone_rule

from .zone_fixtures import write_region_yaml, write_terrain_csv, zone_row

ROOT = pathlib.Path(__file__).resolve().parents[2]
MIGRATION_CSV = ROOT / "reports" / "zone_v2_migration.csv"
RYUIKI_DB = ROOT / "data" / "db" / "ryuiki.sqlite"


def verify_migration(rows, sites, points, rule):
    """`rows`: 移行 csv の行（dict）。`sites`: `{site_id: (lat, lon, elevation_m)}`。
    サンプルに無い地点・csv に無い座標は飛ばす。食い違いの一覧（空なら一致）と検査した件数を返す。"""
    bad, checked = [], 0
    for r in rows:
        s = sites.get(r["site_id"])
        if s is None or s[2] is None:
            continue
        p = points.get(zone_rule.coord_key(s[0], s[1]))
        if p is None:
            continue
        checked += 1
        got = zone_rule.classify(p, rule, s[2])[0]
        declared = int(r["zone_v2"]) if r["zone_v2"] != "" else None
        if got != declared:
            bad.append(f"{r['site_id']}: 宣言 {declared} / classify {got}")
    return bad, checked


def test_verify_migration_detects_a_moved_zone(tmp_path):
    rule = zone_rule.load_zone_definition()["rule"]
    terrain = tmp_path / "t.csv"
    write_terrain_csv(terrain, [zone_row(35.0, 139.0, 2), zone_row(35.1, 139.1, 5)])
    region = tmp_path / "r.yaml"
    write_region_yaml(region)
    points = zone_rule.load_terrain_points(
        terrain, zone_rule.load_zone_definition()["terrain"], zone_rule.load_region_summits(region))
    sites = {"s1": (35.0, 139.0, 100.0), "s2": (35.1, 139.1, 10.0), "s3": (35.5, 139.5, 1.0), "s4": (35.0, 139.0, None)}
    rows = [{"site_id": "s1", "zone_v2": "2"}, {"site_id": "s2", "zone_v2": "5"},
            {"site_id": "s3", "zone_v2": "1"},   # csv に無い座標は飛ばす
            {"site_id": "s4", "zone_v2": "1"},   # 標高なしは対象外
            {"site_id": "zz", "zone_v2": "1"}]   # サンプルに無い地点
    assert verify_migration(rows, sites, points, rule) == ([], 2)
    rows[1]["zone_v2"] = "4"                      # 閾値やデータが動いて zone が変わった状態
    bad, _ = verify_migration(rows, sites, points, rule)
    assert bad == ["s2: 宣言 4 / classify 5"]


def test_declared_zone_v2_matches_classify_for_the_committed_migration():
    terrain_csv = zone_rule.TERRAIN_POINTS_CSV
    if not (MIGRATION_CSV.exists() and terrain_csv.exists() and RYUIKI_DB.exists()):
        pytest.skip("reports/zone_v2_migration.csv・terrain_points.csv・sites のいずれかがまだ無い（統合前）")
    defn = zone_rule.load_zone_definition()
    points = zone_rule.load_terrain_points(terrain_csv, defn["terrain"], zone_rule.load_region_summits())
    conn = sqlite3.connect(f"file:{RYUIKI_DB}?mode=ro", uri=True)
    try:
        sites = {r[0]: (r[1], r[2], r[3]) for r in conn.execute("SELECT site_id, lat, lon, elevation_m FROM sites")}
    finally:
        conn.close()
    with MIGRATION_CSV.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    bad, checked = verify_migration(rows, sites, points, defn["rule"])
    assert checked > 0
    assert bad == [], "宣言済みの差分と classify() が食い違う。意図した変更なら m09 を回して宣言を作り直す:\n" + "\n".join(bad[:20])
