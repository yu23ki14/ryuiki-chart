"""scripts/m09_site_zone.py のテスト。一時 DB だけで完結する（原本には触らない）。"""
import csv
import sqlite3

import pytest

import m09_site_zone as m09
from registry import zone_rule

from .zone_fixtures import write_region_yaml, write_terrain_csv, zone_row

# (site_id, lat, lon, elevation_m, 旧 zone)。s4 は標高なし（zone の対象外）。
SITES = [
    ("a__s1", 35.0, 139.0, 100.0, 4),   # 新: 2 の指標 -> 旧 4 から 2
    ("a__s2", 35.1, 139.1, 10.0, 5),    # 新: 5（一致）
    ("a__s3", 35.2, 139.2, 50.0, 3),    # 新: 3（一致）
    ("a__s4", 35.3, 139.3, None, None),  # 対象外
    ("a__s5", 35.4, 139.4, 1.0, 5),     # 新: 標高無効（None）
]
NEW_ZONES = {"a__s1": 2, "a__s2": 5, "a__s3": 3, "a__s5": None}


@pytest.fixture
def env(tmp_path):
    db = tmp_path / "ryuiki.sqlite"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE sites (site_id TEXT PRIMARY KEY, lat REAL, lon REAL, elevation_m REAL, zone INTEGER)")
    conn.executemany("INSERT INTO sites VALUES (?,?,?,?,?)", SITES)
    conn.commit()
    conn.close()
    terrain = tmp_path / "terrain_points.csv"
    write_terrain_csv(terrain, [
        zone_row(35.0, 139.0, 2), zone_row(35.1, 139.1, 5), zone_row(35.2, 139.2, 3), zone_row(35.4, 139.4, None),
    ])
    region = tmp_path / "region.yaml"
    write_region_yaml(region)
    report = tmp_path / "reports" / "zone_v2_migration.csv"
    argv = ["--db", str(db), "--terrain", str(terrain), "--region-yaml", str(region), "--migration-csv", str(report)]
    return db, terrain, report, argv


def _zones(db):
    c = sqlite3.connect(db)
    try:
        return dict(c.execute("SELECT site_id, zone FROM sites ORDER BY site_id"))
    finally:
        c.close()


def _rows(report):
    with report.open(encoding="utf-8", newline="") as f:
        return {r["site_id"]: r for r in csv.DictReader(f)}


def test_dry_run_writes_nothing_and_prints_crosstab_and_changes(env, capsys):
    db, _t, report, argv = env
    before = db.read_bytes()
    assert m09.main(argv + ["--dry-run"]) == 0
    assert db.read_bytes() == before and not report.exists()
    out = capsys.readouterr().out
    assert "a__s1: 4 -> 2" in out and "a__s5: 5 -> None" in out
    assert "a__s3" not in out  # 一致した地点は変更一覧に出ない
    assert "一致 2 / 変更 2 / 対象 4" in out


def test_run_updates_zone_and_writes_migration_csv_with_declared_diff(env):
    db, _t, report, argv = env
    assert m09.main(argv) == 0
    assert _zones(db) == {"a__s1": 2, "a__s2": 5, "a__s3": 3, "a__s4": None, "a__s5": None}
    rows = _rows(report)
    assert set(rows) == {"a__s1", "a__s2", "a__s3", "a__s5"}   # 対象外の s4 は載らない
    assert (rows["a__s1"]["zone_v1"], rows["a__s1"]["zone_v2"]) == ("4", "2")
    assert rows["a__s1"]["reason"] == "mountain_relief_ge_200"
    assert rows["a__s5"]["zone_v2"] == "" and rows["a__s5"]["reason"] == "relief_unavailable"  # DEM 無効・台帳の標高 1.0 でも海岸距離が無く 5 に当たらない
    assert rows["a__s2"]["reason"] == "unchanged"
    assert list(next(iter(rows.values())).keys()) == list(m09.CSV_COLUMNS)


def test_idempotent_and_zone_v1_is_preserved_across_runs(env):
    db, _t, report, argv = env
    m09.main(argv)
    csv1, db1 = report.read_bytes(), _zones(db)
    m09.main(argv)
    assert report.read_bytes() == csv1 and _zones(db) == db1
    assert _rows(report)["a__s1"]["zone_v1"] == "4"   # 2回目で v2 を v1 と取り違えない


def test_zone_v1_survives_m01_rerun_that_nulls_the_ledger(env):
    db, _t, report, argv = env
    m09.main(argv)
    c = sqlite3.connect(db)
    c.execute("UPDATE sites SET zone = NULL")   # m01 の INSERT OR REPLACE を模す
    c.commit()
    c.close()
    csv1 = report.read_bytes()
    m09.main(argv)
    assert report.read_bytes() == csv1
    assert _zones(db)["a__s1"] == 2


def test_missing_coordinates_stop_before_any_write(env, capsys):
    db, terrain, report, argv = env
    write_terrain_csv(terrain, [zone_row(35.0, 139.0, 2)])
    before = db.read_bytes()
    assert m09.main(argv) == 2
    assert "c68" in capsys.readouterr().err
    assert db.read_bytes() == before and not report.exists()


def test_stale_params_digest_stops(env, capsys):
    db, terrain, report, argv = env
    write_terrain_csv(terrain, [zone_row(35.0, 139.0, 2, digest="000000000000")])
    assert m09.main(argv) == 2
    assert "params_digest" in capsys.readouterr().err
    assert not report.exists()


def test_zone_on_a_site_without_elevation_stops(env, capsys):
    db, _t, report, argv = env
    c = sqlite3.connect(db)
    c.execute("UPDATE sites SET zone = 3 WHERE site_id = 'a__s4'")
    c.commit()
    c.close()
    assert m09.main(argv) == 2
    assert "a__s4" in capsys.readouterr().err


def test_report_flag_prints_markdown_crosstab(env, capsys):
    _db, _t, _r, argv = env
    assert m09.main(argv + ["--dry-run", "--report"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("| 旧＼新 |") and "付かない" in out


def test_migration_reason_is_unchanged_or_the_classify_reason():
    assert m09.migration_reason(3, 3, "lowland_elev_gt_100") == "unchanged"
    assert m09.migration_reason(5, 3, "lowland_elev_gt_100") == "lowland_elev_gt_100"
    assert m09.migration_reason(5, None, "elevation_invalid") == "elevation_invalid"
    assert m09.migration_reason(2, None, "relief_unavailable") == "relief_unavailable"


def test_non_default_db_requires_explicit_migration_csv(env, capsys):
    """--db に一時コピーを渡しても、コミットされる reports/zone_v2_migration.csv を黙って書き換えない。"""
    db, terrain, _report, argv = env
    i = argv.index("--migration-csv")
    no_csv = argv[:i] + argv[i + 2:]
    with pytest.raises(SystemExit) as e:
        m09.main(no_csv)
    assert e.value.code == 2
    assert "--migration-csv" in capsys.readouterr().err
