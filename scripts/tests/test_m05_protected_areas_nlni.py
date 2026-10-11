"""m05 load_protected_areas_nlni（奄美の A10・A15・A45。Issue #96）。一時ディレクトリの csv/geojson と一時 sqlite だけで動く。"""
import csv
import json
import pathlib
import sqlite3

import pytest

pytest.importorskip("shapely")

import m05_tier1  # noqa: E402
from common import ensure_column, round_coords  # noqa: E402
from shapely.geometry import Point, shape  # noqa: E402

SCRIPTS = pathlib.Path(m05_tier1.__file__).parent

# 細長い L 字（重心は区域の外に落ちる）
L_SHAPE = {"type": "Polygon", "coordinates": [[[129.0, 28.0], [129.6, 28.0], [129.6, 28.01], [129.01, 28.01],
                                                [129.01, 28.6], [129.0, 28.6], [129.0, 28.0]]]}


class FakeWs:
    def find(self, lon, lat):
        return "dem-amami-001"


@pytest.fixture
def con():
    c = sqlite3.connect(":memory:")
    c.executescript((SCRIPTS / "schema_tier1.sql").read_text(encoding="utf-8"))
    return c


def write(tmp, src, rows, geoms=None):
    cols = list(rows[0])
    with open(tmp / f"{src}.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    feats = [{"type": "Feature", "properties": {"source_ref": r["source_ref"]}, "geometry": (geoms or {}).get(i, L_SHAPE)}
             for i, r in enumerate(rows)]
    (tmp / f"{src}.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats}), encoding="utf-8")


@pytest.fixture
def proc(tmp_path, monkeypatch):
    monkeypatch.setattr(m05_tier1, "PROC", tmp_path)
    a10 = [dict(source_id="nlni_a10_natparks_amami", source_ref=f"z#a.shp:{i}", object_id=str(100 + i),
                municipality_names_ja="" if i else "奄美市", fiscal_year_raw="2006" if i else "", fiscal_year="2006" if i else "",
                layer_no=ln, layer_name_ja=nm, area_size_ha_raw="296227.3", area_km2="2.5")
           for i, (ln, nm) in enumerate([("11", "自然公園地域"), ("12", "特別地域"), ("13", "特別保護地区")])]
    a15 = [dict(source_id="nlni_a15_wildlife_amami", source_ref=f"z#x.xml:TJ_{i}", feature_id=f"TJ_{i}", name_ja="湯湾岳",
                protection_class_ja=pc, designated_date="2007-11-01", cancel_date="2017-10-31", area_km2="1.2")
           for i, pc in enumerate(["鳥獣保護区", "鳥獣保護区", "特別保護地区"])]
    # 小班IDが重複する2行（source_ref の末尾=shp レコード番号は別）
    a45 = [dict(source_id="nlni_a45_forest_amami", source_ref=f"z#A45-19_46:{n}", subcompartment_id="700",
                national_forest_name_ja="佐仁川内", compartment_label_ja="201_林班_る", municipality_name_ja="奄美市",
                function_type_ja="水源涵養", forest_subtype_ja="天然生林", area_ha_source="12.5", area_km2="0.1")
           for n in (712, 713)]
    write(tmp_path, "nlni_a10_natparks_amami", a10)
    write(tmp_path, "nlni_a15_wildlife_amami", a15)
    write(tmp_path, "nlni_a45_forest_amami", a45)
    return tmp_path


def rows(con):
    con.row_factory = sqlite3.Row
    return [dict(r) for r in con.execute("SELECT * FROM protected_areas ORDER BY area_id")]


def test_load_three_sources(con, proc):
    msg = m05_tier1.load_protected_areas_nlni(con, FakeWs())
    assert "[nlni_a10_natparks_amami]: 3 行" in msg
    rs = rows(con)
    assert len(rs) == 8 and len({r["area_id"] for r in rs}) == 8
    a10 = [r for r in rs if r["source_id"] == "nlni_a10_natparks_amami"]
    assert {r["category_code"] for r in a10} == {"natpark_area", "natpark_special", "natpark_special_protection"}
    assert all(r["name_ja"] is None and r["area_ha"] == pytest.approx(250) and r["area_ha_raw"] is None for r in a10)
    assert all("入れ子" in r["note_ja"] for r in a10)
    assert [r["municipality_ja"] for r in a10 if r["area_id"].endswith(":100")] == ["奄美市"]
    assert all(r["designated_on"] is None for r in a10)
    assert [r["designated_on_raw"] for r in sorted(a10, key=lambda r: r["area_id"])] == [None, "2006", "2006"]
    a15 = [r for r in rs if r["source_id"] == "nlni_a15_wildlife_amami"]
    assert {r["category_code"] for r in a15} == {"wildlife_reserve", "wildlife_special_protection"}
    assert "2007-11-01〜2017-10-31" in a15[0]["note_ja"]
    a45 = [r for r in rs if r["source_id"] == "nlni_a45_forest_amami"]
    # 小班ID重複でも別行（主キーは shp レコード番号）
    assert [r["area_id"] for r in a45] == ["nlni_a45_forest_amami:712", "nlni_a45_forest_amami:713"]
    assert a45[0]["name_ja"] == "佐仁川内 201_林班_る" and a45[0]["area_ha_raw"] == "12.5"
    assert "機能類型: 水源涵養" in a45[0]["note_ja"]
    assert all(r["watershed"] == "dem-amami-001" and r["geometry_geojson"] for r in rs)


def test_representative_point_inside_polygon(con, proc):
    m05_tier1.load_protected_areas_nlni(con, FakeWs())
    for r in rows(con):
        assert shape(json.loads(r["geometry_geojson"])).contains(Point(r["lon"], r["lat"]))
    # 重心は L 字の外に落ちる（代表点にしている理由）
    assert not shape(L_SHAPE).contains(shape(L_SHAPE).centroid)


def test_idempotent_and_kanagawa_untouched(con, proc):
    con.execute("INSERT INTO protected_areas (area_id, source_id) VALUES ('k1', 'kanagawa_x')")
    m05_tier1.load_protected_areas_nlni(con, FakeWs())
    m05_tier1.load_protected_areas_nlni(con, FakeWs())
    assert con.execute("SELECT COUNT(*) FROM protected_areas").fetchone()[0] == 9
    assert con.execute("SELECT geometry_geojson FROM protected_areas WHERE area_id='k1'").fetchone()[0] is None


def test_id_collision_with_other_source_stops(con, proc):
    con.execute("INSERT INTO protected_areas (area_id, source_id) VALUES ('nlni_a45_forest_amami:712', 'other')")
    with pytest.raises(SystemExit, match="衝突"):
        m05_tier1.load_protected_areas_nlni(con, FakeWs())


def test_count_mismatch_stops(con, proc):
    p = proc / "nlni_a15_wildlife_amami.geojson"
    g = json.loads(p.read_text())
    g["features"].pop()
    p.write_text(json.dumps(g))
    with pytest.raises(SystemExit, match="合わない"):
        m05_tier1.load_protected_areas_nlni(con, FakeWs())


def test_order_mismatch_stops(con, proc):
    p = proc / "nlni_a10_natparks_amami.geojson"
    g = json.loads(p.read_text())
    g["features"].reverse()
    p.write_text(json.dumps(g))
    with pytest.raises(SystemExit, match="順序"):
        m05_tier1.load_protected_areas_nlni(con, FakeWs())


def test_no_csv_returns_none(con, tmp_path, monkeypatch):
    monkeypatch.setattr(m05_tier1, "PROC", tmp_path)
    assert m05_tier1.load_protected_areas_nlni(con, FakeWs()) is None


def test_ensure_geometry_column_adds_to_legacy_table():
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE protected_areas (area_id TEXT PRIMARY KEY, source_id TEXT)")
    ensure_column(c, 'protected_areas', 'geometry_geojson', 'TEXT')
    ensure_column(c, 'protected_areas', 'geometry_geojson', 'TEXT')
    assert "geometry_geojson" in {r[1] for r in c.execute("PRAGMA table_info(protected_areas)")}


def test_unknown_category_stops(con, proc):
    p = proc / "nlni_a10_natparks_amami.csv"
    p.write_text(p.read_text(encoding="utf-8").replace(",13,", ",99,"), encoding="utf-8")
    with pytest.raises(SystemExit, match="nlni_a10_natparks_amami.*99"):
        m05_tier1.load_protected_areas_nlni(con, FakeWs())


def test_round_coords_accepts_integer_coordinates():
    assert round_coords([[1, 2], [3.123456789, 4]]) == [[1, 2], [3.123457, 4]]
