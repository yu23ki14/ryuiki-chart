"""m01_sites.py の再実行が既存の sites.zone を消さない（UPSERT）。一時 DB だけで完結する。"""
import pathlib
import sqlite3

import pytest

pytest.importorskip("shapely")   # m01_sites は import 時に shapely を読む（CI の requirements に無い収集側ツール）

import m01_sites  # noqa: E402

SCHEMA = pathlib.Path(__file__).resolve().parents[1] / "schema_app.sql"


def _row(site_id, name, zone=None, elev=10.0):
    cols = dict.fromkeys(m01_sites.SITES_COLUMNS)
    cols.update(site_id=site_id, name=name, zone=zone, lat=35.0, lon=139.0, elevation_m=elev,
                source_id="s", is_synthetic=0)
    return tuple(cols[c] for c in m01_sites.SITES_COLUMNS)


def test_rerun_keeps_existing_zone_and_updates_other_columns():
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    conn.executemany(m01_sites.UPSERT_SITES_SQL, [_row("a", "旧名")])
    conn.execute("UPDATE sites SET zone = 3 WHERE site_id = 'a'")   # m09 が付けた
    conn.executemany(m01_sites.UPSERT_SITES_SQL, [_row("a", "新名", elev=20.0), _row("b", "新地点")])
    got = {r[0]: r[1:] for r in conn.execute("SELECT site_id, name, zone, elevation_m FROM sites")}
    assert got["a"] == ("新名", 3, 20.0)      # zone は残り、他の列は更新される
    assert got["b"] == ("新地点", None, 10.0)  # 新しい地点は NULL（m09 が付ける）
